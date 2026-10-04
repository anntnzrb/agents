# Verify a change in CI

CI checks repository structure and runs the suites owned by the changed code. The workflows under [`.github/workflows/`](../.github/workflows/) own triggers, runners, schedules, and tool versions. Local hooks run sync gates and selected owner checks; see [Git hooks](../.githooks/README.md).

## Run checks locally

Run these commands from the repository root. Inspect the suites selected for your committed branch:

```bash
uv run --script .github/scripts/ci.py plan --base origin/main
```

Omit `--base` to select all active code suites. Selection compares the merge base with `HEAD`; uncommitted changes are not included.

Run metadata validation, then the selected skill and harness suites:

```bash
uv run --script .github/scripts/ci.py local
```

`local` defaults to `--base origin/main` and stops at the first failure. Each selected harness runs `bun install --frozen-lockfile` then `bun test` in a temporary copy. The `pre-push` hook runs this command from the repository root after the sync static gates and serial test suite.

Validate every active skill's metadata, and check repository Markdown outside `skills/` and `legacy/` for en and em dashes:

```bash
uv run --script .github/scripts/ci.py metadata
```

Run a selected skill's gates using [Manage shared skills](skills.md#validate-python-skills-standard). Run sync checks using [Develop the sync application](sync/development.md#run-the-full-checks). Harness validation stays beside its source.

The `repository-checks` job in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) also lints, formats, type-checks, and tests `.github/` and the Python tools under `tools/` with pinned `uvx` commands. Run the same commands locally after changing those paths.

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

Run or inspect the workflow from GitHub's **Actions** tab. CI runs on pull requests, manual dispatch, and a weekly schedule. Manual dispatch and scheduled CI select all active code suites. A merge to `main` does not rerun CI; see [Merge a pull request](#merge-a-pull-request). The workflow does not invoke harness CLIs, inference providers, automatic agent reviews, or model evaluations.

Live smoke tests, native harness integration tests, and model-based skill evaluations remain explicit manual operations owned by their source. They do not run in CI. Structural skill validation does not establish instruction quality or activation accuracy.

## Compare performance without skipping validation

Skill shards share uv's dependency and tool environments within a runner. Cache keys separate shard membership and platforms, and include inline dependency declarations as well as tool configuration. This prevents one parallel job's incomplete cache from becoming every job's immutable cache hit. Managed Python installations are cached too.

Caches store dependencies and interpreters, never successful check results. Every selected owner runs its gates on both supported platforms. Keep the platform matrix and shard count in the workflow and planner, respectively; do not tune them by omitting owners or weakening the required check.

For a local comparison, use fresh `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`, and `UV_TOOL_DIR` directories for each group. Run the same owners with the same concurrency, first with empty caches and then again with those caches retained. Compare total elapsed time and the sum of group durations separately. Keep source, interpreter requirements, and gate commands unchanged. Local timings exclude GitHub runner provisioning, checkout, and cache transfer; Darwin measurements require a Darwin runner.

## Merge a pull request

The repository requires `CI required` and a strict up-to-date ruleset before merging. Use merge commits titled from the PR. CI has no push trigger because the merged tree has already passed CI; the weekly scheduled run catches dependency drift.

Land with `uv run --script skills/current/ship/scripts/cli.py land <number>`.

## Update dependencies

Dependabot ([`.github/dependabot.yml`](../.github/dependabot.yml)) opens one grouped weekly PR per ecosystem: GitHub Actions, uv lock files under `sync/` and `skills/current/*/`, and the bun harness packages. The `auto-merge` workflow queues each Dependabot PR to merge once `CI required` passes. Workflows reference actions by version tag, not commit SHA, so these PRs stay readable; tool versions that are pinned in commands, such as the `uvx` gate tools and the skill-creator gate pins, are updated by hand.

## Repository settings

The Settings app (https://github.com/apps/settings) syncs [`.github/settings.yml`](../.github/settings.yml) to GitHub whenever it changes on `main`. The file extends the shared baseline in the `anntnzrb/.github` repository; override a value here for this repository only. A baseline change does not trigger a sync: this repository picks it up the next time its own `.github/settings.yml` changes on `main`, so apply it now with `gh api -X PATCH repos/anntnzrb/agents` when it cannot wait. The app does not manage rulesets, so merge protection below stays a separate setting.

## Maintain merge protection

The default branch's ruleset requires `CI required` from GitHub Actions. Keep the final check name stable when changing job selection. Preserve existing protection rules, and do not add bypass actors to make a failing change mergeable.

The `repository-checks` and `sync-gates` jobs run on every pull request. The plan selects a skill only when a changed path is under `skills/current/<name>/` and that directory contains Python files; other skills get metadata validation only. Changes under `.github/` select every skill and harness suite. Changes under `skills/current/skill-creator/`, `docs/skills.md`, or `HARNESS.md` select every Python skill. Deleted or archived skills no longer produce code jobs; metadata validation still covers every published skill.
