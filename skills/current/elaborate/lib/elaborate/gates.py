# Copyright (c) 2026
"""Extensible registry of unit and book validation gates."""

import importlib
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from typing import cast

from .adapted import Parsed, span_text
from .config import language, section
from .data import Facts, GateResult, Table, integer, number, strings, table
from .freq import supported, zipf
from .images import MARKER
from .text import (
    NUMBERS,
    hedge_counts,
    name_token,
    nominal_ratio,
    normalize,
    occurrences,
    plain,
    readability,
    sentences,
    words,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Context:
    """Validated input for pure gate functions."""

    parsed: Parsed
    source: str
    facts: Facts
    lang: str
    config: Table

    @property
    def body_words(self) -> int:
        """Body words with gloss definitions, excluding asides."""
        return len(words(self.parsed.body_text))

    @property
    def prose(self) -> str:
        """Body text with quotations excluded for sentence gates."""
        blocks: list[str] = []
        quotes = sorted(
            (normalize(quote) for quote in self.facts["quotes"]),
            key=len,
            reverse=True,
        )
        for block in self.parsed.blocks:
            if block.kind == "quote":
                continue
            text = normalize(block.text(glosses=False))
            for quote in quotes:
                if quote:
                    text = text.replace(quote, " ")
            blocks.append(text)
        return "\n\n".join(blocks)

    @property
    def sentence_lengths(self) -> list[int]:
        """Per-sentence word counts with quotes excluded."""
        return [
            count
            for sentence in sentences(self.prose)
            if (count := len(words(sentence)))
        ]

    @property
    def stem_length(self) -> int:
        """Prefer the source language's prefix length over the gate fallback."""
        rules = language(self.config, self.lang)
        fallback = section(section(self.config, "gates"), "F-coverage")["stem_length"]
        return integer(rules.get("stem_length", fallback) if rules else fallback)

    @property
    def rare_stem_length(self) -> int:
        """Use the resolved prefix length with a five-character minimum."""
        return max(MIN_RARE_STEM_LENGTH, self.stem_length)


type Outcome = tuple[bool, str, list[str]] | None
type Gate = Callable[[Context, Table], Outcome]
REGISTRY: dict[str, Gate] = {}
DESCRIPTIONS: dict[str, str] = {}
TABLE_PIPES = 2
CONTENT_MIN_LENGTH = 3
MIN_RARE_STEM_LENGTH = 5
EMOJI_PRESENTATION_START = 0x1F000


def register(gid: str) -> Callable[[Gate], Gate]:
    """Register one independently extensible gate."""

    def decorator(function: Gate) -> Gate:
        REGISTRY[gid] = function
        DESCRIPTIONS[gid] = " ".join((function.__doc__ or "").split())
        return function

    return decorator


def result(gid: str, outcome: Outcome, settings: Table) -> GateResult:
    """Map boolean outcomes to configured gate severity."""
    if outcome is None:
        return GateResult(
            id=gid,
            category=gid.split("-", maxsplit=1)[0],
            status="skip",
            message="Not applicable",
            details=[],
        )
    passed, message, details = outcome
    return GateResult(
        id=gid,
        category=gid.split("-", maxsplit=1)[0],
        status="pass"
        if passed
        else "warn"
        if settings["severity"] == "warn"
        else "fail",
        message=message,
        details=details,
    )


def evaluate(context: Context) -> list[GateResult]:
    """Run enabled unit gates in registry order."""
    settings = section(context.config, "gates")
    return [
        result(
            gid,
            function(context, table(settings[gid]))
            if table(settings[gid])["enabled"] or gid == "K-format"
            else None,
            table(settings[gid]),
        )
        for gid, function in REGISTRY.items()
    ]


@register("K-format")
def format_gate(ctx: Context, settings: Table) -> Outcome:
    """Record successful parsing."""
    del ctx, settings
    return True, "Adapted format parses", []


@register("K-no-h1")
def no_h1(ctx: Context, settings: Table) -> Outcome:
    """Reject model-supplied top-level titles."""
    del settings
    hits = re.findall(r"(?m)^# .*$", ctx.parsed.raw)
    return not hits, "No H1 headings", hits


def emoji(text: str) -> list[str]:
    """Find Extended_Pictographic characters with emoji presentation."""
    module = importlib.import_module("regex")
    findall = cast("Callable[[str, str], list[str]]", module.findall)
    return list(
        dict.fromkeys(
            value
            for value in findall(r"\p{Extended_Pictographic}(?:\ufe0f)?", text)
            if ord(value[0]) >= EMOJI_PRESENTATION_START or value.endswith("\ufe0f")
        )
    )


@register("K-no-emoji")
def no_emoji(ctx: Context, settings: Table) -> Outcome:
    """Reject emoji anywhere in the original adapted content."""
    del settings
    hits = [value for value in emoji(ctx.parsed.raw) if value[0] not in ctx.source]
    return not hits, "No emoji or pictographs", hits


@register("K-no-tables")
def no_tables(ctx: Context, settings: Table) -> Outcome:
    """Reject Markdown table rows."""
    del settings
    hits = [
        line
        for line in ctx.parsed.raw.splitlines()
        if line.count("|") >= TABLE_PIPES or re.match(r"^\s*\|.*\|?\s*$", line)
    ]
    return not hits, "No Markdown tables", hits


@register("F-quotes")
def quotes(ctx: Context, settings: Table) -> Outcome:
    """Require normalized quotations verbatim in body text."""
    del settings
    body = normalize(ctx.parsed.bare_body)
    missing = [quote for quote in ctx.facts["quotes"] if normalize(quote) not in body]
    return not missing, "Protected quotations retained verbatim", missing


@register("F-numbers")
def numbers_gate(ctx: Context, settings: Table) -> Outcome:
    """Protect numeric tokens without accepting substrings of larger numbers."""
    del settings
    present = Counter(NUMBERS.findall(ctx.parsed.body_text))
    source = Counter(NUMBERS.findall(ctx.source))
    missing = [
        f"{token}: {present[token]}/{max(1, source[token])}"
        for token in ctx.facts["numbers"]
        if present[token] < max(1, source[token])
    ]
    return not missing, "Protected numbers retained", missing


@register("F-names")
def names(ctx: Context, settings: Table) -> Outcome:
    """Require case-sensitive proper nouns."""
    source_body = "\n\n".join(
        paragraph
        for paragraph in ctx.source.split("\n\n")
        if paragraph not in ctx.facts["headings"]
    )
    body = "\n\n".join(
        block.text() for block in ctx.parsed.blocks if block.kind != "heading"
    )
    counts = [
        (
            name,
            max(1, len(occurrences(source_body, name))),
            len(occurrences(body, name)),
        )
        for name in ctx.facts["proper_nouns"]
    ]
    required = sum(source for _, source, _ in counts)
    retained = sum(min(source, present) for _, source, present in counts)
    share = retained / required if required else 1.0
    missing = [
        f"{name}: {present}/{source}"
        for name, source, present in counts
        if present < source
    ]
    return (
        share >= number(settings["min_coverage"]),
        f"Retained name occurrences: {retained}/{required} ({share:.1%})",
        missing,
    )


@register("F-hedges")
def hedges(ctx: Context, settings: Table) -> Outcome:
    """Protect the total amount of uncertainty."""
    rules = language(ctx.config, ctx.lang)
    if rules is None or "hedges" not in rules:
        return None
    present = hedge_counts(ctx.parsed.body_text, strings(rules["hedges"]))
    required = sum(ctx.facts["hedges"].values()) * number(settings["min_ratio"])
    deficits = [
        f"{term}: {present.get(term, 0)}/{count}"
        for term, count in ctx.facts["hedges"].items()
        if present.get(term, 0) < count
    ]
    return (
        sum(present.values()) >= required,
        f"Hedges: {sum(present.values())}, required {required:g}",
        deficits,
    )


@register("F-length")
def length(ctx: Context, settings: Table) -> Outcome:
    """Bound content shrinkage."""
    required = ctx.facts["words"] * number(settings["min_ratio"])
    count = len(words(ctx.parsed.bare_body))
    return (
        count >= required,
        f"Body words: {count}, required {required:g}",
        [],
    )


@register("F-hedges-each")
def hedges_each(ctx: Context, settings: Table) -> Outcome:
    """Protect each hedge count without allowing substitutions."""
    del settings
    present = hedge_counts(ctx.parsed.body_text, list(ctx.facts["hedges"]))
    deficits = [
        f"{term}: {count} -> {present.get(term, 0)}"
        for term, count in ctx.facts["hedges"].items()
        if present.get(term, 0) < count
    ]
    return not deficits, "Each protected hedge retained", deficits


def content_tokens(text: str, lang: str, settings: Table) -> list[str]:
    """Select content words, preserving repeated occurrences."""
    stop = number(settings["stop_zipf"])
    return [
        token
        for word in words(MARKER.sub("", text))
        if (token := word.lower()).isalpha()
        and len(token) >= CONTENT_MIN_LENGTH
        and zipf(token, lang) < stop
    ]


def content_words(text: str, lang: str, settings: Table) -> set[str]:
    """Select F-coverage's distinct lowercase content words."""
    return set(content_tokens(text, lang, settings))


def fold_accents(word: str) -> str:
    """Case-fold and drop combining marks before comparing vocabulary stems."""
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", word.casefold())
        if not unicodedata.combining(char)
    )


