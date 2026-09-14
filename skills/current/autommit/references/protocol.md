# Autommit Protocol

Read this before invoking the CLI, parsing its JSON, or recovering a transaction.

## Invocation

Run one command:

```text
uv run --script <skill-dir>/scripts/cli.py [options] [context ...]
```

Success is one JSON line on stdout. Expected failure is one JSON line on stderr. Every payload has `schema:"autommit/v1"`, `ok:true|false`, `command`, and either `result` or `error`.

`--repo PATH` defaults to the current directory. Git is the only external executable.

## Commands

### `run` (default)

```text
uv run --script <skill-dir>/scripts/cli.py [--repo PATH] [--scope auto|staged|all] [--model M] [--base-url URL] [--api-key KEY] [--timeout S] [--reasoning-effort LEVEL] [--config PATH] [--smoke CMD] [--dry-run] [--json] [context ...]
```

`run` is the default command when no subcommand is given, and the only one that mutates anything. It owns the whole loop:

1. Recover a prepared receipt, then re-prepare in the same invocation.
2. Send the inventory, repository policy, and exact zero-context diff to the planner through the transport ladder: strict `json_schema`, then one forced tool call, then `json_object` plus local validation.
3. Validate each returned plan against the prepared snapshot. A rejected plan is retried at most three times, with the exact validation message as correction context.
4. When the plan needs atomicity review, ask an independent critic, at most twice. An `accept` verdict writes a decision file. A `split` verdict forces at most three replans that must produce at least two commits.
5. Apply commits in dependency order inside a detached temporary worktree, then create the commits by compare-and-swap.

Provider failures are terminal and never count as plan rejections. `--dry-run` prints the inventory and snapshot without a model call and without an API key. `--smoke CMD` runs one validation command inside the temporary worktree after each commit and creates nothing when it fails; it applies to that invocation only and is never persisted in config or environment.

Each request carries `model`, the system and user messages, and the response-format or tool field for the current rung. `--reasoning-effort LEVEL`, `AUTOMMIT_REASONING_EFFORT`, or a `reasoning_effort` config key adds that field, and an unset level sends none. `--model` and `--base-url` are required: autommit ships no model or endpoint default. No sampling or token parameter is sent: a provider that rejects `temperature` would fail every rung and hide the real cause, and a token cap would truncate a plan the CLI has already accepted.

Plan files, decision files, and the snapshot token live in a private temporary directory. They are never caller-facing flags.

### `rewrite`

```text
uv run --script <skill-dir>/scripts/cli.py rewrite --base <rev> [options]
```

`rewrite` rebuilds the commits since an ancestor revision while preserving the final content exactly. It:

1. Resolves `--base` (default order: `origin/HEAD`, `origin/main`, `main`) and refuses a revision that is not an ancestor of `HEAD`.
2. Freezes the current worktree, including uncommitted work, into a target tree through a temporary index, so the real index is never touched.
3. Builds the planner evidence from the range diff between `--base` and that target tree.
4. Rebuilds the commits in dependency order inside a detached temporary worktree placed at `--base`.
5. Requires the rebuilt tip tree to equal the frozen target tree, then moves the branch with one compare-and-swap and refreshes the index. Worktree files never change.

The previous tip is reported as the recovery point and stays reachable through the reflog. `rewrite` never pushes. Use `--dry-run` to print the frozen scope without a model call.

### `models`

```text
uv run --script <skill-dir>/scripts/cli.py models [--filter TEXT] [--base-url URL] [--api-key KEY] [--reasoning-effort LEVEL] [--config PATH] [--json]
```

Read-only discovery against the configured endpoint's `GET {base-url}/models`. It lists the advertised model ids, one per line, filtered by a case-insensitive substring when `--filter` is given. `--json` wraps the same ids and the resolved `base_url` in one `autommit/v1` object on stdout. It never reads or writes a repository, so use it to pick a `--model` before a run.

