---
disable-model-invocation: true
name: unslop
description: "Use when asked to deslop, remove AI writing patterns, clean prose, or perform bounded behavior-preserving code cleanup."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb
---

# Unslop

One skill, two modes. Both remove AI-generated slop; the artifact decides the mode. Writing goes through the prose pattern catalog; code goes through a bounded, behavior-preserving cleanup.

## Choose the mode

- Prose (replies, docs, PR descriptions, commit messages, log text) -> prose mode below
- Code (an explicit file list or a branch diff) -> code mode below

## Prose mode

- NEVER use U+2013 (en dash) or U+2014 (em dash) in prose. Replace them with a period, comma, colon, or semicolon. Use ASCII `-` only for syntax, flags, identifiers, and true compound words, not as dash punctuation.

1. Scan for the patterns in `references/slop-patterns.md`.
2. Rewrite. Preserve meaning, match intended tone.
3. Add soul (below).
4. Self-audit: "What makes this obviously AI generated?" Fix remaining tells.

### Adding soul

- Have opinions. React to facts instead of neutrally listing pros and cons.
- Vary rhythm. Short sentences. Then longer ones that take their time.
- Acknowledge complexity. "Impressive but also kind of unsettling" beats "impressive."
- Use "I" when it fits. First person isn't unprofessional.
- Let some mess in. Perfect structure looks machine-made.
- Be specific. Not "this is concerning" but "there's something unsettling about agents churning away at 3am."

## Code mode

Use for a bounded cleanup of AI-generated code, not a general refactor. Keep behavior, public APIs, type hints, dependencies, and project conventions intact.

### Scope and safety

1. Use the caller's explicit file list. Otherwise inspect the branch diff against its merge-base. Exclude deleted, binary, generated, vendored, and lock files.
2. Read `references/cleanup-playbook.md` before making a cleanup plan or judging a diff.
3. Lock observable behavior with existing or narrow regression tests before edits. A prose-only file has no behavioral seam: do not add wording-pinning tests.
4. Establish a green relevant baseline. If it cannot be established, stop and report it; cleanup on unverified ground is reckless garbage.
5. Prefer deletion, reuse, or a platform/standard-library capability before simplifying code. Make only behavior-obvious changes. When uncertain, keep the code.

### Execution

- Write a per-file plan: deletion-ladder result, applicable categories, order, and risk.
- Work safest to riskiest: comments, dead code, defensive code, duplication, complexity, abstraction/boundaries, performance, coverage, then module size.
- For a multi-file pass, delegate independent files only through the runtime's currently exposed agent tools. Give each worker the exact file, scope, constraints, and required category review; batch only within available concurrency. The owner integrates and verifies every change.
- Use project-native tests, lint, type checks, and scanners. Do not invent unavailable tools or silently skip a gate; report genuinely inapplicable gates as `N/A` with the reason.
- If a change fails validation, revert only the faulty hunk, fix it if safety is evident, and rerun the affected validation. Escalate after three failed attempts on one file.

### Review output

Report scope, baseline/behavior lock, cleanup plan, per-file results and deliberate skips, each quality gate, safety/behavior/quality review, issues fixed, net impact, and deferred risks. Never claim a passing gate without its observed output.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| The 31-pattern slop catalog | `references/slop-patterns.md` | Prose mode, before rewriting |
| Category definitions, keep/refactor rules, deletion ladder, validation | `references/cleanup-playbook.md` | Code mode, before planning, modifying, or reviewing a cleanup |

Merged from remove-ai-slops (GPL-3.0-or-later, anntnzrb) and pstack unslop (MIT, Lauren Tan).