def content_stems(text: str, lang: str, settings: Table, stem_length: int) -> set[str]:
    """Apply the resolved prefix length to accent-free content words."""
    return {
        fold_accents(token)[:stem_length]
        for token in content_words(text, lang, settings)
    }


def coverage(ctx: Context, settings: Table) -> float | None:
    """Compare distinct content-word prefix stems."""
    if not supported(ctx.lang):
        return None
    source = content_stems(ctx.source, ctx.lang, settings, ctx.stem_length)
    return (
        len(
            source
            & content_stems(ctx.parsed.bare_body, ctx.lang, settings, ctx.stem_length)
        )
        / len(source)
        if source
        else 1.0
    )


def paragraph_coverages(
    ctx: Context, settings: Table
) -> list[tuple[str, float]] | None:
    """Measure eligible source paragraphs against the rendered body stems."""
    if not supported(ctx.lang):
        return None
    parameters = section(section(ctx.config, "gates"), "F-coverage")
    body = content_stems(ctx.parsed.bare_body, ctx.lang, parameters, ctx.stem_length)
    values: list[tuple[str, float]] = []
    for paragraph in re.split(r"\n\s*\n", ctx.source):
        tokens = content_tokens(paragraph, ctx.lang, parameters)
        if len(tokens) < integer(settings["min_words"]):
            continue
        stems = {fold_accents(token)[: ctx.stem_length] for token in tokens}
        share = len(stems & body) / len(stems) if stems else 1.0
        values.append((" ".join(paragraph.split()[:8]), share))
    return values


