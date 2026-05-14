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
- Keep that loop near the start, follow it flexibly, and recap it at the end.
- You NEVER use `/skill-test` or any other testing skill.
- Preserve exact schemas, field names, paths, and command syntax.
- Description optimization comes after core behavior works, not before.
</critical>

## Core Loop

Figure out where the user is, then move them forward:

1. **Identify** what the skill should enable and when it should trigger.
2. **Draft** or edit `SKILL.md` and bundled resources.
3. **Test** realistic prompts with the skill enabled.
4. **Evaluate** outputs with the user, qualitative review, and quantitative checks.
5. **Iterate** from feedback and benchmark evidence.
6. **Package** the final skill for installation.

The user may already have a draft, evals, or a vague idea. Start at the right point. If they explicitly want a lighter collaborative pass instead of full evals, help them, but keep the loop available.

## Entry Point

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

## Communicating With the User

Adapt to the user's technical level. Many users can follow concise coding jargon; some cannot. Use context cues.

- "evaluation" and "benchmark" are borderline but usually OK.
- Explain "JSON" or "assertion" unless the user signals familiarity.
- Define terms briefly when in doubt.
- Reduce burden: extract intent from conversation history before asking.
- Ask for confirmation before moving past ambiguous requirements.

## Creating a Skill

### Capture Intent

Start by understanding intent. If the current conversation already contains the workflow, extract the tools, step sequence, corrections, input formats, output formats, and success criteria before asking questions.

Ask only what remains unknown:

1. What should this skill enable Claude to do?
2. When should this skill trigger? (what user phrases/contexts)
3. What's the expected output format?
4. Should we set up test cases to verify the skill works? Skills with objectively verifiable outputs (file transforms, data extraction, code generation, fixed workflow steps) benefit from test cases. Skills with subjective outputs (writing style, art) often skip them. Suggest the appropriate default based on the skill type, but let the user decide.

### Interview and Research

Ask about edge cases, input/output formats, example files, success criteria, and dependencies. Wait to write test prompts until the workflow is clear.

Research docs, similar skills, or best practices when useful. Use subagents in parallel when available; otherwise research inline. Bring context back to the user instead of making them carry it.

### Write `SKILL.md`

Based on the interview, compose:

- **name**: Skill identifier.
- **description**: Trigger contract + capability. This is the primary trigger. Put all "when to use" guidance here, not in the body. Skills tend to undertrigger, so write a pushy description: include explicit contexts and nearby user phrasing. Example: instead of "How to build a simple fast dashboard to display internal Anthropic data.", write "How to build a simple fast dashboard to display internal Anthropic data. Use this skill whenever the user mentions dashboards, data visualization, internal metrics, or displaying company data, even without the word 'dashboard.'"
- **compatibility**: Required tools or dependencies. OPTIONAL; rarely needed.
- **body**: Imperative instructions, examples, references, workflows, and resource pointers.

### Anatomy of a Skill

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

### Progressive Disclosure

Skills load in three levels:

1. **Metadata** (`name` + `description`) — always in context (~100 words).
2. **`SKILL.md` body** — loaded when the skill triggers (<500 lines ideal).
3. **Bundled resources** — loaded on demand; scripts can execute without loading.

Key patterns:

- Keep `SKILL.md` under 500 lines.
- Near the limit? Add hierarchy and point to references.
- Reference files clearly, with when-to-read guidance.
- Prefer `scripts/` for deterministic or repetitive work.
- Keep inline snippets tiny.
- Add a table of contents for reference files >300 lines.

When a skill supports multiple domains or frameworks, organize by variant:

```text
cloud-deploy/
├── SKILL.md (workflow + selection)
└── references/
    ├── aws.md
    ├── gcp.md
    └── azure.md
```

Claude reads only the relevant reference file.

### Principle of Lack of Surprise

Skills MUST match the user's stated intent. They NEVER contain malware, exploit code, unauthorized-access workflows, data exfiltration, or misleading behavior. Roleplay and harmless persona skills are acceptable when accurately described.

### Writing Patterns

Use imperative instructions.

**Defining output formats**:

```markdown
## Report structure
ALWAYS use this exact template:
# [Title]
## Executive summary
## Key findings
## Recommendations
```

**Examples pattern**:

```markdown
## Commit message format
**Example 1:**
Input: Added user authentication with JWT tokens
Output: feat(auth): implement JWT-based authentication
```

### Writing Style

Explain why instructions matter instead of leaning on rigid MUSTs. Use RFC keywords for technical and operational constraints, not taste. Give the model enough purpose and theory of mind to generalize beyond examples. Draft, reread cold, then improve.

### Test Cases

After drafting, propose 2-3 realistic test prompts — things real users would actually say. Share them before running: "Here are a few test cases I'd like to try. Do these look right, or do you want to add more?"

Save prompts to `evals/evals.json`. NEVER write assertions yet; draft them while runs are in progress.

```json
{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "User's task prompt",
      "expected_output": "Description of expected result",
      "files": []
    }
  ]
}
```

See `references/schemas.md` for the full schema, including the `assertions` field added later.

## Running and Evaluating Test Cases

