import json
from io import StringIO
from pathlib import Path

from amz_live.cli import main
from amz_live.protocol import serialize_results

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "search_results_fragment.html"


def test_rpc_search_type_emits_llm_payload() -> None:
    stdin = StringIO(
        json.dumps(
            {
                "id": "search-1",
                "type": "search",
                "query": "usb c to usb c braided cable",
                "htmlPath": str(FIXTURE_PATH),
                "minRating": 4.5,
                "maxPrice": 9.0,
                "limit": 2,
            }
        )
        + "\n"
    )
    stdout = StringIO()

    exit_code = main(["--mode", "rpc"], stdin=stdin, stdout=stdout)

    assert exit_code == 0

    lines = stdout.getvalue().splitlines()
    assert len(lines) == 1

    response = json.loads(lines[0])
    assert response["id"] == "search-1"
    assert response["type"] == "response"
    assert response["command"] == "search"
    assert response["success"] is True

    payload = response["data"]
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


def test_rpc_search_accepts_zip_code() -> None:
    stdin = StringIO(
        json.dumps(
            {
                "id": "search-zip-1",
                "type": "search",
                "query": "usb c pd charger",
                "htmlPath": str(FIXTURE_PATH),
                "zipCode": "33101",
            }
        )
        + "\n"
    )
    stdout = StringIO()

    exit_code = main(["--mode", "rpc"], stdin=stdin, stdout=stdout)

    assert exit_code == 0

    response = json.loads(stdout.getvalue().strip())
    assert response["id"] == "search-zip-1"
    assert response["success"] is True
    assert response["data"]["query"]["zip_code"] == "33101"

def test_rpc_accepts_legacy_command_and_prefers_type() -> None:
    stdin = StringIO(
        json.dumps({"id": "legacy-1", "command": "ping"})
        + "\n"
        + json.dumps({"id": "preferred-2", "type": "ping", "command": "wat"})
        + "\n"
    )
    stdout = StringIO()

    exit_code = main(["--mode", "rpc"], stdin=stdin, stdout=stdout)

    assert exit_code == 0

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert responses == [
        {
            "id": "legacy-1",
            "type": "response",
            "command": "ping",
            "success": True,
            "data": {"ok": True, "version": "1"},
        },
        {
            "id": "preferred-2",
            "type": "response",
            "command": "ping",
            "success": True,
            "data": {"ok": True, "version": "1"},
        },
    ]


def test_rpc_parse_unknown_command_and_whitespace_only_line_errors() -> None:
    stdin = StringIO("   \n" + "{not json}\n" + json.dumps({"id": "bad-2", "type": "wat"}) + "\n")
    stdout = StringIO()

    exit_code = main(["--mode", "rpc"], stdin=stdin, stdout=stdout)

    assert exit_code == 0

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert responses == [
        {
            "type": "response",
            "command": "unknown",
            "success": False,
            "error": {"code": "parse_error", "message": "Invalid JSON request."},
        },
        {
            "type": "response",
            "command": "unknown",
            "success": False,
            "error": {"code": "parse_error", "message": "Invalid JSON request."},
        },
        {
            "id": "bad-2",
            "type": "response",
            "command": "wat",
            "success": False,
            "error": {"code": "unknown_command", "message": "Unknown command: wat"},
        },
    ]


def test_rpc_search_scoring_mode_emits_scores_and_reasons(monkeypatch) -> None:
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

    monkeypatch.setattr("amz_live.rpc.build_llm_json", fake_build_llm_json)

    stdin = StringIO(
        json.dumps(
            {
                "id": "search-score-1",
                "type": "search",
                "query": "usb c to usb c braided cable",
                "htmlPath": str(FIXTURE_PATH),
                "scoring": True,
            }
        )
        + "\n"
    )
    stdout = StringIO()

    exit_code = main(["--mode", "rpc"], stdin=stdin, stdout=stdout)

    assert exit_code == 0

    response = json.loads(stdout.getvalue().strip())
    assert response["id"] == "search-score-1"
    assert response["type"] == "response"
    assert response["command"] == "search"
    assert response["success"] is True
    assert [item["asin"] for item in response["data"]["results"]] == [
        "B07CWC39TL",
        "B0CG1LGWR6",
        "B0CHJF41K4",
    ]
    assert response["data"]["results"][0]["score"] == 0.97
    assert response["data"]["results"][0]["reasons"] == ["best title match", "best price"]
    assert response["data"]["results"][1]["score"] == 0.72
    assert response["data"]["results"][2]["reasons"] == ["weaker title match"]
