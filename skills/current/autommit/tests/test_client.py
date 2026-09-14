"""Unit tests for the autommit config resolver and model client ladder."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import cast

SKILL_ROOT = Path(__file__).resolve().parents[1]
_ = sys.path.insert(0, str(SKILL_ROOT / "lib"))
from autommit.client import (
    CRITIC_JSON_SCHEMA,
    PLAN_JSON_SCHEMA,
    HttpResponse,
    ModelRequest,
    call_critic,
    call_planner,
    list_models,
)
from autommit.config import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    ConfigOverrides,
    load_config,
)
from autommit.errors import AutommitError
from autommit.proposal import MAX_SUBJECT_LENGTH, normalize_proposal

PLAN = {
    "commits": [
        {
            "summary": "Update tracked value",
            "details": [],
            "dependencies": [],
            "changes": [{"path": "tracked.txt", "hunks": "all"}],
        }
    ]
}

VERDICT = {"decision": "accept", "concerns": [], "rationale": "One behavior."}


def _request(api_key: str | None = "test-key") -> ModelRequest:
    return ModelRequest(
        model="test-model",
        base_url="https://example.test/v1",
        api_key=api_key,
        timeout=5.0,
        system="system",
        user="user",
    )


def _content(payload: object) -> HttpResponse:
    return HttpResponse(
        200, {"choices": [{"message": {"content": json.dumps(payload)}}]}
    )


def _unsupported() -> HttpResponse:
    return HttpResponse(400, {"error": {"message": "unsupported"}})


class TransportLadderTests(unittest.TestCase):
    """Cover ladder fallthrough, provider errors, and result validation."""

    def test_ladder_falls_through_unsupported_rungs(self) -> None:
        seen: list[str] = []

        def post(payload: dict[str, object]) -> HttpResponse:
            if "tools" in payload:
                seen.append("tool")
                return _unsupported()
            response_format = payload.get("response_format")
            kind = (
                response_format.get("type")
                if isinstance(response_format, dict)
                else None
            )
            if kind == "json_schema":
                seen.append("json_schema")
                return _unsupported()
            seen.append("json_object")
            return _content(PLAN)

        result = call_planner(_request(), post=post, attempts=1)
        self.assertEqual(seen, ["json_schema", "tool", "json_object"])
        self.assertEqual(
            normalize_proposal(result).commits[0].summary, "Update tracked value"
        )

    def test_payload_carries_no_reasoning_or_sampling_field_by_default(self) -> None:
        payloads: list[dict[str, object]] = []

        def post(payload: dict[str, object]) -> HttpResponse:
            payloads.append(payload)
            return _content(PLAN)

        _ = call_planner(_request(), post=post, attempts=1)

        self.assertEqual(len(payloads), 1)
        payload = payloads[0]
        self.assertEqual(payload["model"], _request().model)
        for absent in (
            "reasoning_effort",
            "reasoning",
            "thinking",
            "temperature",
            "top_p",
            "max_tokens",
            "max_completion_tokens",
            "stream",
            "seed",
        ):
            self.assertNotIn(absent, payload)

    def test_configured_reasoning_effort_reaches_every_rung_and_the_critic(
        self,
    ) -> None:
        escalated = replace(_request(), reasoning_effort="xhigh")
        planner_payloads: list[dict[str, object]] = []
        critic_payloads: list[dict[str, object]] = []

        def planner_post(payload: dict[str, object]) -> HttpResponse:
            planner_payloads.append(payload)
            if "tools" in payload:
                return _unsupported()
            response_format = payload.get("response_format")
            kind = (
                response_format.get("type")
                if isinstance(response_format, dict)
                else None
            )
            if kind == "json_schema":
                return _unsupported()
            return _content(PLAN)

        def critic_post(payload: dict[str, object]) -> HttpResponse:
            critic_payloads.append(payload)
            return _content({"decision": "accept", "concerns": [], "rationale": "one"})

        _ = call_planner(escalated, post=planner_post, attempts=1)
        _ = call_critic(escalated, post=critic_post, attempts=1)

        self.assertEqual(len(planner_payloads), 3)
        self.assertTrue(
            all(payload["reasoning_effort"] == "xhigh" for payload in planner_payloads)
        )
        self.assertEqual(critic_payloads[0]["reasoning_effort"], "xhigh")

    def test_tool_rung_arguments_are_accepted(self) -> None:
        def post(payload: dict[str, object]) -> HttpResponse:
            if "tools" in payload:
                return HttpResponse(
                    200,
                    {
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {"function": {"arguments": json.dumps(PLAN)}}
                                    ]
                                }
                            }
                        ]
                    },
                )
            return _unsupported()

        result = call_planner(_request(), post=post, attempts=1)
        self.assertEqual(result["commits"], PLAN["commits"])

    def test_rate_limit_is_a_provider_error(self) -> None:
        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            return HttpResponse(429, {"error": {"message": "slow down"}})

        with self.assertRaises(AutommitError) as raised:
            _ = call_planner(_request(), post=post, attempts=1)
        self.assertEqual(raised.exception.code, "provider_error")
        self.assertEqual(raised.exception.exit_code, 1)

    def test_unusable_responses_become_invalid_plan(self) -> None:
        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            return _content("not json at all")

        with self.assertRaises(AutommitError) as raised:
            _ = call_planner(_request(), post=post, attempts=1)
        self.assertEqual(raised.exception.code, "invalid_plan")

    def test_missing_api_key_is_a_config_error(self) -> None:
        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            return _content(PLAN)

        with self.assertRaises(AutommitError) as raised:
            _ = call_planner(_request(api_key=None), post=post, attempts=1)
        self.assertEqual(raised.exception.code, "missing_api_key")
        self.assertEqual(raised.exception.exit_code, 2)

    def test_critic_accepts_a_strict_schema_response(self) -> None:
        def post(payload: dict[str, object]) -> HttpResponse:
            response_format = payload.get("response_format")
            if (
                isinstance(response_format, dict)
                and response_format.get("type") == "json_schema"
            ):
                return _content(VERDICT)
            return _unsupported()

        result = call_critic(_request(), post=post, attempts=1)
        self.assertEqual(result["decision"], "accept")

    def test_critic_invalid_json_uses_the_decision_code(self) -> None:
        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            return _content("nope")

        with self.assertRaises(AutommitError) as raised:
            _ = call_critic(_request(), post=post, attempts=1)
        self.assertEqual(raised.exception.code, "invalid_atomicity_decision")


class ConfigResolutionTests(unittest.TestCase):
    """Cover precedence, environment aliases, and invalid configuration."""

    def test_precedence_flags_env_file_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            _ = (repo / ".autommit.json").write_text(
                json.dumps(
                    {
                        "model": "from-file",
                        "base_url": "https://file.test/v1",
                        "timeout": 60,
                    }
                ),
                encoding="utf-8",
            )
            environ = {"AUTOMMIT_MODEL": "from-env", "AUTOMMIT_TIMEOUT": "42"}
            config = load_config(repo, environ=environ)
            self.assertEqual(config.model, "from-env")
            self.assertEqual(config.base_url, "https://file.test/v1")
            self.assertEqual(config.timeout, 42.0)
            self.assertIsNone(config.api_key)

            overridden = load_config(
                repo,
                overrides=ConfigOverrides(
                    model="from-flag", api_key="flag-key", timeout=9.5
                ),
                environ=environ,
            )
            self.assertEqual(overridden.model, "from-flag")
            self.assertEqual(overridden.api_key, "flag-key")
            self.assertEqual(overridden.timeout, 9.5)

    def test_defaults_and_trailing_slash_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            config = load_config(repo, environ={})
            self.assertEqual(config.model, DEFAULT_MODEL)
            self.assertEqual(config.base_url, DEFAULT_BASE_URL)
            self.assertEqual(config.timeout, DEFAULT_TIMEOUT)

            trimmed = load_config(
                repo,
                overrides=ConfigOverrides(base_url="https://flag.test/v1/"),
                environ={},
            )
            self.assertEqual(trimmed.base_url, "https://flag.test/v1")

    def test_openai_environment_aliases_are_honored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(
                Path(temp_dir),
                environ={
                    "OPENAI_API_KEY": "openai-key",
                    "OPENAI_BASE_URL": "https://openai.test/v1",
                },
            )
            self.assertEqual(config.api_key, "openai-key")
            self.assertEqual(config.base_url, "https://openai.test/v1")

    def test_invalid_config_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            _ = (repo / ".autommit.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(AutommitError) as raised:
                _ = load_config(repo, environ={})
            self.assertEqual(raised.exception.code, "invalid_json")

    def test_unknown_config_keys_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            _ = (repo / ".autommit.json").write_text(
                json.dumps(
                    {"model": "file-model", "smoke": "make test", "max_commits": 500}
                ),
                encoding="utf-8",
            )
            config = load_config(repo, environ={})
            self.assertEqual(config.model, "file-model")
            self.assertFalse(hasattr(config, "smoke"))
            self.assertFalse(hasattr(config, "max_commits"))

    def test_plan_schema_publishes_no_count_ceilings(self) -> None:
        plan_properties = cast("dict[str, object]", PLAN_JSON_SCHEMA["properties"])
        commits = cast("dict[str, object]", plan_properties["commits"])
        commit_items = cast("dict[str, object]", commits["items"])
        commit_properties = cast("dict[str, object]", commit_items["properties"])
        summary = cast("dict[str, object]", commit_properties["summary"])
        self.assertEqual(summary["maxLength"], MAX_SUBJECT_LENGTH)
        self.assertEqual(MAX_SUBJECT_LENGTH, 72)
        self.assertNotIn("maxItems", commits)
        for name in ("details", "dependencies", "changes"):
            self.assertNotIn(
                "maxItems", cast("dict[str, object]", commit_properties[name])
            )
        critic_properties = cast("dict[str, object]", CRITIC_JSON_SCHEMA["properties"])
        critic_concerns = cast("dict[str, object]", critic_properties["concerns"])
        self.assertNotIn("maxItems", critic_concerns)


class ModelListingTests(unittest.TestCase):
    """Cover endpoint model discovery."""

    def test_list_models_sorts_and_reports_ids(self) -> None:
        def fetch(url: str) -> HttpResponse:
            self.assertTrue(url.endswith("/v1/models"))
            return HttpResponse(
                200, {"data": [{"id": "z-model"}, {"id": "a-model"}, {"nope": 1}]}
            )

        self.assertEqual(list_models(_request(), fetch=fetch), ("a-model", "z-model"))

    def test_list_models_requires_a_key(self) -> None:
        def fetch(url: str) -> HttpResponse:
            del url
            return HttpResponse(200, {})

        with self.assertRaises(AutommitError) as raised:
            _ = list_models(_request(api_key=None), fetch=fetch)
        self.assertEqual(raised.exception.code, "missing_api_key")

    def test_list_models_reports_provider_errors(self) -> None:
        def fetch(url: str) -> HttpResponse:
            del url
            return HttpResponse(500, {"error": {"message": "boom"}})

        with self.assertRaises(AutommitError) as raised:
            _ = list_models(_request(), fetch=fetch)
        self.assertEqual(raised.exception.code, "provider_error")


if __name__ == "__main__":
    _ = unittest.main()
