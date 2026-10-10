# Copyright (c) 2026
"""Behavioral checks for adapted."""

import xml.etree.ElementTree as ET

import pytest

from lib.elaborate.adapted import parse, render_blocks
from lib.elaborate.text import sentences

from .test_gates import context


@pytest.mark.parametrize(
    "text",
    [
        r"\{Interpolaciones de la edición de Alcalá\}",
        r"\{~ literal ~\}",
        r"\{analogy\} literal",
        r"\} suelta y \{ suelta",
    ],
)
def test_escaped_literal_braces(text: str) -> None:
    """Escaped braces render literally without becoming adaptation markers."""
    parsed = parse(text + " Más palabra{= definición}.")
    literal = text.replace(r"\{", "{").replace(r"\}", "}")
    assert parsed.body_text == literal + " Más palabra (definición)."
    assert parsed.aside_texts == []
    assert parsed.glosses == [("palabra", "definición")]
    assert literal in render_blocks(parsed.blocks)


def test_literal_braces_in_marker_content() -> None:
    """Aside and glossary views expose decoded literal braces as well."""
    parsed = parse(r"{~ Literal \{braces\}. ~} palabra{= con \{literal\}}.")
    assert parsed.aside_texts == ["Literal {braces}."]
    assert parsed.glosses == [("palabra", "con {literal}")]
    assert "palabra (con {literal})" in render_blocks(parsed.blocks)


@pytest.mark.parametrize("marker", ["9\\.", "9."])
def test_adapted_numbered_text(marker: str) -> None:
    """Keep escaped paragraph and ordered-item numbers in the body view."""
    parsed = parse(f"{marker} The cat sits.")
    assert parsed.body_text == "9. The cat sits."
    assert "9\\." not in render_blocks(parsed.blocks)


@pytest.mark.parametrize(
    ("text", "term", "rendered"),
    [
        ("*esprit*{= spirit}", "esprit", "<em>esprit (spirit)</em>"),
        ("**word**{= meaning}", "word", "<strong>word (meaning)</strong>"),
        (
            "{*esprit de corps*}{= group spirit and loyalty}",
            "esprit de corps",
            "<em>esprit de corps (group spirit and loyalty)</em>",
        ),
    ],
)
def test_gloss_after_and_inside_emphasis(text: str, term: str, rendered: str) -> None:
    """Accept emphasis around attached words and within multiword gloss terms."""
    parsed = parse(text)
    assert parsed.glosses[0][0] == term
    assert rendered in render_blocks(parsed.blocks)


def test_sentence_spans_respect_blocks_and_directive_items() -> None:
    """Unpunctuated headings, lists, quotations, and directives stay separate."""
    parsed = parse("""## A heading

- One item
- Another item

A paragraph

> A quotation

Another paragraph

@recap:
- First recap
- Second recap
""")
    assert sentences(parsed.full_text) == [
        "A heading",
        "One item",
        "Another item",
        "A paragraph",
        "A quotation",
        "Another paragraph",
        "First recap",
        "Second recap",
    ]
    assert context(
        "## A heading\n\n- One item\n- Another item\n\nA paragraph"
    ).sentence_lengths == [2, 2, 2, 2]


def test_ordered_item_is_one_sentence_span() -> None:
    """A list number is part of its item, not a standalone sentence."""
    assert sentences(parse("9. A short item").body_text) == ["9. A short item"]


@pytest.mark.parametrize("style", ["italic", "plain"])
def test_aside_block_and_inline_markup(style: str) -> None:
    """Mark each aside, use a paragraph for standalone voice, and escape text."""
    parsed = parse("""Author text {~ A & B < C. ~}

{~ No pressure, then. ~}

## Heading {~ Listen. ~}

> Quote {~ Indeed. ~}

- Item {~ Fine. ~}""")
    root = ET.fromstring(  # noqa: S314 - trusted XHTML rendered from this test's text
        f"<body>{render_blocks(parsed.blocks, style)}</body>"
    )
    asides = root.findall(".//*[@class='aside']")
    assert [aside.tag for aside in asides] == ["span", "p", "span", "span", "span"]
    assert ["".join(aside.itertext()) for aside in asides] == parsed.aside_texts
    assert all(
        (aside.find("em") is not None) == (style == "italic") for aside in asides
    )
    assert root.find(".//p[@class='aside']/span") is None
