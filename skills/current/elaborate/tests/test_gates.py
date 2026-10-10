# Copyright (c) 2026
"""Passing and failing behavioral examples for every registered gate."""

from copy import replace

import pytest

from lib.elaborate.adapted import parse, render_blocks
from lib.elaborate.config import load_config, section
from lib.elaborate.data import Facts, Table, table
from lib.elaborate.gates import (
    REGISTRY,
    Context,
    book_gates,
    evaluate,
    first_glossed,
    metrics,
)
from lib.elaborate.text import words

from .helpers import (
    DIRECTIVES,
)

CASES: list[tuple[str, str, str]] = [
    ("K-no-h1", "## Good", "# Bad"),
    ("K-no-emoji", "Plain text.", "Plain 😀 text."),
    ("K-no-tables", "Plain text.", "| a | b |"),
    ("F-quotes", "> The cat sat on the green mat.", "The cat sat elsewhere."),
    ("F-numbers", "There are 42 cats.", "There are 142 cats."),
    ("F-names", "We see Rome.", "We see rome."),
    ("F-hedges", "It may work.", "It will work."),
    ("F-length", "The cat may sit by Rome and see 42 birds.", "Cat."),
    ("F-coverage", "The cat may sit by Rome and see 42 birds.", "Zebras dance."),
    ("F-aside-facts", "Text {~ Oh how odd ~}.", "Text {~ Oh NASA has 2 cats ~}."),
    ("L-rare-kept", "Parsimony is wise.", "Saving is wise."),
    (
        "L-gloss",
        "Parsimony{= saving} is wise.",
        "Parsimony is wise. Parsimony{= saving} helps.",
    ),
    ("R-sentence-avg", "The cat sits. It sees birds.", "Word " * 20 + "."),
    ("R-sentence-max", "The cat sits.", "Word " * 31 + "."),
    ("R-paragraph", "The cat sits.", "Cat sits. " * 5),
    (
        "R-grade",
        "The cat sits.",
        "Incomprehensibility characterizes internationalization.",
    ),
    ("R-nominal", "The cat sits.", "Characterization of management."),
    ("S-headings", "## Heading\n\nCat.", "Cat " * 401),
    ("V-aside-length", "Text {~ nice ~}.", "Text {~ " + "word " * 13 + "~}."),
    ("V-aside-cadence", "Cat " * 200 + "{~ oh ~} " + "Cat " * 100, "Cat " * 351),
    ("V-analogy", "{analogy} One.", "{analogy} One.\n\n{analogy} Two."),
    ("V-banned", "Kind words.", "Forbidden words."),
]


def context(text: str, gid: str = "", config: Table | None = None) -> Context:
    """Construct a source with independently known protected facts."""
    settings = config or load_config()
    section(settings, "voice")["banned"] = ["forbidden"]
    source = "The cat may sit by Rome and see 42 birds."
    facts = Facts(
        quotes=["The cat sat on the green mat."],
        numbers=["42"],
        proper_nouns=["Rome"],
        hedges={"may": 1},
        rare_words=["parsimony"],
        headings=[],
        words=len(words(source)),
    )
    prefix = "" if gid.startswith("S-") and gid != "S-headings" else DIRECTIVES
    return Context(
        parsed=parse(prefix + text),
        source=source,
        facts=facts,
        lang="en",
        config=settings,
    )


@pytest.mark.parametrize(("gid", "passing", "failing"), CASES)
def test_gate_examples(gid: str, passing: str, failing: str) -> None:
    """Each content gate accepts a conforming unit and rejects a violation."""
    good = context(passing, gid)
    bad = context(failing, gid)
    parameters = section(section(good.config, "gates"), gid)
    good_outcome = REGISTRY[gid](good, parameters)
    bad_outcome = REGISTRY[gid](bad, parameters)
    assert good_outcome is not None, gid
    assert good_outcome[0], (gid, good_outcome)
    assert bad_outcome is not None, gid
    assert not bad_outcome[0], (gid, bad_outcome)