### Debug subcommands

`prepare`, `validate-plan`, `apply`, and `schema` remain available for debugging and tests. They keep the exact envelopes, snapshot algorithm, and exit codes documented below. Do not build workflows on them.

### `schema`

Print protocol discovery without reading or mutating a repository:

```text
uv run --script <skill-dir>/scripts/cli.py schema
```

### `prepare`

```text
uv run --script <skill-dir>/scripts/cli.py prepare [--scope auto|staged|all] [context ...] [--context TEXT ...] [--repo PATH]
```

Behavior:

1. Resolve the worktree-local Git directory with `git rev-parse --absolute-git-dir` and acquire `<git-dir>/autommit/operation.lock` with exclusive creation. This allows concurrent autommit runs across distinct worktrees.
2. Recover a durable prepared receipt before considering current changes.
3. In `auto` scope (default), use the existing staged snapshot unchanged. If nothing is staged, stage all uncommitted changes with `git add --all`. Explicit `all` scope stages all changes regardless of the index. `staged` scope requires existing staged changes and never stages anything.
4. Require a branch checkout with an existing `HEAD`.
5. Bind the branch ref, `HEAD`, and index tree into `snapshot`.
6. Return the exact cached binary diff, staged paths, changed-hunk count, composed context, recent subjects, and repository context.

Prepared result fields:

- `status`: `prepared`
- `snapshot`: opaque SHA-256 state binding used by later commands
- `ref`, `before`, `index_tree`: inspectable Git evidence
- `staged_files`: NUL-safe staged path list
- `changed_hunk_count`: regular unified-diff hunk count
- `context`: non-empty context values joined with two newlines
- `repository_context`: advisory naming/grouping evidence
- `diff`: exact cached binary diff used for planning

Recovery returns `status:recovered`, `ref`, and `after`. Stop after recovery; do not reuse an earlier plan.

### `validate-plan`

```text
uv run --script <skill-dir>/scripts/cli.py validate-plan --snapshot SNAPSHOT --plan-file PATH [--require-split] [--repo PATH]
```

This command rejects a changed branch, `HEAD`, or index; malformed/oversized JSON; unknown or unsafe paths; extra object keys; empty commits; duplicate paths inside one commit; omitted staged files/hunks; invented files; overlapping selections; and partial binary or metadata-only selections.

`--require-split` rejects plans with fewer than two commits after the atomicity critic returns `split`.

The result includes `commit_count`, `staged_file_count`, `changed_hunk_count`, and `requires_atomicity_review`. Critique is skipped only for one commit over one staged file with at most one changed hunk and at most one detail.

### `apply`

```text
uv run --script <skill-dir>/scripts/cli.py apply --snapshot SNAPSHOT --plan-file PATH [--decision-file PATH] [--repo PATH]
```

A broad one-commit plan requires a valid decision file. `accept` requires zero concerns and a non-empty rationale. `split` requires at least one concern and is rejected until the plan is replaced by a validated multi-commit plan.

Apply behavior:

1. Acquire the worktree-local operation lock and recover any receipt.
2. Recheck the snapshot and complete plan coverage.
3. Build selected patches from the original staged diff.
4. Apply commits in exact plan order in a detached temporary worktree.
5. Commit from a temporary UTF-8 message file. Details become `- ` body bullets, and one trailing period on the subject is stripped before the commit.
6. Require the final commit tree to equal the prepared index tree exactly.
7. Recheck the cached diff and snapshot.
8. Fsync a prepared receipt in the worktree-local directory, advance the branch with CAS (`git update-ref REF AFTER BEFORE`), verify branch/index evidence, then remove the receipt.
9. Remove the temporary worktree. Never fall back to in-place commits.

The original worktree index becomes clean relative to the new `HEAD`. In `auto` scope with an existing staged snapshot, and in `staged` scope, unrelated unstaged work remains in place.

