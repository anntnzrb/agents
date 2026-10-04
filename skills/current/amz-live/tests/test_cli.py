import json
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, TypeIs

from amz_live.cli import main

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

    from amz_live.protocol import SearchResultsPayload

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "search_results_fragment.html"


class _ScoredResult(TypedDict):
    asin: str
    score: float
    reasons: list[str]


class _SchemaCommand(TypedDict):
    request: dict[str, object]


class _SchemaRpc(TypedDict):
    pi_inspired: bool
    full_pi_rpc: bool
    request_command_field: str
    legacy_request_command_field: str
    commands: dict[str, _SchemaCommand]


class _SchemaDocument(TypedDict):
    type: str
    version: str
    name: str
    rpc: _SchemaRpc
    llm_json: dict[str, object]


def _is_dict_list(val: object) -> TypeIs[list[dict[str, object]]]:
    return isinstance(val, list)


def _is_str_dict(val: object) -> TypeIs[dict[str, object]]:
    return isinstance(val, dict)


def _is_schema_document(val: object) -> TypeIs[_SchemaDocument]:
    return isinstance(val, dict)


def _is_search_results_payload(val: object) -> TypeIs[SearchResultsPayload]:
    return isinstance(val, dict)


def _is_scored_result_list(val: object) -> TypeIs[list[_ScoredResult]]:
    return isinstance(val, list)


def _loads_json(text: str) -> object:
    fn: Callable[..., object] = json.loads
    return fn(text)


def test_cli_parses_fixture_filters_results_and_emits_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
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

    raw_payload = _loads_json(capsys.readouterr().out)
    assert _is_dict_list(raw_payload)
    payload = raw_payload
    assert [item["asin"] for item in payload] == ["B0CG1LGWR6", "B07CWC39TL"]


def test_cli_parses_fixture_include_filter_and_emits_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
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

    raw_payload = _loads_json(capsys.readouterr().out)
    assert _is_dict_list(raw_payload)
    payload = raw_payload
    assert [item["asin"] for item in payload] == ["B07CWC39TL"]


def test_cli_emits_llm_json_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
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

    raw_payload = _loads_json(capsys.readouterr().out)
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


def test_cli_schema_output_shape(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--schema"])

    assert exit_code == 0

    raw_payload = _loads_json(capsys.readouterr().out)
    assert _is_schema_document(raw_payload)
    payload = raw_payload
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


def test_cli_llm_json_scoring_mode_emits_scores_and_reasons(
    scoring_boundary: None, capsys: pytest.CaptureFixture[str]
) -> None:
    del scoring_boundary

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

    raw_payload = _loads_json(capsys.readouterr().out)
    assert _is_str_dict(raw_payload)
    payload = raw_payload
    raw_results = payload.get("results")
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
