---
name: remove-ai-slops
description: Clean AI-generated code in a bounded diff while preserving behavior; use for deslop, AI cleanup, or review.
---

# Remove AI Slops

Use for a bounded cleanup of AI-generated code, not a general refactor. Keep behavior,
public APIs, type hints, dependencies, and project conventions intact.

## Scope and safety

1. Use the caller's explicit file list. Otherwise inspect the branch diff against its merge-base
   Exclude deleted, binary, generated, vendored, and lock files.
2. Read `references/cleanup-playbook.md` before making a cleanup plan or judging a diff
3. Lock observable behavior with existing or narrow regression tests before edits. A prose-only
   file has no behavioral seam: do not add wording-pinning tests.
4. Establish a green relevant baseline. If it cannot be established, stop and report it;
   cleanup on unverified ground is reckless garbage.
5. Prefer deletion, reuse, or a platform/standard-library capability before simplifying code
   Make only behavior-obvious changes. When uncertain, keep the code.

## Execution

- Write a per-file plan: deletion-ladder result, applicable categories, order, and risk
- Work safest to riskiest: comments, dead code, defensive code, duplication, complexity,
  abstraction/boundaries, performance, coverage, then module size.
- For a multi-file pass, delegate independent files only through the runtime's currently exposed
  agent tools. Give each worker the exact file, scope, constraints, and required category review;
  batch only within available concurrency. The owner integrates and verifies every change.
- Use project-native tests, lint, type checks, and scanners. Do not invent unavailable tools or
  silently skip a gate; report genuinely inapplicable gates as `N/A` with the reason.
- If a change fails validation, revert only the faulty hunk, fix it if safety is evident, and rerun
  the affected validation. Escalate after three failed attempts on one file.

## Review output

Report scope, baseline/behavior lock, cleanup plan, per-file results and deliberate skips, each
quality gate, safety/behavior/quality review, issues fixed, net impact, and deferred risks.
Never claim a passing gate without its observed output.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Category definitions, keep/refactor rules, deletion ladder, and validation | `references/cleanup-playbook.md` | Before planning, modifying, or reviewing a cleanup |