This section is one continuous sequence. Finish it once started. You NEVER use `/skill-test` or any other testing skill.

Put results in `<skill-name>-workspace/` as a sibling to the skill directory. Organize by iteration (`iteration-1/`, `iteration-2/`, etc.). Within each iteration, create one directory per test case (`eval-0/`, `eval-1/`, etc., or descriptive names). Create directories as you go, not upfront.

### Step 1: Spawn all runs in the same turn

For each test case, spawn both runs in the same turn:

- with-skill
- baseline

This is load-bearing. NEVER spawn with-skill runs first and return later for baselines. Launch all runs together so timing and conditions are comparable.

**With-skill run:**

```text
Execute this task:
- Skill path: <path-to-skill>
- Task: <eval prompt>
- Input files: <eval files if any, or "none">
- Save outputs to: <workspace>/iteration-<N>/eval-<ID>/with_skill/outputs/
- Outputs to save: <what the user cares about — e.g., "the .docx file", "the final CSV">
```

**Baseline run** uses the same prompt and changes by context:

- **Creating a new skill**: no skill. Use no skill path. Save to `without_skill/outputs/`.
- **Improving an existing skill**: old version. Before editing, snapshot it with `cp -r <skill-path> <workspace>/skill-snapshot/`, point the baseline subagent at the snapshot, and save to `old_skill/outputs/`.

Write an `eval_metadata.json` for each test case in each iteration. Assertions can be empty at first. Give each eval a descriptive name based on what it tests; use the same name for the directory. If prompts are new or modified, create fresh metadata files for the new eval directories. NEVER assume metadata carries over.

```json
{
  "eval_id": 0,
  "eval_name": "descriptive-name-here",
  "prompt": "The user's task prompt",
  "assertions": []
}
```

### Step 2: Draft assertions while runs are in progress

Use run time productively. Draft quantitative assertions for each test case and explain them to the user. If `evals/evals.json` already has assertions, review and explain what they check.

Good assertions are objectively verifiable and have descriptive names. They should read clearly in the benchmark viewer. Subjective skills such as writing style and design quality often need qualitative review instead; NEVER force fake objectivity onto human judgment.

Update each `eval_metadata.json` and `evals/evals.json` with the assertions once drafted. Explain what the user will see in the viewer: qualitative outputs plus quantitative benchmark.

### Step 3: Capture timing data as notifications arrive

When each subagent completes, its notification contains `total_tokens` and `duration_ms`. Save that data immediately to `timing.json` in the run directory:

```json
{
  "total_tokens": 84852,
  "duration_ms": 23332,
  "total_duration_seconds": 23.3
}
```

This is the only opportunity to capture timing data. It comes through the task notification and is not persisted elsewhere. Process each notification as it arrives; NEVER wait to batch timing capture later.

### Step 4: Grade, aggregate, analyze, then launch viewer

After all runs finish:

1. **Grade each run** — spawn a grader subagent or grade inline. The grader reads `agents/grader.md` and evaluates each assertion against outputs. Save results to `grading.json` in each run directory. The `grading.json` expectations array MUST use exactly the fields `text`, `passed`, and `evidence`; the viewer depends on those exact names. For programmatically checkable assertions, write and run a script instead of eyeballing.

2. **Aggregate into benchmark** — run the aggregation script from the skill-creator directory:

   ```bash
   uv run --script <skill-creator-path>/scripts/cli.py aggregate-benchmark <workspace>/iteration-N --skill-name <name>
   ```

   This produces `benchmark.json` and `benchmark.md` with pass_rate, time, and tokens for each configuration, including mean ± stddev and delta. If generating `benchmark.json` manually, see `references/schemas.md` for the exact viewer schema. Put each `with_skill` version before its baseline counterpart.

3. **Do an analyst pass** — read the benchmark data before launching the viewer. Surface patterns aggregate stats can hide: non-discriminating assertions, high-variance evals, flaky tests, and time/token tradeoffs. See `agents/analyzer.md`, especially "Analyzing Benchmark Results".

4. **Launch the viewer** with qualitative outputs and quantitative data:

   ```bash
   nohup uv run --script <skill-creator-path>/scripts/cli.py generate-review \
     <workspace>/iteration-N \
     --skill-name "my-skill" \
     --benchmark <workspace>/iteration-N/benchmark.json \
     > /dev/null 2>&1 &
   VIEWER_PID=$!
   ```

   For iteration 2+, also pass `--previous-workspace <workspace>/iteration-<N-1>`.

   **Cowork / headless environments:** If `webbrowser.open()` is unavailable or the environment has no display, use `--static <output_path>` to write standalone HTML instead of starting a server. Feedback downloads as `feedback.json` when the user clicks "Submit All Reviews". After download, copy `feedback.json` into the workspace directory for the next iteration.

Use `uv run --script <skill-creator-path>/scripts/cli.py generate-review` to create the viewer. NEVER write custom HTML.

Tell the user: "I've opened the results in your browser. There are two tabs — 'Outputs' lets you click through each test case and leave feedback, 'Benchmark' shows the quantitative comparison. When you're done, come back here and let me know."

