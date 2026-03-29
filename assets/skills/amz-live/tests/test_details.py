import json
from pathlib import Path
from typing import Any

from amz_live.cli import main
from amz_live.parser import parse_search_results
from amz_live.protocol import get_schema_document

SEARCH_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "search_results_fragment.html"


def _detail_payload(item: dict[str, Any]) -> dict[str, Any] | None:
    details = item.get("details")
    if isinstance(details, dict):
        return details

    flat = {
        "availability_text": item.get("availability_text"),
        "bullet_points": item.get("bullet_points"),
        "delivery_text": item.get("delivery_text"),
    }
    if any(value not in (None, [], "") for value in flat.values()):
        return flat
    return None


def _patch_detail_fetch(monkeypatch, detail_html: str) -> list[str]:
    fetched: list[str] = []

    def fake_fetch_product_page(self, *args, **kwargs):  # pragma: no cover - future hook
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


def _patch_load_results_to_put_fixture_asin_first(monkeypatch, search_html: str) -> None:
    parsed = parse_search_results(search_html)
    prioritized = sorted(parsed, key=lambda result: result.asin != "B07CWC39TL")

    def fake_load_results(**kwargs):
        return prioritized

    monkeypatch.setattr("amz_live.protocol.load_results", fake_load_results)


def test_cli_json_details_enriches_only_up_to_detail_limit(
    capsys,
    monkeypatch,
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

    payload = json.loads(capsys.readouterr().out)
    assert [item["asin"] for item in payload] == ["B07CWC39TL", "B0CG1LGWR6"]
    assert fetched == ["B07CWC39TL"]

    first_details = _detail_payload(payload[0])
    assert first_details is not None
    assert "In Stock" in first_details["availability_text"]
    assert "delivery" in first_details["delivery_text"].lower()
    assert any("IN THE BOX" in bullet for bullet in first_details["bullet_points"])

    assert _detail_payload(payload[1]) is None


def test_rpc_search_details_enriches_only_up_to_detail_limit(
    monkeypatch,
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

    response = json.loads(stdout.getvalue())
    assert response["id"] == "details-1"
    assert response["success"] is True
    assert fetched == ["B07CWC39TL"]

    payload = response["data"]
    assert [item["asin"] for item in payload["results"]] == ["B07CWC39TL", "B0CG1LGWR6"]
    assert _detail_payload(payload["results"][0]) is not None
    assert _detail_payload(payload["results"][1]) is None


def test_schema_advertises_details_and_detail_limit_support() -> None:
    schema = get_schema_document()

    search_properties = schema["rpc"]["commands"]["search"]["request"]["properties"]
    assert search_properties["details"] == {"type": ["boolean", "null"]}
    assert search_properties["detailLimit"] == {"type": ["integer", "null"], "minimum": 0}

    assert schema["cli"]["options"]["--details"] == {"enrichment": "product_details"}
    assert schema["cli"]["options"]["--detail-limit"] == {"enrichment_limit": "product_details"}
