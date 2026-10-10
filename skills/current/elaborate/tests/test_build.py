# Copyright (c) 2026
"""Behavioral checks for build."""

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING
from zipfile import ZipFile

import pytest

from .helpers import ADAPTED_BODY, DIRECTIVES, adapted, run

if TYPE_CHECKING:
    from pathlib import Path


XHTML = "{http://www.w3.org/1999/xhtml}"


@pytest.mark.parametrize("style", [None, "plain"])
def test_built_epub_aside_voice(
    tmp_path: Path, synthetic_work: Path, style: str | None
) -> None:
    """Default italics and explicit plain preserve aside classes and EPUB bytes."""
    work = synthetic_work
    body = ADAPTED_BODY.replace("birds.", "birds. {~ So it goes. ~}", 1)
    adapted(
        work,
        "001",
        DIRECTIVES.replace("We can look.", "We can look. {~ Listen. ~}")
        + body
        + "\n\n{~ No pressure, then. ~}\n",
    )
    config_args: list[str] = []
    if style is not None:
        config = tmp_path / "style.toml"
        _ = config.write_text(f'[build]\naside_style = "{style}"\n', encoding="utf-8")
        config_args = ["--config", str(config)]
    first, second = tmp_path / "first.epub", tmp_path / "second.epub"
    for out in (first, second):
        result = run(
            "build",
            "--work",
            str(work),
            "--out",
            str(out),
            "--allow-pending",
            *config_args,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        chapter = ET.fromstring(  # noqa: S314 - trusted EPUB built by this test
            archive.read("EPUB/chapter-001.xhtml")
        )
        asides = chapter.findall(".//*[@class='aside']")
        assert [aside.tag for aside in asides] == [
            XHTML + "span",
            XHTML + "p",
            XHTML + "span",
        ]
        assert ["".join(aside.itertext()) for aside in asides] == [
            "So it goes.",
            "No pressure, then.",
            "Listen.",
        ]
        assert all(
            (aside.find(XHTML + "em") is not None) == (style is None)
            for aside in asides
        )
        css = archive.read("EPUB/style.css").decode()
        assert ".aside" in css
        assert "font-style: italic" in css
        assert "p.aside" in css
        assert "border-left:" in css or "margin-left:" in css
