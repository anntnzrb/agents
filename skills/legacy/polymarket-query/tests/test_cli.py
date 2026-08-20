"""Deterministic CLI routing, envelope, and validation tests."""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from urllib.request import Request

import _path  # noqa: F401
import pytest
from polymarket_query import cli, provider

FIXED_NOW = "2026-08-09T00:00:00Z"
CONDITION_ID = "0x" + "a" * 64
CONDITION_ID_2 = "0x" + "b" * 64
TOKEN = "12345678901234567890"


class Response:
    """Small urllib-compatible response double for CLI wire tests."""

    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = io.BytesIO(body)
        self.status = status
        self.code = status
        self.headers = headers or {}
        self.closed = False

    def read(self, *args: int) -> bytes:
        return self.body.read(*args)

    def geturl(self) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def getheader(self, name: str, default: str | None = None) -> str | None:
        wanted = name.lower()
        return next(
            (value for key, value in self.headers.items() if key.lower() == wanted),
            default,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self.closed = True
        self.body.close()


class QueueOpener:
    """FIFO response opener that fails on hidden second calls."""

    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.requests: list[Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: Request, timeout: float = 0) -> object:
        self.requests.append(request)
        self.timeouts.append(timeout)
        if not self.responses:
            raise AssertionError("unexpected second request")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _response(payload: object, *, status: int = 200) -> Response:
    return Response(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
        status=status,
    )


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    payload: object,
    *,
    status: int = 200,
) -> tuple[int, dict[str, Any], str, QueueOpener]:
    opener = QueueOpener(_response(payload, status=status))
    monkeypatch.setattr(provider, "urlopen", opener)
    monkeypatch.setattr(provider, "_utc_now", lambda: FIXED_NOW)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli.main(argv, stdout=stdout, stderr=stderr)
    envelope = json.loads(stdout.getvalue())
    assert isinstance(envelope, dict)
    return code, envelope, stderr.getvalue(), opener


def _market() -> dict[str, object]:
    return {"id": "42", "conditionId": CONDITION_ID, "question": "Question"}


def _event() -> dict[str, object]:
    return {"id": "7", "title": "Event", "markets": []}


def _book() -> dict[str, object]:
    return {
        "market": CONDITION_ID,
        "asset_id": TOKEN,
        "timestamp": "1700000000",
        "hash": "book-hash",
        "bids": [{"price": "0.40", "size": "2"}],
        "asks": [{"price": "0.60", "size": "3"}],
        "min_order_size": "0.01",
        "tick_size": "0.01",
        "neg_risk": False,
        "last_trade_price": "0.50",
    }


ROUTE_CASES = [
    pytest.param(
        "markets",
        ["markets", "--limit", "1"],
        {"markets": []},
        "https://gamma-api.polymarket.com/markets/keyset?limit=1",
        "gamma",
        id="markets",
    ),
    pytest.param(
        "events",
        ["events", "--limit", "1"],
        {"events": []},
        "https://gamma-api.polymarket.com/events/keyset?limit=1",
        "gamma",
        id="events",
    ),
    pytest.param(
        "search",
        ["search", "bitcoin price", "--limit-per-type", "1", "--page", "2"],
        {
            "events": [_event()],
            "tags": [{"id": "1", "name": "Bitcoin"}],
            "profiles": [{"username": "must-not-leak"}],
            "pagination": {"hasMore": False, "totalResults": 1},
        },
        "https://gamma-api.polymarket.com/public-search?q=bitcoin+price&limit_per_type=1&page=2&search_profiles=false",
        "gamma",
        id="search",
    ),
    pytest.param(
        "market",
        ["market", "--id", "42"],
        _market(),
        "https://gamma-api.polymarket.com/markets/42",
        "gamma",
        id="market-id",
    ),
    pytest.param(
        "market",
        ["market", "--slug", "bitcoin-market"],
        _market(),
        "https://gamma-api.polymarket.com/markets/slug/bitcoin-market",
        "gamma",
        id="market-slug",
    ),
    pytest.param(
        "event",
        ["event", "--id", "7"],
        _event(),
        "https://gamma-api.polymarket.com/events/7",
        "gamma",
        id="event-id",
    ),
    pytest.param(
        "event",
        ["event", "--slug", "bitcoin-daily"],
        _event(),
        "https://gamma-api.polymarket.com/events/slug/bitcoin-daily",
        "gamma",
        id="event-slug",
    ),
    pytest.param(
        "market-by-token",
        ["market-by-token", TOKEN],
        {
            "condition_id": CONDITION_ID,
            "primary_token_id": TOKEN,
            "secondary_token_id": "987654321",
        },
        f"https://clob.polymarket.com/markets-by-token/{TOKEN}",
        "clob",
        id="market-by-token",
    ),
    pytest.param(
        "market-info",
        ["market-info", CONDITION_ID],
        {"t": [{"t": TOKEN, "o": "Yes"}]},
        f"https://clob.polymarket.com/clob-markets/{CONDITION_ID}",
        "clob",
        id="market-info",
    ),
    pytest.param(
        "orderbook",
        ["orderbook", TOKEN],
        _book(),
        f"https://clob.polymarket.com/book?token_id={TOKEN}",
        "clob",
        id="orderbook",
    ),
    pytest.param(
        "price",
        ["price", TOKEN, "--side", "BUY"],
        {"price": 0.42},
        f"https://clob.polymarket.com/price?token_id={TOKEN}&side=BUY",
        "clob",
        id="price",
    ),
    pytest.param(
        "midpoint",
        ["midpoint", TOKEN],
        {"mid_price": "0.42"},
        f"https://clob.polymarket.com/midpoint?token_id={TOKEN}",
        "clob",
        id="midpoint",
    ),
    pytest.param(
        "last-trade",
        ["last-trade", TOKEN],
        {"price": "0.42", "side": "BUY"},
        f"https://clob.polymarket.com/last-trade-price?token_id={TOKEN}",
        "clob",
        id="last-trade",
    ),
    pytest.param(
        "price-history",
        ["price-history", TOKEN, "--start-ts", "100", "--end-ts", "200"],
        {"history": [{"t": 100, "p": 0.42}]},
        f"https://clob.polymarket.com/prices-history?market={TOKEN}&startTs=100&endTs=200",
        "clob",
        id="price-history",
    ),
    pytest.param(
        "live-volume",
        ["live-volume", "7"],
        [{"total": 1.0, "markets": [{"market": CONDITION_ID, "value": 1.0}]}],
        "https://data-api.polymarket.com/live-volume?id=7",
        "data",
        id="live-volume",
    ),
    pytest.param(
        "open-interest",
        ["open-interest", "--market", CONDITION_ID, "--market", CONDITION_ID_2],
        [{"market": CONDITION_ID, "value": 1.0}],
        f"https://data-api.polymarket.com/oi?market={CONDITION_ID}%2C{CONDITION_ID_2}",
        "data",
        id="open-interest",
    ),
]


