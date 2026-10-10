# Copyright (c) 2026
"""Ingest once per session; copy mutable work directories into each test."""

from typing import TYPE_CHECKING

import pytest

from .helpers import ROOT, make_epub, run

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(scope="session")
def synthetic_ingested(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Keep the default two-unit work directory pristine for reuse."""
    directory = tmp_path_factory.mktemp("synthetic-ingested")
    book = make_epub(directory / "book.epub")
    work = directory / "work"
    result = run("ingest", str(book), "--work", str(work), "--json")
    assert result.returncode == 0, result.stderr
    return work


@pytest.fixture
def synthetic_work(tmp_path: Path, synthetic_ingested: Path) -> Path:
    """Isolate adaptations, checks, and manifest edits in a private copy."""
    return synthetic_ingested.copy(tmp_path / "work")


@pytest.fixture(scope="session")
def art_of_war_ingested(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Share the expensive real default-config ingest across chapter tests."""
    work = tmp_path_factory.mktemp("art-of-war-ingested")
    result = run(
        "ingest",
        str(ROOT / "tests" / "fixtures" / "art-of-war.epub"),
        "--work",
        str(work),
    )
    assert result.returncode == 0, result.stderr
    return work


@pytest.fixture
def art_of_war_work(tmp_path: Path, art_of_war_ingested: Path) -> Path:
    """Give builds and the golden adaptation their own real-fixture work files."""
    return art_of_war_ingested.copy(tmp_path / "art")
