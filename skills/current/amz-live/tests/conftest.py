import sys
from pathlib import Path

import pytest

_ = sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

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
