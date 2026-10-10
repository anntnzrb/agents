# Copyright (c) 2026
"""Pure text, marker, and protected-fact behavior."""

import pytest

from lib.elaborate.adapted import ParseError, parse, render_blocks
from lib.elaborate.config import load_config, section
from lib.elaborate.text import protect, readability, sentences, syllables, words

from .helpers import (
    DIRECTIVES,
)

TWO_SYLLABLES = 2


def test_parser_views_and_rendering() -> None:
    """Retain all directives and render escaped inline and block structures."""
    body = (
        "## Small & clear\n\n"
        "Parsimony{= saving carefully} is **good** {~ so it goes ~}.\n\n"
        "{analogy} Use {test terms}{= two words} like *this*.\n\n"
        "> A quote.\n> Next line.\n\n- First\n- Second\n\n1. Ordered\n"
    )
    parsed = parse(DIRECTIVES + body)
    assert set(parsed.directives) == {
        "idea",
        "question",
        "why",
        "recap",
        "quiz",
        "answers",
    }
    assert parsed.aside_texts == ["so it goes"]
    assert "so it goes" not in parsed.body_text
    assert "so it goes" in parsed.full_text
    assert "Parsimony (saving carefully)" in parsed.body_text
    assert parsed.glosses == [
        ("Parsimony", "saving carefully"),
        ("test terms", "two words"),
    ]
    assert sum(block.analogy for block in parsed.blocks) == 1
    rendered = render_blocks(parsed.blocks, "italic")
    assert "&amp;" in rendered
    assert "<strong>good</strong>" in rendered
    assert "<em>so it goes</em>" in rendered
    assert "<blockquote>" in rendered
    assert "<ul>" in rendered
    assert "<ol>" in rendered
    assert "{analogy}" not in rendered


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("Text\n\n@unknown: nope", 3),
        ("Text\n\nBad {~ broken", 3),
        ("Bad gloss {= nope}", 1),
        ("Bad {term}", 1),
        ("Bad }", 1),
        ("@recap:\nwrong", 2),
        ("## Heading\n\nFine\nBad {= no}", 4),
        ("@idea: one\n\n@idea: two", 3),
    ],
)
def test_parse_error_line(text: str, line: int) -> None:
    """Identify the exact source line of malformed markers and directives."""
    with pytest.raises(ParseError, match=f"line {line}:"):
        _ = parse(text)


def test_sentences_syllables_and_formulas() -> None:
    """Keep abbreviations and initials intact and apply the specified formulas."""
    assert sentences("Dr. Smith met J. Doe. He left! Did he? Yes… Fine.") == [
        "Dr. Smith met J. Doe.",
        "He left!",
        "Did he?",
        "Yes…",
        "Fine.",
    ]
    assert sentences("Use e.g. a cat. It sits.") == ["Use e.g. a cat.", "It sits."]
    assert syllables("make", "en") == 1
    assert syllables("casa", "es") == TWO_SYLLABLES
    assert syllables("rey", "es") == 1
    assert readability("The cat sat.", "en") == pytest.approx(0.39 * 3 + 11.8 - 15.59)
    assert readability("La casa.", "es") == pytest.approx(206.84 - 90 - 51)
    assert words("señor 1,234.5 can't") == ["señor", "1,234.5", "can't"]


def test_protected_facts() -> None:
    """Extract quotes, numeric tokens, rare vocabulary, hedges, and Unicode names."""
    text = (
        "A cat met Lázaro in Rome with 1,234.5 coins. He might keep them. "
        "He may say «these are all the coins I own». "
        "Using parsimony helps; parsimony saves."
    )
    facts = protect(text, ["A whole block quote."], ["Heading"], "en", load_config())
    assert facts["quotes"] == ["A whole block quote.", "these are all the coins I own"]
    assert facts["numbers"] == ["1,234.5"]
    assert "Lázaro" in facts["proper_nouns"]
    assert "Rome" in facts["proper_nouns"]
    assert facts["hedges"] == {"might": 1, "may": 1}
    assert "parsimony" in facts["rare_words"]
    assert "lázaro" not in facts["rare_words"]
    assert facts["headings"] == ["Heading"]
    assert facts["words"] == len(words(text))


def test_marker_emphasis_and_literal_asterisk() -> None:
    """Keep arithmetic numbers separate and render emphasis across gloss spans."""
    facts = protect("The result is 2*3.", [], [], "en", load_config())
    assert facts["numbers"] == ["2", "3"]
    rendered = render_blocks(parse("**Parsimony{= saving}** helps.").blocks)
    assert "<strong>Parsimony (saving)</strong>" in rendered


def test_unknown_language_facts() -> None:
    """Use empty language-specific facts when wordfreq has no data."""
    facts = protect("An unfamiliar word may appear.", [], [], "zz", load_config())
    assert facts["rare_words"] == []
    assert facts["hedges"] == {}
    assert facts["words"] == len(words("An unfamiliar word may appear."))


@pytest.mark.parametrize("opening", ["[", "(", '"', "“", "\u2018", "¿", "¡", "«"])
def test_sentence_initial_names_after_opening_marks(opening: str) -> None:
    """Opening punctuation cannot turn sentence-initial words into names."""
    text = (
        f"We see Rome. {opening}Hence we leave. {opening}Morally we agree. "
        f"{opening}Lure them away. {opening}Less is enough."
    )
    facts = protect(text, [], [], "en", load_config())
    assert facts["proper_nouns"] == ["Rome"]


def test_heading_only_names_and_possessives() -> None:
    """Ignore heading-only names and normalize possessive Unicode names."""
    text = (
        "Chapter I. LAYING PLANS\n\n"
        "We read Ts\u2019ao and Ts\u2019ao\u2019s words. We read Rome and Rome's words."
    )
    facts = protect(text, [], ["Chapter I. LAYING PLANS"], "en", load_config())
    assert facts["proper_nouns"] == ["Ts\u2019ao", "Rome"]


def test_numbered_and_quoted_sentence_initial_names() -> None:
    """Number labels and opening quotes do not create spurious proper nouns."""
    text = '19. Hence we leave.\n\nThe book says "Lure him on and tire him out."'
    facts = protect(text, [], [], "en", load_config())
    assert facts["proper_nouns"] == []


def test_spanish_quoted_opening_marks() -> None:
    """Spanish opening punctuation also follows an inline opening quote."""
    facts = protect(
        '¿Quién piensa eso? Dice "¡Oh, qué alegría!" Vamos a Roma.',
        [],
        [],
        "es",
        load_config(),
    )
    assert facts["proper_nouns"] == ["Roma"]


@pytest.mark.parametrize(
    "heading", ["LA VIDA DE LAZARILLO DE TORMES", "Lazarillo de Tormes"]
)
def test_rare_words_exclude_headings_and_capitalized_body(heading: str) -> None:
    """Title tokens and names used in either case are not rare vocabulary."""
    config = load_config()
    section(config, "protect")["rare_zipf"] = 10.0
    facts = protect(
        (
            f"{heading}\n\nParsimony aparece. parsimony vuelve. "
            "Vive Anaxágoras. anaxágoras vuelve. Hay escudriñar."
        ),
        [],
        [heading],
        "es",
        config,
    )
    assert "lazarillo" not in facts["rare_words"]
    assert "tormes" not in facts["rare_words"]
    assert "parsimony" not in facts["rare_words"]
    assert "anaxágoras" not in facts["rare_words"]
    assert "escudriñar" in facts["rare_words"]