### What the user sees in the viewer

The "Outputs" tab shows one test case at a time:

- **Prompt**: task prompt.
- **Output**: generated files, rendered inline where possible.
- **Previous Output** (iteration 2+): collapsed previous iteration output.
- **Formal Grades** (if grading was run): collapsed assertion pass/fail.
- **Feedback**: auto-saving textbox.
- **Previous Feedback** (iteration 2+): prior comments below the textbox.

The "Benchmark" tab shows pass rates, timing, token usage, per-eval breakdowns, and analyst observations. Put `with_skill` before baseline in the viewer.

Navigation uses prev/next buttons or arrow keys. "Submit All Reviews" saves all feedback to `feedback.json`.

### Step 5: Read feedback

When the user says they are done, read `feedback.json`:

```json
{
  "reviews": [
    {"run_id": "eval-0-with_skill", "feedback": "the chart is missing axis labels", "timestamp": "..."},
    {"run_id": "eval-1-with_skill", "feedback": "", "timestamp": "..."},
    {"run_id": "eval-2-with_skill", "feedback": "perfect, love this", "timestamp": "..."}
  ],
  "status": "complete"
}
```

Empty feedback means the user thought it was fine. Focus improvements on test cases with specific complaints.

Kill the viewer server when finished:

```bash
kill $VIEWER_PID 2>/dev/null
```

## Improving the Skill

This is the heart of the loop: use transcripts, user feedback, and benchmark data to make the skill better.

### How to think about improvements

1. **Generalize from feedback.** The user and evals cover only a few examples. The skill must work across many prompts. Avoid overfitted patches and brittle rules; when an issue persists, change the framing, workflow, or examples so the model understands the underlying task.

2. **Keep the prompt lean.** Remove instructions that NEVER change behavior. Read transcripts, not just final outputs. If the skill causes unproductive work, cut or rewrite the prompt that caused it.

3. **Explain the why.** Even terse feedback usually points to a real user need. Understand the task, the user's words, and the missed expectation; transmit that understanding into the skill. If you reach for rigid ALWAYS/NEVER language, first ask whether an explanation would generalize better.

4. **Bundle repeated work.** If multiple test runs independently create the same helper script or repeat the same multi-step procedure, bundle that script in `scripts/` and point the skill to it. Save future invocations from reinventing it.

Draft the revision, reread it cold, and improve it before retesting.

### Iteration loop

After improving the skill:

1. Apply improvements.
2. Rerun all test cases into a new `iteration-<N+1>/` directory, including baseline runs. For new skills, baseline remains `without_skill`. For existing skills, choose the original version or previous iteration as the baseline based on what comparison the user needs.
3. Launch the reviewer with `--previous-workspace` pointing at the previous iteration.
4. Wait for the user to review and say they are done.
5. Read new feedback, improve again, repeat.

Continue until:

- the user says they are happy
- feedback is all empty
- changes stop producing meaningful improvement

## Advanced: Blind Comparison

For rigorous comparison between two skill versions, read `agents/comparator.md` and `agents/analyzer.md`. Give two outputs to an independent agent without revealing which is which, let it judge quality, then analyze why the winner won.

This is OPTIONAL, requires subagents, and most users can skip it. The human review loop is usually sufficient.

## Description Optimization

Offer description optimization after core skill behavior is in good shape.

Use `references/description-optimization.md` when you need:

- trigger eval query generation and review
- the `eval_review.html` workflow
- `run_loop.py` / held-out scoring details
- before/after description updates and score reporting

## Package and Present

If the `present_files` tool is unavailable, skip presentation. If it is available, package the skill and present the `.skill` file:

```bash
uv run --script <skill-creator-path>/scripts/cli.py package <path/to/skill-folder>
```

Tell the user the resulting `.skill` file path so they can install it.

## Runtime-Specific Instructions

Default to the Claude Code workflow in this file. Read `references/runtime-modes.md` only when you are:

- in Claude.ai with no subagents
- in Cowork / headless mode
- adapting the review flow because browser or server support is missing

## Reference Files

The `agents/` directory contains specialized subagent instructions. Read them when needed:

- `agents/grader.md` — evaluate assertions against outputs.
- `agents/comparator.md` — run blind A/B comparison.
- `agents/analyzer.md` — analyze benchmark and comparison results.

The `references/` directory contains supporting docs:

- `references/schemas.md` — JSON structures for `evals.json`, `grading.json`, etc.
- `references/description-optimization.md` — trigger-tuning workflow and eval review loop.
- `references/runtime-modes.md` — Claude.ai and Cowork adaptations.

<critical>
- Core loop: identify → draft → test → evaluate → iterate → package.
- Evaluation sequence: spawn with-skill and baseline in the same turn; draft assertions while runs run; capture timing once from notifications; write per-test-case per-iteration `eval_metadata.json`; grade; aggregate; analyze; launch viewer.
- `grading.json` expectations MUST use exactly `text`, `passed`, and `evidence`.
- Put `with_skill` before baseline in viewer ordering.
- NEVER use `/skill-test` or custom review HTML.
- Package the final skill when the user is satisfied.
</critical>