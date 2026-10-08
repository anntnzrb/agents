"""Build eBay search URLs without browser state."""

from typing import TYPE_CHECKING
from urllib.parse import urlencode

from .models import CONDITIONS, SORTS

if TYPE_CHECKING:
    from .models import SearchQuery

EBAY_BASE_URL = "https://www.ebay.com"


def build_search_url(query: SearchQuery, *, base_url: str = EBAY_BASE_URL) -> str:
    """Translate readable options to eBay's current query keys."""
    params = {
        "_nkw": query.keywords,
        "_sop": SORTS[query.sort],
        "_ipg": str(query.per_page),
        "_pgn": str(query.page),
    }
    for name, value in (("_udlo", query.min_price), ("_udhi", query.max_price)):
        if value is not None:
            params[name] = str(value)
    if query.condition:
        params["LH_ItemCondition"] = CONDITIONS[query.condition]
    if query.buy_it_now:
        params["LH_BIN"] = "1"
    if query.auction:
        params["LH_Auction"] = "1"
    if query.zip_code:
        params["_stpos"] = query.zip_code
    return f"{base_url.rstrip('/')}/sch/i.html?{urlencode(params)}"
