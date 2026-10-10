# Copyright (c) 2026
"""Behavioral checks for ingest."""

from copy import replace
from typing import TYPE_CHECKING

from lib.elaborate.config import section
from lib.elaborate.data import read_facts
from lib.elaborate.gates import REGISTRY

from .helpers import (
    make_epub,
    rewrite_epub,
    run,
)
from .test_gates import context

if TYPE_CHECKING:
    from pathlib import Path


def test_ingest_literal_braces_and_protected_text(tmp_path: Path) -> None:
    """Escape source marker collisions while protecting unescaped quotes."""
    book = make_epub(tmp_path / "braces.epub", single=True)
    quote = "{Interpolaciones de la edición de Alcalá}"
    rewrite_epub(
        book,
        {
            "OPS/one.xhtml": (
                f"<html><body><h2 id='one'>One</h2><blockquote><p>{quote}</p>"
                "</blockquote><p>9. Literal {word}.</p></body></html>"
            ).encode()
        },
    )
    work = tmp_path / "work"
    result = run("ingest", str(book), "--work", str(work))
    assert result.returncode == 0, result.stderr
    source = (work / "source" / "001.md").read_text(encoding="utf-8")
    assert r"\{Interpolaciones de la edición de Alcalá\}" in source
    facts = read_facts(work / "protected" / "001.json")
    assert facts["quotes"] == [quote]
    ctx = replace(context(source.partition("\n")[2]), facts=facts)
    settings = section(section(ctx.config, "gates"), "F-quotes")
    assert REGISTRY["F-quotes"](ctx, settings) == (
        True,
        "Protected quotations retained verbatim",
        [],
    )


def test_ingest_numbered_paragraphs(tmp_path: Path) -> None:
    """Protect paragraph numbers before Markdown and escape list-like prose."""
    book = make_epub(tmp_path / "book.epub")
    rewrite_epub(
        book,
        {
            "OPS/one.xhtml": (
                b"<html><body><h2 id='one'>One</h2>"
                b"<p>9. The cat sits.</p><p>25. The cat leaves.</p>"
                b"</body></html>"
            ),
        },
    )
    work = tmp_path / "work"
    result = run("ingest", str(book), "--work", str(work))
    assert result.returncode == 0, result.stderr
    facts = read_facts(work / "protected" / "001.json")
    assert facts["numbers"] == ["9", "25", "42"]
    source = (work / "source" / "001.md").read_text(encoding="utf-8")
    assert "9\\. The cat sits." in source
    assert "25\\. The cat leaves." in source
