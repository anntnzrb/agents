from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, cast

from flight_live.models import PlannerOffer, ResolvedPlace, SearchRequest
from flight_live.protocol import get_schema_document, search_flights
from flight_live.providers import parse_kiwi_price_buttons

if TYPE_CHECKING:
    import pytest

_FIXTURES = Path(__file__).parent / "fixtures"


def test_kiwi_parser_extracts_expected_shapes() -> None:
    snapshot = (_FIXTURES / "kiwi_snapshot_sample.txt").read_text(encoding="utf-8")
    offers = parse_kiwi_price_buttons(
        snapshot,
        default_origin="GYE",
        default_destination="MIA",
        month_hint=date(2026, 5, 15),
        include_return=True,
    )

    assert len(offers) == 5
    assert offers[0].origin == "GYE"
    assert offers[0].destination == "MIA"
    assert offers[0].currency == "USD"
    assert offers[0].source == "kiwi_web_scrape"


def test_search_protocol_with_monkeypatched_scraper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = SearchRequest(
        origin="Guayaquil",
        destination="Miami",
        depart_start=date(2026, 5, 14),
        depart_end=date(2026, 5, 18),
        trip_type="roundtrip",
        planner_limit=5,
    )

    def fake_resolve(
        query: str, *, locale: str, client: object | None = None
    ) -> ResolvedPlace:
        del locale, client
        code = "GYE" if "guayaquil" in query.lower() else "MIA"
        return ResolvedPlace(
            query=query,
            iata=code,
            name=query.title(),
            resolved_via_autocomplete=True,
        )

    offers = [
        PlannerOffer(
            origin="GYE",
            destination="MIA",
            depart_date=date(2026, 5, 15),
            return_date=date(2026, 5, 22),
            price=360.0,
            currency="USD",
            transfers=None,
            airline=None,
            source="kiwi_web_scrape",
        ),
        PlannerOffer(
            origin="GYE",
            destination="MIA",
            depart_date=date(2026, 5, 13),
            return_date=date(2026, 5, 20),
            price=296.0,
            currency="USD",
            transfers=None,
            airline=None,
            source="kiwi_web_scrape",
        ),
    ]

    def fake_planner(**kwargs: object) -> list[PlannerOffer]:
        del kwargs
        return offers

    monkeypatch.setattr("flight_live.protocol.resolve_place", fake_resolve)
    monkeypatch.setattr("flight_live.protocol.fetch_kiwi_web_calendar", fake_planner)

    payload = search_flights(request)

    assert payload["summary"]["planner_received"] == 2
    assert payload["summary"]["after_filters"] == 1
    assert payload["summary"]["returned"] == 1
    assert payload["results"][0]["source"] == "kiwi_web_scrape"
    assert payload["warnings"] == []


def test_schema_has_expected_rpc_commands() -> None:
    schema = get_schema_document()

    assert schema["type"] == "flight-live.schema"
    assert schema["version"] == "1"
    rpc = cast("dict[str, object]", schema["rpc"])
    assert sorted(cast("list[str]", rpc["commands"])) == [
        "get_schema",
        "ping",
        "search",
    ]
    capabilities = cast("dict[str, object]", schema["capabilities"])
    credentials = cast("dict[str, object]", capabilities["credentials"])
    assert credentials["required"] == []
