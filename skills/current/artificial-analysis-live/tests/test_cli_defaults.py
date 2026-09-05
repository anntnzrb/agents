"""CLI default-path regression tests."""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest

from artificial_analysis import cli
from artificial_analysis.cli import (
    _capability_schema,  # pyright: ignore[reportPrivateUsage]
    _coding_namespace,  # pyright: ignore[reportPrivateUsage]
    _ensure_default_snapshot_fresh,  # pyright: ignore[reportPrivateUsage]
    _envelope,  # pyright: ignore[reportPrivateUsage]
    _evaluation_namespace,  # pyright: ignore[reportPrivateUsage]
    _evaluation_payload,  # pyright: ignore[reportPrivateUsage]
    _fetch_namespace,  # pyright: ignore[reportPrivateUsage]
    _fetch_payload,  # pyright: ignore[reportPrivateUsage]
    _handle_fetch,  # pyright: ignore[reportPrivateUsage]
    _harness_payload,  # pyright: ignore[reportPrivateUsage]
    _load_dotenv,  # pyright: ignore[reportPrivateUsage]
    _normalize_argv,  # pyright: ignore[reportPrivateUsage]
    _query_payload,  # pyright: ignore[reportPrivateUsage]
    _required_api_key,  # pyright: ignore[reportPrivateUsage]
    _stats_namespace,  # pyright: ignore[reportPrivateUsage]
)
from artificial_analysis.rsc import ExtractionError

TMP_ARTIFACT_DIR = Path(tempfile.gettempdir()) / "artifacts" / "artificial-analysis"
TMP_SNAPSHOT = TMP_ARTIFACT_DIR / "full-data.json"
TMP_ENDPOINTS = TMP_ARTIFACT_DIR / "endpoints.txt"
TMP_URL = TMP_ARTIFACT_DIR / "full-url.txt"
TMP_CODING = TMP_ARTIFACT_DIR / "coding-data.json"


def _ns_dict(namespace: argparse.Namespace) -> dict[str, object]:
    return cast("dict[str, object]", vars(namespace))


