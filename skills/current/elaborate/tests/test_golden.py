# Copyright (c) 2026
"""Behavioral checks for golden."""

from typing import TYPE_CHECKING

from .helpers import (
    ROOT,
    adapted,
    run,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_golden_art_of_war_chapter_one(art_of_war_work: Path) -> None:
    """Run the real default-config ingest and check on the golden adaptation."""
    work = art_of_war_work
    (work / "adapted").mkdir(exist_ok=True)
    _ = (work / "adapted" / "013.md").write_bytes(
        (ROOT / "cookbook" / "art-of-war-ch01.adapted.txt").read_bytes()
    )
    result = run("check", "013", "--work", str(work))
    assert result.returncode == 0, result.stdout + result.stderr


def test_golden_lazarillo_prologo(tmp_path: Path) -> None:
    """The approved Spanish adaptation passes freshly ingested defaults."""
    work = tmp_path / "lazarillo"
    result = run(
        "ingest",
        str(ROOT / "tests" / "fixtures" / "lazarillo.epub"),
        "--work",
        str(work),
    )
    assert result.returncode == 0, result.stderr
    adapted(
        work,
        "001",
        (ROOT / "cookbook" / "lazarillo-prologo.adapted.txt").read_text(
            encoding="utf-8"
        ),
    )
    result = run("check", "001", "--work", str(work))
    assert result.returncode == 0, result.stdout + result.stderr
