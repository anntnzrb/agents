"""Deal evidence survives parsing and the public CLI/RPC entrypoint."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeIs

import pytest

from amz_live.models import AmazonClientError
from amz_live.parser import discover_deal_filter, parse_search_results

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from amz_live.models import SearchResultPayload
    from amz_live.protocol import SearchResultsPayload

SKILL_ROOT = Path(__file__).resolve().parents[1]
CAPTURED_OFFERS = SKILL_ROOT / "tests" / "fixtures" / "current_offers_fragment.html"
US_OFFERS = SKILL_ROOT / "tests" / "fixtures" / "us_prime_offers.html"


def _loads_json(text: str) -> object:
    load: Callable[..., object] = json.loads
    return load(text)


def _is_results(value: object) -> TypeIs[list[SearchResultPayload]]:
    return isinstance(value, list)


def _is_envelope(value: object) -> TypeIs[SearchResultsPayload]:
    return isinstance(value, dict)


def _is_response(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict)


def _run_cli(args: Sequence[str], home: Path, *, stdin: str | None = None) -> str:
    result = subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts" / "cli.py"), *args],
        input=stdin,
        check=False,
        capture_output=True,
        text=True,
        env={
            **{
                key: os.environ[key]
                for key in ("PATH", "SYSTEMROOT", "WINDIR")
                if key in os.environ
            },
            "HOME": str(home),
            "USERPROFILE": str(home),
        },
        cwd=home,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("output", ["--json", "--llm-json", "rpc"])
def test_captured_offers_report_reference_prices_and_coupon(output: str, tmp_path: Path) -> None:
    if output == "rpc":
        raw = _run_cli(
            ["--mode", "rpc"],
            tmp_path,
            stdin=json.dumps(
                {"type": "search", "query": "earbuds", "htmlPath": str(CAPTURED_OFFERS)}
            )
            + "\n",
        )
        response = _loads_json(raw)
        assert _is_response(response)
        assert response.get("success") is True
        data: object = response.get("data")
        assert _is_envelope(data)
        results = data["results"]
    else:
        raw = _run_cli(["earbuds", "--html", str(CAPTURED_OFFERS), output], tmp_path)
        payload = _loads_json(raw)
        if output == "--json":
            assert _is_results(payload)
            results = payload
        else:
            assert _is_envelope(payload)
            results = payload["results"]

    apple, coupon = results
    assert apple["title"].startswith("Airpods (4Th Generation)")
    assert apple["price"] == 128.47
    assert apple["reference_price"] == 136.71
    assert apple["reference_price_label"] == "Typical price"
    assert apple["discount_percent"] == 6.03
    assert apple["prime_exclusive"] is None
    assert coupon["price"] == 75.98
    assert coupon["reference_price"] == 179.99
    assert coupon["reference_price_label"] == "List Price"
    assert coupon["coupon_text"] == "Save 50% with coupon"


@pytest.mark.parametrize(
    "label", ["Prime exclusive deal", "Prime Big Deal", "Exclusive Prime price"]
)
@pytest.mark.parametrize("badge_class", ["a-badge-text", "a-color-price"])
def test_explicit_prime_offer_is_reported_and_filterable(
    label: str, badge_class: str, tmp_path: Path
) -> None:
    html = f"""
    <div data-component-type="s-search-result" data-asin="PRIMEOFFER">
      <h2><a href="/dp/PRIMEOFFER"><span>Wireless earbuds</span></a></h2>
      <div data-cy="price-recipe">
        <span class="{badge_class}">{label}</span>
        <span class="a-price" data-a-size="xl"><span class="a-offscreen">$24.99</span></span>
      </div>
    </div>
    """
    fixture = tmp_path / "prime.html"
    _ = fixture.write_text(html, encoding="utf-8")
    raw = _run_cli(["earbuds", "--html", str(fixture), "--badge", "Prime", "--llm-json"], tmp_path)
    payload = _loads_json(raw)
    assert _is_envelope(payload)
    assert payload["summary"]["returned_result_count"] == 1
    if label == "Prime Big Deal":
        assert payload["results"][0]["prime_exclusive"] is None
    else:
        assert payload["results"][0]["prime_exclusive"] is True
    assert label in payload["results"][0]["badges"]


def test_human_output_preserves_coupon_and_reference_evidence(tmp_path: Path) -> None:
    output = _run_cli(["earbuds", "--html", str(CAPTURED_OFFERS)], tmp_path)
    assert "Typical price: $136.71 (6.03% below reference)" in output
    assert "Save 50% with coupon" in output
    assert "Prime exclusive" not in output


def test_us_captured_deals_have_correct_price_evidence_and_location(tmp_path: Path) -> None:
    raw = _run_cli(
        ["earbuds", "--html", str(US_OFFERS), "--deals", "--zip", "33101", "--llm-json"],
        tmp_path,
    )
    payload = _loads_json(raw)
    assert _is_envelope(payload)
    assert payload["summary"]["delivery_location"] == "Miami 33101"
    assert payload["query"]["deal_refinement"] == "Prime Big Deals"
    results = {r["asin"]: r for r in payload["results"]}
    unit_price = results["B0CVVTXVG6"]
    assert unit_price["price"] == 16.79
    assert unit_price["reference_price"] == 28.99
    assert unit_price["discount_percent"] == 42.08
    assert unit_price["prime_exclusive"] is True
    assert results["B0FQFB8FMG"]["reference_price_label"] == "List"
    assert results["B0GT8CG3V2"]["sponsored"] is True
    assert results["B0C1QWWZR4"]["prime_exclusive"] is None


def test_unrecognized_empty_page_fails_instead_of_claiming_no_deals(tmp_path: Path) -> None:
    fixture = tmp_path / "empty.html"
    _ = fixture.write_text("<html><body></body></html>", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "cli.py"),
            "earbuds",
            "--html",
            str(fixture),
            "--llm-json",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "unrecognized" in result.stderr.lower()
    assert not result.stdout


def test_explicit_empty_search_is_success_without_claiming_no_event_deals(tmp_path: Path) -> None:
    fixture = tmp_path / "no-results.html"
    _ = fixture.write_text(
        """<html><span id="glow-ingress-line2">Miami 33101</span>
        <h2>No results for impossible-query</h2></html>""",
        encoding="utf-8",
    )
    payload = _loads_json(
        _run_cli(
            ["impossible-query", "--html", str(fixture), "--zip", "33101", "--llm-json"], tmp_path
        )
    )
    assert _is_envelope(payload)
    assert payload["ok"] is True
    assert payload["summary"]["raw_result_count"] == 0
    assert "warnings" in payload
    assert payload["warnings"]


@pytest.mark.parametrize("hidden", ['class="aok-hidden"', 'aria-hidden="true"'])
def test_hidden_prime_templates_do_not_imply_membership(hidden: str) -> None:
    html = f"""
    <div data-component-type="s-search-result" data-asin="NORMAL">
      <h2><a href="/dp/NORMAL"><span>Earbuds</span></a></h2>
      <div data-cy="price-recipe">
        <div {hidden}><span class="a-badge-text">Prime exclusive deal</span></div>
        <span class="a-price" data-a-size="xl"><span class="a-offscreen">$24.99</span></span>
      </div>
    </div>
    """
    result = parse_search_results(html)[0]
    assert result.prime_exclusive is None
    assert not result.badges


def test_zero_limit_returns_no_products(tmp_path: Path) -> None:
    payload = _loads_json(
        _run_cli(
            ["earbuds", "--html", str(CAPTURED_OFFERS), "--limit", "0", "--llm-json"], tmp_path
        )
    )
    assert _is_envelope(payload)
    assert payload["summary"]["raw_result_count"] == 2
    assert payload["summary"]["returned_result_count"] == 0
    assert not payload["results"]


def test_prime_shipping_is_not_a_prime_deal_and_reference_is_not_current_price() -> None:
    html = """
    <div data-component-type="s-search-result" data-asin="SHIPPING">
      <h2><a href="/dp/SHIPPING"><span>Prime compatible earbuds</span></a></h2>
      <div data-cy="price-recipe">
        <span class="a-price a-text-price" data-a-strike="true">
          <span class="a-offscreen">$49.99</span>
        </span>
      </div>
      <i class="a-icon-prime" aria-label="Prime"></i><span>FREE delivery with Prime</span>
    </div>
    """
    result = parse_search_results(html)[0].to_dict()
    assert result["price"] is None
    assert result["reference_price"] == 49.99
    assert result["discount_percent"] is None
    assert result["prime_exclusive"] is None
    assert "Prime" not in result["badges"]


@pytest.mark.parametrize("reference", ["$0.00", "$19.00", "$24.99"])
def test_non_discounted_reference_does_not_invent_savings(reference: str) -> None:
    html = f"""
    <div data-component-type="s-search-result" data-asin="NORMAL">
      <h2><a href="/dp/NORMAL"><span>Wireless earbuds</span></a></h2>
      <div data-cy="price-recipe">
        <span class="a-badge-text">Limited time deal</span>
        <span class="a-price" data-a-size="xl"><span class="a-offscreen">$24.99</span></span>
        <span class="a-price a-text-price" data-a-strike="true">
          <span class="a-offscreen">{reference}</span>
        </span>
      </div>
    </div>
    """
    result = parse_search_results(html)[0].to_dict()
    assert "Limited time deal" in result["badges"]
    assert result["discount_percent"] is None
    assert result["prime_exclusive"] is None


def test_replayed_location_does_not_verify_requested_zip(tmp_path: Path) -> None:
    fixture = tmp_path / "ecuador.html"
    _ = fixture.write_text(
        '<span id="glow-ingress-line2">Ecuador</span>' + CAPTURED_OFFERS.read_text(),
        encoding="utf-8",
    )
    payload = _loads_json(
        _run_cli(["earbuds", "--html", str(fixture), "--zip", "33101", "--llm-json"], tmp_path)
    )
    assert _is_envelope(payload)
    assert payload["summary"]["delivery_location"] == "Ecuador"
    assert "warnings" in payload
    assert any("Ecuador" in warning for warning in payload["warnings"])


def test_sponsored_results_emit_canonical_product_urls() -> None:
    results = parse_search_results(US_OFFERS.read_text(encoding="utf-8"))
    assert any(result.sponsored for result in results)
    assert all(result.url == f"https://www.amazon.com/dp/{result.asin}" for result in results)


def test_html_rpc_validates_zip_before_parsing(tmp_path: Path) -> None:
    raw = _run_cli(
        ["--mode", "rpc"],
        tmp_path,
        stdin=json.dumps(
            {
                "type": "search",
                "query": "earbuds",
                "htmlPath": str(CAPTURED_OFFERS),
                "zipCode": "invalid",
            }
        )
        + "\n",
    )
    response = _loads_json(raw)
    assert _is_response(response)
    assert response["success"] is False


def test_deal_discovery_prefers_all_deals_and_preserves_only_the_deal_term() -> None:
    html = """<ul id="filter-p_n_deal_type">
      <a href="/s?rh=p_n_deal_type%3A111">Prime Day Deals</a>
      <a href="/s?rh=p_47%3A90210%2Cp_n_deal_type%3A222&amp;page=8"> <span>All Deals</span> </a>
    </ul>"""
    assert discover_deal_filter(html, base_url="https://www.amazon.com") == (
        "p_n_deal_type:222",
        "All Deals",
    )


@pytest.mark.parametrize(
    "href",
    [
        "https://other.example/s?rh=p_n_deal_type:123",
        "//other.example/s?rh=p_n_deal_type:123",
        "/sspa/click?rh=p_n_deal_type:123",
        "/s?rh=p_n_deal_type:old",
        "/s?k=all",
        "javascript:void(0)",
    ],
)
def test_deal_discovery_rejects_unusable_or_external_links(href: str) -> None:
    html = f'<ul id="filter-p_n_deal_type"><a href="{href}">Deals</a></ul>'
    with pytest.raises(AmazonClientError, match="no usable deal filter"):
        _ = discover_deal_filter(html, base_url="https://www.amazon.com")


@pytest.mark.parametrize("label", ["All Deals", "All Discounts", "Today's Deals"])
def test_deal_discovery_prefers_broad_options_over_event(label: str) -> None:
    html = (
        '<ul id="filter-p_n_deal_type">'
        '<a href="/s?rh=p_n_deal_type:1">Prime Day Deals</a>'
        f'<a href="/s?rh=p_n_deal_type:2">{label}</a></ul>'
    )
    assert discover_deal_filter(html, base_url="https://www.amazon.com") == (
        "p_n_deal_type:2",
        label,
    )
