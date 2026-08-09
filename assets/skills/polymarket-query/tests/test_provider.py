"""Deterministic transport and URL-boundary tests for polymarket_query."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Self
from urllib.error import HTTPError, URLError

if TYPE_CHECKING:
    from urllib.request import Request

import _path  # noqa: F401
import pytest
from polymarket_query import provider

FIXED_NOW = "2026-08-09T00:00:00Z"
CONDITION_ID = "0x" + "a" * 64
CONDITION_ID_2 = "0x" + "b" * 64


class Response:
    """Small urllib-compatible response fixture backed by ``BytesIO``."""

    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        final_url: str | None = None,
    ) -> None:
        self.body = io.BytesIO(body)
        self.status = status
        self.code = status
        self.headers = headers or {}
        self.final_url = final_url
        self.read_calls: list[tuple[int, ...]] = []
        self.closed = False

    def read(self, *args: int) -> bytes:
        """Read bytes using urllib's optional bounded-size argument."""
        self.read_calls.append(args)
        return self.body.read(*args)

    def geturl(self) -> str | None:
        """Return the configured final URL, if one was supplied."""
        return self.final_url

    def getcode(self) -> int:
        """Return the HTTP status through urllib's alternate status seam."""
        return self.status

    def getheader(self, name: str, default: str | None = None) -> str | None:
        """Return a case-insensitive response header value."""
        wanted = name.lower()
        return next(
            (value for key, value in self.headers.items() if key.lower() == wanted),
            default,
        )

    def __enter__(self) -> Self:
        """Support urllib response context-manager use."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Close the in-memory body at context-manager exit."""
        self.close()

    def close(self) -> None:
        """Close the in-memory body while retaining inspection metadata."""
        self.closed = True
        self.body.close()


