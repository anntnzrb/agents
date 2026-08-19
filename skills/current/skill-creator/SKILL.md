---
name: skill-creator
description: "Use when creating, auditing, refactoring, validating, benchmarking, packaging, or tuning a skill and its triggers."
license: AGPL-3.0-or-later
metadata:
  author: Anthropic
  local-maintainer: anntnzrb
  upstream: https://github.com/anthropics/skills/tree/main/skills/skill-creator

---

# Skill Creator

Create, audit, refactor, validate, benchmark, optimize, and package skills.

<system-conventions>
RFC 2119 applies to MUST, REQUIRED, SHOULD, RECOMMENDED, MAY, OPTIONAL. `NEVER` and `AVOID` mean `MUST NOT` and `SHOULD NOT` respectively.
</system-conventions>

<critical>
- Loop: identify → draft → test → evaluate → iterate → package.
- `SKILL.md` entrypoint; load references only when routed.
- NEVER use `/skill-test` or any other testing skill.
- Preserve exact schemas, field names, paths, and command syntax.
- Optimize description only after core behavior works.
</critical>

## Capability and Trigger

In scope: create, repair, refactor, validate, design evals, benchmark, optimize frontmatter descriptions, and package `.skill` artifacts. Cleanup, iteration, benchmark design, triggering accuracy, and skill polish also qualify.

Start at the user's current stage. Drafts, evals, and vague ideas each enter the appropriate loop stage. An explicitly requested lighter collaborative pass MAY replace full evals; keep the full loop available.

## Core Loop

1. Identify capability and trigger conditions.
2. Draft or edit `SKILL.md` and bundled resources.
3. Test realistic prompts with the skill enabled.
4. Evaluate with the user, qualitative review, and quantitative checks.
5. Iterate from feedback and benchmark evidence.
6. Package the final skill for installation.

## Public CLI Entrypoint

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

`<skill-dir>`: skill directory. NEVER rely on shell sourcing, executable bits, or shebang dispatch.

Useful commands:

```bash
uv run --script <skill-dir>/scripts/cli.py aggregate-benchmark <workspace>/iteration-N --skill-name <name>
uv run --script <skill-dir>/scripts/cli.py generate-review <workspace>/iteration-N --skill-name <name>
uv run --script <skill-dir>/scripts/cli.py package <path-to-skill-folder>
uv run --script <skill-dir>/scripts/cli.py quick-validate <path-to-skill-folder>
```

Read `references/eval-workflow.md` for aggregate/review usage; `references/packaging.md` for package validation and handoff.

## Progressive Disclosure Rules

Three load levels:

1. Metadata (`name` + `description`): always in context (~100 words).
2. `SKILL.md` body: when triggered (<500 lines ideal; under 250 when practical).
3. Bundled resources: on demand; scripts can execute without loading.

Patterns:

- `SKILL.md`: focus on trigger, routing, and core workflow.
- Move long procedures, schemas, examples, and domain variants to `references/`.
- Every reference: explicit when-to-read guidance at its top and in the routing table.
- Prefer `scripts/` for deterministic or repetitive work.
- Keep inline snippets tiny.
- Add a table of contents to reference files >300 lines.
- Multiple domains/frameworks: organize by variant so the agent reads only the relevant reference.

## Eval Workflow Summary

After drafting, propose 2-3 realistic test prompts before running. Save prompts to `evals/evals.json`; read `references/schemas.md` for the full schema, including the later-added `assertions` field.

Detailed workflow: `references/eval-workflow.md`.

1. Results: `<skill-name>-workspace/`, sibling to the skill directory; organize by `iteration-N/`, one directory per test case.
2. Spawn with-skill and baseline in the same turn for comparable timing/conditions. For existing-skill improvement, snapshot the old version before editing and use it as baseline when appropriate.
3. Draft objectively verifiable assertions while runs proceed; do not force fake objectivity onto subjective work.
4. Immediately capture each task notification's `total_tokens` and `duration_ms` in `timing.json`; this data is not persisted elsewhere.
5. Grade runs, aggregate benchmark data, perform an analyst pass, then launch the review viewer with `generate-review`. NEVER write custom HTML.
6. Read `feedback.json`; improve from transcripts, user feedback, and benchmark data; rerun in a new iteration until the user is satisfied or changes stop producing meaningful improvement.

<critical>
- Sequence: spawn with-skill and baseline in the same turn; draft assertions while runs execute; capture timing once from notifications; write per-test-case, per-iteration `eval_metadata.json`; grade; aggregate; analyze; launch viewer.
- `grading.json` expectations MUST contain exactly `text`, `passed`, and `evidence`.
- Viewer ordering: `with_skill` before baseline.
- NEVER use `/skill-test` or custom review HTML.
</critical>

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|Intent capture, research, authoring, and user communication|`references/authoring.md`|Creating or materially refactoring a skill|
|Exact eval/benchmark JSON|`references/schemas.md`|Creating or validating artifacts|
|Eval, timing, grading, viewer, iteration|`references/eval-workflow.md`|Running evaluations|
|Trigger tuning and held-out scoring|`references/description-optimization.md`|Optimizing metadata descriptions|
|Package validation and handoff|`references/packaging.md`|Packaging a skill|
|Runtime-specific adaptations|`references/runtime-modes.md`|The default runner is unavailable|
|Assertion grading|`agents/grader.md`|Grading an eval run|
|Benchmark analysis|`agents/analyzer.md`|Comparing benchmark results|
|Blind A/B comparison|`agents/comparator.md`|Comparing skill versions|

## Description Optimization

Offer description optimization only after core behavior is in good shape. Read `references/description-optimization.md` for trigger-eval query generation/review, the `eval_review.html` workflow, `run_loop.py` and held-out scoring, or before/after description updates and score reporting.

## Packaging

When the user is satisfied, read `references/packaging.md` for exact validation, packaging, and presentation; package the final skill and tell the user the resulting `.skill` file path for installation.

<critical>
- Keep long schemas, eval mechanics, viewer details, description optimization, runtime variants, and package details in references until needed.
- Package the final skill when the user is satisfied.
</critical>