@pytest.mark.parametrize(
    ("gid", "name"),
    [
        ("S-idea", "idea"),
        ("S-question", "question"),
        ("S-why", "why"),
        ("S-recap", "recap"),
        ("S-quiz", "quiz"),
        ("S-answers", "answers"),
    ],
)
def test_directive_gates(gid: str, name: str) -> None:
    """Require all scaffolding directives and their exact item constraints."""
    good = context(DIRECTIVES, gid)
    parameters = section(section(good.config, "gates"), gid)
    outcome = REGISTRY[gid](good, parameters)
    assert outcome is not None
    assert outcome[0]
    bad = context(
        "@" + name + ":\n\n" if name in ("idea", "question", "why") else "", gid
    )
    outcome = REGISTRY[gid](bad, parameters)
    assert outcome is not None
    assert not outcome[0]


def test_format_severity_disabled_and_unknown_language() -> None:
    """Retain the mandatory parser gate and skip inapplicable language checks."""
    ctx = context("Cat.")
    settings = section(ctx.config, "gates")
    table(settings["K-format"])["enabled"] = False
    table(settings["F-numbers"])["severity"] = "warn"
    results = {result["id"]: result["status"] for result in evaluate(ctx)}
    assert results["K-format"] == "pass"
    assert results["F-numbers"] == "warn"
    unknown = Context(
        parsed=ctx.parsed,
        source=ctx.source,
        facts=ctx.facts,
        lang="zz",
        config=ctx.config,
    )
    results = {result["id"]: result["status"] for result in evaluate(unknown)}
    for gid in (
        "F-hedges",
        "F-coverage",
        "L-rare-kept",
        "L-gloss",
        "R-grade",
        "R-nominal",
    ):
        assert results[gid] == "skip"
    table(settings["V-banned"])["enabled"] = False
    assert (
        next(gate for gate in evaluate(ctx) if gate["id"] == "V-banned")["status"]
        == "skip"
    )


def test_book_gates() -> None:
    """Normalize repeated asides and warn about differing term definitions."""
    config = load_config()
    first = parse("Parsimony{= saving} {~ Oh, wow! ~}")
    second = parse("Parsimony{= stinginess} {~ oh wow ~}")
    results = book_gates([("001", first), ("002", second)], config)
    assert [result["status"] for result in results] == ["fail", "warn"]
    passing = book_gates(
        [("001", first), ("002", parse("Parsimony{= saving} {~ different ~}"))], config
    )
    assert all(result["status"] == "pass" for result in passing)


def test_quotes_excluded_and_gloss_first_occurrence() -> None:
    """Do not penalize long quotes or accept a later gloss as the first one."""
    ctx = context("> " + "Word " * 100)
    for gid in ("R-sentence-avg", "R-sentence-max", "R-paragraph"):
        outcome = REGISTRY[gid](ctx, section(section(ctx.config, "gates"), gid))
        assert outcome is not None
        assert outcome[0]
    assert (
        first_glossed(
            parse("**Parsimony** is wise. Parsimony{= saving} helps."), "parsimony"
        )
        is False
    )
    assert first_glossed(parse("Parsimony{= saving} helps."), "parsimony")


def test_spanish_readability() -> None:
    """Use the Spanish ease threshold in its increasing direction."""
    ctx = context("La casa es buena.")
    spanish = Context(
        parsed=ctx.parsed,
        source=ctx.source,
        facts=ctx.facts,
        lang="es",
        config=ctx.config,
    )
    settings = section(section(ctx.config, "gates"), "R-grade")
    good = REGISTRY["R-grade"](spanish, settings)
    assert good is not None
    assert good[0]
    difficult = Context(
        parsed=parse("Internacionalización extraordinariamente incomprensible."),
        source=ctx.source,
        facts=ctx.facts,
        lang="es",
        config=ctx.config,
    )
    bad = REGISTRY["R-grade"](difficult, settings)
    assert bad is not None
    assert not bad[0]


def test_protected_quote_with_gloss_and_emphasis() -> None:
    """Reading aids do not change the verbatim text compared by F-quotes."""
    ctx = context('"The **cat** sat on the green mat{= a small carpet}."')
    outcome = REGISTRY["F-quotes"](
        ctx, section(section(ctx.config, "gates"), "F-quotes")
    )
    assert outcome == (True, "Protected quotations retained verbatim", [])
    assert "mat (a small carpet)" in render_blocks(ctx.parsed.blocks)


