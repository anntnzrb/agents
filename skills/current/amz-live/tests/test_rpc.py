import json
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, TypeIs

from amz_live.cli import main

if TYPE_CHECKING:
    from collections.abc import Callable

    from amz_live.protocol import SearchResultsPayload

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "search_results_fragment.html"


class _ScoredResult(TypedDict):
    asin: str
    score: float
    reasons: list[str]


def _is_str_dict(val: object) -> TypeIs[dict[str, object]]:
    return isinstance(val, dict)


def _is_search_results_payload(val: object) -> TypeIs[SearchResultsPayload]:
    return isinstance(val, dict)


def _is_scored_result_list(val: object) -> TypeIs[list[_ScoredResult]]:
    return isinstance(val, list)


def _parse_json_obj(line: str) -> dict[str, object]:
    fn: Callable[..., object] = json.loads
    raw = fn(line)
    assert _is_str_dict(raw)
    return raw


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
            },
        )
        + "\n",
    )
    stdout = StringIO()

    exit_code = main(["--mode", "rpc"], stdin=stdin, stdout=stdout)

    assert exit_code == 0

    lines = stdout.getvalue().splitlines()
    assert len(lines) == 1

    response = _parse_json_obj(lines[0])
    assert response["id"] == "search-1"
    assert response["type"] == "response"
    assert response["command"] == "search"
    assert response["success"] is True

    raw_payload = response.get("data")
    assert _is_search_results_payload(raw_payload)
    payload = raw_payload
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
        "deals": False,
        "deal_refinement": None,
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
    assert payload["summary"] == {
        "raw_result_count": 3,
        "returned_result_count": 2,
        "delivery_location": None,
    }
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
            },
        )
        + "\n",
    )
    stdout = StringIO()

    exit_code = main(["--mode", "rpc"], stdin=stdin, stdout=stdout)

    assert exit_code == 0

    response = _parse_json_obj(stdout.getvalue().strip())
    assert response["id"] == "search-zip-1"
    assert response["success"] is True
    data = response.get("data")
    assert _is_str_dict(data)
    query = data.get("query")
    assert _is_str_dict(query)
    assert query["zip_code"] == "33101"


def test_rpc_accepts_legacy_command_and_prefers_type() -> None:
    stdin = StringIO(
        json.dumps({"id": "legacy-1", "command": "ping"})
        + "\n"
        + json.dumps({"id": "preferred-2", "type": "ping", "command": "wat"})
        + "\n",
    )
    stdout = StringIO()

    exit_code = main(["--mode", "rpc"], stdin=stdin, stdout=stdout)

    assert exit_code == 0

    responses = [_parse_json_obj(line) for line in stdout.getvalue().splitlines()]
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

    responses = [_parse_json_obj(line) for line in stdout.getvalue().splitlines()]
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


def test_rpc_search_scoring_mode_emits_scores_and_reasons(
    scoring_boundary: None,
) -> None:
    del scoring_boundary

    stdin = StringIO(
        json.dumps(
            {
                "id": "search-score-1",
                "type": "search",
                "query": "usb c to usb c braided cable",
                "htmlPath": str(FIXTURE_PATH),
                "scoring": True,
            },
        )
        + "\n",
    )
    stdout = StringIO()

    exit_code = main(["--mode", "rpc"], stdin=stdin, stdout=stdout)

    assert exit_code == 0

    response = _parse_json_obj(stdout.getvalue().strip())
    assert response["id"] == "search-score-1"
    assert response["type"] == "response"
    assert response["command"] == "search"
    assert response["success"] is True
    data = response.get("data")
    assert _is_str_dict(data)
    raw_results = data.get("results")
    assert _is_scored_result_list(raw_results)
    results = raw_results
    assert [item["asin"] for item in results] == [
        "B07CWC39TL",
        "B0CG1LGWR6",
        "B0CHJF41K4",
    ]
    assert results[0]["score"] == 0.97
    assert results[0]["reasons"] == ["best title match", "best price"]
    assert results[1]["score"] == 0.72
    assert results[2]["reasons"] == ["weaker title match"]
