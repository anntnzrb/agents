from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

from amz_live.cli import main
from amz_live.protocol import serialize_results

if TYPE_CHECKING:
    from collections.abc import Sequence
    from decimal import Decimal

    import pytest

    from amz_live.models import SearchResult
    from amz_live.protocol import SearchResultsPayload, SerializedSearchResultPayload

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "search_results_fragment.html"


class _ScoredResult(TypedDict):
    asin: str
    score: float
    reasons: list[str]


class _FakeScore(TypedDict):
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

    payload = cast("list[SerializedSearchResultPayload]", json.loads(capsys.readouterr().out))
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

    payload = cast("list[SerializedSearchResultPayload]", json.loads(capsys.readouterr().out))
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

    payload = cast("SearchResultsPayload", json.loads(capsys.readouterr().out))
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

    payload = cast("_SchemaDocument", json.loads(capsys.readouterr().out))
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
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    score_map: dict[str, _FakeScore] = {
        "B07CWC39TL": {"score": 0.97, "reasons": ["best title match", "best price"]},
        "B0CG1LGWR6": {"score": 0.72, "reasons": ["strong rating"]},
        "B0CHJF41K4": {"score": 0.41, "reasons": ["weaker title match"]},
    }

    def fake_build_llm_json(
        *,
        query: str,
        html_path: str | None,
        page: int,
        pages: int,
        amazon_sort: str | None,
        min_rating: float | Decimal | None,
        max_price: float | Decimal | None,
        badge: str | None,
        title_contains: str | None,
        include: Sequence[str] | None,
        exclude: Sequence[str] | None,
        limit: int | None,
        raw_results: Sequence[SearchResult],
        filtered_results: Sequence[SearchResult],
        scoring: bool = False,
        **_rest: object,
    ) -> dict[str, object]:
        assert scoring is True
        ranked_results = sorted(
            filtered_results,
            key=lambda result: score_map[result.asin]["score"],
            reverse=True,
        )
        results = serialize_results(ranked_results)
        for item in results:
            entry = score_map[item["asin"]]
            item["score"] = entry["score"]
            item["reasons"] = entry["reasons"]
        return {
            "type": "amz-live.search_results",
            "version": "1",
            "ok": True,
            "source": {"mode": "html", "html_path": html_path},
            "query": {
                "keywords": query,
                "page": page,
                "pages": pages,
                "amazon_sort": amazon_sort,
            },
            "filters": {
                "min_rating": min_rating,
                "max_price": max_price,
                "badge": badge,
                "title_contains": title_contains,
                "include": list(include or []),
                "exclude": list(exclude or []),
                "limit": limit,
            },
            "summary": {
                "raw_result_count": len(raw_results),
                "returned_result_count": len(ranked_results),
            },
            "results": results,
        }

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

    payload = cast("dict[str, object]", json.loads(capsys.readouterr().out))
    results = cast("list[_ScoredResult]", payload["results"])
    assert [item["asin"] for item in results] == [
        "B07CWC39TL",
        "B0CG1LGWR6",
        "B0CHJF41K4",
    ]
    assert results[0]["score"] == 0.97
    assert results[0]["reasons"] == ["best title match", "best price"]
    assert results[1]["score"] == 0.72
    assert results[2]["reasons"] == ["weaker title match"]