@register("F-paragraphs")
def paragraphs_gate(ctx: Context, settings: Table) -> Outcome:
    """Protect the vocabulary of each substantive source paragraph."""
    values = paragraph_coverages(ctx, settings)
    if values is None:
        return None
    failures = [
        f"{label}: {share:.1%}"
        for label, share in values
        if share < number(settings["min"])
    ]
    minimum = min((share for _, share in values), default=1.0)
    return not failures, f"Minimum paragraph coverage: {minimum:.1%}", failures


@register("F-images")
def images_gate(ctx: Context, settings: Table) -> Outcome:
    """Require every source image occurrence in the same relative order."""
    del settings
    source = ctx.facts.get(
        "images", [match.group(1) for match in MARKER.finditer(ctx.source)]
    )
    adapted = [block.image for block in ctx.parsed.blocks if block.kind == "image"]
    position = 0
    missing: list[str] = []
    for name in source:
        try:
            position = adapted.index(name, position) + 1
        except ValueError:
            missing.append(name)
    return not missing, "Source images retained in order", missing


@register("F-coverage")
def coverage_gate(ctx: Context, settings: Table) -> Outcome:
    """Require content vocabulary coverage."""
    value = coverage(ctx, settings)
    return (
        None
        if value is None
        else (
            value >= number(settings["min"]),
            f"Content-word coverage: {value:.1%}",
            [],
        )
    )


