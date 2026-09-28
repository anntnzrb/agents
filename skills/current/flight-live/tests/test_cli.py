import json
from io import StringIO
from typing import TYPE_CHECKING, TypeIs

from flight_live.cli import main


def _is_str_dict(val: object) -> TypeIs[dict[str, object]]:
    return isinstance(val, dict)


def _is_object_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

    from flight_live.models import SearchRequest
    from flight_live.protocol import SearchPayload

_json_loads: Callable[[str], object] = json.loads


def test_cli_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_payload: SearchPayload = {
        "type": "flight-live.search_results",
        "version": "1",
        "ok": True,
        "warnings": [],
        "query": {
            "origin": "SFO",
            "destination": "JFK",
            "depart_start": "2026-05-15",
            "depart_end": "2026-05-25",
            "trip_type": "roundtrip",
            "stay_min": None,
            "stay_max": None,
            "adults": 1,
            "children": 0,
            "infants": 0,
            "cabin": "economy",
            "currency": "USD",
            "locale": "en",
            "market": "us",
            "nonstop": False,
            "max_budget": None,
            "planner_limit": 20,
        },
        "resolved": {
            "origin": {
                "query": "SFO",
                "iata": "SFO",
                "name": "San Francisco",
                "resolved_via_autocomplete": False,
            },
            "destination": {
                "query": "JFK",
                "iata": "JFK",
                "name": "New York",
                "resolved_via_autocomplete": False,
            },
        },
        "summary": {"planner_received": 2, "after_filters": 2, "returned": 1},
        "insights": {},
        "decision": {
            "recommendation": "Book the UA flight on Wed May 20.",
            "actions": [],
            "avoid": [],
        },
        "results": [
            {
                "origin": "SFO",
                "destination": "JFK",
                "depart_date": "2026-05-20",
                "return_date": "2026-05-24",
                "price": 290.0,
                "effective_price": 290.0,
                "currency": "USD",
                "transfers": 0,
                "nonstop": True,
                "airline": "UA",
                "source": "kiwi_web_scrape",
                "score": 0.8,
                "reasons": ["weekday_departure_bonus"],
                "hints": ["Weekday departure tends cheaper (Tue-Thu bias)."],
            },
        ],
    }

    def fake_search(request: SearchRequest) -> SearchPayload:
        del request
        return fake_payload

    monkeypatch.setattr("flight_live.cli.search_flights", fake_search)

    exit_code = main(
        [
            "--origin",
            "SFO",
            "--destination",
            "JFK",
            "--depart-start",
            "2026-05-15",
            "--depart-end",
            "2026-05-25",
            "--json",
        ],
    )

    assert exit_code == 0
    results = _json_loads(capsys.readouterr().out)
    assert _is_object_list(results)
    assert len(results) == 1
    first = results[0]
    assert _is_str_dict(first)
    assert first["origin"] == "SFO"


def test_cli_schema_output(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--schema"])

    assert exit_code == 0
    payload = _json_loads(capsys.readouterr().out)
    assert _is_str_dict(payload)
    assert payload["type"] == "flight-live.schema"
    rpc = payload["rpc"]
    assert _is_str_dict(rpc)
    assert rpc["request_command_field"] == "type"


def test_cli_rpc_ping_round_trip() -> None:
    stdin = StringIO('{"id":"p-1","type":"ping"}\n')
    stdout = StringIO()

    exit_code = main(["--mode", "rpc"], stdin=stdin, stdout=stdout)

    assert exit_code == 0
    response = _json_loads(stdout.getvalue().strip())
    assert response == {
        "id": "p-1",
        "type": "response",
        "command": "ping",
        "success": True,
        "data": {"ok": True, "version": "1"},
    }
