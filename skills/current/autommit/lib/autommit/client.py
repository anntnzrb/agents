"""OpenAI-compatible model client with an explicit transport ladder."""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from autommit.errors import AutommitError
from autommit.proposal import (
    MAX_CHANGES_PER_COMMIT,
    MAX_COMMITS,
    MAX_CONCERN_LENGTH,
    MAX_DEPENDENCIES,
    MAX_DETAIL_LENGTH,
    MAX_DETAILS,
    MAX_PATH_LENGTH,
    MAX_RATIONALE_LENGTH,
    MAX_SUMMARY_LENGTH,
    normalize_atomicity_decision,
    normalize_proposal,
)

if TYPE_CHECKING:
    from collections.abc import Callable

USER_AGENT: Final[str] = "autommit/1.0"
MAX_ATTEMPTS: Final[int] = 3
BACKOFF_SECONDS: Final[float] = 1.5
REASONING_EFFORT: Final[str] = "low"
RETRYABLE_STATUSES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
UNSUPPORTED_RUNG_STATUSES: Final[frozenset[int]] = frozenset({400, 422})
OK_STATUS: Final[int] = 200

PLAN_TOOL_NAME: Final[str] = "submit_plan"
CRITIC_TOOL_NAME: Final[str] = "submit_atomicity_decision"

KNOWN_CA_LOCATIONS: Final[tuple[str, ...]] = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/ca-bundle.pem",
    "/etc/ssl/cert.pem",
)

_SELECTOR_SCHEMA: Final[dict[str, object]] = {
    "anyOf": [
        {"type": "string", "enum": ["all"]},
        {"type": "array", "minItems": 1, "items": {"type": "integer", "minimum": 1}},
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["type", "indices"],
            "properties": {
                "type": {"type": "string", "enum": ["indices"]},
                "indices": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "integer", "minimum": 1},
                },
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["type", "start", "end"],
            "properties": {
                "type": {"type": "string", "enum": ["lines"]},
                "start": {"type": "integer", "minimum": 1},
                "end": {"type": "integer", "minimum": 1},
            },
        },
    ]
}

_CHANGE_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["path", "hunks"],
    "properties": {
        "path": {"type": "string", "maxLength": MAX_PATH_LENGTH},
        "hunks": _SELECTOR_SCHEMA,
    },
}

PLAN_JSON_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["commits"],
    "properties": {
        "commits": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_COMMITS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["summary", "details", "dependencies", "changes"],
                "properties": {
                    "summary": {"type": "string", "maxLength": MAX_SUMMARY_LENGTH},
                    "details": {
                        "type": "array",
                        "maxItems": MAX_DETAILS,
                        "items": {
                            "type": "string",
                            "maxLength": MAX_DETAIL_LENGTH,
                        },
                    },
                    "dependencies": {
                        "type": "array",
                        "maxItems": MAX_DEPENDENCIES,
                        "items": {"type": "integer", "minimum": 0},
                    },
                    "changes": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_CHANGES_PER_COMMIT,
                        "items": _CHANGE_SCHEMA,
                    },
                },
            },
        }
    },
}