@pytest.mark.parametrize("gid", ["R-sentence-avg", "R-sentence-max"])
def test_sentence_gates_exclude_inline_protected_quotes(gid: str) -> None:
    """Count only surrounding prose for every occurrence of a protected quote."""
    quote = " ".join(["word"] * 40)
    ctx = context(f'He says "{quote}" and "{quote}". We listen.')
    ctx = replace(ctx, facts=ctx.facts | {"quotes": [quote]})
    outcome = REGISTRY[gid](ctx, section(section(ctx.config, "gates"), gid))
    assert outcome is not None
    assert outcome[0], outcome
    assert ctx.sentence_lengths == [3, 2]


@pytest.mark.parametrize("gid", ["L-rare-kept", "L-gloss"])
@pytest.mark.parametrize("stem_length", [3, 5, 6, 7])
def test_rare_vocabulary_stems(gid: str, stem_length: int) -> None:
    """An earlier glossed stem covers inflections, but a later gloss does not."""
    ctx = context("Feign{= pretend} weakness.")
    del section(section(ctx.config, "lang"), "en")["stem_length"]
    section(section(ctx.config, "gates"), "F-coverage")["stem_length"] = stem_length
    ctx = replace(ctx, facts=ctx.facts | {"rare_words": ["feigning"]})
    settings = section(section(ctx.config, "gates"), gid)
    outcome = REGISTRY[gid](ctx, settings)
    assert outcome is not None
    assert outcome[0], outcome
    if gid == "L-gloss":
        later_inflection = replace(
            ctx, parsed=parse("Feign{= pretend}. He is feigning weakness.")
        )
        outcome = REGISTRY[gid](later_inflection, settings)
        assert outcome is not None
        assert outcome[0], outcome
        late = replace(ctx, parsed=parse("He is feigning weakness. Feign{= pretend}."))
        outcome = REGISTRY[gid](late, settings)
        assert outcome is not None
        assert not outcome[0], outcome


@pytest.mark.parametrize(
    "gid", ["R-sentence-avg", "R-sentence-max", "R-paragraph", "R-grade", "R-nominal"]
)
def test_readability_ignores_glosses(gid: str) -> None:
    """Long, complex reading aids cannot worsen body readability scores."""
    ctx = context("The cat sits.")
    gloss = "Characterization internationalization management. " * 35
    aided = replace(ctx, parsed=parse(f"The cat{{= {gloss}}} sits."))
    settings = section(section(ctx.config, "gates"), gid)
    assert REGISTRY[gid](aided, settings) == REGISTRY[gid](ctx, settings)
    assert metrics(aided)["grade"] == metrics(ctx)["grade"]


def test_common_stem_before_first_rare_occurrence() -> None:
    """Common unglossed forms do not move a rare word's first-use deadline."""
    ctx = context("Keep discipline. He is a disciplinarian{= strict rule enforcer}.")
    ctx = replace(ctx, facts=ctx.facts | {"rare_words": ["disciplinarian"]})
    outcome = REGISTRY["L-gloss"](ctx, section(section(ctx.config, "gates"), "L-gloss"))
    assert outcome == (True, "First-occurrence gloss coverage: 100.0%", [])


def test_aside_possessive_source_name() -> None:
    """A possessive form of an existing source name is not an invented fact."""
    ctx = context("Text. {~ His plans hang on Bonaparte's ~}")
    ctx = replace(ctx, source="We know Bonaparte.")
    outcome = REGISTRY["F-aside-facts"](
        ctx, section(section(ctx.config, "gates"), "F-aside-facts")
    )
    assert outcome == (True, "Asides introduce no numbers or names", [])


def test_nominal_ratio_inclusive_boundary() -> None:
    """An unchanged nominalization ratio passes the inclusive threshold."""
    ctx = context("The management works.")
    ctx = replace(ctx, source="The management works.")
    outcome = REGISTRY["R-nominal"](
        ctx, section(section(ctx.config, "gates"), "R-nominal")
    )
    assert outcome == (True, "Nominalization ratio: 0.333, source 0.333", [])


@pytest.mark.parametrize("gid", ["F-coverage", "S-grounded", "L-rare-kept", "L-gloss"])
@pytest.mark.parametrize(
    ("source", "adaptation"),
    [
        ("heredó", "heredaron"),
        ("alabado", "alabados"),
        ("áureo", "aureo"),
        ("a\u0301ureo", "aureo"),
        ("aureo", "a\u0301ureo"),
    ],
)
def test_spanish_normalized_stems(gid: str, source: str, adaptation: str) -> None:
    """All vocabulary gates share accent normalization and Spanish prefixes."""
    text = f"{adaptation}{{= significado}}."
    if gid == "S-grounded":
        text = (
            f"@idea: {adaptation}.\n\n@recap:\n- {adaptation}."
            f"\n\n@answers:\n1. {adaptation}."
        )
    if gid == "L-gloss":
        text += f" {source}."
    ctx = replace(context(text, gid), source=source, lang="es")
    ctx = replace(ctx, facts=ctx.facts | {"rare_words": [source]})
    section(section(ctx.config, "gates"), "F-coverage")["stop_zipf"] = 10.0
    outcome = REGISTRY[gid](ctx, section(section(ctx.config, "gates"), gid))
    assert outcome is not None
    assert outcome[0], outcome


