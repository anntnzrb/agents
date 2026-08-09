---
name: skill-creator
description: Create, audit, refactor, validate, benchmark, or optimize skills and their trigger metadata.
license: Apache-2.0
metadata:
  author: Anthropic
  local-maintainer: anntnzrb
  upstream: https://github.com/anthropics/skills/tree/main/skills/skill-creator

---

# Skill Creator

Create, audit, refactor, benchmark, optimize, and package skills.

<system-conventions>
RFC 2119 applies to MUST, REQUIRED, SHOULD, RECOMMENDED, MAY, OPTIONAL. `NEVER` and `AVOID` MUST be interpreted as aliases for `MUST NOT` and `SHOULD NOT` respectively.
</system-conventions>

<critical>
- Core loop: identify → draft → test → evaluate → iterate → package
- Keep `SKILL.md` as the entrypoint. Load references only when their routing condition applies
- You NEVER use `/skill-test` or any other testing skill
- Preserve exact schemas, field names, paths, and command syntax
- Description optimization comes after core behavior works, not before
</critical>

## Capability and Trigger

Use this skill to create new skills, repair or refactor existing skills, validate structure, design evals, run benchmarks, optimize frontmatter descriptions, and package `.skill` artifacts. If the user asks for cleanup, iteration, benchmark design, triggering accuracy, or skill polish, treat that as in scope.

## Core Loop

Figure out where the user is, then move them forward:

1. **Identify** what the skill should enable and when it should trigger
2. **Draft** or edit `SKILL.md` and bundled resources
3. **Test** realistic prompts with the skill enabled
4. **Evaluate** outputs with the user, qualitative review, and quantitative checks
5. **Iterate** from feedback and benchmark evidence
6. **Package** the final skill for installation

The user may already have a draft, evals, or a vague idea. Start at the right point. If they explicitly want a lighter collaborative pass instead of full evals, help them, but keep the loop available.

## Public CLI Entrypoint

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. NEVER rely on shell sourcing, executable bits, or shebang dispatch.

Useful commands:

```bash
uv run --script <skill-dir>/scripts/cli.py aggregate-benchmark <workspace>/iteration-N --skill-name <name>
uv run --script <skill-dir>/scripts/cli.py generate-review <workspace>/iteration-N --skill-name <name>
uv run --script <skill-dir>/scripts/cli.py package <path-to-skill-folder>
uv run --script <skill-dir>/scripts/cli.py quick-validate <path-to-skill-folder>
```

Read `references/eval-workflow.md` for detailed aggregate/review usage. Read `references/packaging.md` for package validation and handoff details.

## Progressive Disclosure Rules

Skills load in three levels:

1. **Metadata** (`name` + `description`) — always in context (~100 words)
2. **`SKILL.md` body** — loaded when the skill triggers (<500 lines ideal; under 250 when practical)
3. **Bundled resources** — loaded on demand; scripts can execute without loading

Key patterns:

- Keep `SKILL.md` focused on trigger, routing, and core workflow
- Move long procedures, schemas, examples, and domain variants into `references/`
- Give every reference explicit when-to-read guidance at the top and in this routing table
- Prefer `scripts/` for deterministic or repetitive work
- Keep inline snippets tiny
- Add a table of contents for reference files >300 lines

When a skill supports multiple domains or frameworks, organize by variant so the agent reads only the relevant reference file.

## Eval Workflow Summary

After drafting, propose 2-3 realistic test prompts before running them. Save prompts to `evals/evals.json`; see `references/schemas.md` for the full schema, including the `assertions` field added later.

Detailed eval workflow lives in `references/eval-workflow.md`. Summary:

1. Put results in `<skill-name>-workspace/` as a sibling to the skill directory, organized by `iteration-N/` and one directory per test case
2. Spawn with-skill and baseline runs in the same turn so timing and conditions are comparable. For existing skill improvement, snapshot the old version before editing and use it as the baseline when appropriate
3. Draft objectively verifiable assertions while runs are in progress; do not force fake objectivity onto subjective work
4. Capture `total_tokens` and `duration_ms` from each task notification immediately into `timing.json`; this data is not persisted elsewhere
5. Grade runs, aggregate benchmark data, do an analyst pass, then launch the review viewer with `generate-review`. NEVER write custom HTML
6. Read `feedback.json`, improve the skill from transcripts, user feedback, and benchmark data, then rerun into a new iteration until the user is satisfied or changes stop producing meaningful improvement

<critical>
- Evaluation sequence: spawn with-skill and baseline in the same turn; draft assertions while runs run; capture timing once from notifications; write per-test-case per-iteration `eval_metadata.json`; grade; aggregate; analyze; launch viewer
- `grading.json` expectations MUST use exactly `text`, `passed`, and `evidence`
- Put `with_skill` before baseline in viewer ordering
- NEVER use `/skill-test` or custom review HTML
</critical>

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Intent capture, research, authoring, and user communication | `references/authoring.md` | Creating or materially refactoring a skill |
| Exact eval/benchmark JSON | `references/schemas.md` | Creating or validating artifacts |
| Eval, timing, grading, viewer, iteration | `references/eval-workflow.md` | Running evaluations |
| Trigger tuning and held-out scoring | `references/description-optimization.md` | Optimizing metadata descriptions |
| Package validation and handoff | `references/packaging.md` | Packaging a skill |
| Runtime-specific adaptations | `references/runtime-modes.md` | The default runner is unavailable |
| Assertion grading | `agents/grader.md` | Grading an eval run |
| Benchmark analysis | `agents/analyzer.md` | Comparing benchmark results |
| Blind A/B comparison | `agents/comparator.md` | Comparing skill versions |

## Description Optimization

Offer description optimization after core skill behavior is in good shape. Read `references/description-optimization.md` when you need trigger eval query generation and review, the `eval_review.html` workflow, `run_loop.py` / held-out scoring details, or before/after description updates and score reporting.

## Packaging

When the user is satisfied, package the final skill. Read `references/packaging.md` for exact validation, package, and presentation details. Tell the user the resulting `.skill` file path so they can install it.

<critical>
- Core loop: identify → draft → test → evaluate → iterate → package
- Keep long schemas, eval mechanics, viewer details, description optimization, runtime variants, and package details in references until needed
- Package the final skill when the user is satisfied
</critical>