@pytest.mark.parametrize(
    ("command", "argv", "payload", "source_url", "provider_name"),
    ROUTE_CASES,
)
def test_every_registered_route_makes_one_exact_get_and_nested_success_envelope(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    argv: list[str],
    payload: object,
    source_url: str,
    provider_name: str,
) -> None:
    code, envelope, diagnostics, opener = _invoke(monkeypatch, argv, payload)

    assert code == 0
    assert diagnostics == ""
    assert envelope["ok"] is True
    assert envelope["schema_version"] == 1
    assert envelope["command"] == command
    data = envelope["data"]
    assert set(data) == {"provenance", "request", "coverage", "result"}
    assert data["provenance"] == {
        "provider": provider_name,
        "official": True,
        "auth_mode": "none",
        "source_url": source_url,
        "endpoint": source_url.split(".com", 1)[1].split("?", 1)[0],
        "http_status": 200,
        "fetched_at": FIXED_NOW,
    }
    assert len(opener.requests) == 1
    assert opener.requests[0].get_method() == "GET"
    assert {name.lower() for name, _value in opener.requests[0].header_items()} == {
        "accept",
        "user-agent",
    }
    assert opener.timeouts == [10.0]


@pytest.mark.parametrize(
    ("argv", "payload", "expected"),
    [
        (
            ["markets", "--limit", "2"],
            {"markets": [{"id": "1"}], "next_cursor": "opaque-next"},
            {
                "mode": "keyset",
                "requested_count": 2,
                "returned_count": 1,
                "input_cursor": None,
                "output_cursor": "opaque-next",
                "has_more": True,
                "complete": False,
                "complete_reason": "bounded_page",
            },
        ),
        (
            ["events", "--limit", "2", "--after-cursor", "opaque-in"],
            {"events": []},
            {
                "mode": "keyset",
                "requested_count": 2,
                "returned_count": 0,
                "input_cursor": "opaque-in",
                "output_cursor": None,
                "has_more": False,
                "complete": True,
                "complete_reason": "provider_exhausted",
            },
        ),
    ],
)
def test_keyset_coverage_is_bounded_and_never_auto_pages(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    payload: object,
    expected: dict[str, object],
) -> None:
    code, envelope, _diagnostics, opener = _invoke(monkeypatch, argv, payload)

    assert code == 0
    assert envelope["data"]["coverage"] == expected
    assert len(opener.requests) == 1


@pytest.mark.parametrize(
    "pagination",
    [
        None,
        {"hasMore": "yes", "totalResults": 1},
        [],
    ],
)
def test_search_missing_or_malformed_pagination_is_incomplete_not_exhaustive(
    monkeypatch: pytest.MonkeyPatch,
    pagination: object,
) -> None:
    payload: dict[str, object] = {"events": [], "tags": []}
    if pagination is not None:
        payload["pagination"] = pagination
    code, envelope, _diagnostics, opener = _invoke(
        monkeypatch,
        ["search", "bitcoin", "--limit-per-type", "1"],
        payload,
    )

    assert code == 0
    coverage = envelope["data"]["coverage"]
    assert coverage["has_more"] is None
    assert coverage["total_results"] is None
    assert coverage["complete"] is None
    assert coverage["complete_reason"] == "provider_incomplete"
    assert "profiles" not in envelope["data"]["result"]
    assert len(opener.requests) == 1


