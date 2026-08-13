import string
from urllib.parse import parse_qs, urlparse

from hypothesis import given
from hypothesis import strategies as st

from amz_live.query import SearchQuery, build_search_url

_KEYWORDS = st.text(
    alphabet=string.ascii_letters + string.digits + " -_+/",
    min_size=1,
    max_size=60,
).filter(lambda value: value.strip() != "")
_OPTIONAL_SORT = st.one_of(st.none(), _KEYWORDS)
_OPTIONAL_ZIP = st.one_of(st.none(), st.from_regex(r"\d{5}", fullmatch=True))


@given(
    keywords=_KEYWORDS,
    page=st.integers(min_value=1, max_value=20),
    amazon_sort=_OPTIONAL_SORT,
    zip_code=_OPTIONAL_ZIP,
)
def test_search_query_to_params_normalizes_boundary_inputs(
    keywords: str,
    page: int,
    amazon_sort: str | None,
    zip_code: str | None,
) -> None:
    query = SearchQuery(
        f"  {keywords}  ",
        page=page,
        amazon_sort=None if amazon_sort is None else f"  {amazon_sort}  ",
        zip_code=None if zip_code is None else f"  {zip_code}  ",
    )

    params = query.to_params()
    assert params["k"] == keywords.strip()
    assert params["page"] == str(page)

    if amazon_sort is None:
        assert "s" not in params
    else:
        assert params["s"] == amazon_sort.strip()

    if zip_code is None:
        assert "rh" not in params
    else:
        assert params["rh"] == f"p_47:{zip_code}"


@given(
    keywords=_KEYWORDS,
    page=st.integers(min_value=1, max_value=20),
    zip_code=_OPTIONAL_ZIP,
)
def test_build_search_url_round_trips_query_params(
    keywords: str,
    page: int,
    zip_code: str | None,
) -> None:
    query = SearchQuery(keywords, page=page, zip_code=zip_code)
    url = build_search_url(query)
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "www.amazon.com"
    assert parsed.path == "/s"
    assert params["k"] == [query.keywords]
    assert params["page"] == [str(page)]

    if zip_code is None:
        assert "rh" not in params
    else:
        assert params["rh"] == [f"p_47:{zip_code}"]
