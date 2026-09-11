"""FxTwitter v2 provider: URL building, one-shot HTTP GET, and status mapping."""

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, TypedDict

from models import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT,
    UNDEFINED,
    CliError,
    ProviderError,
)

MAX_REASON_LENGTH = 160
CONTROL_CHAR_MIN = 32
CONTROL_CHAR_MAX = 127

# Characters left unescaped by JavaScript encodeURIComponent beyond the set
# urllib.parse.quote already keeps (letters, digits, "_.-~").
_ENCODE_SAFE = "!'()*"
_TIMEOUT_MAX_SECONDS = 60
_PARAM_PAIR_LEN = 2
_PROVIDER_ERROR_MIN = 400
_HTTP_SUCCESS_MIN = 200
_HTTP_SUCCESS_MAX = 300

type Transport = Callable[[urllib.request.Request, float], "tuple[int, str]"]
"""Perform one GET and return ``(http_status, body_text)``."""


def compact_text(value: object) -> str:
    text = (
        ("" if value is None or value is UNDEFINED else str(value))
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )
    if len(text) > MAX_REASON_LENGTH:
        return text[: MAX_REASON_LENGTH - 1] + "…"
    return text


# Forbidden code points in WHATWG hosts for special schemes (https). The
# backslash is included because urlsplit does not treat it as a delimiter.
_FORBIDDEN_HOST_CHARS = frozenset(
    '\x00\t\n\r "#%/<>?@[\\]^`|{}' + "".join(chr(c) for c in range(0x7F, 0xA0))
)


def _preprocess_url_input(value: str) -> str:
    """Mirror WHATWG URL input preprocessing: drop tab/LF/CR, trim C0+space."""
    return "".join(ch for ch in value if ch not in "\t\n\r").strip(
        "".join(chr(c) for c in range(0x21))
    )


def _has_forbidden_host_char(hostname: str) -> bool:
    """Return True when a parsed host contains a WHATWG-forbidden code point."""
    return any(ch in _FORBIDDEN_HOST_CHARS for ch in hostname)


def validate_base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url or base_url.strip() != base_url:
        raise CliError(
            code="invalid_base_url",
            message="base URL must be a non-empty HTTPS URL",
            details={},
        )
    for ch in base_url:
        code = ord(ch)
        if code < CONTROL_CHAR_MIN or code > CONTROL_CHAR_MAX:
            raise CliError(
                code="invalid_base_url",
                message="base URL must not contain surrounding whitespace",
                details={},
            )
    try:
        parsed = urllib.parse.urlsplit(base_url)
        _ = parsed.port  # force the same malformed-port failure as new URL()
    except ValueError as err:
        raise CliError(
            code="invalid_base_url",
            message="base URL is malformed",
            details={"reason": compact_text(err)},
        ) from None
    if parsed.scheme != "https":
        raise CliError(
            code="invalid_base_url",
            message="base URL must use HTTPS and include a host",
            details={},
        )
    if not parsed.hostname or _has_forbidden_host_char(parsed.hostname):
        raise CliError(
            code="invalid_base_url",
            message="base URL must use HTTPS and include a host",
            details={},
        )
    if parsed.username or parsed.password:
        raise CliError(
            code="invalid_base_url",
            message="base URL must not include credentials",
            details={},
        )
    if parsed.query or parsed.fragment:
        raise CliError(
            code="invalid_base_url",
            message="base URL must not include a query or fragment",
            details={},
        )
    return base_url.removesuffix("/")


def validate_timeout(timeout: float) -> float:
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
        or timeout > _TIMEOUT_MAX_SECONDS
    ):
        raise ProviderError(
            code="invalid_timeout",
            message="timeout must be greater than 0 and at most 60 seconds",
            details={},
        )
    return timeout