def test_history_uses_explicit_token_and_single_response_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, envelope, _diagnostics, opener = _invoke(
        monkeypatch,
        ["price-history", TOKEN, "--interval", "1h", "--fidelity", "5"],
        {"history": [{"t": 1700000000, "p": 0.5}]},
    )

    assert code == 0
    assert opener.requests[0].full_url == (
        f"https://clob.polymarket.com/prices-history?market={TOKEN}&interval=1h&fidelity=5"
    )
    assert envelope["data"]["coverage"] == {
        "mode": "single_response",
        "returned_count": 1,
        "complete": None,
        "complete_reason": "single_response_not_population_complete",
    }


def test_pretty_changes_only_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    compact_code, compact, compact_diag, _ = _invoke(
        monkeypatch,
        ["midpoint", TOKEN],
        {"mid_price": "0.5"},
    )
    pretty_code, pretty, pretty_diag, _ = _invoke(
        monkeypatch,
        ["--pretty", "midpoint", TOKEN],
        {"mid_price": "0.5"},
    )

    assert compact_code == pretty_code == 0
    assert compact == pretty
    assert compact_diag == pretty_diag == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["markets", "--limit", "0"],
        ["markets", "--after-cursor", "bad\n"],
        ["market", "--id", "0"],
        ["market", "--id", "1", "--slug", "one"],
        ["market-by-token", "bad/token"],
        ["market-info", "0x" + "a" * 63],
        ["price", TOKEN],
        ["price-history", TOKEN, "--start-ts", "1"],
        [
            "price-history",
            TOKEN,
            "--interval",
            "1h",
            "--start-ts",
            "1",
            "--end-ts",
            "2",
        ],
    ],
)
def test_invalid_arguments_fail_before_transport(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    calls: list[Request] = []

    def fail_open(request: Request, timeout: float = 0) -> object:
        calls.append(request)
        raise AssertionError("invalid CLI input reached transport")

    monkeypatch.setattr(provider, "urlopen", fail_open)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli.main(argv, stdout=stdout, stderr=stderr)
    envelope = json.loads(stdout.getvalue())

    assert code == 2
    assert envelope["ok"] is False
    assert envelope["error"]["code"] in {
        "usage",
        "invalid_id",
        "invalid_identifier",
        "invalid_token_id",
        "invalid_condition_id",
        "invalid_cursor",
        "invalid_history_range",
    }
    assert calls == []
    assert 0 < len(stderr.getvalue().splitlines()) == 1
    assert len(stderr.getvalue().splitlines()[0]) <= 240


@pytest.mark.parametrize(
    "argv",
    [
        ["positions"],
        ["trades"],
        ["comments"],
        ["wallet"],
        ["history/volume"],
        ["markets", "--credential", "file"],
        ["markets", "--auth", "token"],
        ["markets", "--out", "result.json"],
        ["markets", "--format", "csv"],
        ["search", "bitcoin", "--search-profiles", "true"],
    ],
)
def test_unsupported_commands_and_flags_fail_before_transport(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
) -> None:
    calls: list[Request] = []

    def fail_open(request: Request, timeout: float = 0) -> object:
        calls.append(request)
        raise AssertionError("unsupported request reached transport")

    monkeypatch.setattr(provider, "urlopen", fail_open)
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli.main(argv, stdout=stdout, stderr=stderr)
    envelope = json.loads(stdout.getvalue())

    assert code == 2
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "unsupported_command"
    assert calls == []
    assert len(stderr.getvalue().splitlines()) == 1


def test_provider_failure_is_one_stdout_envelope_with_bounded_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, envelope, diagnostics, opener = _invoke(
        monkeypatch,
        ["markets", "--limit", "1"],
        {"ignored": True},
        status=503,
    )

    assert code == 1
    assert envelope == {
        "ok": False,
        "schema_version": 1,
        "command": "markets",
        "error": {
            "code": "http_error",
            "message": "provider returned HTTP 503",
            "details": {
                "endpoint": "/markets/keyset",
                "http_status": 503,
                "source_url": "https://gamma-api.polymarket.com/markets/keyset?limit=1",
            },
        },
    }
    assert len(diagnostics.splitlines()) == 1
    assert len(diagnostics.splitlines()[0]) <= 240
    assert len(opener.requests) == 1


def test_help_exposes_the_fourteen_command_router() -> None:
    parser = cli.build_parser()
    help_text = parser.format_help()
    for command in (
        "markets",
        "events",
        "search",
        "market",
        "event",
        "market-by-token",
        "market-info",
        "orderbook",
        "price",
        "midpoint",
        "last-trade",
        "price-history",
        "live-volume",
        "open-interest",
    ):
        assert command in help_text


if __name__ == "__main__":
    pytest.main([__file__])
