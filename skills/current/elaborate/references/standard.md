# Elaboration standard

The standard every adapted unit meets. `check` enforces the rules marked with a gate id. The audit enforces the rules marked `audit`. Thresholds live in the merged configuration (`lib/elaborate/defaults.toml` plus the reader's override). This page explains intent, not values.

## Contents

- [Core invariant](#core-invariant)
- [Fidelity](#fidelity)
- [Author vocabulary](#author-vocabulary)
- [Readability](#readability)
- [Structure](#structure)
- [Voice](#voice)
- [Format](#format)
- [Process](#process)

## Core invariant

Elaborate, never simplify. A skilled reader of the original and a reader of the adapted edition reach the same conclusions and know the same facts, nuances, and author vocabulary. Ease comes from shorter sentences, structure, glosses, and attention aids. It never comes from removing content.

- The output language is the source language.
- The whole book is adapted. No unit is summarized or condensed.

## Fidelity

| Rule | Enforced by |
|---|---|
| Every atomic claim of the source survives with the same meaning: facts, causal links, judgments, conditions, and sequence | audit |
| Hedges and modality survive (might, may, perhaps, it seems). Certainty never increases or decreases | F-hedges, audit |
| Intensity survives ("monstrously", "infinitely"). No softening or exaggeration | audit |
| Every number, year, and date survives, as often as the source uses it | F-numbers |
| Every proper noun survives, as often as the source uses it | F-names |
| Every source paragraph keeps most of its content words, which catches a dropped paragraph | F-paragraphs |
| Every image survives in the same order | F-images |
| Direct quotations stay verbatim, with attribution | F-quotes |
| The adapted body is not materially shorter than the source | F-length |
| Content-word coverage stays high, which catches silent omissions | F-coverage |
| The author's tone survives (sober, ironic, cold). The voice layer reacts to it without replacing it | audit |
| Sections keep the source order. Epigraphs and sidebars stay near their source position | audit |

## Author vocabulary

| Rule | Enforced by |
|---|---|
| Rare author words stay in the text | L-rare-kept |
| Each rare word carries a gloss at its first occurrence: `parsimony{= extreme stinginess}` | L-gloss |
| A gloss is accurate for the word's sense in context and period | audit |
| A gloss keeps the word's grammar: tense, mood, person, and number ("ahondaren", future subjunctive, glosses as "profundicen", not "profundizaran") | audit |
| A gloss explains a figure of speech without making it literal | audit |
| A term keeps the same gloss across the book | B-gloss-consistent |
| The build collects every gloss into a glossary | build |

Keeping the vocabulary is the difference between elaboration and simplification: the reader ends with the author's lexicon, not a reduced one.

## Readability

| Rule | Enforced by |
|---|---|
| Short sentences on average. No very long sentence outside quotations | R-sentence-avg, R-sentence-max |
| Short paragraphs, measured in sentences and words | R-paragraph |
| Reading grade at or below the target (Flesch-Kincaid for English, Fernández Huerta for Spanish) | R-grade |
| No more nominalizations than the source. Turn hidden actions back into verbs | R-nominal |
| Parallel enumerations of three or more items become lists | audit |
| Active voice unless the source's passive carries meaning (unknown or hidden agent) | audit |

## Structure

| Rule | Enforced by |
|---|---|
| `@idea`: the unit's central claim in one sentence | S-idea, audit |
| `@question`: a question aimed at the unit's central claim, answered by the text | S-question, audit |
| Headings at least every few hundred words. Headings name what comes, not "Part 2" | S-headings, audit |
| Headings assert nothing the section does not. A heading never generalizes, drops a condition, or narrows a claim | audit |
| `@idea` and `@question` keep the source's modality and exceptions ("I hold it good that" never becomes "must") | S-grounded (`@idea`), audit |
| Where the source contrasts two views, show them as two labeled paragraphs | audit |
| `@why`: one prompt that connects the idea to the reader's life | S-why |
| `@recap`: three points, each traceable to the source | S-recap, audit |
| `@quiz` and `@answers`: questions answerable from the unit, answers matching the source | S-quiz, S-answers, audit |
| Progress and reading time per chapter | build |

## Voice

The voice layer adds short asides that react to what the text just said. They keep attention on the page.

| Rule | Enforced by |
|---|---|
| Asides appear at a steady cadence and never far apart | V-aside-cadence |
| Asides are short | V-aside-length |
| Asides react. They never assert a fact, number, name, or judgment absent from the source | F-aside-facts, audit |
| An aside is either a reaction with no claim or a restatement with the same scope as the source. Never an evaluation, generalization, invented motive, or "literally" for a figure of speech | audit |
| No aside repeats within the book. Vary the wording | B-aside-unique |
| At most one labeled modern analogy per unit, drawn from the reader's domains | V-analogy |
| Banned terms from the reader profile never appear | V-banned |
| Slang, code-switching, and tone follow the reader profile in the configuration | audit |
| Quotations, the image, and the authority passages carry no voice layer inside them | audit |

## Format

| Rule | Enforced by |
|---|---|
| The adapted file follows [the adapted format](adapted-format.md) | K-format |
| No `#` title heading. The build writes the title | K-no-h1 |
| No emoji and no tables. Both render poorly on e-ink | K-no-emoji, K-no-tables |
| Asides render in italics with their own style, so the adapter's voice never reads as the author's | build |
| The EPUB is valid EPUB 3 | build `--epubcheck` |

## Process

1. Write the unit from the `prompt --kind rewrite` brief.
2. Run `check` on the unit and fix every failing gate.
3. Run two audits from independent agents with `prompt --kind audit`. Each agent sees only the brief.
4. Apply every finding that changes meaning, then run `check` again.
5. After two fix rounds with open findings, stop and report the unit for human review instead of looping.