def validate_endpoint(endpoint: str) -> str:
    if not isinstance(endpoint, str) or not endpoint or not endpoint.startswith("/"):
        raise ProviderError(
            code="invalid_endpoint",
            message="endpoint must be a non-empty absolute path",
            details={},
        )
    if endpoint.startswith("//"):
        raise ProviderError(
            code="invalid_endpoint",
            message="endpoint must not be a network-path reference",
            details={},
        )
    for ch in endpoint:
        code = ord(ch)
        if code < CONTROL_CHAR_MIN or code > CONTROL_CHAR_MAX:
            raise ProviderError(
                code="invalid_endpoint",
                message="endpoint contains a control character",
                details={},
            )
    try:
        parsed = urllib.parse.urlsplit(endpoint)
    except ValueError:
        raise ProviderError(
            code="invalid_endpoint",
            message="endpoint is malformed",
            details={},
        ) from None
    if parsed.query or parsed.fragment:
        raise ProviderError(
            code="invalid_endpoint",
            message="endpoint must contain only a path",
            details={},
        )
    return endpoint


def validate_params(params: Any) -> list[tuple[str, str]]:
    if params is None:
        return []
    if not isinstance(params, (list, tuple)):
        raise ProviderError(
            code="invalid_endpoint",
            message="query parameters must be a sequence of pairs",
            details={},
        )
    pairs: list[tuple[str, str]] = []
    for pair in params:
        if not isinstance(pair, (list, tuple)) or len(pair) != _PARAM_PAIR_LEN:
            raise ProviderError(
                code="invalid_endpoint",
                message="query parameters must be a sequence of pairs",
                details={},
            )
        key, value = pair
        if not isinstance(key, str) or not isinstance(value, str):
            raise ProviderError(
                code="invalid_endpoint",
                message="query parameter names and values must be strings",
                details={},
            )
        pairs.append((key, value))
    return pairs


def encode_query(params: Sequence[tuple[str, str]]) -> str:
    parts = []
    for key, value in params:
        ek = urllib.parse.quote(key, safe=_ENCODE_SAFE).replace("%20", "+")
        ev = urllib.parse.quote(value, safe=_ENCODE_SAFE).replace("%20", "+")
        parts.append(f"{ek}={ev}")
    return "&".join(parts)


def build_url(
    base_url: str,
    endpoint: str,
    params: Sequence[tuple[str, str]] | None = None,
) -> str:
    validated_base = validate_base_url(base_url)
    validated_endpoint = validate_endpoint(endpoint)
    validated_pairs = validate_params(params)
    query = encode_query(validated_pairs)
    return f"{validated_base}{validated_endpoint}" + (f"?{query}" if query else "")


class FetchResult(TypedDict):
    payload: Any
    bytes: int
    http_status: int
    provider_status: int | None
    source_url: str
    endpoint: str
    fetched_at: str


class FxTwitterClient(Protocol):
    """The injectable provider service used by lib/commands.py."""

    def request_json(
        self, endpoint: str, params: Sequence[tuple[str, str]] | None = None
    ) -> FetchResult: ...


def _reject_json_constant(value: str) -> Any:
    raise ValueError(value)


def _decode_payload(
    text: str, source_url: str, endpoint: str, http_status: int
) -> tuple[Any, int]:
    byte_count = len(text.encode("utf-8"))
    try:
        payload = json.loads(text, parse_constant=_reject_json_constant)
    except ValueError:
        raise ProviderError(
            code="invalid_json",
            message="provider response was not valid JSON",
            details={
                "source_url": source_url,
                "endpoint": endpoint,
                "http_status": http_status,
                "byte_count": byte_count,
            },
        ) from None
    return payload, byte_count


def _check_provider_status(
    payload: object,
    http_status: int,
    source_url: str,
    endpoint: str,
    byte_count: int,
) -> int | None:
    if not isinstance(payload, dict):
        raise ProviderError(
            code="invalid_payload",
            message="provider response must be a JSON object",
            details={
                "source_url": source_url,
                "endpoint": endpoint,
                "http_status": http_status,
                "byte_count": byte_count,
            },
        )

    if "code" not in payload or payload["code"] is UNDEFINED:
        return None

    raw_code = payload["code"]
    if (
        isinstance(raw_code, bool)
        or not isinstance(raw_code, (int, float))
        or not raw_code.is_integer()
    ):
        raise ProviderError(
            code="invalid_provider_status",
            message="provider status code is malformed",
            details={
                "source_url": source_url,
                "endpoint": endpoint,
                "http_status": http_status,
                "byte_count": byte_count,
            },
        )

    provider_code = int(raw_code)
    if provider_code >= _PROVIDER_ERROR_MIN:
        raise ProviderError(
            code="provider_error",
            message=f"provider returned API status {provider_code}",
            details={
                "source_url": source_url,
                "endpoint": endpoint,
                "http_status": http_status,
                "provider_status": provider_code,
                "byte_count": byte_count,
            },
        )

    return provider_code