@register("F-aside-facts")
def aside_facts(ctx: Context, settings: Table) -> Outcome:
    """Keep new numbers and unsupported names out of asides."""
    del settings
    source = {name_token(token) for token in words(ctx.source)}
    failures: list[str] = []
    for aside in ctx.parsed.aside_texts:
        names_in_aside = [
            token
            for sentence in sentences(aside)
            for token in words(sentence)[1:]
            if token[0].isupper() and name_token(token) not in source
        ]
        if any(char.isdigit() for char in aside) or names_in_aside:
            failures.append(aside)
    return not failures, "Asides introduce no numbers or names", failures


@register("L-rare-kept")
def rare_kept(ctx: Context, settings: Table) -> Outcome:
    """Keep the author's rare vocabulary."""
    if not supported(ctx.lang):
        return None
    rare = ctx.facts["rare_words"]
    tokens = words(ctx.parsed.bare_body)
    missing = [
        term
        for term in rare
        if not any(same_stem(token, term, ctx.rare_stem_length) for token in tokens)
    ]
    share = (len(rare) - len(missing)) / len(rare) if rare else 1.0
    return (
        share >= number(settings["min_coverage"]),
        f"Retained {len(rare) - len(missing)}/{len(rare)} ({share:.1%})",
        missing,
    )


def same_stem(word: str, term: str, stem_length: int) -> bool:
    """Match exact short words or a shared prefix of at least five characters."""
    word, term = fold_accents(word), fold_accents(term)
    length = min(max(MIN_RARE_STEM_LENGTH, stem_length), len(word), len(term))
    return (
        word == term
        if length < MIN_RARE_STEM_LENGTH
        else word[:length] == term[:length]
    )


def first_glossed(parsed: Parsed, term: str, stem_length: int = 6) -> bool:
    """Find a matching gloss at or before the term's first body occurrence."""
    tokens = [
        (token, span.kind == "gloss")
        for block in parsed.blocks
        if block.kind != "heading"
        for span in block.spans
        if span.kind != "aside"
        for token in words(plain(span.text))
    ]
    exact = next(
        (
            index
            for index, (token, _) in enumerate(tokens)
            if fold_accents(token) == fold_accents(term)
        ),
        None,
    )
    first = (
        exact
        if exact is not None
        else next(
            (
                index
                for index, (token, _) in enumerate(tokens)
                if same_stem(token, term, stem_length)
            ),
            -1,
        )
    )
    return any(
        glossed and same_stem(token, term, stem_length)
        for token, glossed in tokens[: first + 1]
    )


@register("L-gloss")
def gloss_gate(ctx: Context, settings: Table) -> Outcome:
    """Require a gloss on the first occurrence of kept rare words."""
    if not supported(ctx.lang):
        return None
    kept = [
        term
        for term in ctx.facts["rare_words"]
        if any(
            same_stem(token, term, ctx.rare_stem_length)
            for token in words(ctx.parsed.bare_body)
        )
    ]
    missing = [
        term
        for term in kept
        if not first_glossed(ctx.parsed, term, ctx.rare_stem_length)
    ]
    share = (len(kept) - len(missing)) / len(kept) if kept else 1.0
    return (
        share >= number(settings["min_coverage"]),
        f"First-occurrence gloss coverage: {share:.1%}",
        missing,
    )


