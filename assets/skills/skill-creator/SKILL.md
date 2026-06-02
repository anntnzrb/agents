---
name: skill-creator
description: Create, audit, refactor, benchmark, and optimize skills. Use whenever the user wants a new skill, a second pass on an existing skill, help validating SKILL.md structure, evals, benchmarks, packaging, or trigger descriptions — even if they only ask for cleanup, iteration, or skill polish.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
disable-model-invocation: true
---

# Skill Creator

Create, audit, refactor, benchmark, optimize, and package skills.

<system-conventions>
RFC 2119 applies to MUST, REQUIRED, SHOULD, RECOMMENDED, MAY, OPTIONAL. `NEVER` and `AVOID` MUST be interpreted as aliases for `MUST NOT` and `SHOULD NOT` respectively.
</system-conventions>

<critical>
- Core loop: identify → draft → test → evaluate → iterate → package.
- Keep `SKILL.md` as the entrypoint. Load references only when their routing condition applies.
- You NEVER use `/skill-test` or any other testing skill.
- Preserve exact schemas, field names, paths, and command syntax.
- Description optimization comes after core behavior works, not before.
</critical>

## Capability and Trigger

Use this skill to create new skills, repair or refactor existing skills, validate structure, design evals, run benchmarks, optimize frontmatter descriptions, and package `.skill` artifacts. If the user asks for cleanup, iteration, benchmark design, triggering accuracy, or skill polish, treat that as in scope.

## Core Loop

Figure out where the user is, then move them forward:

1. **Identify** what the skill should enable and when it should trigger.
2. **Draft** or edit `SKILL.md` and bundled resources.
3. **Test** realistic prompts with the skill enabled.
4. **Evaluate** outputs with the user, qualitative review, and quantitative checks.
5. **Iterate** from feedback and benchmark evidence.
6. **Package** the final skill for installation.

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

## Communicating With the User

Adapt to the user's technical level. Many users can follow concise coding jargon; some cannot. Use context cues.

- "evaluation" and "benchmark" are borderline but usually OK.
- Explain "JSON" or "assertion" unless the user signals familiarity.
- Define terms briefly when in doubt.
- Reduce burden: extract intent from conversation history before asking.
- Ask for confirmation before moving past ambiguous requirements.

## Core Authoring Rules

### Capture intent

Start by understanding intent. If the current conversation already contains the workflow, extract the tools, step sequence, corrections, input formats, output formats, and success criteria before asking questions.

Ask only what remains unknown:

1. What should this skill enable Claude to do?
2. When should this skill trigger? (what user phrases/contexts)
3. What's the expected output format?
4. Should we set up test cases to verify the skill works? Skills with objectively verifiable outputs benefit from test cases. Skills with subjective outputs often skip them. Suggest the appropriate default based on skill type, but let the user decide.

### Research before writing

Ask about edge cases, input/output formats, example files, success criteria, and dependencies. Wait to write test prompts until the workflow is clear. Research docs, similar skills, or best practices when useful. Use subagents in parallel when available; otherwise research inline. Bring context back to the user instead of making them carry it.

### Write `SKILL.md`

Compose:

- **name**: Skill identifier.
- **description**: Trigger contract + capability. This is the primary trigger. Put all "when to use" guidance here, not in the body. Skills tend to undertrigger, so write a pushy description with explicit contexts and nearby user phrasing.
- **compatibility**: Required tools or dependencies. OPTIONAL; rarely needed.
- **body**: Imperative instructions, examples, references, workflows, and resource pointers.

Skill anatomy:

```text
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter (name, description required)
│   └── Markdown instructions
└── Bundled Resources (optional)
    ├── scripts/    - Executable code for deterministic/repetitive tasks
    ├── references/ - Docs loaded into context as needed
    └── assets/     - Files used in output (templates, icons, fonts)
```

### Safety and surprise

Skills MUST match the user's stated intent. They NEVER contain malware, exploit code, unauthorized-access workflows, data exfiltration, or misleading behavior. Roleplay and harmless persona skills are acceptable when accurately described.

### Writing style

Use imperative instructions. Explain why instructions matter instead of leaning on rigid MUSTs. Use RFC keywords for technical and operational constraints, not taste. Give the model enough purpose and theory of mind to generalize beyond examples. Draft, reread cold, then improve.

