from amz_live.filters import filter_results
from amz_live.parser import parse_search_results


def test_filter_results_supports_rating_price_and_limit(search_html: str) -> None:
    results = parse_search_results(search_html)

    filtered = filter_results(results, min_rating=4.5, max_price=9.0, limit=2)

    assert [result.asin for result in filtered] == ["B0CG1LGWR6", "B07CWC39TL"]


def test_filter_results_supports_title_and_badge_filters(search_html: str) -> None:
    results = parse_search_results(search_html)

    badge_filtered = filter_results(results, badge="Best Seller")
    title_filtered = filter_results(results, title_contains="amazon basics")

    assert [result.asin for result in badge_filtered] == ["B0CG1LGWR6"]
    assert [result.asin for result in title_filtered] == ["B07CWC39TL"]


def test_filter_results_supports_include_and_exclude_terms(search_html: str) -> None:
    results = parse_search_results(search_html)

    filtered = filter_results(
        results,
        include=["usb", "charging"],
        exclude=["amazon basics"],
    )

    assert [result.asin for result in filtered] == ["B0CG1LGWR6", "B0CHJF41K4"]