@pytest.mark.parametrize(
    ("lang", "length", "expected"), [("es", 6, True), ("en", 4, False), ("es", 4, True)]
)
def test_language_stem_length_overrides_gate(
    lang: str, length: int, *, expected: bool
) -> None:
    """Language defaults take precedence over the generic gate parameter."""
    ctx = replace(context("heredaron."), source="heredó.", lang=lang)
    settings = section(section(ctx.config, "gates"), "F-coverage")
    settings["stop_zipf"] = 10.0
    settings["stem_length"] = length
    outcome = REGISTRY["F-coverage"](ctx, settings)
    assert outcome is not None
    assert outcome[0] == expected


def test_first_gloss_ignores_heading_occurrences() -> None:
    """A heading names vocabulary without consuming its first prose use."""
    ctx = context("## Parsimony\n\nParsimony{= saving} is wise.")
    settings = section(section(ctx.config, "gates"), "L-gloss")
    assert REGISTRY["L-gloss"](ctx, settings) == (
        True,
        "First-occurrence gloss coverage: 100.0%",
        [],
    )
    late = replace(
        ctx,
        parsed=parse("## Parsimony\n\nParsimony is wise. Parsimony{= saving} helps."),
    )
    assert REGISTRY["L-gloss"](late, settings) == (
        False,
        "First-occurrence gloss coverage: 0.0%",
        ["parsimony"],
    )


@pytest.mark.parametrize(
    ("text", "status", "details"),
    [
        ("The whole plan works. {~ The WHOLE game. ~}", "pass", []),
        ("The plan works. {~ The whole game. ~}", "warn", ["The whole game.: whole"]),
        ("The WHOLE plan works.\n\n{~ The whole game. ~}", "pass", []),
        (
            "The whole plan works.\n\nCats chase mice.\n\n{~ Literally. ~}",
            "warn",
            ["Literally.: literally"],
        ),
        ("Everything works. {~ Every time. ~}", "warn", ["Every time.: every"]),
        ("Nothing works. {~ Nothingness. ~}", "pass", []),
        ("{~ Always. ~}", "warn", ["Always.: always"]),
        ("{~ Always. ~} It always works.", "pass", []),
        (
            "The whole plan works.\n\nCats chase mice. {~ The whole game. ~}",
            "warn",
            ["The whole game.: whole"],
        ),
        (
            "The whole plan works.\n\n@why: Listen. {~ The whole game. ~}",
            "pass",
            [],
        ),
        (
            "@why: Listen. {~ The whole game. ~}\n\nThe whole plan works.",
            "warn",
            ["The whole game.: whole"],
        ),
    ],
)
def test_aside_absolutes(text: str, status: str, details: list[str]) -> None:
    """Match whole words without borrowing support from an earlier paragraph."""
    gate = next(
        gate
        for gate in evaluate(context(text, "S-grounded"))
        if gate["id"] == "V-aside-absolutes"
    )
    assert (gate["status"], gate["details"]) == (status, details)


def test_aside_absolutes_spanish_and_missing_list() -> None:
    """Use Spanish boundaries and skip a language without an absolute list."""
    ctx = replace(context("El plan funciona. {~ SÓLO eso. ~}"), lang="es")
    settings = section(section(ctx.config, "gates"), "V-aside-absolutes")
    assert REGISTRY["V-aside-absolutes"](ctx, settings) == (
        False,
        "Asides introduce no unsupported absolutes",
        ["SÓLO eso.: sólo"],
    )
    assert REGISTRY["V-aside-absolutes"](
        replace(ctx, parsed=parse("Sólo el plan funciona. {~ SÓLO eso. ~}")), settings
    ) == (True, "Asides introduce no unsupported absolutes", [])
    del section(section(ctx.config, "lang"), "es")["aside_absolutes"]
    assert REGISTRY["V-aside-absolutes"](ctx, settings) is None