@register("R-sentence-avg")
def sentence_avg(ctx: Context, settings: Table) -> Outcome:
    """Limit mean sentence length outside quotations."""
    lengths = ctx.sentence_lengths
    value = sum(lengths) / max(1, len(lengths))
    return value <= number(settings["max"]), f"Average sentence length: {value:.2f}", []


@register("R-sentence-max")
def sentence_max(ctx: Context, settings: Table) -> Outcome:
    """Limit each sentence outside quotations."""
    failures = [
        sentence
        for sentence in sentences(ctx.prose)
        if len(words(sentence)) > number(settings["max"])
    ]
    return not failures, "Sentence length maximum", failures


@register("R-paragraph")
def paragraph(ctx: Context, settings: Table) -> Outcome:
    """Limit prose paragraphs, excluding quotations and lists."""
    failures = [
        f"line {block.line}: {block.text()}"
        for block in ctx.parsed.blocks
        if block.kind == "paragraph"
        and (
            len(words(block.text(glosses=False))) > number(settings["max_words"])
            or len(sentences(block.text(glosses=False)))
            > number(settings["max_sentences"])
        )
    ]
    return not failures, "Paragraph size limits", failures


@register("R-grade")
def grade(ctx: Context, settings: Table) -> Outcome:
    """Apply the configured English or Spanish readability formula."""
    rules = language(ctx.config, ctx.lang)
    if rules is None or ctx.lang not in ("en", "es"):
        return None
    value = readability(ctx.parsed.bare_body, ctx.lang)
    passed = (
        value >= number(settings["min_ease"])
        if ctx.lang == "es"
        else value <= number(settings["max_grade"])
    )
    return passed, f"Readability ({rules['readability']}): {value:.2f}", []


@register("R-nominal")
def nominal(ctx: Context, settings: Table) -> Outcome:
    """Prevent increasing the nominalization ratio."""
    rules = language(ctx.config, ctx.lang)
    if rules is None or "nominal_suffixes" not in rules:
        return None
    suffixes = strings(rules["nominal_suffixes"])
    source = nominal_ratio(ctx.source, suffixes)
    body = nominal_ratio(ctx.parsed.bare_body, suffixes)
    return (
        body <= source * number(settings["max_ratio"]),
        f"Nominalization ratio: {body:.3f}, source {source:.3f}",
        [],
    )


def _directive(ctx: Context, name: str) -> Outcome:
    entries = ctx.parsed.directives.get(name, [])
    return (
        bool(entries and span_text(entries[0]).strip()),
        f"@{name} present and non-empty",
        [],
    )


@register("S-idea")
def idea(ctx: Context, settings: Table) -> Outcome:
    """Require the one-line idea."""
    del settings
    return _directive(ctx, "idea")


@register("S-question")
def question(ctx: Context, settings: Table) -> Outcome:
    """Require the guiding question."""
    del settings
    return _directive(ctx, "question")


@register("S-why")
def why(ctx: Context, settings: Table) -> Outcome:
    """Require the reflective prompt."""
    del settings
    return _directive(ctx, "why")


@register("S-recap")
def recap(ctx: Context, settings: Table) -> Outcome:
    """Require the exact recap item count."""
    count = len(ctx.parsed.directives.get("recap", []))
    return count == integer(settings["count"]), f"Recap items: {count}", []


@register("S-quiz")
def quiz(ctx: Context, settings: Table) -> Outcome:
    """Require the configured quiz item range."""
    count = len(ctx.parsed.directives.get("quiz", []))
    return (
        integer(settings["min"]) <= count <= integer(settings["max"]),
        f"Quiz items: {count}",
        [],
    )


@register("S-answers")
def answers(ctx: Context, settings: Table) -> Outcome:
    """Require one answer per quiz item."""
    del settings
    quiz_count = len(ctx.parsed.directives.get("quiz", []))
    answer_count = len(ctx.parsed.directives.get("answers", []))
    return (
        "answers" in ctx.parsed.directives and answer_count == quiz_count,
        f"Answers: {answer_count}; quiz: {quiz_count}",
        [],
    )