class TestCliDefaultPaths(unittest.TestCase):
    def test_omitted_command_defaults_to_fetch(self) -> None:
        args = _ns_dict(cli.build_parser().parse_args(_normalize_argv([])))

        assert args["command"] == "fetch"
        assert args["handler"] is _handle_fetch

    def test_cli_command_set_remains_present(self) -> None:
        parser = cli.build_parser()
        subparsers = next(
            cast("argparse._SubParsersAction[argparse.ArgumentParser]", action)  # pyright: ignore[reportPrivateUsage]
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)  # pyright: ignore[reportPrivateUsage]
        )

        choices = cast("dict[str, object]", subparsers.choices)
        assert set(choices) == {
            "fetch",
            "stats",
            "diff",
            "diagnose",
            "coding",
            "harness",
            "evaluation",
            "reasoning",
            "query",
            "qa",
            "schema",
        }

    def test_success_envelope_keeps_protocol_v1_shape(self) -> None:
        data: dict[str, object] = {"counts": {"models": 1}}

        assert _envelope("stats", data) == {
            "ok": True,
            "version": "1",
            "command": "stats",
            "data": data,
        }

    def test_fetch_parser_uses_tmp_artifacts_defaults(self) -> None:
        args = _ns_dict(cli.build_parser().parse_args(["fetch"]))

        assert args["output_json"] == TMP_SNAPSHOT
        assert args["output_endpoints"] == TMP_ENDPOINTS
        assert args["output_url"] == TMP_URL
        assert args["stale_policy"] == "error"
        assert args["allow_stale"] is False
        assert args["strict"] is False

        strict_args = _ns_dict(cli.build_parser().parse_args(["fetch", "--strict"]))
        assert strict_args["strict"] is True
        stale_args = _ns_dict(cli.build_parser().parse_args(["fetch", "--allow-stale"]))
        assert stale_args["allow_stale"] is True
        policy_args = _ns_dict(
            cli.build_parser().parse_args(
                ["fetch", "--stale-policy", "allow-last-good"],
            ),
        )
        assert policy_args["stale_policy"] == "allow-last-good"

    def test_reader_commands_default_to_tmp_snapshot(self) -> None:
        parser = cli.build_parser()
        for command in (["stats"], ["harness"], ["reasoning"], ["query"]):
            with self.subTest(command=command[0]):
                args = _ns_dict(parser.parse_args(command))
                assert args["snapshot"] == TMP_SNAPSHOT

        args = _ns_dict(parser.parse_args(["qa", "best provider"]))
        assert args["snapshot"] == TMP_SNAPSHOT

    def test_coding_parser_uses_tmp_output_default(self) -> None:
        args = _ns_dict(cli.build_parser().parse_args(["coding"]))

        assert args["output_json"] == TMP_CODING

    def test_evaluation_parser_accepts_url_and_generic_controls(self) -> None:
        args = _ns_dict(
            cli.build_parser().parse_args(
                [
                    "evaluation",
                    "https://example.test/evaluations/demo",
                    "--sort-by",
                    "score",
                    "--order",
                    "desc",
                    "--limit",
                    "3",
                ],
            ),
        )
        assert args["url"] == "https://example.test/evaluations/demo"
        assert args["sort_by"] == "score"
        assert args["order"] == "desc"
        assert args["limit"] == 3

    def test_rpc_namespace_defaults_use_tmp_artifacts(self) -> None:
        fetch_args = _ns_dict(_fetch_namespace({}))

        assert fetch_args["output_json"] == TMP_SNAPSHOT
        assert fetch_args["output_endpoints"] == TMP_ENDPOINTS
        assert fetch_args["output_url"] == TMP_URL
        assert _ns_dict(_stats_namespace({}))["snapshot"] == TMP_SNAPSHOT
        assert _ns_dict(_coding_namespace({}))["output_json"] == TMP_CODING

    def test_capability_schema_reports_tmp_fetch_defaults(self) -> None:
        schema = _capability_schema()
        commands = cast("dict[str, dict[str, dict[str, str]]]", schema["commands"])
        flags = commands["fetch"]["flags"]

        assert (
            flags["output_json"]
            == "Path (default <temp-dir>/artifacts/artificial-analysis/full-data.json)"
        )
        assert (
            flags["output_endpoints"]
            == "Path (default <temp-dir>/artifacts/artificial-analysis/endpoints.txt)"
        )
        assert (
            flags["output_url"]
            == "Path (default <temp-dir>/artifacts/artificial-analysis/full-url.txt)"
        )

    def test_default_snapshot_guard_rejects_stale_tmp_snapshot(self) -> None:
        stale_snapshot: dict[str, object] = {
            "meta": {"fetched_at": (datetime.now(UTC) - timedelta(days=2)).isoformat()},
        }

        with pytest.raises(ExtractionError, match="Default snapshot is stale"):
            _ensure_default_snapshot_fresh(TMP_SNAPSHOT, stale_snapshot)

    def test_default_snapshot_guard_allows_explicit_stale_snapshot(self) -> None:
        stale_snapshot: dict[str, object] = {
            "meta": {"fetched_at": "2000-01-01T00:00:00+00:00"},
        }

        _ensure_default_snapshot_fresh(
            Path("fixtures/old-snapshot.json"),
            stale_snapshot,
        )

    def test_fetch_requires_exact_key_error_before_network(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(cli, "_dotenv_candidates", return_value=[]),
            pytest.raises(
                cli.CliUsageError,
                match=(
                    r"^ARTIFICIAL_ANALYSIS_API_KEY required; inject it in the process "
                    r"or set ARTIFICIAL_ANALYSIS_ENV_FILE to a "
                    r"permissions-restricted external file\.$"
                ),
            ),
        ):
            _ = _required_api_key()

    def test_dotenv_preserves_existing_process_variables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            _ = env_file.write_text(
                "ARTIFICIAL_ANALYSIS_API_KEY=file-key\nUNRELATED=file-value\n",
                encoding="utf-8",
            )
            with (
                patch.dict(
                    os.environ,
                    {
                        "ARTIFICIAL_ANALYSIS_API_KEY": "process-key",
                        "UNRELATED": "process-value",
                    },
                    clear=True,
                ),
                patch.object(cli, "_dotenv_candidates", return_value=[env_file]),
            ):
                _load_dotenv()
                assert os.environ["ARTIFICIAL_ANALYSIS_API_KEY"] == "process-key"
                assert os.environ["UNRELATED"] == "process-value"

    def test_schema_v2_readers_join_slim_endpoints_to_canonical_models(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir) / "snapshot.json"
            _ = snapshot_path.write_text(
                '{"meta":{"schema_version":2,"fetched_at":"2026-01-01T00:00:00+00:00"},"models":[{"slug":"model-a","name":"Model A","creator":{"name":"Lab"},"agentic_index":80,"coding_index":60,"intelligence_index":70}],"hosts_models":[{"slug":"host_model-a","model_slug":"model-a","host":{"slug":"host","name":"Host"},"timescaleData":{"median_output_speed":10},"price_1m_blended_7_to_2_to_1":4}]}',
                encoding="utf-8",
            )
            query = _query_payload(
                argparse.Namespace(
                    snapshot=snapshot_path,
                    model=None,
                    provider=None,
                    endpoint=None,
                    sort_by="intelligence",
                    order="auto",
                    limit=10,
                ),
            )
            harness = _harness_payload(
                argparse.Namespace(
                    snapshot=snapshot_path,
                    model=None,
                    creator=None,
                    open_weights_only=False,
                    limit=10,
                ),
            )
        query_rows = cast("list[dict[str, object]]", query["rows"])
        assert query_rows[0]["model_name"] == "Model A"
        assert query_rows[0]["price_blended"] == 4
        harness_rows = cast("list[dict[str, object]]", harness["rows"])
        assert harness_rows[0]["creator"] == "Lab"

    def test_fetch_uses_last_good_snapshot_when_required_source_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cache"
            cache_dir.mkdir()
            _ = (cache_dir / "last-good.json").write_text(
                '{"meta":{"fetched_at":"2026-01-01T00:00:00+00:00"},"models":[],"hosts":[],"hosts_models":[{"slug":"host_model-1"}]}',
                encoding="utf-8",
            )
            args = argparse.Namespace(
                cache_dir=cache_dir,
                timeout_seconds=1.0,
                min_endpoints=0,
                min_providers=0,
                stale_policy="allow-last-good",
                allow_stale=True,
                strict=False,
                output_json=Path(temp_dir) / "snapshot.json",
                output_endpoints=Path(temp_dir) / "endpoints.txt",
                output_url=Path(temp_dir) / "url.txt",
            )
            with (
                patch.object(cli, "_required_api_key", return_value="secret"),
                patch.object(cli, "fetch_rsc", side_effect=OSError("HTTP 503")),
            ):
                payload = _fetch_payload(args)
        fallback = cast("dict[str, object]", payload["fallback"])
        assert fallback["used"]
        sources = cast("dict[str, dict[str, object]]", payload["sources"])
        assert sources["rsc"]["status_code"] is None

    def test_fetch_falls_back_when_official_api_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir) / "cache"
            cache_dir.mkdir()
            _ = (cache_dir / "last-good.json").write_text(
                '{"meta":{"fetched_at":"2026-01-01T00:00:00+00:00"},"models":[],"hosts":[],"hosts_models":[{"slug":"host_model-1"}]}',
                encoding="utf-8",
            )
            args = argparse.Namespace(
                cache_dir=cache_dir,
                timeout_seconds=1.0,
                min_endpoints=0,
                min_providers=0,
                stale_policy="allow-last-good",
                allow_stale=True,
                strict=False,
                output_json=Path(temp_dir) / "snapshot.json",
                output_endpoints=Path(temp_dir) / "endpoints.txt",
                output_url=Path(temp_dir) / "url.txt",
            )
            with (
                patch.object(cli, "_required_api_key", return_value="secret"),
                patch.object(
                    cli,
                    "fetch_rsc",
                    return_value=SimpleNamespace(status_code=200, headers={}, body=""),
                ),
                patch.object(cli, "fetch_models", side_effect=OSError("HTTP 503")),
            ):
                payload = _fetch_payload(args)
        fallback = cast("dict[str, object]", payload["fallback"])
        assert fallback["used"]
        sources = cast("dict[str, dict[str, object]]", payload["sources"])
        assert sources["official_api"]["status_code"] is None

    def test_evaluation_payload_reads_saved_next_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "evaluation.html"
            _ = input_path.write_text(
                (
                    "<script>self.__next_f.push([1,"
                    '"0:{\\"rows\\":[{\\"name\\":\\"A\\",\\"score\\":70},'
                    '{\\"name\\":\\"B\\",\\"score\\":80}]}'
                    '"])</script>'
                ),
                encoding="utf-8",
            )
            args = _evaluation_namespace(
                {"input": str(input_path), "sort_by": "score", "order": "desc"},
            )
            payload = _evaluation_payload(args)

        counts = cast("dict[str, object]", payload["counts"])
        assert counts["matched_rows"] == 2
        rows = cast("list[dict[str, object]]", payload["rows"])
        assert [row["name"] for row in rows] == ["B", "A"]


if __name__ == "__main__":
    _ = unittest.main()