Define output formats with exact templates when structure matters. Use examples for transformations and style choices, but keep examples small and realistic.

## Progressive Disclosure Rules

Skills load in three levels:

1. **Metadata** (`name` + `description`) — always in context (~100 words).
2. **`SKILL.md` body** — loaded when the skill triggers (<500 lines ideal; under 250 when practical).
3. **Bundled resources** — loaded on demand; scripts can execute without loading.

Key patterns:

- Keep `SKILL.md` focused on trigger, routing, and core workflow.
- Move long procedures, schemas, examples, and domain variants into `references/`.
- Give every reference explicit when-to-read guidance at the top and in this routing table.
- Prefer `scripts/` for deterministic or repetitive work.
- Keep inline snippets tiny.
- Add a table of contents for reference files >300 lines.

When a skill supports multiple domains or frameworks, organize by variant so Claude reads only the relevant reference file.

## Eval Workflow Summary

After drafting, propose 2-3 realistic test prompts before running them. Save prompts to `evals/evals.json`; see `references/schemas.md` for the full schema, including the `assertions` field added later.

Detailed eval workflow lives in `references/eval-workflow.md`. Summary:

1. Put results in `<skill-name>-workspace/` as a sibling to the skill directory, organized by `iteration-N/` and one directory per test case.
2. Spawn with-skill and baseline runs in the same turn so timing and conditions are comparable. For existing skill improvement, snapshot the old version before editing and use it as the baseline when appropriate.
3. Draft objectively verifiable assertions while runs are in progress; do not force fake objectivity onto subjective work.
4. Capture `total_tokens` and `duration_ms` from each task notification immediately into `timing.json`; this data is not persisted elsewhere.
5. Grade runs, aggregate benchmark data, do an analyst pass, then launch the review viewer with `generate-review`. NEVER write custom HTML.
6. Read `feedback.json`, improve the skill from transcripts, user feedback, and benchmark data, then rerun into a new iteration until the user is satisfied or changes stop producing meaningful improvement.

<critical>
- Evaluation sequence: spawn with-skill and baseline in the same turn; draft assertions while runs run; capture timing once from notifications; write per-test-case per-iteration `eval_metadata.json`; grade; aggregate; analyze; launch viewer.
- `grading.json` expectations MUST use exactly `text`, `passed`, and `evidence`.
- Put `with_skill` before baseline in viewer ordering.
- NEVER use `/skill-test` or custom review HTML.
</critical>

## Routing Table

| Need                                                                                                                     | Read / Use                               |
| ------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------- |
| Exact JSON structures for evals, metadata, grading, benchmarks, feedback                                                 | `references/schemas.md`                  |
| Detailed eval runner, timing capture, grading, benchmark aggregation, viewer, feedback, iteration loop                   | `references/eval-workflow.md`            |
| Trigger tuning, eval query generation, `eval_review.html`, `run_loop.py`, held-out scoring, before/after score reporting | `references/description-optimization.md` |
| Package validation, `.skill` generation, presentation handoff                                                            | `references/packaging.md`                |
| Claude.ai, Cowork, browserless/headless, or server-unavailable adaptations                                               | `references/runtime-modes.md`            |
| Assertion grading                                                                                                        | `agents/grader.md`                       |
| Benchmark and comparison analysis                                                                                        | `agents/analyzer.md`                     |
| Rigorous blind A/B comparison between skill versions                                                                     | `agents/comparator.md`                   |

## Description Optimization

Offer description optimization after core skill behavior is in good shape. Read `references/description-optimization.md` when you need trigger eval query generation and review, the `eval_review.html` workflow, `run_loop.py` / held-out scoring details, or before/after description updates and score reporting.

## Packaging

When the user is satisfied, package the final skill. Read `references/packaging.md` for exact validation, package, and presentation details. Tell the user the resulting `.skill` file path so they can install it.

<critical>
- Core loop: identify → draft → test → evaluate → iterate → package.
- Keep long schemas, eval mechanics, viewer details, description optimization, runtime variants, and package details in references until needed.
- Package the final skill when the user is satisfied.
</critical>
