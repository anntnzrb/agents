from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from flight_live.models import FlightLiveError
from flight_live.providers import (
    _ensure_agent_browser_available,
    fetch_kiwi_web_calendar,
    parse_kiwi_price_buttons,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_kiwi_price_buttons() -> None:
    snapshot = (_FIXTURES / "kiwi_snapshot_sample.txt").read_text(encoding="utf-8")
    offers = parse_kiwi_price_buttons(
        snapshot,
        default_origin="GYE",
        default_destination="MIA",
        month_hint=date(2026, 5, 15),
        include_return=True,
    )

    assert len(offers) == 5
    assert offers[0].depart_date == date(2026, 5, 13)
    assert offers[0].return_date == date(2026, 5, 20)
    assert offers[0].price == 296.0
    assert offers[0].source == "kiwi_web_scrape"


def test_fetch_kiwi_calendar_with_monkeypatched_sources(monkeypatch) -> None:
    snapshot = (_FIXTURES / "kiwi_snapshot_sample.txt").read_text(encoding="utf-8")

    monkeypatch.setattr(
        "flight_live.providers._ensure_agent_browser_available",
        lambda: None,
    )
    monkeypatch.setattr(
        "flight_live.providers.scrape_kiwi_snapshot_text",
        lambda url: snapshot,
    )

    def fake_lookup(term: str, *, locale: str) -> dict[str, str]:
        del locale
        mapping = {
            "guayaquil": {
                "iata": "GYE",
                "slug": "guayaquil-ecuador",
                "name": "Guayaquil",
            },
            "miami": {
                "iata": "MIA",
                "slug": "miami-florida-united-states",
                "name": "Miami International",
            },
        }
        return mapping[term.lower()]

    monkeypatch.setattr("flight_live.providers._lookup_kiwi_place", fake_lookup)

    offers = fetch_kiwi_web_calendar(
        origin="Guayaquil",
        destination="Miami",
        depart_start=date(2026, 5, 14),
        depart_end=date(2026, 5, 16),
        trip_type="roundtrip",
        currency="USD",
        locale="en",
        market="us",
        stay_min=5,
        stay_max=9,
    )

    assert len(offers) >= 3
    assert all(item.source == "kiwi_web_scrape" for item in offers)


def test_provider_hard_error_when_nix_missing(monkeypatch) -> None:
    _ensure_agent_browser_available.cache_clear()
    monkeypatch.setattr("flight_live.providers.shutil.which", lambda _: None)

    with pytest.raises(FlightLiveError, match="requires `nix` in PATH"):
        _ensure_agent_browser_available()

    _ensure_agent_browser_available.cache_clear()