@register("S-headings")
def headings(ctx: Context, settings: Table) -> Outcome:
    """Bound the longest stretch of body words without a heading."""
    stretches = [0]
    for block in ctx.parsed.blocks:
        if block.kind == "heading":
            stretches.append(0)
        else:
            stretches[-1] += len(words(block.text()))
    longest = max(stretches)
    return (
        longest <= integer(settings["max_words"]),
        f"Longest heading-free stretch: {longest} words",
        [],
    )


@register("S-grounded")
def grounded(ctx: Context, settings: Table) -> Outcome:
    """Require each recap, answer, and idea to reuse source content stems."""
    if not supported(ctx.lang):
        return None
    parameters = section(section(ctx.config, "gates"), "F-coverage")
    source = content_stems(ctx.source, ctx.lang, parameters, ctx.stem_length)
    stem_length = ctx.stem_length
    failures: list[str] = []
    for name in ("recap", "answers", "idea"):
        minimum = number(settings["idea_min" if name == "idea" else "min"])
        for index, spans in enumerate(ctx.parsed.directives.get(name, []), 1):
            tokens = content_words(span_text(spans), ctx.lang, parameters)
            stems = {fold_accents(token)[:stem_length] for token in tokens}
            share = len(stems & source) / len(stems) if stems else 1.0
            if share < minimum:
                missing = sorted(
                    token
                    for token in tokens
                    if fold_accents(token)[:stem_length] not in source
                )
                label = f"@{name} item {index}: {share:.1%} grounded"
                failures.append(f"{label}; missing: {', '.join(missing)}")
    return not failures, "Directive content grounded in source", failures


@register("V-aside-absolutes")
def aside_absolutes(ctx: Context, settings: Table) -> Outcome:
    """Keep new absolute claims out of asides following a body block."""
    del settings
    rules = language(ctx.config, ctx.lang)
    if rules is None or "aside_absolutes" not in rules:
        return None
    terms = strings(rules["aside_absolutes"])
    failures: list[str] = []
    contexts = [(block.line, block.spans, True) for block in ctx.parsed.blocks]
    directive_lines = {
        match.group(1): ctx.parsed.raw[: match.start()].count("\n") + 1
        for match in re.finditer(r"(?m)^@([^:]+):", ctx.parsed.raw)
    }
    contexts.extend(
        (directive_lines[name], spans, False)
        for name, items in ctx.parsed.directives.items()
        for spans in items
    )
    preceding = ""
    for _, spans, is_body in sorted(contexts, key=lambda item: item[0]):
        body = span_text(spans)
        associated = body if is_body and body.strip() else preceding
        failures.extend(
            f"{span.text}: {', '.join(missing)}"
            for span in spans
            if span.kind == "aside"
            and (
                missing := [
                    term
                    for term in terms
                    if occurrences(span.text, term, insensitive=True)
                    and not occurrences(associated, term, insensitive=True)
                ]
            )
        )
        if is_body:
            preceding = body
    return not failures, "Asides introduce no unsupported absolutes", failures


@register("V-aside-length")
def aside_length(ctx: Context, settings: Table) -> Outcome:
    """Keep each aside brief."""
    failures = [
        aside
        for aside in ctx.parsed.aside_texts
        if len(words(aside)) > integer(settings["max_words"])
    ]
    return not failures, "Aside length maximum", failures


@register("V-aside-cadence")
def aside_cadence(ctx: Context, settings: Table) -> Outcome:
    """Check aside count and start, middle, and end gaps."""
    positions = ctx.parsed.aside_positions
    required = math.floor(ctx.body_words / integer(settings["per_words"]))
    longest = max(
        (end - start for start, end in pairwise([0, *positions, ctx.body_words])),
        default=0,
    )
    return (
        len(positions) >= required and longest <= integer(settings["max_gap"]),
        f"Asides: {len(positions)}, required {required}; longest gap: {longest} words",
        [],
    )


