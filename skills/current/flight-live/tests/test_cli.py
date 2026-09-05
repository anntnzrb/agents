from __future__ import annotations

import json
from io import StringIO
from typing import TYPE_CHECKING, cast

from flight_live.cli import main

if TYPE_CHECKING:
    import pytest

    from flight_live.models import SearchRequest
    from flight_live.protocol import SearchPayload


def test_cli_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_payload = {
        "type": "flight-live.search_results",
        "version": "1",
        "ok": True,
        "warnings": [],
        "query": {},
        "resolved": {},
        "summary": {"planner_received": 2, "after_filters": 2, "returned": 1},
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
        return cast("SearchPayload", cast("object", fake_payload))

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
    results = cast("list[object]", json.loads(capsys.readouterr().out))
    assert len(results) == 1
    first = cast("dict[str, object]", results[0])
    assert first["origin"] == "SFO"


def test_cli_schema_output(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--schema"])

    assert exit_code == 0
    payload = cast("dict[str, object]", json.loads(capsys.readouterr().out))
    assert payload["type"] == "flight-live.schema"
    rpc = cast("dict[str, object]", payload["rpc"])
    assert rpc["request_command_field"] == "type"


def test_cli_rpc_ping_round_trip() -> None:
    stdin = StringIO('{"id":"p-1","type":"ping"}\n')
    stdout = StringIO()

    exit_code = main(["--mode", "rpc"], stdin=stdin, stdout=stdout)

    assert exit_code == 0
    response = cast("object", json.loads(stdout.getvalue().strip()))
    assert response == {
        "id": "p-1",
        "type": "response",
        "command": "ping",
        "success": True,
        "data": {"ok": True, "version": "1"},
    }