CRITIC_JSON_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "concerns", "rationale"],
    "properties": {
        "decision": {"type": "string", "enum": ["accept", "split"]},
        "concerns": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": MAX_CONCERN_LENGTH},
        },
        "rationale": {"type": "string", "maxLength": MAX_RATIONALE_LENGTH},
    },
}


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """One logical model call against an OpenAI-compatible endpoint."""

    model: str
    base_url: str
    api_key: str | None
    timeout: float
    system: str
    user: str


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Transport-level response used by the ladder."""

    status: int
    body: dict[str, object]


@dataclass(frozen=True, slots=True)
class _Rung:
    """One transport attempt shape for the same logical call."""

    name: str
    decorate: Callable[[dict[str, object]], dict[str, object]]
    extract: Callable[[dict[str, object]], str]


def _create_secure_ssl_context() -> ssl.SSLContext:
    """Create an SSL context with resilient CA bundle resolution."""
    context = ssl.create_default_context()
    for ca_path in KNOWN_CA_LOCATIONS:
        try:
            context.load_verify_locations(ca_path)
            break
        except OSError:
            continue
    return context


def _decode_body(raw: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    return cast("dict[str, object]", value)


def _error_detail(body: dict[str, object]) -> str:
    error = body.get("error")
    if isinstance(error, dict):
        message = cast("dict[str, object]", error).get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return "no error detail"


def _extract_content(body: dict[str, object]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AutommitError("invalid_response", "Model response contains no choices.")
    first = choices[0]
    if not isinstance(first, dict):
        raise AutommitError("invalid_response", "Model choice is not an object.")
    message = cast("dict[str, object]", first).get("message")
    if not isinstance(message, dict):
        raise AutommitError("invalid_response", "Model response contains no message.")
    content = cast("dict[str, object]", message).get("content")
    if not isinstance(content, str) or not content.strip():
        raise AutommitError("invalid_response", "Model response contains no content.")
    return content


def _extract_tool_arguments(body: dict[str, object]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AutommitError("invalid_response", "Model response contains no choices.")
    first = choices[0]
    if not isinstance(first, dict):
        raise AutommitError("invalid_response", "Model choice is not an object.")
    message = cast("dict[str, object]", first).get("message")
    if not isinstance(message, dict):
        raise AutommitError("invalid_response", "Model response contains no message.")
    tool_calls = cast("dict[str, object]", message).get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        raise AutommitError("invalid_response", "Model response contains no tool call.")
    call = tool_calls[0]
    if not isinstance(call, dict):
        raise AutommitError("invalid_response", "Model tool call is not an object.")
    function = cast("dict[str, object]", call).get("function")
    if not isinstance(function, dict):
        raise AutommitError("invalid_response", "Model tool call has no function.")
    arguments = cast("dict[str, object]", function).get("arguments")
    if not isinstance(arguments, str) or not arguments.strip():
        raise AutommitError("invalid_response", "Model tool call has no arguments.")
    return arguments


def _loads(text: str) -> object:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```")
        stripped = stripped.removesuffix("```").strip()
    return json.loads(stripped)


def _schema_rung(name: str, schema: dict[str, object]) -> _Rung:
    def decorate(payload: dict[str, object]) -> dict[str, object]:
        return {
            **payload,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": schema},
            },
        }

    return _Rung("json_schema", decorate, _extract_content)


def _tool_rung(name: str, schema: dict[str, object]) -> _Rung:
    def decorate(payload: dict[str, object]) -> dict[str, object]:
        return {
            **payload,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": f"Return the {name} object.",
                        "parameters": schema,
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": name}},
        }

    return _Rung("tool", decorate, _extract_tool_arguments)


def _json_object_rung() -> _Rung:
    def decorate(payload: dict[str, object]) -> dict[str, object]:
        return {**payload, "response_format": {"type": "json_object"}}

    return _Rung("json_object", decorate, _extract_content)


def _http_post(request: ModelRequest) -> Callable[[dict[str, object]], HttpResponse]:
    ssl_context = _create_secure_ssl_context()
    url = f"{request.base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {request.api_key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }

    def post(payload: dict[str, object]) -> HttpResponse:
        http_request = urllib.request.Request(  # noqa: S310
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310
                http_request, timeout=request.timeout, context=ssl_context
            ) as response:
                return HttpResponse(
                    response.status, _decode_body(response.read().decode("utf-8"))
                )
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            return HttpResponse(error.code, _decode_body(detail))

    return post


@dataclass(frozen=True, slots=True)
class _CallOptions:
    """Ladder, retry, and validation settings for one logical call."""

    rungs: tuple[_Rung, ...]
    invalid_code: str
    post: Callable[[dict[str, object]], HttpResponse] | None
    attempts: int
    backoff: float


def _call_model(request: ModelRequest, options: _CallOptions) -> dict[str, object]:
    if not request.api_key:
        raise AutommitError(
            "missing_api_key",
            "Set AUTOMMIT_API_KEY or OPENAI_API_KEY, or pass an API key argument.",
        )
    send = _http_post(request) if options.post is None else options.post
    base_payload: dict[str, object] = {
        "model": request.model,
        "messages": [
            {"role": "system", "content": request.system},
            {"role": "user", "content": request.user},
        ],
        # Planning is bounded structured extraction over evidence the CLI already
        # computed, so a low effort is enough. A gateway without thinking support
        # drops the field instead of failing the request.
        "reasoning_effort": REASONING_EFFORT,
    }
    attempts = max(1, options.attempts)
    last_invalid: AutommitError | None = None
    for rung in options.rungs:
        for attempt in range(attempts):
            try:
                response = send(rung.decorate(dict(base_payload)))
            except OSError as error:
                if attempt + 1 < attempts:
                    time.sleep(options.backoff * (attempt + 1))
                    continue
                raise AutommitError(
                    "provider_error",
                    f"{request.base_url} is unreachable: {error}.",
                    1,
                ) from error
            if response.status in RETRYABLE_STATUSES:
                if attempt + 1 < attempts:
                    time.sleep(options.backoff * (attempt + 1))
                    continue
                raise AutommitError(
                    "provider_error",
                    f"{request.base_url} returned HTTP {response.status}: "
                    f"{_error_detail(response.body)}.",
                    1,
                )
            if response.status in UNSUPPORTED_RUNG_STATUSES:
                break
            if response.status != OK_STATUS:
                raise AutommitError(
                    "provider_error",
                    f"{request.base_url} returned HTTP {response.status}: "
                    f"{_error_detail(response.body)}.",
                    1,
                )
            try:
                payload = _loads(rung.extract(response.body))
                return _validate(payload, options.invalid_code)
            except AutommitError as error:
                last_invalid = AutommitError(options.invalid_code, error.message)
                break
            except (KeyError, IndexError, TypeError, ValueError) as error:
                last_invalid = AutommitError(
                    options.invalid_code, f"Unusable model response: {error}."
                )
                break
    if last_invalid is not None:
        raise last_invalid
    raise AutommitError(options.invalid_code, "Model returned no usable result.")


def _validate(payload: object, invalid_code: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise AutommitError(invalid_code, "Model result must be a JSON object.")
    record = cast("dict[str, object]", payload)
    try:
        if invalid_code == "invalid_plan":
            _ = normalize_proposal(record)
        else:
            _ = normalize_atomicity_decision(record)
    except AutommitError as error:
        raise AutommitError(invalid_code, error.message) from error
    return record


def _http_get(request: ModelRequest) -> Callable[[str], HttpResponse]:
    ssl_context = _create_secure_ssl_context()
    headers = {
        "Authorization": f"Bearer {request.api_key}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }

    def fetch(url: str) -> HttpResponse:
        http_request = urllib.request.Request(url, headers=headers)  # noqa: S310
        try:
            with urllib.request.urlopen(  # noqa: S310
                http_request, timeout=request.timeout, context=ssl_context
            ) as response:
                return HttpResponse(
                    response.status, _decode_body(response.read().decode("utf-8"))
                )
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            return HttpResponse(error.code, _decode_body(detail))

    return fetch


def list_models(
    request: ModelRequest,
    *,
    fetch: Callable[[str], HttpResponse] | None = None,
) -> tuple[str, ...]:
    """List the model ids an OpenAI-compatible endpoint exposes."""
    if not request.api_key:
        raise AutommitError(
            "missing_api_key",
            "Set AUTOMMIT_API_KEY or OPENAI_API_KEY, or pass an API key argument.",
        )
    url = f"{request.base_url.rstrip('/')}/models"
    sender = _http_get(request) if fetch is None else fetch
    response = sender(url)
    if response.status != OK_STATUS:
        raise AutommitError(
            "provider_error",
            f"{url} returned HTTP {response.status}: {_error_detail(response.body)}.",
            1,
        )
    data = response.body.get("data")
    if not isinstance(data, list):
        raise AutommitError("invalid_response", f"{url} returned no model list.")
    ids = {
        entry["id"]
        for entry in cast("list[object]", data)
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    return tuple(sorted(ids))


def call_planner(
    request: ModelRequest,
    *,
    post: Callable[[dict[str, object]], HttpResponse] | None = None,
    attempts: int = MAX_ATTEMPTS,
    backoff: float = BACKOFF_SECONDS,
) -> dict[str, object]:
    """Ask the model for a plan, walking the transport ladder in order."""
    rungs = (
        _schema_rung(PLAN_TOOL_NAME, PLAN_JSON_SCHEMA),
        _tool_rung(PLAN_TOOL_NAME, PLAN_JSON_SCHEMA),
        _json_object_rung(),
    )
    return _call_model(
        request,
        _CallOptions(
            rungs=rungs,
            invalid_code="invalid_plan",
            post=post,
            attempts=attempts,
            backoff=backoff,
        ),
    )


def call_critic(
    request: ModelRequest,
    *,
    post: Callable[[dict[str, object]], HttpResponse] | None = None,
    attempts: int = MAX_ATTEMPTS,
    backoff: float = BACKOFF_SECONDS,
) -> dict[str, object]:
    """Ask the model for an atomicity verdict, walking the transport ladder."""
    rungs = (
        _schema_rung(CRITIC_TOOL_NAME, CRITIC_JSON_SCHEMA),
        _tool_rung(CRITIC_TOOL_NAME, CRITIC_JSON_SCHEMA),
        _json_object_rung(),
    )
    return _call_model(
        request,
        _CallOptions(
            rungs=rungs,
            invalid_code="invalid_atomicity_decision",
            post=post,
            attempts=attempts,
            backoff=backoff,
        ),
    )
