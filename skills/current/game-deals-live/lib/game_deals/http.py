"""Redacting JSON HTTP transport implemented with the standard library."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .errors import ProviderError

SECRET_QUERY_NAMES = frozenset(
    {"key", "apikey", "api_key", "token", "access_token", "auth", "secret"},
)
SECRET_QUERY_RE = re.compile(
    r"(?i)([?&](?:key|apikey|api_key|token|access_token|auth|secret)=)[^&#\s\"']+",
)
SECRET_HEADER_NAMES = frozenset(
    {"authorization", "itad-api-key", "x-api-key", "api-key"},
)


def redact_url(url: str) -> str:
    """Redact sensitive query values while retaining useful request context."""
    parts = urlsplit(url)
    safe_query = [
        (name, "[REDACTED]" if name.casefold() in SECRET_QUERY_NAMES else value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(safe_query), ""),
    )


def redact_data(value: Any) -> Any:
    """Remove secret-shaped keys and query values from provider payloads."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if str(key).casefold() in SECRET_QUERY_NAMES else redact_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, str):
        return SECRET_QUERY_RE.sub(r"\1[REDACTED]", value)
    return value


def parse_retry_after(
    value: str | None,
    *,
    now: datetime | None = None,
) -> float | None:
    """Parse Retry-After seconds or HTTP date."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        current = now or datetime.now(UTC)
        return max(0.0, (when - current).total_seconds())


@dataclass(frozen=True)
class JsonResponse:
    """Transport result retained by provider snapshots."""

    data: Any
    status: int
    safe_url: str
    headers: Mapping[str, str]


class HttpClient:
    """Tiny injectable JSON client with one Retry-After retry."""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        sleep: Callable[[float], None] = time.sleep,
        opener: Callable[..., Any] = urlopen,
        max_retries: int = 1,
    ) -> None:
        self.timeout = timeout
        self.sleep = sleep
        self.opener = opener
        self.max_retries = max_retries

    def request_json(
        self,
        method: str,
        base_url: str,
        *,
        provider: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        body: Any | None = None,
    ) -> JsonResponse:
        """Issue a JSON request and convert transport failures to safe errors."""
        query = urlencode(
            [(key, value) for key, value in (params or {}).items() if value is not None],
            doseq=True,
        )
        url = f"{base_url}{'&' if '?' in base_url else '?'}{query}" if query else base_url
        safe_url = redact_url(url)
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "game-deals-live/0.1 (+local executable skill)",
            **dict(headers or {}),
        }
        secret_values = {
            str(value)
            for name, value in (params or {}).items()
            if name.casefold() in SECRET_QUERY_NAMES and value
        }
        secret_values.update(
            str(value)
            for name, value in request_headers.items()
            if name.casefold() in SECRET_HEADER_NAMES and value
        )
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        for attempt in range(self.max_retries + 1):
            request = Request(url, data=payload, headers=request_headers, method=method)
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                    return JsonResponse(
                        data=redact_data(json.loads(raw)),
                        status=int(getattr(response, "status", 200)),
                        safe_url=safe_url,
                        headers=dict(response.headers.items()),
                    )
            except HTTPError as error:
                retry_after = parse_retry_after(error.headers.get("Retry-After"))
                if attempt < self.max_retries and retry_after is not None:
                    self.sleep(retry_after)
                    continue
                detail = _safe_error_detail(error, secret_values)
                raise ProviderError(
                    f"{provider} HTTP {error.code} for {safe_url}{detail}",
                    provider=provider,
                    status=error.code,
                    retry_after=retry_after,
                ) from None
            except (URLError, TimeoutError, OSError) as error:
                raise ProviderError(
                    f"{provider} request failed for {safe_url}: {error.reason if isinstance(error, URLError) else error}",
                    provider=provider,
                ) from None
            except json.JSONDecodeError as error:
                raise ProviderError(
                    f"{provider} returned invalid JSON for {safe_url}: {error.msg}",
                    provider=provider,
                ) from None
        raise AssertionError("unreachable")

    def get_json(self, url: str, **kwargs: Any) -> JsonResponse:
        """Issue a GET request."""
        return self.request_json("GET", url, **kwargs)

    def post_json(self, url: str, **kwargs: Any) -> JsonResponse:
        """Issue a POST request."""
        return self.request_json("POST", url, **kwargs)


def _safe_error_detail(error: HTTPError, secret_values: set[str]) -> str:
    try:
        body = error.read(512).decode("utf-8", errors="replace").strip()
    except OSError:
        return ""
    if not body:
        return ""
    safe_body = SECRET_QUERY_RE.sub(r"\1[REDACTED]", body)
    for secret in secret_values:
        safe_body = safe_body.replace(secret, "[REDACTED]")
        safe_body = safe_body.replace(quote_plus(secret), "[REDACTED]")
    return f": {safe_body[:300]}"
