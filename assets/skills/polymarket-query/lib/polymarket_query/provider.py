"""Bounded, anonymous transport for the Polymarket public APIs."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import (
    HTTPDefaultErrorHandler,
    HTTPErrorProcessor,
    HTTPRedirectHandler,
    HTTPSHandler,
    OpenerDirector,
    ProxyHandler,
    Request,
    UnknownHandler,
)

DEFAULT_TIMEOUT: Final[float] = 10.0
MAX_TIMEOUT: Final[float] = 60.0
MAX_BODY_BYTES: Final[int] = 4_000_000

GAMMA_HOST: Final[str] = "gamma-api.polymarket.com"
CLOB_HOST: Final[str] = "clob.polymarket.com"
DATA_HOST: Final[str] = "data-api.polymarket.com"
USER_AGENT: Final[str] = "polymarket-query/1"

_PROVIDER_HOSTS: Final[dict[str, str]] = {
    "gamma": GAMMA_HOST,
    "clob": CLOB_HOST,
    "data": DATA_HOST,
}
_HOST_PROVIDER: Final[dict[str, str]] = {
    host: provider for provider, host in _PROVIDER_HOSTS.items()
}

_ROUTE_QUERY_KEYS: Final[dict[str, frozenset[str]]] = {
    "/markets/keyset": frozenset(
        {
            "limit",
            "after_cursor",
            "order",
            "ascending",
            "closed",
            "id",
            "slug",
            "clob_token_ids",
            "condition_ids",
            "tag_id",
            "liquidity_num_min",
            "liquidity_num_max",
            "volume_num_min",
            "volume_num_max",
            "decimalized",
            "related_tags",
            "tag_match",
            "include_tag",
        },
    ),
    "/events/keyset": frozenset(
        {
            "limit",
            "after_cursor",
            "order",
            "ascending",
            "closed",
            "live",
            "featured",
            "id",
            "slug",
            "title_search",
            "liquidity_min",
            "liquidity_max",
            "volume_min",
            "volume_max",
            "tag_id",
            "tag_slug",
            "exclude_tag_id",
            "related_tags",
            "tag_match",
            "series_id",
            "game_id",
            "recurrence",
            "event_date",
            "event_week",
        },
    ),
    "/public-search": frozenset(
        {
            "q",
            "limit_per_type",
            "page",
            "events_status",
            "events_tag",
            "keep_closed_markets",
            "sort",
            "ascending",
            "search_profiles",
            "search_tags",
            "recurrence",
            "exclude_tag_id",
            "optimized",
            "cache",
        },
    ),
    "/markets/{id}": frozenset({"include_tag"}),
    "/markets/slug/{slug}": frozenset({"include_tag"}),
    "/events/{id}": frozenset(),
    "/events/slug/{slug}": frozenset(),
    "/markets-by-token/{token_id}": frozenset(),
    "/clob-markets/{condition_id}": frozenset(),
    "/book": frozenset({"token_id"}),
    "/price": frozenset({"token_id", "side"}),
    "/midpoint": frozenset({"token_id"}),
    "/last-trade-price": frozenset({"token_id"}),
    "/prices-history": frozenset(
        {"market", "startTs", "endTs", "interval", "fidelity"},
    ),
    "/live-volume": frozenset({"id"}),
    "/oi": frozenset({"market"}),
}

_ROUTE_PROVIDERS: Final[dict[str, str]] = {
    "/markets/keyset": "gamma",
    "/events/keyset": "gamma",
    "/public-search": "gamma",
    "/markets/{id}": "gamma",
    "/markets/slug/{slug}": "gamma",
    "/events/{id}": "gamma",
    "/events/slug/{slug}": "gamma",
    "/markets-by-token/{token_id}": "clob",
    "/clob-markets/{condition_id}": "clob",
    "/book": "clob",
    "/price": "clob",
    "/midpoint": "clob",
    "/last-trade-price": "clob",
    "/prices-history": "clob",
    "/live-volume": "data",
    "/oi": "data",
}

_PERCENT_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")
_CONDITION_ID = re.compile(r"0x[0-9A-Fa-f]{64}")


class _ReadableResponse(Protocol):
    def read(self, *args: int) -> bytes: ...

    def close(self) -> None: ...


class ProviderError(Exception):
    """A stable, bounded, JSON-compatible provider or transport failure."""

    code: str
    message: str
    details: dict[str, object]

    def __init__(
        self,
        code: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = _compact_text(code)
        self.message = _compact_text(message)
        self.details = dict(details or {})
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class FetchResult:
    payload: object
    source_url: str
    endpoint: str
    http_status: int
    fetched_at: str


def _compact_text(value: object, limit: int = 160) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _error(
    code: str,
    message: str,
    *,
    source_url: str | None = None,
    endpoint: str | None = None,
    http_status: int | None = None,
    byte_count: int | None = None,
    reason: object | None = None,
    final_url: object | None = None,
) -> ProviderError:
    details: dict[str, object] = {}
    if source_url is not None:
        details["source_url"] = _compact_text(source_url)
    if endpoint is not None:
        details["endpoint"] = _compact_text(endpoint)
    if http_status is not None:
        details["http_status"] = http_status
    if byte_count is not None:
        details["bytes"] = byte_count
    if reason is not None:
        details["reason"] = _compact_text(reason)
    if final_url is not None:
        details["final_url"] = _compact_text(final_url)
    return ProviderError(code, message, details)


def _is_control(value: str) -> bool:
    return any(
        ord(char) < 32 or ord(char) == 127 or unicodedata.category(char) == "Cc"
        for char in value
    )


def _validate_timeout(timeout: object) -> float:
    if isinstance(timeout, bool) or not isinstance(
        timeout,
        (int, float, str, bytes, bytearray),
    ):
        raise _error(
            "invalid_timeout", "timeout must be a finite number from 1 to 60 seconds"
        )
    try:
        value = float(timeout)
    except (TypeError, ValueError) as exc:
        raise _error(
            "invalid_timeout",
            "timeout must be a finite number from 1 to 60 seconds",
        ) from exc
    if not math.isfinite(value) or value < 1.0 or value > MAX_TIMEOUT:
        raise _error(
            "invalid_timeout",
            "timeout must be a finite number from 1 to 60 seconds",
        )
    return value


def _validate_provider(provider: object) -> tuple[str, str]:
    if not isinstance(provider, str) or provider != provider.strip():
        raise _error("invalid_provider", "provider must be gamma, clob, or data")
    if provider in _PROVIDER_HOSTS:
        return provider, _PROVIDER_HOSTS[provider]
    if provider in _HOST_PROVIDER:
        return _HOST_PROVIDER[provider], provider
    raise _error("invalid_provider", "provider must be gamma, clob, or data")


def _validate_percent_escapes(value: str) -> None:
    index = 0
    while index < len(value):
        if value[index] == "%":
            if index + 2 >= len(value) or not _PERCENT_ESCAPE.fullmatch(
                value[index : index + 3],
            ):
                raise _error("invalid_endpoint", "endpoint contains an invalid escape")
            index += 3
        else:
            index += 1


def _validate_path_segment(segment: str, *, condition_id: bool = False) -> bool:
    if not segment or "/" in segment or "\\" in segment:
        return False
    if any(char.isspace() for char in segment) or _is_control(segment):
        return False
    try:
        _validate_percent_escapes(segment)
    except ProviderError:
        return False
    for match in re.finditer(r"%([0-9A-Fa-f]{2})", segment):
        decoded = int(match.group(1), 16)
        if decoded < 32 or decoded == 127 or decoded in {35, 47, 63, 92}:
            return False
    if condition_id:
        return _CONDITION_ID.fullmatch(segment) is not None
    return True


def _match_route(endpoint: str) -> tuple[str, frozenset[str]] | None:
    if endpoint in _ROUTE_PROVIDERS:
        return endpoint, _ROUTE_QUERY_KEYS[endpoint]

    match = re.fullmatch(r"/markets/([0-9]+)", endpoint)
    if match is not None and match.group(1).lstrip("0"):
        route = "/markets/{id}"
        return route, _ROUTE_QUERY_KEYS[route]

    if endpoint.startswith("/markets/slug/"):
        segment = endpoint[len("/markets/slug/") :]
        if _validate_path_segment(segment):
            route = "/markets/slug/{slug}"
            return route, _ROUTE_QUERY_KEYS[route]

    match = re.fullmatch(r"/events/([0-9]+)", endpoint)
    if match is not None and match.group(1).lstrip("0"):
        route = "/events/{id}"
        return route, _ROUTE_QUERY_KEYS[route]

    if endpoint.startswith("/events/slug/"):
        segment = endpoint[len("/events/slug/") :]
        if _validate_path_segment(segment):
            route = "/events/slug/{slug}"
            return route, _ROUTE_QUERY_KEYS[route]

    if endpoint.startswith("/markets-by-token/"):
        segment = endpoint[len("/markets-by-token/") :]
        if _validate_path_segment(segment):
            route = "/markets-by-token/{token_id}"
            return route, _ROUTE_QUERY_KEYS[route]

    if endpoint.startswith("/clob-markets/"):
        segment = endpoint[len("/clob-markets/") :]
        if _validate_path_segment(segment, condition_id=True):
            route = "/clob-markets/{condition_id}"
            return route, _ROUTE_QUERY_KEYS[route]

    return None


def _validate_endpoint(endpoint: object) -> tuple[str, frozenset[str]]:
    if not isinstance(endpoint, str) or not endpoint or endpoint != endpoint.strip():
        raise _error("invalid_endpoint", "endpoint must be a fixed absolute path")
    if not endpoint.startswith("/") or endpoint.startswith("//"):
        raise _error("invalid_endpoint", "endpoint must be a fixed absolute path")
    if _is_control(endpoint) or any(char.isspace() for char in endpoint):
        raise _error("invalid_endpoint", "endpoint contains a control character")
    if "\\" in endpoint:
        raise _error("invalid_endpoint", "endpoint contains an invalid path character")
    try:
        parsed = urlsplit(endpoint)
    except ValueError as exc:
        raise _error("invalid_endpoint", "endpoint is malformed", reason=exc) from exc
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise _error(
            "invalid_endpoint", "endpoint must contain only an allowlisted path"
        )
    _validate_percent_escapes(endpoint)
    matched = _match_route(endpoint)
    if matched is None:
        raise _error(
            "invalid_endpoint", "endpoint is not allowlisted", endpoint=endpoint
        )
    return matched


def _validate_params(
    params: object,
    allowed: frozenset[str],
) -> tuple[tuple[str, str], ...]:
    if isinstance(params, (str, bytes, bytearray)) or not isinstance(params, Iterable):
        raise _error("invalid_query", "query parameters must be pairs of strings")
    pairs = tuple(params)
    checked: list[tuple[str, str]] = []
    for pair in pairs:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise _error("invalid_query", "query parameters must be pairs of strings")
        key, value = pair
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or not key
            or _is_control(key)
            or _is_control(value)
            or any(char.isspace() for char in key)
            or key not in allowed
        ):
            raise _error("invalid_query", "query parameter is not allowlisted")
        checked.append((key, value))
    return tuple(checked)


def _build_url(
    host: str,
    endpoint: str,
    params: Sequence[tuple[str, str]],
    allowed: frozenset[str],
) -> str:
    checked_endpoint, _ = _validate_endpoint(endpoint)
    del checked_endpoint
    checked_params = _validate_params(params, allowed)
    query = urlencode(checked_params, doseq=False)
    return f"https://{host}{endpoint}" + (f"?{query}" if query else "")


def _status(response: object, default: int = 200) -> int:
    raw = getattr(response, "status", None)
    if raw is None:
        getter = getattr(response, "getcode", None)
        raw = getter() if callable(getter) else None
    if isinstance(raw, bool) or not isinstance(
        raw,
        (int, str, bytes, bytearray),
    ):
        raise _error("invalid_response", "response status is malformed")
    try:
        result = int(raw)
    except (TypeError, ValueError) as exc:
        raise _error("invalid_response", "response status is malformed") from exc
    if result < 100 or result > 599:
        raise _error("invalid_response", "response status is malformed")
    return result


def _header(response: object, name: str) -> object | None:
    headers = getattr(response, "headers", None)
    if headers is not None:
        getter = getattr(headers, "get", None)
        if callable(getter):
            try:
                value = getter(name)
            except (AttributeError, TypeError, ValueError):
                value = None
            if value is not None:
                return value
        items = getattr(headers, "items", None)
        if callable(items):
            try:
                raw_items = items()
                if isinstance(raw_items, Iterable):
                    for entry in raw_items:
                        if (
                            isinstance(entry, tuple)
                            and len(entry) == 2
                            and isinstance(entry[0], str)
                            and entry[0].lower() == name.lower()
                        ):
                            return entry[1]
            except (AttributeError, TypeError, ValueError):
                pass
    getter = getattr(response, "getheader", None)
    if callable(getter):
        try:
            return getter(name)
        except (AttributeError, TypeError, ValueError):
            return None
    return None


def _response_url(response: object) -> object | None:
    getter = getattr(response, "geturl", None)
    if callable(getter):
        return getter()
    return getattr(response, "url", None)


def _validate_response_identity(
    response: object,
    source_url: str,
    host: str,
    endpoint: str,
) -> None:
    location = _header(response, "Location")
    if location is not None:
        raise _error(
            "redirect_error",
            "provider response attempted a redirect",
            source_url=source_url,
            endpoint=endpoint,
            reason="Location header present",
            final_url=location,
        )
    final_url = _response_url(response)
    if final_url is None:
        return
    if not isinstance(final_url, str):
        raise _error(
            "redirect_error",
            "provider response final URL is malformed",
            source_url=source_url,
            endpoint=endpoint,
            final_url=final_url,
        )
    try:
        parsed = urlsplit(final_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise _error(
            "redirect_error",
            "provider response final URL is malformed",
            source_url=source_url,
            endpoint=endpoint,
            reason=exc,
            final_url=final_url,
        ) from exc
    expected = urlsplit(source_url)
    same_request = final_url == source_url or (
        parsed.scheme.lower() == "https"
        and hostname == host
        and port == 443
        and parsed.path == expected.path
        and parsed.query == expected.query
        and parsed.fragment == expected.fragment
    )
    if (
        parsed.scheme.lower() != "https"
        or hostname != host
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and port != 443)
        or not same_request
    ):
        raise _error(
            "redirect_error",
            "provider response final URL does not match the request",
            source_url=source_url,
            endpoint=endpoint,
            final_url=final_url,
        )


def _content_length(response: object, source_url: str, endpoint: str) -> int | None:
    raw = _header(response, "Content-Length")
    if raw is None:
        return None
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise _error(
                "invalid_response",
                "Content-Length is malformed",
                source_url=source_url,
                endpoint=endpoint,
            ) from exc
    if not isinstance(raw, str):
        raw = str(raw)
    value = raw.strip()
    if not value or not value.isascii() or not value.isdecimal():
        raise _error(
            "invalid_response",
            "Content-Length is malformed",
            source_url=source_url,
            endpoint=endpoint,
        )
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise _error(
            "invalid_response",
            "Content-Length is malformed",
            source_url=source_url,
            endpoint=endpoint,
        ) from exc
    if size > MAX_BODY_BYTES:
        raise _error(
            "response_too_large",
            "provider response exceeds the byte limit",
            source_url=source_url,
            endpoint=endpoint,
            byte_count=size,
        )
    return size


def _coerce_body(body: object, source_url: str, endpoint: str) -> bytes:
    if isinstance(body, bytes):
        data = body
    elif isinstance(body, bytearray):
        data = bytes(body)
    elif isinstance(body, memoryview):
        data = body.tobytes()
    elif isinstance(body, str):
        try:
            data = body.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise _error(
                "invalid_json",
                "provider response was not valid UTF-8 JSON",
                source_url=source_url,
                endpoint=endpoint,
            ) from exc
    else:
        raise _error(
            "invalid_response",
            "provider response body is not bytes",
            source_url=source_url,
            endpoint=endpoint,
        )
    if len(data) > MAX_BODY_BYTES:
        raise _error(
            "response_too_large",
            "provider response exceeds the byte limit",
            source_url=source_url,
            endpoint=endpoint,
            byte_count=len(data),
        )
    return data


def _read_body(response: _ReadableResponse, source_url: str, endpoint: str) -> bytes:
    _content_length(response, source_url, endpoint)
    reader = getattr(response, "read", None)
    if not callable(reader):
        raise _error(
            "invalid_response",
            "provider response is not readable",
            source_url=source_url,
            endpoint=endpoint,
        )
    try:
        try:
            body = reader(MAX_BODY_BYTES + 1)
        except TypeError:
            body = reader()
    except (OSError, TimeoutError, URLError) as exc:
        raise _error(
            "network_error",
            "provider response read failed",
            source_url=source_url,
            endpoint=endpoint,
            reason=getattr(exc, "reason", exc),
        ) from exc
    data = _coerce_body(body, source_url, endpoint)
    if len(data) == MAX_BODY_BYTES + 1:
        raise _error(
            "response_too_large",
            "provider response exceeds the byte limit",
            source_url=source_url,
            endpoint=endpoint,
            byte_count=len(data),
        )
    return data


def _close_response(response: object | None) -> None:
    if response is None:
        return
    close = getattr(response, "close", None)
    if callable(close):
        with suppress(OSError, ValueError):
            close()
        return
    exit_method = getattr(response, "__exit__", None)
    if callable(exit_method):
        with suppress(Exception):
            exit_method(None, None, None)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite JSON number")
    return number


def _decode_json(data: bytes, source_url: str, endpoint: str) -> object:
    try:
        text = data.decode("utf-8")
        payload = json.loads(
            text,
            parse_constant=_reject_json_constant,
            parse_float=_finite_float,
        )
    except (UnicodeDecodeError, TypeError, ValueError) as exc:
        raise _error(
            "invalid_json",
            "provider response was not valid UTF-8 JSON",
            source_url=source_url,
            endpoint=endpoint,
            byte_count=len(data),
        ) from exc
    if not isinstance(payload, (dict, list)):
        raise _error(
            "invalid_payload",
            "provider response JSON root must be an object or array",
            source_url=source_url,
            endpoint=endpoint,
            byte_count=len(data),
        )
    return payload


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


_NO_REDIRECT_OPENER = OpenerDirector()
for _handler in (
    ProxyHandler({}),
    UnknownHandler(),
    HTTPSHandler(),
    HTTPDefaultErrorHandler(),
    _NoRedirectHandler(),
    HTTPErrorProcessor(),
):
    _NO_REDIRECT_OPENER.add_handler(_handler)


def urlopen(request: Request, timeout: float = DEFAULT_TIMEOUT) -> _ReadableResponse:
    return _NO_REDIRECT_OPENER.open(request, timeout=timeout)


def _http_error_status(error: HTTPError) -> int:
    raw = getattr(error, "code", None)
    if isinstance(raw, bool) or not isinstance(
        raw,
        (int, str, bytes, bytearray),
    ):
        return 500
    try:
        status = int(raw)
    except (TypeError, ValueError):
        return 500
    return status if 100 <= status <= 599 else 500


class PolymarketClient:
    def __init__(self, provider: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.provider, self.host = _validate_provider(provider)
        self.timeout = _validate_timeout(timeout)

    def get(
        self,
        endpoint: str,
        params: Sequence[tuple[str, str]] = (),
    ) -> FetchResult:
        route, allowed = _validate_endpoint(endpoint)
        expected_provider = _ROUTE_PROVIDERS[route]
        if expected_provider != self.provider:
            raise _error(
                "invalid_endpoint",
                "endpoint does not belong to the selected provider",
                endpoint=endpoint,
            )
        source_url = _build_url(self.host, endpoint, params, allowed)
        request = Request(
            source_url,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            method="GET",
        )
        response: object | None = None
        try:
            try:
                response = urlopen(request, timeout=self.timeout)
            except HTTPError as exc:
                status = _http_error_status(exc)
                location = _header(exc, "Location")
                final_url = getattr(exc, "url", None)
                _close_response(exc)
                if (
                    300 <= status < 400
                    or location is not None
                    or (final_url is not None and final_url != source_url)
                ):
                    raise _error(
                        "redirect_error",
                        "provider response attempted a redirect",
                        source_url=source_url,
                        endpoint=endpoint,
                        http_status=status,
                        reason="redirect refused",
                        final_url=location or final_url,
                    ) from exc
                raise _error(
                    "http_error",
                    f"provider returned HTTP {status}",
                    source_url=source_url,
                    endpoint=endpoint,
                    http_status=status,
                ) from exc
            except (URLError, TimeoutError, OSError) as exc:
                raise _error(
                    "network_error",
                    "provider request failed",
                    source_url=source_url,
                    endpoint=endpoint,
                    reason=getattr(exc, "reason", exc),
                ) from exc

            status = _status(response)
            _validate_response_identity(response, source_url, self.host, endpoint)
            if 300 <= status < 400:
                raise _error(
                    "redirect_error",
                    "provider response attempted a redirect",
                    source_url=source_url,
                    endpoint=endpoint,
                    http_status=status,
                )
            if status >= 400:
                raise _error(
                    "http_error",
                    f"provider returned HTTP {status}",
                    source_url=source_url,
                    endpoint=endpoint,
                    http_status=status,
                )
            if status < 200:
                raise _error(
                    "http_error",
                    f"provider returned HTTP {status}",
                    source_url=source_url,
                    endpoint=endpoint,
                    http_status=status,
                )
            body = _read_body(response, source_url, endpoint)
        finally:
            _close_response(response)

        payload = _decode_json(body, source_url, endpoint)
        return FetchResult(
            payload=payload,
            source_url=source_url,
            endpoint=endpoint,
            http_status=status,
            fetched_at=_utc_now(),
        )


__all__ = [
    "CLOB_HOST",
    "DATA_HOST",
    "DEFAULT_TIMEOUT",
    "GAMMA_HOST",
    "MAX_BODY_BYTES",
    "MAX_TIMEOUT",
    "FetchResult",
    "PolymarketClient",
    "ProviderError",
    "_utc_now",
    "urlopen",
]
