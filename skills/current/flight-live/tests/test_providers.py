import subprocess
from datetime import date
from pathlib import Path

import pytest

from flight_live.models import FlightLiveError, MissingExecutableError
from flight_live.providers import (
    ensure_agent_browser_available,
    fetch_kiwi_web_calendar,
    parse_kiwi_price_buttons,
    scrape_kiwi_snapshot_text,
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


def test_fetch_kiwi_calendar_with_monkeypatched_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = (_FIXTURES / "kiwi_snapshot_sample.txt").read_text(encoding="utf-8")

    def fake_scrape(url: str) -> str:
        del url
        return snapshot

    monkeypatch.setattr(
        "flight_live.providers.scrape_kiwi_snapshot_text",
        fake_scrape,
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


def fake_uv(_name: str) -> str:
    """Provide a deterministic executable path."""
    return "/tools/uv"


def no_uv(_name: str) -> None:
    """Simulate a missing executable."""


def test_browser_commands_use_sibling_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake_run(
        args: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="snapshot", stderr="")

    monkeypatch.setattr("flight_live.providers.shutil.which", fake_uv)
    monkeypatch.setattr("flight_live.providers.subprocess.run", fake_run)
    ensure_agent_browser_available.cache_clear()
    try:
        assert scrape_kiwi_snapshot_text("https://example.com") == "snapshot"
    finally:
        ensure_agent_browser_available.cache_clear()

    wrapper = Path(__file__).resolve().parents[2] / "agent-browser/scripts/cli.py"
    assert all(
        command[:4] == ["/tools/uv", "run", "--script", str(wrapper)]
        for command in commands
    )
    assert commands[0][4:] == ["--version"]
    session = commands[1][5]
    assert session.startswith("flight-live-")
    assert all(command[4:6] == ["--session", session] for command in commands[1:])
    assert any(command[6:] == ["open", "https://example.com"] for command in commands)
    assert any(command[6:] == ["snapshot", "-i"] for command in commands)
    assert commands[-1][6:] == ["close"]


@pytest.mark.parametrize(
    ("returncode", "error"), [(127, MissingExecutableError), (1, FlightLiveError)]
)
def test_browser_validation_failure(
    monkeypatch: pytest.MonkeyPatch, returncode: int, error: type[FlightLiveError]
) -> None:
    def fake_run(
        args: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args, returncode, stdout="", stderr="unavailable"
        )

    monkeypatch.setattr("flight_live.providers.shutil.which", fake_uv)
    monkeypatch.setattr("flight_live.providers.subprocess.run", fake_run)
    ensure_agent_browser_available.cache_clear()
    with pytest.raises(error, match="unavailable"):
        ensure_agent_browser_available()
    ensure_agent_browser_available.cache_clear()


def test_browser_missing_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("flight_live.providers.shutil.which", no_uv)
    ensure_agent_browser_available.cache_clear()
    with pytest.raises(MissingExecutableError, match="uv"):
        ensure_agent_browser_available()
    ensure_agent_browser_available.cache_clear()