## Plan Shape

```json
{
  "commits": [
    {
      "summary": "Imperative repository-style subject",
      "details": ["Concrete change detail."],
      "dependencies": [],
      "changes": [
        {"path": "src/example.py", "hunks": "all"},
        {"path": "tests/test_example.py", "hunks": {"type": "indices", "indices": [1, 2]}},
        {"path": "new.txt", "hunks": {"type": "lines", "start": 1, "end": 8}}
      ]
    }
  ]
}
```

`dependencies` is optional per commit. It holds 0-based indices into `commits` for commits that must be applied first. Autommit rejects self-references, duplicates, out-of-range indices, and cycles, then applies commits in dependency order. Dependency order matters because every commit is applied as a patch into one temporary worktree.

Valves, not product limits: there is no ceiling on commits, changes per commit, details, or dependencies. `summary` is capped at 72 characters and each detail and path at 2,048 and 4,096 characters. A plan or decision file is capped at 1 MiB and rejected as `invalid_file` above that.

Selectors:

- `"all"`: whole tracked, binary, metadata-only, rename, or ordinary file diff
- `{"type":"indices","indices":[1]}`: unique positive 1-based regular-diff hunk indices
- `{"type":"lines","start":1,"end":8}`: inclusive positive new-file line range, selected from the zero-context diff

Use line selectors when hunk selectors cannot separate the concerns and separate commits must own disjoint changed lines inside one file, including a modified file. Ranges must be disjoint and cover every changed new-file line exactly once.

## Atomicity Shape

```json
{"decision":"accept","concerns":[],"rationale":"The snapshot implements one cohesive behavior."}
```

or:

```json
{"decision":"split","concerns":["Behavior A.","Behavior B."],"rationale":"They are independently reversible."}
```

Valves: concern <=512 characters; rationale <=2,000 characters; concern count is not capped. The critic reviews a broad single-commit plan only. A narrow single-commit plan (one file, one hunk, at most one detail) and every multi-commit plan skip the review, because the critic can only demand more splits and would push an already-split plan toward over-fragmentation.

## Exit Codes

|Code|Meaning|Action|
|---|---|---|
|0|Success|Parse `result`|
|1|Provider or network failure|Wait for the provider, or configure another endpoint|
|2|Usage, JSON, plan, coverage, config, or critic error|Correct bounded model/input data; retry only within workflow limits|
|3|Lock, snapshot, branch, index, in-progress Git state, or receipt refusal|Preserve state; report exact blocker|
|4|Git, filesystem, cleanup, or smoke failure|Preserve state and inspect evidence|
|127|Git executable unavailable|Install/fix Git before retrying|
|130|Cancelled by a signal|Lock released, temporary worktree removed; no commits were created|

## Recovery Point

An interrupted or failed run that already built commits writes `recovery.json` beside the lock in the worktree-local autommit state directory, holding the branch ref and the commit it pointed at before the run. The failure message repeats it as `Recovery point: <ref> at <before>.`

Autommit never restores a recovery point automatically. Read it, inspect the repository, and decide. A successful run removes the file.

## Environment Invariants

Every Git invocation pins diff shape so hunk indices stay portable across machines: `core.quotepath=false`, `diff.mnemonicprefix=false`, `diff.noprefix=false`, `diff.algorithm=myers`, `diff.renames=true`, `diff.interHunkContext=0`, and the diff flags `--no-color --no-ext-diff --no-textconv`. `GIT_DIFF_OPTS` and `GIT_EXTERNAL_DIFF` are dropped from the environment, and `GIT_PAGER` is `cat`. Commits are created with `core.hooksPath=` and `--no-verify` inside the temporary worktree, so repository hooks never observe the temporary state. Pass `--smoke` to run repository validation deliberately.

Locks are never broken automatically. A prepared receipt is durable recovery evidence. Re-run `prepare` to recover it under the same branch and index state.
