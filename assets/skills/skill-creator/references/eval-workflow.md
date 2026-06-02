# Eval Workflow

Read this file when the user wants to create, run, grade, benchmark, review, or iterate skill evals. This file holds the detailed runner, viewer, grading, feedback, and iteration process; keep `SKILL.md` as the routing entrypoint.

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
    {
      "run_id": "eval-0-with_skill",
      "feedback": "the chart is missing axis labels",
      "timestamp": "..."
    },
    { "run_id": "eval-1-with_skill", "feedback": "", "timestamp": "..." },
    {
      "run_id": "eval-2-with_skill",
      "feedback": "perfect, love this",
      "timestamp": "..."
    }
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

## Related agent references

- `agents/grader.md` — evaluate assertions against outputs.
- `agents/analyzer.md` — analyze benchmark and comparison results.
- `agents/comparator.md` — run blind A/B comparison when needed.
- `references/schemas.md` — exact JSON structures for `evals.json`, `eval_metadata.json`, `grading.json`, `benchmark.json`, and feedback payloads.
