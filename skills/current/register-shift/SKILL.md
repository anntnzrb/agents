---
name: register-shift
description: "Use when rewriting text in any language to a higher or lower complexity, density, or academic register level."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb
---

# Register shift

Rewrite a text to a target complexity level in its own language while keeping its meaning identical. The output says the same thing in a denser or a plainer register.

## When to use

- The user asks to make a text more academic, dense, formal, or complex, or simpler, plainer, or easier to read.
- The user names a level, a direction (`max`, `min`), or a target audience.
- Not for removing AI writing patterns (`unslop`), translating, summarizing, or adding content. Length MAY change. Content MUST NOT.

## Levels

Target an absolute level, never a relative one. Map the request:

| Level | Name | Target reader | Anchor |
| --- | --- | --- | --- |
| 1 | Easy-to-read | Low literacy, early learner | Lectura Fácil, Leichte Sprache, CEFR A1-A2 |
| 2 | Plain | General public | ISO 24495-1 plain language, CEFR B1 |
| 3 | Standard | Educated adult | Quality press, CEFR B2 |
| 4 | Academic | Specialist reader | Peer-reviewed article, CEFR C1 |
| 5 | Maximal | Expert in the field | Densest grammatical academic prose, CEFR C2 |

- `max` means level 5. `min` means level 1.
- Without a level or direction, ask which direction. Without a level but with a direction, use 5 or 1.

## Invariants

The rewrite MUST preserve every item below. These rules override every lever.

- Propositions: every claim in the source, and no claim absent from it.
- Negation, conditions, exceptions, and scope words such as "only", "all", "some".
- Quantities, dates, units, names, quotations, and technical terms the reader needs.
- Certainty: do not add or remove hedges. "X causes Y" stays certain, and "may" stays "may".
- Agents: keep a named actor when the source names one. Agentless constructions apply only when the source omits the actor.
- Causal and temporal order. Do not invent causal links between adjacent facts.
- Language and script: write in the source language and variety.
- References: never invent citations, sources, authors, or data, even at level 5.
- Formatting: keep lists, headings, code, and URLs. Rewrite only the prose.

## Workflow

1. Detect the source language and the target level.
2. List the source propositions for your own checking: claims, numbers, names, conditions, negations, certainty markers. Do not print the list unless asked.
3. Rewrite with the levers for the direction, strongest first, from `references/levers.md`. Stop when the rewrite meets the level's anchor. Never stack levers past grammaticality.
4. Score the source and the rewrite:

   ```text
   uv run --script <skill-dir>/scripts/cli.py <source-file> <rewrite-file>
   ```

   Write both texts to files under `<temp-dir>` first. For `max`, `lix` and `words_per_sentence` SHOULD rise. For `min`, they SHOULD fall. If they move the wrong way, apply the next lever and score again. When `unsegmented_script` is true, skip the score and say the metric does not apply to that script.
5. Check equivalence in both directions against the proposition list:
   - Forward: every claim in the rewrite is supported by the source. Nothing added.
   - Backward: every source proposition appears in the rewrite. Nothing dropped.
6. Fix any failure and repeat steps 4 and 5. After two failed repairs, deliver the closest valid rewrite and name the unresolved item.

## Output

- Print the rewritten text first, ready to paste.
- Then one line: level, LIX before and after, and the equivalence result. Omit this line when the user asks for text only.
- Do not explain the levers unless asked.

## Public entrypoint

```text
uv run --script <skill-dir>/scripts/cli.py ORIGINAL [REWRITE]
```

- Each argument is a file path, or `-` for stdin.
- One argument prints metrics for that text. Two print `original`, `rewrite`, and `delta` (rewrite minus original).
- Metrics: `words`, `sentences`, `long_words` (more than 6 characters), `words_per_sentence`, `long_word_pct`, `lix`, `rix`, `unsegmented_script`.
- LIX and RIX measure surface length only. Use them as a direction check, not a quality score. Step 5 checks equivalence.
- Exit `2`: usage error, unreadable file, or a text with no words.

## Follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Ranked levers for raising and lowering complexity, with per-language mechanisms | `references/levers.md` | Before step 3 of every rewrite |

## Validation

```text
uv run --script skills/current/skill-creator/scripts/cli.py gates skills/current/register-shift --tests
uv run --script skills/current/skill-creator/scripts/cli.py quick-validate skills/current/register-shift
```
