from amz_live.parser import parse_search_results


def test_parse_search_results_extracts_expected_fields(search_html: str) -> None:
    results = parse_search_results(search_html)

    assert [result.asin for result in results] == [
        "B0CG1LGWR6",
        "B0CHJF41K4",
        "B07CWC39TL",
    ]

    first = results[0]
    assert first.title.startswith("LISEN USB C to USB C Cable")
    assert first.url.startswith("https://www.amazon.com/")
    assert float(first.price) == 8.99
    assert float(first.rating) == 4.6
    assert first.review_count == 7233
    assert "Best Seller" in first.badges


def test_parse_search_results_uses_primary_price_not_more_buying_choices(search_html: str) -> None:
    results = parse_search_results(search_html)

    amazon_basics = next(result for result in results if result.asin == "B07CWC39TL")
    assert float(amazon_basics.price) == 7.99
    assert float(amazon_basics.rating) == 4.5
    assert amazon_basics.review_count == 22038


def test_parse_search_results_skips_placeholder_title_links_for_sponsored_cards(
    sponsored_search_html: str,
) -> None:
    results = parse_search_results(sponsored_search_html)

    assert [result.asin for result in results] == ["B01GGKZ1VA"]

    sponsored = results[0]
    assert sponsored.title.startswith("Amazon Basics USB-C to USB-C 2.0 Fast Charging Cable")
    assert sponsored.url.startswith("https://www.amazon.com/sspa/click?")
    assert "B01GGKZ1VA" in sponsored.url
    assert sponsored.url not in {
        "https://www.amazon.com/javascript:void(0)",
        "https://www.amazon.com/#",
    }
    assert float(sponsored.price) == 7.84
    assert float(sponsored.rating) == 4.5
    assert sponsored.review_count == 54722