@register("V-analogy")
def analogy(ctx: Context, settings: Table) -> Outcome:
    """Limit labeled analogy paragraphs."""
    count = sum(block.analogy for block in ctx.parsed.blocks)
    return count <= integer(settings["max"]), f"Analogy paragraphs: {count}", []


@register("V-banned")
def banned(ctx: Context, settings: Table) -> Outcome:
    """Reject configured terms anywhere in rendered content."""
    del settings
    failures = [
        term
        for term in strings(section(ctx.config, "voice")["banned"])
        if occurrences(ctx.parsed.full_text, term, insensitive=True)
    ]
    return not failures, "Banned vocabulary absent", failures


def metrics(ctx: Context) -> Table:
    """Collect stable measurable report fields."""
    lengths = ctx.sentence_lengths
    return {
        "words": ctx.body_words,
        "sentences": len(lengths),
        "avg_sentence_length": sum(lengths) / max(1, len(lengths)),
        "grade": readability(ctx.parsed.bare_body, "en") if ctx.lang == "en" else None,
        "ease": readability(ctx.parsed.bare_body, "es") if ctx.lang == "es" else None,
        "asides": len(ctx.parsed.aside_texts),
        "glosses": len(ctx.parsed.glosses),
        "coverage": coverage(ctx, section(section(ctx.config, "gates"), "F-coverage")),
        "paragraph_coverage_min": min(
            (
                share
                for _, share in (
                    paragraph_coverages(
                        ctx, section(section(ctx.config, "gates"), "F-paragraphs")
                    )
                    or []
                )
            ),
            default=1.0,
        )
        if supported(ctx.lang)
        else None,
    }


def _aside_key(text: str) -> str:
    return " ".join(
        "".join(
            char
            for char in text.lower()
            if not unicodedata.category(char).startswith("P")
        ).split()
    )


type BookGate = Callable[[list[tuple[str, Parsed]], Table], Outcome]
BOOK_REGISTRY: dict[str, BookGate] = {}


def register_book(gid: str) -> Callable[[BookGate], BookGate]:
    """Register an independently extensible book gate."""

    def decorator(function: BookGate) -> BookGate:
        BOOK_REGISTRY[gid] = function
        DESCRIPTIONS[gid] = " ".join((function.__doc__ or "").split())
        return function

    return decorator


@register_book("B-aside-unique")
def aside_unique(parsed: list[tuple[str, Parsed]], settings: Table) -> Outcome:
    """Reject repeated normalized asides across all supplied units."""
    del settings
    seen: dict[str, str] = {}
    repeated: list[str] = []
    for uid, unit in parsed:
        for aside in unit.aside_texts:
            key = _aside_key(aside)
            if key in seen:
                repeated.append(f"{seen[key]}/{uid}: {aside}")
            seen[key] = uid
    return not repeated, "Asides are unique", repeated


@register_book("B-gloss-consistent")
def gloss_consistent(parsed: list[tuple[str, Parsed]], settings: Table) -> Outcome:
    """Require consistent definitions for each glossed term."""
    del settings
    seen: dict[str, tuple[str, str]] = {}
    inconsistent: list[str] = []
    for uid, unit in parsed:
        for term, gloss in unit.glosses:
            key = term.casefold()
            value = " ".join(gloss.split())
            if key in seen and seen[key][0] != value:
                inconsistent.append(
                    f"{seen[key][1]}/{uid}: {term}: {seen[key][0]} / {value}"
                )
            _ = seen.setdefault(key, (value, uid))
    return not inconsistent, "Glosses are consistent", inconsistent


def book_gates(parsed: list[tuple[str, Parsed]], config: Table) -> list[GateResult]:
    """Run the enabled book-level registry."""
    settings = section(config, "gates")
    return [
        result(
            gid,
            function(parsed, table(settings[gid]))
            if table(settings[gid])["enabled"]
            else None,
            table(settings[gid]),
        )
        for gid, function in BOOK_REGISTRY.items()
    ]
