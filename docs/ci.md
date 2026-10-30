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

The `repository-checks` job in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) also lints, formats, type-checks, and tests `.github/` with pinned `uvx` commands. Run the same commands locally after changing that directory.

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

1. Open the failing job in GitHub's **Actions** tab or the PR's **Checks** tab.
2. Read the first failing command and its output.
3. Reproduce it locally with the owning suite's command.
4. Fix the cause and rerun that suite before pushing.

The final `CI required` check succeeds only when every selected suite succeeds. A skipped matrix is acceptable only when the plan selected no owners for that matrix. Failures, cancellations, missing results, and unexpected skips block this check.

## Keep CI deterministic

CI uses recorded fixtures and local test servers without provider credentials. Live tests are disabled. Python skill gates reject sockets outside loopback; Unix sockets remain available for local process coordination. Extension tests preload an HTTP guard, so calls using the default fetch transport fail instead of contacting a provider.

Run or inspect the workflow from GitHub's **Actions** tab. CI runs on pull requests, pushes to `main`, manual dispatch, and a weekly schedule. Selection uses the PR base commit or the push's before commit, so a multi-commit push covers the complete range. Missing, zero, unavailable, or unrelated baselines select all active code suites and check whitespace against the full tree. Manual dispatch and scheduled CI also run all suites. A PR merge can trigger another run on `main`. The workflow does not invoke harness CLIs, inference providers, automatic agent reviews, or model evaluations.

Live smoke tests, native harness integration tests, and model-based skill evaluations remain explicit manual operations owned by their source. They do not run in CI. Structural skill validation does not establish instruction quality or activation accuracy.

## Compare performance without skipping validation

Skill shards share uv's dependency and tool environments within a runner. Cache keys separate shard membership and platforms, and include inline dependency declarations as well as tool configuration. This prevents one parallel job's incomplete cache from becoming every job's immutable cache hit. Managed Python installations are cached too.

Caches store dependencies and interpreters, never successful check results. Every selected owner runs its gates on both supported platforms. Keep the platform matrix and shard count in the workflow and planner, respectively; do not tune them by omitting owners or weakening the required check.

For a local comparison, use fresh `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR`, and `UV_TOOL_DIR` directories for each group. Run the same owners with the same concurrency, first with empty caches and then again with those caches retained. Compare total elapsed time and the sum of group durations separately. Keep source, interpreter requirements, and gate commands unchanged. Local timings exclude GitHub runner provisioning, checkout, and cache transfer; Darwin measurements require a Darwin runner.

## Integrate and publish a change

Use local integration into `main` and normal direct pushes by default. Use short `work/<8-lowercase-hex>` branches to isolate parallel tasks. Generate each suffix mechanically, for example with `openssl rand -hex 4`.

1. Assign one owner to integrate the final target. Keep each task in its own checkout while other contributors are active.
2. Inspect the diff and run the relevant checks under [Run checks locally](#run-checks-locally). Commit with the `autommit` skill.
3. In the integration owner's clean checkout, run `git fetch origin` and `git merge --ff-only origin/main`. Integrate the task branch with `git merge <task-branch>`, or keep the checked commits already on local `main`.
4. Verify the combined diff against `origin/main` and rerun checks affected by integration. Run `git diff --check origin/main HEAD` and `uv run --script .github/scripts/ci.py local --base origin/main`. Run the sync gates and tests linked above; the pre-push hook also runs them.
5. Publish with `git push origin main`. Inspect the resulting CI run before reporting publication as checked.

In T3, a read-only scout child can verify the push's expected CI checks and wake the parent on completion. Do not create a placeholder PR for a watcher or poll from the parent.

If `origin/main` has advanced beyond the local history, stop the fast-forward step and reconcile the histories in the owner's isolated checkout. Review conflicts and repeat the relevant checks before pushing. Do not force-push, reset, discard unfamiliar changes, or switch a shared checkout's branch or worktree state.

Direct pushes require compatible server rules. If a rule rejects publication, report the exact blocker and use an approved integration path. Never disable hooks or bypass server rules. Repository policy does not change GitHub settings.

## Merge a pull request

Use a pull request when requested or required by server rules. Push the task branch normally and open the PR. Wait for `CI required` on the current head and satisfy the repository's review and protection rules. Use a merge commit titled from the PR. The push to `main` can run CI again after the merge.

Follow the [ship skill's PR route](../skills/current/ship/SKILL.md). In T3, use `watch_pull_request` for passive waits, then check readiness for the exact current head and merge on wake. The polling CLI, `uv run --script skills/current/ship/scripts/cli.py <number>`, serves harnesses without T3 managed waiting.

## Update dependencies

Dependabot ([`.github/dependabot.yml`](../.github/dependabot.yml)) opens one grouped weekly PR per ecosystem: GitHub Actions, uv lock files under `sync/` and `skills/current/*/`, and the bun harness packages. The `auto-merge` workflow waits for a successful `ci` workflow run. It merges only an associated open, non-draft Dependabot PR whose current head matches that run's head SHA. This gate does not rely on a required-status rule. Workflows reference actions by version tag, not commit SHA, so these PRs stay readable; tool versions that are pinned in commands, such as the `uvx` gate tools and the skill-creator gate pins, are updated by hand.

After a successful bot merge, the workflow explicitly dispatches `ci.yml` on `main` to check the integrated tree. Merges made with `GITHUB_TOKEN` suppress push-triggered workflows, but GitHub permits explicit `workflow_dispatch` events from that token. A rejected merge does not dispatch CI.

## Repository settings

The Settings app (https://github.com/apps/settings) syncs [`.github/settings.yml`](../.github/settings.yml) to GitHub whenever it changes on `main`. The file extends the shared baseline in the `anntnzrb/.github` repository; override a value here for this repository only. A baseline change does not trigger a sync: this repository picks it up the next time its own `.github/settings.yml` changes on `main`, so apply it now with `gh api -X PATCH repos/anntnzrb/agents` when it cannot wait. The app does not manage rulesets, so merge protection below stays a separate setting.

## Maintain merge protection

Server-side rulesets belong to the repository owner. Keep rules compatible with the intended integration path: mandatory PRs or required pre-push status checks can block normal direct publication. Inspect the live rules before claiming that direct pushes are allowed, and report blockers for an authorized owner decision. Preserve deletion and non-fast-forward protections. Do not add bypass actors or change settings to make a failing change publishable. Keep the final `CI required` check stable for optional PRs and post-push verification.

Before relaxing required checks, inspect and explicitly disable pre-existing PR auto-merge requests. Changing the workflow does not cancel those requests; removing required checks can make them merge immediately. Deploy the workflow's successful-CI merge gate before changing the rules.

The `repository-checks` and `sync-gates` jobs run on every CI event. The plan selects a skill only when a changed path is under `skills/current/<name>/` and that directory contains Python files; other skills get metadata validation only. Changes under `.github/` select every skill and harness suite. Changes under `skills/current/skill-creator/`, `docs/skills.md`, or `HARNESS.md` select every Python skill. Deleted or archived skills no longer produce code jobs; metadata validation still covers every published skill.
