# Copyright (c) 2026
"""Behavioral checks for prompt."""

from typing import TYPE_CHECKING

from lib.elaborate.config import load_config, section
from lib.elaborate.data import read_facts, read_manifest, table, write_json
from lib.elaborate.work import prompt

from .test_gates import context

if TYPE_CHECKING:
    from pathlib import Path


def test_voice_preferences_render_readable_bullets(
    tmp_path: Path, synthetic_work: Path
) -> None:
    """Render populated voice settings as named prose, without JSON syntax."""
    config = load_config()
    section(config, "voice").update(
        style="Sharp friend",
        code_switch="Brief Spanish",
        slang="Light slang",
        analogy_domains=["football", "teams"],
        banned=["synergy", "leverage"],
        aside_examples=["No pressure.", "Brutal."],
    )
    template = tmp_path / "rewrite.md"
    _ = template.write_text("{{voice}}\n", encoding="utf-8")
    assert prompt(
        synthetic_work, read_manifest(synthetic_work), config, "001", template
    ) == (
        "- Style: Sharp friend\n- Code-switching: Brief Spanish\n- Slang: Light slang\n"
        "- Analogy domains: football, teams\n- Banned terms: synergy, leverage\n"
        "- Sample asides: No pressure., Brutal.\n"
    )


def test_empty_voice_preferences_render_fallback(
    tmp_path: Path, synthetic_work: Path
) -> None:
    """Empty voice preferences produce a readable explicit fallback."""
    config = load_config()
    section(config, "voice")["style"] = ""
    template = tmp_path / "rewrite.md"
    _ = template.write_text("{{voice}}\n", encoding="utf-8")
    assert (
        prompt(synthetic_work, read_manifest(synthetic_work), config, "001", template)
        == "- (no extra voice preferences)\n"
    )


def test_thresholds_render_descriptions_and_parameters(
    tmp_path: Path, synthetic_work: Path
) -> None:
    """Only enabled gates appear, with severity, descriptions, and plain params."""
    config = load_config()
    for value in section(config, "gates").values():
        table(value)["enabled"] = False
    section(section(config, "gates"), "F-coverage")["enabled"] = True
    section(section(config, "gates"), "B-gloss-consistent")["enabled"] = True
    template = tmp_path / "rewrite.md"
    _ = template.write_text("{{thresholds}}\n", encoding="utf-8")
    assert prompt(
        synthetic_work, read_manifest(synthetic_work), config, "001", template
    ) == (
        "- F-coverage (error): Require content vocabulary coverage.; "
        "min=0.85, stop_zipf=5.5, stem_length=6\n"
        "- B-gloss-consistent (warn): "
        "Require consistent definitions for each glossed term.\n"
    )


def test_protected_prompt_compact_lists(tmp_path: Path, synthetic_work: Path) -> None:
    """Render multi-item facts compactly while retaining separate quote lines."""
    work = synthetic_work
    facts = read_facts(work / "protected" / "001.json")
    write_json(
        work / "protected" / "001.json",
        facts
        | {
            "quotes": ["First quotation.", "Second quotation."],
            "numbers": ["42", "100"],
            "proper_nouns": ["Rome", "Madrid"],
            "hedges": {"may": 2, "perhaps": 1},
            "rare_words": ["parsimony", "feigning"],
        },
    )
    template = tmp_path / "rewrite.md"
    _ = template.write_text("{{protected}}\n", encoding="utf-8")
    assert prompt(work, read_manifest(work), context("").config, "001", template) == (
        "Quotes:\n- First quotation.\n- Second quotation.\n\n"
        "Numbers: 42, 100\n\nProper nouns: Rome, Madrid\n\n"
        "Hedges: may x2, perhaps x1\n\nRare words: parsimony, feigning\n"
    )
