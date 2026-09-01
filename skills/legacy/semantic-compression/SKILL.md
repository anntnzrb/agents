---
disable-model-invocation: true
name: semantic-compression
description: "Use when prompts or documents must be compressed aggressively while preserving meaning for an LLM."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Semantic Compression

LLMs reconstruct grammar from content words. Remove predictable glue; keep semantic payload. Prefer fragments over sentences.

## Aggressive Stance

- Output: noun/verb stacks, list fragments, label:value phrases.
- Default delete; retain function words when deletion changes meaning.
- Prefer base verbs; drop tense/aspect unless timeline critical.

## Deletion Tiers

**Tier 1: always delete, even in fragments:**

- Articles: a, an, the
- Copulas: is, are, was, were, am, be, been, being
- Expletive subjects: "There is/are...", "It is..."
- Complementizer `that` as clause marker
- Pure intensifiers: very, quite, rather, really, extremely, somewhat
- Filler: "in order to" → to; "due to the fact that" → because; "in terms of" → delete
- Infinitive `to` before verbs, unless it prevents noun/verb confusion
- Conjunctions when list/contrast obvious: and, or, but

**Tier 2: delete unless meaning changes:**

- Auxiliary verbs: have/has/had, do/does/did, will/would; retain when tense/aspect matters
- Modal verbs: can/could/may/might/should; retain when obligation/permission/possibility critical; always retain must/must not
- Pronouns: it/this/that/these/those/he/she/they; drop when referent obvious, replace with noun if ambiguous
- Relative pronouns: which, that, who, whom
- Prepositions: of, for, to, in, on, at, by; retain for material, direction, agency, or disambiguation

**Tier 3: delete only when relation remains clear:**

- Prepositions: with/without, between/among, within, after/before, over/under, through
- Redundant adverbs: "shout loudly" → "shout"

## Always Preserve

- Nouns, main verbs, meaning-bearing adjectives/adverbs
- Numbers and quantifiers: "at least 5", "approximately", "more than"
- Uncertainty markers: "appears", "seems", "reportedly", "what sounded like"
- Negation: not, no, never, without, none
- Temporal markers: dates, frequencies, durations
- Causality and conditionals: because, therefore, despite, although, if, unless
- Requirements/permissions: must, required, prohibited, allowed
- Proper nouns, titles, technical terms
- Relationship-bearing prepositions: from/to (direction), with/without (inclusion), between/among/within (relation), after/before (temporal), by (passive agent)

## Structural Compression

- Passive → active when agent known: "was eaten by dog" → "dog ate"
- Nominalization → verb: "made a decision" → "decided"
- Drop implied subject when context allows: "System should log errors" → "Log errors"
- Redundant pairs → single: "each and every" → "every"
- Clause → modifier: "anomaly that was reported" → "reported anomaly"

## Examples

|Original|Compressed|
|---|---|
|The system was designed to efficiently process incoming data from multiple sources|System design: efficient process incoming data, multiple sources|
|There were at least 20 people who appeared to be waiting|At least 20 people apparent waiting|
|It is important to note that the medication should not be taken without food|Medication: should not take without food|
|The researcher made a decision to investigate the anomaly that was reported|Researcher decided: investigate reported anomaly|