@pytest.mark.parametrize("name", ["recap", "answers", "idea"])
def test_grounded_items(name: str) -> None:
    """Check each directive item against source vocabulary, never the body."""
    source = "Zebras lanterns orchards glaciers."
    good = "Zebras lanterns orchards glaciers robots."
    bad = "Zebras lanterns robots submarines."
    directive = f"@{name}: " if name == "idea" else f"@{name}:\n- "
    ctx = replace(context(directive + good, "S-grounded"), source=source)
    settings = section(section(ctx.config, "gates"), "S-grounded")
    assert REGISTRY["S-grounded"](ctx, settings) == (
        True,
        "Directive content grounded in source",
        [],
    )
    ctx = replace(ctx, parsed=parse(f"Robots submarines.\n\n{directive}{bad}"))
    gate = next(gate for gate in evaluate(ctx) if gate["id"] == "S-grounded")
    assert gate["status"] == "fail"
    assert gate["details"] == [
        f"@{name} item 1: 50.0% grounded; missing: robots, submarines"
    ]


def test_grounded_idea_threshold_and_all_failures() -> None:
    """Allow the separate idea threshold while reporting every failing item."""
    ctx = replace(
        context(
            """@idea: Zebras lanterns orchards robots.

@recap:
- Zebras lanterns orchards robots.
- Submarines.

@answers:
1. Robots.
2. Zebras lanterns orchards glaciers robots.""",
            "S-grounded",
        ),
        source="Zebras lanterns orchards glaciers.",
    )
    settings = section(section(ctx.config, "gates"), "S-grounded")
    assert REGISTRY["S-grounded"](ctx, settings) == (
        False,
        "Directive content grounded in source",
        [
            "@recap item 1: 75.0% grounded; missing: robots",
            "@recap item 2: 0.0% grounded; missing: submarines",
            "@answers item 1: 0.0% grounded; missing: robots",
        ],
    )


def test_grounded_coverage_parameters_and_empty_stems() -> None:
    """Use F-coverage's configured stemming and filtering in both directions."""
    ctx = replace(
        context("@idea: Planned horse.\n\n@recap:\n- And the 42.", "S-grounded"),
        source="Planning horses.",
    )
    coverage = section(section(ctx.config, "gates"), "F-coverage")
    del section(section(ctx.config, "lang"), "en")["stem_length"]
    coverage["stem_length"] = 4
    coverage["stop_zipf"] = 10.0
    settings = section(section(ctx.config, "gates"), "S-grounded")
    assert REGISTRY["S-grounded"](ctx, settings) == (
        False,
        "Directive content grounded in source",
        ["@recap item 1: 0.0% grounded; missing: and, the"],
    )
    coverage["stop_zipf"] = 5.5
    assert REGISTRY["S-grounded"](ctx, settings) == (
        True,
        "Directive content grounded in source",
        [],
    )
    coverage["stem_length"] = 6
    outcome = REGISTRY["S-grounded"](ctx, settings)
    assert outcome is not None
    assert not outcome[0]
    assert REGISTRY["S-grounded"](replace(ctx, lang="zz"), settings) is None


def test_hedges_each_cannot_trade_or_hide_in_asides() -> None:
    """Warn on individual hedge loss even when total hedge retention passes."""
    ctx = context("It may work. It may work. {~ Perhaps. ~}")
    ctx = replace(ctx, facts=ctx.facts | {"hedges": {"may": 1, "perhaps": 1}})
    gates = {gate["id"]: gate for gate in evaluate(ctx)}
    assert gates["F-hedges"]["status"] == "pass"
    assert gates["F-hedges-each"]["status"] == "warn"
    assert gates["F-hedges-each"]["details"] == ["perhaps: 1 -> 0"]
    good = replace(ctx, parsed=parse("It MAY work. Perhaps it works."))
    settings = section(section(ctx.config, "gates"), "F-hedges-each")
    assert REGISTRY["F-hedges-each"](good, settings) == (
        True,
        "Each protected hedge retained",
        [],
    )
    missing = replace(ctx, parsed=parse("It works."))
    assert REGISTRY["F-hedges-each"](missing, settings) == (
        False,
        "Each protected hedge retained",
        ["may: 1 -> 0", "perhaps: 1 -> 0"],
    )
