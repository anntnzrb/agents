import json
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, TypeIs

from amz_live.cli import main
from amz_live.parser import parse_search_results
from amz_live.protocol import get_schema_document

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    import pytest

    from amz_live.client import AmazonSearchClient
    from amz_live.models import ProductDetailPayload, SearchResult

SEARCH_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "search_results_fragment.html"


class _AsinItem(TypedDict):
    asin: str


class _SearchRequest(TypedDict):
    properties: dict[str, object]


class _SearchCommand(TypedDict):
    request: _SearchRequest


class _RpcSchema(TypedDict):
    commands: dict[str, _SearchCommand]


class _CliSchema(TypedDict):
    options: dict[str, object]


class _DetailsSchema(TypedDict):
    rpc: _RpcSchema
    cli: _CliSchema


def _is_product_detail_payload(val: object) -> TypeIs[ProductDetailPayload]:
    return isinstance(val, dict)


def _is_asin_list(val: object) -> TypeIs[list[_AsinItem]]:
    return isinstance(val, list)


def _is_str_dict(val: object) -> TypeIs[dict[str, object]]:
    return isinstance(val, dict)


def _is_details_schema(val: object) -> TypeIs[_DetailsSchema]:
    return isinstance(val, dict)


def _loads_json(text: str) -> object:
    fn: Callable[..., object] = json.loads
    return fn(text)


def _detail_payload(item: Mapping[str, object]) -> ProductDetailPayload | None:
    details = item.get("details")
    if not _is_product_detail_payload(details):
        return None
    return details


def _patch_detail_fetch(monkeypatch: pytest.MonkeyPatch, detail_html: str) -> list[str]:
    fetched: list[str] = []

    def fake_fetch_product_page(
        _self: AmazonSearchClient, *args: object, **kwargs: object
    ) -> str:  # pragma: no cover - future hook
        haystack = " ".join(
            [*(str(arg) for arg in args), *(f"{key}={value}" for key, value in kwargs.items())],
        )
        if "B07CWC39TL" in haystack:
            fetched.append("B07CWC39TL")
            return detail_html
        if any(asin in haystack for asin in ("B0CG1LGWR6", "B0CHJF41K4")):
            raise AssertionError(f"detail limit ignored; unexpected detail fetch: {haystack}")
        raise AssertionError(f"unexpected detail fetch target: {haystack}")

    monkeypatch.setattr(
        "amz_live.client.AmazonSearchClient.fetch_product_page",
        fake_fetch_product_page,
        raising=False,
    )
    return fetched


def _patch_load_results_to_put_fixture_asin_first(
    monkeypatch: pytest.MonkeyPatch, search_html: str
) -> None:
    parsed = parse_search_results(search_html)
    prioritized = sorted(parsed, key=lambda result: result.asin != "B07CWC39TL")

    def fake_load_results(**_kwargs: object) -> list[SearchResult]:
        return prioritized

    monkeypatch.setattr("amz_live.protocol.load_results", fake_load_results)


def test_cli_json_details_enriches_only_up_to_detail_limit(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    search_html: str,
    product_detail_html: str,
) -> None:
    _patch_load_results_to_put_fixture_asin_first(monkeypatch, search_html)
    fetched = _patch_detail_fetch(monkeypatch, product_detail_html)

    exit_code = main(
        [
            "usb c to usb c braided cable",
            "--html",
            str(SEARCH_FIXTURE_PATH),
            "--max-price",
            "9.0",
            "--limit",
            "2",
            "--details",
            "--detail-limit",
            "1",
            "--json",
        ],
    )

    assert exit_code == 0

    raw_payload = _loads_json(capsys.readouterr().out)
    assert _is_asin_list(raw_payload)
    payload = raw_payload
    assert [item["asin"] for item in payload] == ["B07CWC39TL", "B0CG1LGWR6"]
    assert fetched == ["B07CWC39TL"]

    first_details = _detail_payload(payload[0])
    assert first_details is not None
    availability_text = first_details["availability_text"]
    delivery_text = first_details["delivery_text"]
    assert availability_text is not None
    assert "In Stock" in availability_text
    assert delivery_text is not None
    assert "delivery" in delivery_text.lower()
    assert any("IN THE BOX" in bullet for bullet in first_details["bullet_points"])

    assert _detail_payload(payload[1]) is None


def test_rpc_search_details_enriches_only_up_to_detail_limit(
    monkeypatch: pytest.MonkeyPatch,
    search_html: str,
    product_detail_html: str,
) -> None:
    from io import StringIO

    _patch_load_results_to_put_fixture_asin_first(monkeypatch, search_html)
    fetched = _patch_detail_fetch(monkeypatch, product_detail_html)

    stdin = StringIO(
        json.dumps(
            {
                "id": "details-1",
                "type": "search",
                "query": "usb c to usb c braided cable",
                "htmlPath": str(SEARCH_FIXTURE_PATH),
                "maxPrice": 9.0,
                "limit": 2,
                "details": True,
                "detailLimit": 1,
            },
        )
        + "\n",
    )
    stdout = StringIO()

    exit_code = main(["--mode", "rpc"], stdin=stdin, stdout=stdout)

    assert exit_code == 0

    raw_response = _loads_json(stdout.getvalue())
    assert _is_str_dict(raw_response)
    response = raw_response
    assert response["id"] == "details-1"
    assert response["success"] is True
    assert fetched == ["B07CWC39TL"]

    raw_payload = response.get("data")
    assert _is_str_dict(raw_payload)
    raw_results = raw_payload.get("results")
    assert _is_asin_list(raw_results)
    results = raw_results
    assert [item["asin"] for item in results] == ["B07CWC39TL", "B0CG1LGWR6"]
    assert _detail_payload(results[0]) is not None
    assert _detail_payload(results[1]) is None


def test_schema_advertises_details_and_detail_limit_support() -> None:
    raw_schema = _loads_json(json.dumps(get_schema_document()))
    assert _is_details_schema(raw_schema)
    schema = raw_schema

    search_properties = schema["rpc"]["commands"]["search"]["request"]["properties"]
    assert search_properties["details"] == {"type": ["boolean", "null"]}
    assert search_properties["detailLimit"] == {"type": ["integer", "null"], "minimum": 0}

    assert schema["cli"]["options"]["--details"] == {"enrichment": "product_details"}
    assert schema["cli"]["options"]["--detail-limit"] == {"enrichment_limit": "product_details"}
