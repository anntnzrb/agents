import json
from pathlib import Path

from amz_live.cli import main
from amz_live.protocol import serialize_results

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "search_results_fragment.html"


def test_cli_parses_fixture_filters_results_and_emits_json(capsys) -> None:
    exit_code = main(
        [
            "usb c to usb c braided cable",
            "--html",
            str(FIXTURE_PATH),
            "--min-rating",
            "4.5",
            "--max-price",
            "9.0",
            "--limit",
            "2",
            "--json",
        ],
    )

    assert exit_code == 0

    payload = json.loads(capsys.readouterr().out)
    assert [item["asin"] for item in payload] == ["B0CG1LGWR6", "B07CWC39TL"]


def test_cli_parses_fixture_include_filter_and_emits_json(capsys) -> None:
    exit_code = main(
        [
            "usb c to usb c braided cable",
            "--html",
            str(FIXTURE_PATH),
            "--include",
            "braided",
            "--max-price",
            "10",
            "--json",
        ],
    )

    assert exit_code == 0

    payload = json.loads(capsys.readouterr().out)
    assert [item["asin"] for item in payload] == ["B07CWC39TL"]


def test_cli_emits_llm_json_envelope(capsys) -> None:
    exit_code = main(
        [
            "usb c to usb c braided cable",
            "--html",
            str(FIXTURE_PATH),
            "--min-rating",
            "4.5",
            "--max-price",
            "9.0",
            "--limit",
            "2",
            "--llm-json",
        ],
    )

    assert exit_code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "amz-live.search_results"
    assert payload["version"] == "1"
    assert payload["ok"] is True
    assert payload["source"] == {"mode": "html", "html_path": str(FIXTURE_PATH)}
    assert payload["query"] == {
        "keywords": "usb c to usb c braided cable",
        "page": 1,
        "pages": 1,
        "amazon_sort": None,
        "zip_code": None,
    }
    assert payload["filters"] == {
        "min_rating": 4.5,
        "max_price": 9.0,
        "badge": None,
        "title_contains": None,
        "include": [],
        "exclude": [],
        "limit": 2,
    }
    assert payload["summary"] == {"raw_result_count": 3, "returned_result_count": 2}
    assert [item["asin"] for item in payload["results"]] == ["B0CG1LGWR6", "B07CWC39TL"]


def test_cli_schema_output_shape(capsys) -> None:
    exit_code = main(["--schema"])

    assert exit_code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "amz-live.schema"
    assert payload["version"] == "1"
    assert payload["name"] == "amz-live"
    assert payload["rpc"]["pi_inspired"] is True
    assert payload["rpc"]["full_pi_rpc"] is False
    assert payload["rpc"]["request_command_field"] == "type"
    assert payload["rpc"]["legacy_request_command_field"] == "command"
    assert sorted(payload["rpc"]["commands"]) == ["get_schema", "ping", "search"]
    assert payload["rpc"]["commands"]["ping"]["request"]["anyOf"] == [
        {"required": ["type"], "properties": {"type": {"const": "ping"}}},
        {"required": ["command"], "properties": {"command": {"const": "ping"}}},
    ]
    assert payload["rpc"]["commands"]["search"]["request"]["anyOf"] == [
        {"required": ["type", "query"], "properties": {"type": {"const": "search"}}},
        {"required": ["command", "query"], "properties": {"command": {"const": "search"}}},
    ]
    assert payload["llm_json"]["required"] == [
        "type",
        "version",
        "ok",
        "source",
        "query",
        "filters",
        "summary",
        "results",
    ]


def test_cli_llm_json_scoring_mode_emits_scores_and_reasons(monkeypatch, capsys) -> None:
    score_map = {
        "B07CWC39TL": {"score": 0.97, "reasons": ["best title match", "best price"]},
        "B0CG1LGWR6": {"score": 0.72, "reasons": ["strong rating"]},
        "B0CHJF41K4": {"score": 0.41, "reasons": ["weaker title match"]},
    }

    def fake_build_llm_json(**kwargs):
        assert kwargs["scoring"] is True
        ranked_results = sorted(
            kwargs["filtered_results"],
            key=lambda result: score_map[result.asin]["score"],
            reverse=True,
        )
        payload = {
            "type": "amz-live.search_results",
            "version": "1",
            "ok": True,
            "source": {"mode": "html", "html_path": kwargs["html_path"]},
            "query": {
                "keywords": kwargs["query"],
                "page": kwargs["page"],
                "pages": kwargs["pages"],
                "amazon_sort": kwargs["amazon_sort"],
            },
            "filters": {
                "min_rating": kwargs["min_rating"],
                "max_price": kwargs["max_price"],
                "badge": kwargs["badge"],
                "title_contains": kwargs["title_contains"],
                "include": list(kwargs["include"]),
                "exclude": list(kwargs["exclude"]),
                "limit": kwargs["limit"],
            },
            "summary": {
                "raw_result_count": len(kwargs["raw_results"]),
                "returned_result_count": len(ranked_results),
            },
            "results": serialize_results(ranked_results),
        }
        for item in payload["results"]:
            item.update(score_map[item["asin"]])
        return payload

    monkeypatch.setattr("amz_live.cli.build_llm_json", fake_build_llm_json)

    exit_code = main(
        [
            "usb c to usb c braided cable",
            "--html",
            str(FIXTURE_PATH),
            "--llm-json",
            "--scoring",
        ],
    )

    assert exit_code == 0

    payload = json.loads(capsys.readouterr().out)
    assert [item["asin"] for item in payload["results"]] == [
        "B07CWC39TL",
        "B0CG1LGWR6",
        "B0CHJF41K4",
    ]
    assert payload["results"][0]["score"] == 0.97
    assert payload["results"][0]["reasons"] == ["best title match", "best price"]
    assert payload["results"][1]["score"] == 0.72
    assert payload["results"][2]["reasons"] == ["weaker title match"]
