"""Deterministic, read-only FxTwitter v2 JSON transport."""
# ruff: noqa: CPY001, D202, EM101, EM102, FURB188, PLR0913, PLR2004, S310, TC003, TRY003

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

DEFAULT_BASE_URL: Final[str] = "https://api.fxtwitter.com"
DEFAULT_TIMEOUT: Final[float] = 10.0
_MAX_TIMEOUT: Final[float] = 60.0
_MAX_REASON_LENGTH: Final[int] = 160
_CONTROL_CHAR_MIN: Final[int] = 32
_CONTROL_CHAR_MAX: Final[int] = 127
_HTTP_STATUS_MIN: Final[int] = 100
_HTTP_STATUS_MAX: Final[int] = 599
_HTTP_ERROR_STATUS: Final[int] = 400
_DEFAULT_HTTP_STATUS: Final[int] = 200


class _ReadableResponse(Protocol):
    def read(self) -> bytes: ...

    def close(self) -> None: ...


class ProviderError(Exception):
    """A stable, JSON-compatible provider or transport failure."""

    code: str
    message: str
    details: dict[str, object]

    def __init__(
        self,
        code: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        """Initialize a stable provider error with JSON-safe details."""
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Decoded provider output and the request metadata that produced it."""

    payload: object
    source_url: str
    endpoint: str
    http_status: int
    provider_status: int | None
    fetched_at: str


def _details(
    *,
    source_url: str | None = None,
    endpoint: str | None = None,
    http_status: int | None = None,
    provider_status: int | None = None,
    byte_count: int | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    """Build small, predictable error details without including response bodies."""

    result: dict[str, object] = {}
    if source_url is not None:
        result["source_url"] = source_url
    if endpoint is not None:
        result["endpoint"] = endpoint
    if http_status is not None:
        result["http_status"] = http_status
    if provider_status is not None:
        result["provider_status"] = provider_status
    if byte_count is not None:
        result["bytes"] = byte_count
    if reason:
        result["reason"] = _compact_text(reason)
    return result


def _compact_text(value: object) -> str:
    """Keep exception/provider text bounded and single-line."""

    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) > _MAX_REASON_LENGTH:
        return text[: _MAX_REASON_LENGTH - 1] + "…"
    return text


def _invalid(code: str, message: str, **details: object) -> ProviderError:
    return ProviderError(code, message, details)


def _validate_base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url:
        raise _invalid("invalid_base_url", "base URL must be a non-empty HTTPS URL")
    if base_url != base_url.strip() or any(
        ord(char) < _CONTROL_CHAR_MIN for char in base_url
    ):
        raise _invalid(
            "invalid_base_url", "base URL must not contain surrounding whitespace"
        )

    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise _invalid(
            "invalid_base_url",
            "base URL is malformed",
            reason=_compact_text(exc),
        ) from exc

    if parsed.scheme.lower() != "https" or not parsed.netloc or not hostname:
        raise _invalid("invalid_base_url", "base URL must use HTTPS and include a host")
    if parsed.username is not None or parsed.password is not None:
        raise _invalid("invalid_base_url", "base URL must not include credentials")
    if parsed.query or parsed.fragment:
        raise _invalid(
            "invalid_base_url", "base URL must not include a query or fragment"
        )

    # A trailing slash is removed exactly once so a deployment under a path is
    # retained while joining endpoint paths remains deterministic.
    return base_url[:-1] if base_url.endswith("/") else base_url


def _validate_timeout(timeout: float) -> float:
    if isinstance(timeout, bool):
        raise _invalid("invalid_timeout", "timeout must be a finite positive number")
    try:
        value = float(timeout)
    except (TypeError, ValueError) as exc:
        raise _invalid(
            "invalid_timeout", "timeout must be a finite positive number"
        ) from exc
    if not math.isfinite(value) or value <= 0 or value > _MAX_TIMEOUT:
        raise _invalid(
            "invalid_timeout",
            f"timeout must be greater than 0 and at most {_MAX_TIMEOUT:g} seconds",
        )
    return value


def _validate_endpoint(endpoint: str) -> str:
    if not isinstance(endpoint, str) or not endpoint or not endpoint.startswith("/"):
        raise _invalid("invalid_endpoint", "endpoint must be a non-empty absolute path")
    if endpoint.startswith("//"):
        raise _invalid(
            "invalid_endpoint", "endpoint must not be a network-path reference"
        )
    if any(
        ord(char) < _CONTROL_CHAR_MIN or ord(char) == _CONTROL_CHAR_MAX
        for char in endpoint
    ):
        raise _invalid("invalid_endpoint", "endpoint contains a control character")

    try:
        parsed = urlsplit(endpoint)
    except ValueError as exc:
        raise _invalid("invalid_endpoint", "endpoint is malformed") from exc
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise _invalid("invalid_endpoint", "endpoint must contain only a path")
    return endpoint


def _validate_params(params: Sequence[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    if isinstance(params, (str, bytes)):
        raise _invalid(
            "invalid_endpoint", "query parameters must be a sequence of pairs"
        )
    try:
        pairs = tuple(params)
    except TypeError as exc:
        raise _invalid(
            "invalid_endpoint", "query parameters must be a sequence of pairs"
        ) from exc

    for pair in pairs:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise _invalid(
                "invalid_endpoint", "query parameters must be pairs of strings"
            )
        key, value = pair
        if not isinstance(key, str) or not isinstance(value, str):
            raise _invalid(
                "invalid_endpoint", "query parameter names and values must be strings"
            )
    return pairs


def _build_url(base_url: str, endpoint: str, params: Sequence[tuple[str, str]]) -> str:
    endpoint = _validate_endpoint(endpoint)
    pairs = _validate_params(params)
    query = urlencode(pairs, doseq=False)
    return f"{base_url}{endpoint}" + (f"?{query}" if query else "")


def _http_status(response: object, default: int = _DEFAULT_HTTP_STATUS) -> int:
    """Read a response status while tolerating tiny deterministic test doubles."""

    status: object = getattr(response, "status", None)
    if status is None:
        getcode = getattr(response, "getcode", None)
        status = getcode() if callable(getcode) else None
    if isinstance(status, bool):
        return default
    try:
        value = int(status) if status is not None else default
    except (TypeError, ValueError):
        return default
    return value if _HTTP_STATUS_MIN <= value <= _HTTP_STATUS_MAX else default


def _body_bytes(body: object) -> tuple[str, int]:
    if isinstance(body, bytes):
        return body.decode("utf-8"), len(body)
    if isinstance(body, bytearray):
        data = bytes(body)
        return data.decode("utf-8"), len(data)
    if isinstance(body, memoryview):
        data = body.tobytes()
        return data.decode("utf-8"), len(data)
    if isinstance(body, str):
        return body, len(body.encode("utf-8"))
    raise TypeError("response body is not bytes")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def _decode_payload(body: object) -> tuple[object, int]:
    text, byte_count = _body_bytes(body)
    payload = json.loads(text, parse_constant=_reject_json_constant)
    return payload, byte_count


def _provider_status(
    payload: Mapping[str, object],
    *,
    http_status: int,
    source_url: str,
    endpoint: str,
    byte_count: int,
) -> int:
    if "code" not in payload:
        return http_status
    code = payload["code"]
    if isinstance(code, bool) or not isinstance(code, int):
        raise ProviderError(
            "invalid_payload",
            "provider status code is malformed",
            _details(
                source_url=source_url,
                endpoint=endpoint,
                http_status=http_status,
                byte_count=byte_count,
            ),
        )
    return code


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class FxTwitterClient:
    """One-shot FxTwitter v2 JSON client with no retries or fallback providers."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize a validated base URL and bounded request timeout."""
        self.base_url = _validate_base_url(base_url)
        self.timeout = _validate_timeout(timeout)

    def request_json(
        self,
        endpoint: str,
        params: Sequence[tuple[str, str]] = (),
    ) -> FetchResult:
        """Fetch and decode one JSON endpoint request."""

        source_url = _build_url(self.base_url, endpoint, params)
        endpoint = _validate_endpoint(endpoint)
        request = Request(
            source_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "x-research/1",
            },
            method="GET",
        )

        response: _ReadableResponse | None = None
        try:
            response = urlopen(request, timeout=self.timeout)
            http_status = _http_status(response)
            body = response.read()
        except HTTPError as exc:
            raw_code = getattr(exc, "code", _HTTP_ERROR_STATUS)
            default_status = (
                raw_code if isinstance(raw_code, int) else _HTTP_ERROR_STATUS
            )
            status = _http_status(exc, default=default_status)
            raise ProviderError(
                "http_error",
                f"provider returned HTTP {status}",
                _details(source_url=source_url, endpoint=endpoint, http_status=status),
            ) from exc
        except OSError as exc:
            raise ProviderError(
                "network_error",
                "provider request failed",
                _details(
                    source_url=source_url,
                    endpoint=endpoint,
                    reason=_compact_text(getattr(exc, "reason", exc)),
                ),
            ) from exc
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    with suppress(OSError):
                        close()

        if http_status >= _HTTP_ERROR_STATUS:
            raise ProviderError(
                "http_error",
                f"provider returned HTTP {http_status}",
                _details(
                    source_url=source_url, endpoint=endpoint, http_status=http_status
                ),
            )

        try:
            payload, byte_count = _decode_payload(body)
        except (UnicodeDecodeError, TypeError, ValueError) as exc:
            byte_count = (
                len(body)
                if isinstance(body, (bytes, bytearray, memoryview, str))
                else None
            )
            raise ProviderError(
                "invalid_json",
                "provider response was not valid JSON",
                _details(
                    source_url=source_url,
                    endpoint=endpoint,
                    http_status=http_status,
                    byte_count=byte_count,
                ),
            ) from exc

        if not isinstance(payload, dict):
            raise ProviderError(
                "invalid_payload",
                "provider response must be a JSON object",
                _details(
                    source_url=source_url,
                    endpoint=endpoint,
                    http_status=http_status,
                    byte_count=byte_count,
                ),
            )

        provider_status = _provider_status(
            payload,
            http_status=http_status,
            source_url=source_url,
            endpoint=endpoint,
            byte_count=byte_count,
        )
        if provider_status >= _HTTP_ERROR_STATUS:
            raise ProviderError(
                "provider_error",
                f"provider returned API status {provider_status}",
                _details(
                    source_url=source_url,
                    endpoint=endpoint,
                    http_status=http_status,
                    provider_status=provider_status,
                    byte_count=byte_count,
                ),
            )

        return FetchResult(
            payload=payload,
            source_url=source_url,
            endpoint=endpoint,
            http_status=http_status,
            provider_status=provider_status,
            fetched_at=_utc_timestamp(),
        )


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_TIMEOUT",
    "FetchResult",
    "FxTwitterClient",
    "ProviderError",
]
