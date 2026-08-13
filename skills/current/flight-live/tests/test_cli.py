from __future__ import annotations

import json
from io import StringIO

from flight_live.cli import main


def test_cli_json_output(monkeypatch, capsys) -> None:
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

    monkeypatch.setattr("flight_live.cli.search_flights", lambda request: fake_payload)

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
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["origin"] == "SFO"


def test_cli_schema_output(capsys) -> None:
    exit_code = main(["--schema"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "flight-live.schema"
    assert payload["rpc"]["request_command_field"] == "type"


def test_cli_rpc_ping_round_trip() -> None:
    stdin = StringIO('{"id":"p-1","type":"ping"}\n')
    stdout = StringIO()

    exit_code = main(["--mode", "rpc"], stdin=stdin, stdout=stdout)

    assert exit_code == 0
    response = json.loads(stdout.getvalue().strip())
    assert response == {
        "id": "p-1",
        "type": "response",
        "command": "ping",
        "success": True,
        "data": {"ok": True, "version": "1"},
    }
