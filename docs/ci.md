# Verify a change in CI

CI checks repository structure and runs the suites owned by the changed code. The workflows under [`.github/workflows/`](../.github/workflows/) own triggers, runners, schedules, and tool versions. Local sync hooks remain focused on sync; see [Git hooks](../.githooks/README.md).

## Run checks locally

Run these commands from the repository root. Inspect the suites selected for your committed branch:

```bash
uv run --script .github/scripts/ci.py plan --base origin/main
```

Omit `--base` to select all active code suites. Selection compares the merge base with `HEAD`; uncommitted changes are not included.

Validate every active skill's metadata:

```bash
uv run --script .github/scripts/ci.py metadata
```

Run a selected skill's gates using [Manage shared skills](skills.md#validate-python-skills-standard). Run sync checks using [Develop the sync application](sync/development.md#run-the-full-checks). Harness validation stays beside its source.

Reproduce a skill shard by copying its `SKILLS` JSON array from the job's environment:

```bash
SKILLS='["skill-creator"]' uv run --script .github/scripts/ci.py skills
```

The command runs each owner's full gates sequentially and prints its elapsed time. It stops at the first failed owner. Other shards continue independently.

Check CI orchestration behavior with its adjacent tests:

```bash
uvx --python 3.14 pytest==9.1.1 .github/tests -q
```

## Diagnose a failed check

1. Open the failing job in the PR's **Checks** tab.
2. Read the first failing command and its output.
3. Reproduce it locally with the owning suite's command.
4. Fix the cause and rerun that suite before pushing.

The final `CI required` check succeeds only when every selected suite succeeds. A skipped matrix is acceptable only when the plan selected no owners for that matrix. Failures, cancellations, missing results, and unexpected skips block this check.

## Keep CI deterministic

CI uses recorded fixtures and local test servers without provider credentials. Live tests are disabled. Python skill gates reject sockets outside loopback; Unix sockets remain available for local process coordination. Extension tests preload an HTTP guard, so calls using the default fetch transport fail instead of contacting a provider.

Run or inspect the workflow from GitHub's **Actions** tab. Manual dispatch and scheduled CI select all active code suites. The workflow does not invoke harness CLIs, inference providers, automatic agent reviews, or model evaluations.

Live smoke tests, native harness integration tests, and model-based skill evaluations remain explicit manual operations owned by their source. They do not run in CI. Structural skill validation does not establish instruction quality or activation accuracy.

## Compare performance without skipping validation

Skill shards share uv's dependency and tool environments within a runner. Cache keys separate shard membership and platforms, and include inline dependency declarations as well as tool configuration. This prevents one parallel job's incomplete cache from becoming every job's immutable cache hit. Managed Python installations are cached too.

Caches store dependencies and interpreters, never successful check results. Every selected owner runs its gates on both supported platforms. Keep the platform matrix and shard count in the workflow and planner, respectively; do not tune them by omitting owners or weakening the required check.

For a local comparison, use fresh `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`, and `UV_TOOL_DIR` directories for each group. Run the same owners with the same concurrency, first with empty caches and then again with those caches retained. Compare total elapsed time and the sum of group durations separately. Keep source, interpreter requirements, and gate commands unchanged. Local timings exclude GitHub runner provisioning, checkout, and cache transfer; Darwin measurements require a Darwin runner.

## Maintain merge protection

The default branch's ruleset requires `CI required` from GitHub Actions. Keep the final check name stable when changing job selection. Preserve existing protection rules, and do not add bypass actors to make a failing change mergeable.

Workflow changes select all code suites. Changes to the shared skill gate select all Python skills. Deleted or archived skills no longer produce code jobs; metadata validation still covers every published skill.