class _FxTwitterClient:
    def __init__(
        self, transport: Transport, base_url: str, timeout_seconds: float
    ) -> None:
        self._transport = transport
        self._base_url = validate_base_url(base_url)
        self._timeout = validate_timeout(timeout_seconds)

    def request_json(
        self, endpoint: str, params: Sequence[tuple[str, str]] | None = None
    ) -> FetchResult:
        try:
            source_url = build_url(self._base_url, endpoint, params)
        except (CliError, ProviderError):
            raise
        except Exception as err:
            raise ProviderError(
                code="invalid_endpoint",
                message="failed to construct request URL",
                details={"reason": compact_text(err)},
            ) from err

        request = urllib.request.Request(  # noqa: S310 - base URL is restricted to validated HTTPS
            source_url,
            headers={
                "accept": "application/json",
                "user-agent": "x-research/1",
            },
            method="GET",
        )

        try:
            http_status, text = self._transport(request, self._timeout)
        except (CliError, ProviderError):
            raise
        except Exception as err:
            raise ProviderError(
                code="network_error",
                message="provider request failed",
                details={
                    "source_url": source_url,
                    "endpoint": endpoint,
                    "reason": compact_text(err),
                },
            ) from err

        if http_status < _HTTP_SUCCESS_MIN or http_status >= _HTTP_SUCCESS_MAX:
            raise ProviderError(
                code="http_error",
                message=f"provider returned HTTP {http_status}",
                details={
                    "source_url": source_url,
                    "endpoint": endpoint,
                    "http_status": http_status,
                },
            )

        try:
            payload, byte_count = _decode_payload(
                text, source_url, endpoint, http_status
            )
        except (CliError, ProviderError):
            raise
        except Exception as err:
            raise ProviderError(
                code="invalid_json",
                message="provider response was not valid JSON",
                details={
                    "source_url": source_url,
                    "endpoint": endpoint,
                    "http_status": http_status,
                },
            ) from err

        try:
            provider_status = _check_provider_status(
                payload, http_status, source_url, endpoint, byte_count
            )
        except (CliError, ProviderError):
            raise
        except Exception as err:
            raise ProviderError(
                code="invalid_payload",
                message="provider response validation failed",
                details={
                    "source_url": source_url,
                    "endpoint": endpoint,
                    "http_status": http_status,
                },
            ) from err

        fetched_at = (
            datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        )

        return {
            "payload": payload,
            "bytes": byte_count,
            "http_status": http_status,
            "provider_status": provider_status,
            "source_url": source_url,
            "endpoint": endpoint,
            "fetched_at": fetched_at,
        }


def urllib_transport(
    request: urllib.request.Request, timeout: float
) -> tuple[int, str]:
    """Production transport: one stdlib ``urlopen`` GET, body as UTF-8 text."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - base URL is restricted to validated HTTPS
            body = response.read()
            return response.getcode(), body.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code, ""


def make_fx_twitter_client(
    transport: Transport,
    base_url: str,
    timeout_seconds: float = DEFAULT_TIMEOUT,
) -> FxTwitterClient:
    return _FxTwitterClient(transport, base_url, timeout_seconds)


def live_client() -> FxTwitterClient:
    """Build the production client, honoring ``X_RESEARCH_BASE_URL``."""
    configured_base_url = os.environ.get("X_RESEARCH_BASE_URL", DEFAULT_BASE_URL)
    return make_fx_twitter_client(
        urllib_transport, configured_base_url, DEFAULT_TIMEOUT
    )
