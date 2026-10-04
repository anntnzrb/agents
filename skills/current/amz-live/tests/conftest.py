import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

_ = sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

if TYPE_CHECKING:
    from amz_live.models import ProductDetail, SearchResult

from amz_live.score import ResultScore

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "search_results_fragment.html"
SPONSORED_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "sponsored_search_result_fragment.html"
)
PRODUCT_DETAIL_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "product_detail_B07CWC39TL.html"


@pytest.fixture(scope="session")
def search_html() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def sponsored_search_html() -> str:
    return SPONSORED_FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def product_detail_html() -> str:
    return PRODUCT_DETAIL_FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture
def scoring_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace only scoring; transports run the real pipeline and serializer."""
    scores = {
        "B07CWC39TL": ResultScore(0.97, ("best title match", "best price"), {}, None),
        "B0CG1LGWR6": ResultScore(0.72, ("strong rating",), {}, None),
        "B0CHJF41K4": ResultScore(0.41, ("weaker title match",), {}, None),
    }

    def score(
        results: list[SearchResult],
        *,
        query: str | None = None,
        details_by_asin: dict[str, ProductDetail] | None = None,
    ) -> tuple[list[SearchResult], dict[str, ResultScore]]:
        del query, details_by_asin
        return sorted(results, key=lambda row: -scores[row.asin].score), scores

    monkeypatch.setattr("amz_live.protocol.score_results", score)