class QueueOpener:
    """Queue deterministic responses and capture every urllib request."""

    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.requests: list[Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: Request, timeout: float = 0) -> object:
        self.requests.append(request)
        self.timeouts.append(timeout)
        if not self.responses:
            raise AssertionError("unexpected second urlopen call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def patch_urlopen(monkeypatch: pytest.MonkeyPatch, opener: QueueOpener) -> None:
    """Patch the provider transport and clock without touching the network."""
    monkeypatch.setattr(provider, "urlopen", opener)
    monkeypatch.setattr(provider, "_utc_now", lambda: FIXED_NOW)


def request_headers(request: Request) -> dict[str, str]:
    """Return all ordinary request headers case-insensitively."""
    return {name.lower(): value for name, value in request.header_items()}


ROUTE_CASES = [
    pytest.param(
        "gamma",
        "/markets/keyset",
        (
            ("limit", "2"),
            ("after_cursor", "cursor~next"),
            ("slug", "bitcoin"),
            ("slug", "ethereum"),
        ),
        "https://gamma-api.polymarket.com/markets/keyset?limit=2&after_cursor=cursor~next&slug=bitcoin&slug=ethereum",
        id="gamma-markets-keyset",
    ),
    pytest.param(
        "gamma",
        "/events/keyset",
        (("limit", "3"), ("live", "true"), ("title_search", "bitcoin price")),
        "https://gamma-api.polymarket.com/events/keyset?limit=3&live=true&title_search=bitcoin+price",
        id="gamma-events-keyset",
    ),
    pytest.param(
        "gamma",
        "/public-search",
        (
            ("q", "bitcoin price"),
            ("limit_per_type", "4"),
            ("page", "2"),
            ("search_profiles", "false"),
            ("search_tags", "true"),
        ),
        "https://gamma-api.polymarket.com/public-search?q=bitcoin+price&limit_per_type=4&page=2&search_profiles=false&search_tags=true",
        id="gamma-public-search",
    ),
    pytest.param(
        "gamma",
        "/markets/42",
        (("include_tag", "true"),),
        "https://gamma-api.polymarket.com/markets/42?include_tag=true",
        id="gamma-market-id",
    ),
    pytest.param(
        "gamma",
        "/markets/slug/bitcoin%20up",
        (("include_tag", "false"),),
        "https://gamma-api.polymarket.com/markets/slug/bitcoin%20up?include_tag=false",
        id="gamma-market-slug",
    ),
    pytest.param(
        "gamma",
        "/events/7",
        (),
        "https://gamma-api.polymarket.com/events/7",
        id="gamma-event-id",
    ),
    pytest.param(
        "gamma",
        "/events/slug/bitcoin%20daily",
        (),
        "https://gamma-api.polymarket.com/events/slug/bitcoin%20daily",
        id="gamma-event-slug",
    ),
    pytest.param(
        "clob",
        "/markets-by-token/12345678901234567890",
        (),
        "https://clob.polymarket.com/markets-by-token/12345678901234567890",
        id="clob-market-by-token",
    ),
    pytest.param(
        "clob",
        f"/clob-markets/{CONDITION_ID}",
        (),
        f"https://clob.polymarket.com/clob-markets/{CONDITION_ID}",
        id="clob-market-info",
    ),
    pytest.param(
        "clob",
        "/book",
        (("token_id", "12345678901234567890"),),
        "https://clob.polymarket.com/book?token_id=12345678901234567890",
        id="clob-book",
    ),
    pytest.param(
        "clob",
        "/price",
        (("token_id", "12345678901234567890"), ("side", "BUY")),
        "https://clob.polymarket.com/price?token_id=12345678901234567890&side=BUY",
        id="clob-price",
    ),
    pytest.param(
        "clob",
        "/midpoint",
        (("token_id", "12345678901234567890"),),
        "https://clob.polymarket.com/midpoint?token_id=12345678901234567890",
        id="clob-midpoint",
    ),
    pytest.param(
        "clob",
        "/last-trade-price",
        (("token_id", "12345678901234567890"),),
        "https://clob.polymarket.com/last-trade-price?token_id=12345678901234567890",
        id="clob-last-trade",
    ),
    pytest.param(
        "clob",
        "/prices-history",
        (("market", "12345678901234567890"), ("startTs", "100"), ("endTs", "200")),
        "https://clob.polymarket.com/prices-history?market=12345678901234567890&startTs=100&endTs=200",
        id="clob-price-history",
    ),
    pytest.param(
        "data",
        "/live-volume",
        (("id", "7"),),
        "https://data-api.polymarket.com/live-volume?id=7",
        id="data-live-volume",
    ),
    pytest.param(
        "data",
        "/oi",
        (("market", f"{CONDITION_ID},{CONDITION_ID_2}"),),
        f"https://data-api.polymarket.com/oi?market={CONDITION_ID}%2C{CONDITION_ID_2}",
        id="data-open-interest",
    ),
]


@pytest.mark.parametrize(
    ("provider_name", "endpoint", "params", "source_url"),
    ROUTE_CASES,
)
def test_allowlisted_routes_are_one_exact_anonymous_get(
    monkeypatch: pytest.MonkeyPatch,
    provider_name: str,
    endpoint: str,
    params: tuple[tuple[str, str], ...],
    source_url: str,
) -> None:
    """Every registered route uses one exact production GET request."""
    opener = QueueOpener(Response(b"{}"))
    patch_urlopen(monkeypatch, opener)

    result = provider.PolymarketClient(provider_name).get(endpoint, params)

    assert len(opener.requests) == 1
    request = opener.requests[0]
    assert request.full_url == source_url
    assert request.get_method() == "GET"
    assert request_headers(request) == {
        "accept": "application/json",
        "user-agent": provider.USER_AGENT,
    }
    assert getattr(request, "unredirected_hdrs", {}) == {}
    assert opener.timeouts == [provider.DEFAULT_TIMEOUT]
    assert result.payload == {}
    assert result.source_url == source_url
    assert result.endpoint == endpoint
    assert result.http_status == 200
    assert result.fetched_at == FIXED_NOW


def test_poisoned_environment_cannot_change_base_url_or_add_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Base URL and credential environment variables are never consulted."""
    for name in (
        "POLYMARKET_BASE_URL",
        "POLYMARKET_API_BASE",
        "POLYMARKET_API_KEY",
        "POLYMARKET_API_SECRET",
        "POLYMARKET_PRIVATE_KEY",
        "POLYMARKET_TOKEN",
        "HTTP_PROXY",
        "HTTPS_PROXY",
    ):
        monkeypatch.setenv(name, "https://attacker:secret@staging.invalid/poison")
    opener = QueueOpener(Response(b"{}"))
    patch_urlopen(monkeypatch, opener)

    result = provider.PolymarketClient("gamma").get(
        "/markets/keyset",
        (("limit", "1"),),
    )

    assert result.source_url == (
        "https://gamma-api.polymarket.com/markets/keyset?limit=1"
    )
    request = opener.requests[0]
    assert request.full_url == result.source_url
    assert request_headers(request) == {
        "accept": "application/json",
        "user-agent": provider.USER_AGENT,
    }
    assert all(
        name.lower() not in {"authorization", "cookie", "x-api-key"}
        for name, _value in request.header_items()
    )


@pytest.mark.parametrize(
    "provider_name",
    [
        "",
        "gamma ",
        " staging",
        "staging.gamma-api.polymarket.com",
        "https://gamma-api.polymarket.com",
        "https://user:secret@gamma-api.polymarket.com",
        "gamma-api.polymarket.com:443",
        "gamma-api.polymarket.com:8443",
        "http://gamma-api.polymarket.com",
    ],
)
def test_invalid_provider_is_rejected_before_opener(
    monkeypatch: pytest.MonkeyPatch,
    provider_name: str,
) -> None:
    """Only the three provider names (or exact production hosts) are accepted."""
    opener = QueueOpener(Response(b"{}"))
    patch_urlopen(monkeypatch, opener)

    with pytest.raises(provider.ProviderError) as raised:
        provider.PolymarketClient(provider_name)

    assert raised.value.code == "invalid_provider"
    assert opener.requests == []


@pytest.mark.parametrize(
    "timeout",
    [0, 0.999, 60.001, float("nan"), float("inf"), -float("inf"), True, "bad"],
)
def test_invalid_timeout_is_rejected_before_opener(
    monkeypatch: pytest.MonkeyPatch,
    timeout: object,
) -> None:
    """Timeouts outside the finite one-to-sixty-second bound fail locally."""
    opener = QueueOpener(Response(b"{}"))
    patch_urlopen(monkeypatch, opener)

    with pytest.raises(provider.ProviderError) as raised:
        provider.PolymarketClient("gamma", timeout=timeout)  # type: ignore[arg-type]

    assert raised.value.code == "invalid_timeout"
    assert opener.requests == []


@pytest.mark.parametrize(
    ("endpoint", "params", "error_code"),
    [
        ("/markets", (), "invalid_endpoint"),
        ("/events", (), "invalid_endpoint"),
        ("/geoblock", (), "invalid_endpoint"),
        ("/restricted", (), "invalid_endpoint"),
        ("/v1/market-positions", (), "invalid_endpoint"),
        ("/v1/leaderboard", (), "invalid_endpoint"),
        ("/positions", (), "invalid_endpoint"),
        ("/trades", (), "invalid_endpoint"),
        ("/holders", (), "invalid_endpoint"),
        ("/comments", (), "invalid_endpoint"),
        ("/closed-positions", (), "invalid_endpoint"),
        ("/orders", (), "invalid_endpoint"),
        ("/markets/keyset?limit=1", (), "invalid_endpoint"),
        ("/markets/keyset\n", (), "invalid_endpoint"),
        ("/markets/keyset", (("offset", "0"),), "invalid_query"),
        ("/markets/keyset", (("limit", "1"), ("unknown", "x")), "invalid_query"),
        (
            "/markets/keyset",
            (("limit", "1"), ("after_cursor", "bad\n")),
            "invalid_query",
        ),
        ("/markets/keyset", (("limit", 1),), "invalid_query"),
        ("/markets/keyset", (("limit", "1", "extra"),), "invalid_query"),
        ("/markets/keyset", {"limit": "1"}, "invalid_query"),
        ("/markets/keyset", "limit=1", "invalid_query"),
        ("/book", (), "invalid_endpoint"),
    ],
)
def test_invalid_route_or_query_fails_before_opener(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    params: object,
    error_code: str,
) -> None:
    """Legacy, private, cross-provider, and malformed inputs never reach transport."""
    opener = QueueOpener(Response(b"{}"))
    patch_urlopen(monkeypatch, opener)
    client = provider.PolymarketClient("gamma")

    with pytest.raises(provider.ProviderError) as raised:
        client.get(endpoint, params)  # type: ignore[arg-type]

    assert raised.value.code == error_code
    assert opener.requests == []


@pytest.mark.parametrize(
    "final_url",
    [
        "https://staging.gamma-api.polymarket.com/markets/keyset?limit=1",
        "https://user:secret@gamma-api.polymarket.com/markets/keyset?limit=1",
        "https://gamma-api.polymarket.com:8443/markets/keyset?limit=1",
        "http://gamma-api.polymarket.com/markets/keyset?limit=1",
        "https://gamma-api.polymarket.com/events/keyset?limit=1",
        "https://gamma-api.polymarket.com/markets/keyset?limit=2",
    ],
)
def test_response_final_url_must_match_exact_https_request(
    monkeypatch: pytest.MonkeyPatch,
    final_url: str,
) -> None:
    """Staging, userinfo, non-default ports, path, and query redirects are refused."""
    response = Response(b"{}", final_url=final_url)
    opener = QueueOpener(response)
    patch_urlopen(monkeypatch, opener)

    with pytest.raises(provider.ProviderError) as raised:
        provider.PolymarketClient("gamma").get(
            "/markets/keyset",
            (("limit", "1"),),
        )

    assert raised.value.code == "redirect_error"
    assert len(opener.requests) == 1
    assert response.closed is True
    assert response.read_calls == []


def test_location_header_is_refused_even_when_final_url_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Location header is a redirect attempt and is never followed."""
    response = Response(b"{}", headers={"Location": "https://evil.invalid/next"})
    opener = QueueOpener(response)
    patch_urlopen(monkeypatch, opener)

    with pytest.raises(provider.ProviderError) as raised:
        provider.PolymarketClient("gamma").get(
            "/markets/keyset",
            (("limit", "1"),),
        )

    assert raised.value.code == "redirect_error"
    assert raised.value.details["reason"] == "Location header present"
    assert opener.requests and len(opener.requests) == 1
    assert response.read_calls == []


@pytest.mark.parametrize("status", [300, 301, 302, 303, 307, 308])
def test_redirect_status_is_refused_without_read_or_retry(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    """Every 3xx response fails closed before its body can be interpreted."""
    response = Response(b"{}", status=status)
    opener = QueueOpener(response, Response(b"{}"))
    patch_urlopen(monkeypatch, opener)

    with pytest.raises(provider.ProviderError) as raised:
        provider.PolymarketClient("gamma").get(
            "/markets/keyset",
            (("limit", "1"),),
        )

    assert raised.value.code == "redirect_error"
    assert len(opener.requests) == 1
    assert len(opener.responses) == 1
    assert response.read_calls == []


def test_http_error_redirect_is_not_followed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """urllib HTTPError redirects become one bounded structured failure."""
    source_url = "https://gamma-api.polymarket.com/markets/keyset?limit=1"
    error = HTTPError(
        source_url,
        302,
        "Found",
        {"Location": "https://evil.invalid/next"},
        io.BytesIO(b"redirect"),
    )
    opener = QueueOpener(error, Response(b"{}"))
    patch_urlopen(monkeypatch, opener)

    with pytest.raises(provider.ProviderError) as raised:
        provider.PolymarketClient("gamma").get(
            "/markets/keyset",
            (("limit", "1"),),
        )

    assert raised.value.code == "redirect_error"
    assert len(opener.requests) == 1
    assert len(opener.responses) == 1


def test_content_length_above_limit_fails_before_body_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An oversized declared body is rejected without allocating or reading it."""
    response = Response(
        b"{}",
        headers={"Content-Length": str(provider.MAX_BODY_BYTES + 1)},
    )
    opener = QueueOpener(response)
    patch_urlopen(monkeypatch, opener)

    with pytest.raises(provider.ProviderError) as raised:
        provider.PolymarketClient("gamma").get(
            "/markets/keyset",
            (("limit", "1"),),
        )

    assert raised.value.code == "response_too_large"
    assert response.read_calls == []
    assert response.closed is True
    assert len(opener.requests) == 1


def test_exact_body_limit_succeeds_and_uses_one_sentinel_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exactly four million bytes remain valid while the reader still gets a sentinel."""
    payload = b'{"markets":[]}'
    body = payload + b" " * (provider.MAX_BODY_BYTES - len(payload))
    response = Response(
        body,
        headers={"Content-Length": str(provider.MAX_BODY_BYTES)},
    )
    opener = QueueOpener(response)
    patch_urlopen(monkeypatch, opener)

    result = provider.PolymarketClient("gamma").get(
        "/markets/keyset",
        (("limit", "1"),),
    )

    assert result.payload == {"markets": []}
    assert response.read_calls == [(provider.MAX_BODY_BYTES + 1,)]
    assert response.closed is True
    assert len(opener.requests) == 1


def test_body_sentinel_over_limit_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response with one byte beyond the cap is rejected, never truncated."""
    payload = b"{}"
    body = payload + b" " * (provider.MAX_BODY_BYTES + 1 - len(payload))
    response = Response(body)
    opener = QueueOpener(response)
    patch_urlopen(monkeypatch, opener)

    with pytest.raises(provider.ProviderError) as raised:
        provider.PolymarketClient("gamma").get(
            "/markets/keyset",
            (("limit", "1"),),
        )

    assert raised.value.code == "response_too_large"
    assert response.read_calls == [(provider.MAX_BODY_BYTES + 1,)]
    assert response.closed is True
    assert len(opener.requests) == 1


@pytest.mark.parametrize(
    ("outcome", "error_code"),
    [
        (TimeoutError("timed out"), "network_error"),
        (URLError("offline"), "network_error"),
        (OSError("connection reset"), "network_error"),
    ],
)
def test_network_failures_are_bounded_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    outcome: BaseException,
    error_code: str,
) -> None:
    """Timeout and socket failures produce one error and no hidden retry."""
    opener = QueueOpener(outcome, Response(b"{}"))
    patch_urlopen(monkeypatch, opener)

    with pytest.raises(provider.ProviderError) as raised:
        provider.PolymarketClient("gamma", timeout=7.5).get(
            "/markets/keyset",
            (("limit", "1"),),
        )

    assert raised.value.code == error_code
    assert len(opener.requests) == 1
    assert opener.timeouts == [7.5]
    assert len(opener.responses) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 502, 503, 504])
def test_http_status_failures_are_immediate_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    """HTTP errors, including rate limits and 5xx, never trigger a second GET."""
    response = Response(b"not-json", status=status)
    opener = QueueOpener(response, Response(b"{}"))
    patch_urlopen(monkeypatch, opener)

    with pytest.raises(provider.ProviderError) as raised:
        provider.PolymarketClient("gamma").get(
            "/markets/keyset",
            (("limit", "1"),),
        )

    assert raised.value.code == "http_error"
    assert raised.value.details["http_status"] == status
    assert len(opener.requests) == 1
    assert len(opener.responses) == 1
    assert response.read_calls == []


def test_http_error_from_urlopen_is_bounded_without_body_leak_or_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An HTTPError raised by urllib is translated without reading its body."""
    source_url = "https://gamma-api.polymarket.com/markets/keyset?limit=1"
    error = HTTPError(
        source_url,
        503,
        "service unavailable\nsecret provider body",
        {},
        io.BytesIO(b"<html>secret</html>"),
    )
    opener = QueueOpener(error, Response(b"{}"))
    patch_urlopen(monkeypatch, opener)

    with pytest.raises(provider.ProviderError) as raised:
        provider.PolymarketClient("gamma").get(
            "/markets/keyset",
            (("limit", "1"),),
        )

    assert raised.value.code == "http_error"
    assert raised.value.details["http_status"] == 503
    assert "secret" not in raised.value.message
    assert len(opener.requests) == 1
    assert len(opener.responses) == 1


@pytest.mark.parametrize(
    ("body", "error_code"),
    [
        (b"\xff", "invalid_json"),
        (b'{"markets":', "invalid_json"),
        (b"<html><body>provider failure</body></html>", "invalid_json"),
        (b"null", "invalid_payload"),
        (b"true", "invalid_payload"),
        (b"42", "invalid_payload"),
        (b'"text"', "invalid_payload"),
    ],
)
def test_malformed_utf8_json_html_and_primitive_roots_fail_safely(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
    error_code: str,
) -> None:
    """Only UTF-8 object/list JSON roots are accepted, without raw body leakage."""
    opener = QueueOpener(Response(body))
    patch_urlopen(monkeypatch, opener)

    with pytest.raises(provider.ProviderError) as raised:
        provider.PolymarketClient("gamma").get(
            "/markets/keyset",
            (("limit", "1"),),
        )

    assert raised.value.code == error_code
    assert len(opener.requests) == 1
    assert raised.value.details["bytes"] == len(body)
    assert "provider failure" not in raised.value.message


def test_nonfinite_json_constants_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NaN and Infinity cannot enter provider payloads as non-standard JSON."""
    opener = QueueOpener(Response(b'{"value":NaN}'))
    patch_urlopen(monkeypatch, opener)

    with pytest.raises(provider.ProviderError) as raised:
        provider.PolymarketClient("gamma").get(
            "/markets/keyset",
            (("limit", "1"),),
        )

    assert raised.value.code == "invalid_json"
    assert len(opener.requests) == 1


def test_fetch_result_provenance_uses_injected_clock_and_exact_wire_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FetchResult retains the payload, endpoint, status, URL, and deterministic clock."""
    source_url = "https://clob.polymarket.com/midpoint?token_id=token-123"
    opener = QueueOpener(Response(b'{"mid_price":"0.5"}', final_url=source_url))
    patch_urlopen(monkeypatch, opener)

    result = provider.PolymarketClient("clob", timeout=60).get(
        "/midpoint",
        (("token_id", "token-123"),),
    )

    assert result == provider.FetchResult(
        payload={"mid_price": "0.5"},
        source_url=source_url,
        endpoint="/midpoint",
        http_status=200,
        fetched_at=FIXED_NOW,
    )
    assert opener.timeouts == [60.0]
    assert len(opener.requests) == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "/geoblock",
        "/geoblocked",
        "/markets?offset=0",
        "/events?offset=0",
        "/v1/market-positions",
        "/v1/leaderboard",
        "/v1/positions",
        "/v1/trades",
        "/holders",
        "/comments",
        "/closed-positions",
        "/order",
        "/orders",
        "/cancel",
        "/relayer/orders",
    ],
)
def test_geoblock_legacy_wallet_social_and_private_routes_are_absent(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    """Excluded routes are rejected locally rather than sent to any host."""
    opener = QueueOpener(Response(b"{}"))
    patch_urlopen(monkeypatch, opener)

    with pytest.raises(provider.ProviderError) as raised:
        provider.PolymarketClient("gamma").get(endpoint)

    assert raised.value.code == "invalid_endpoint"
    assert opener.requests == []


if __name__ == "__main__":
    pytest.main([__file__])
