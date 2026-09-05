# Autommit Protocol

Read this before invoking the CLI, parsing its JSON, or recovering a transaction.

## Invocation

Use only:

```text
uv run --script <skill-dir>/scripts/cli.py <command> ...
```

Success is one JSON line on stdout. Expected failure is one JSON line on stderr. Every payload has `schema:"autommit/v1"`, `ok:true|false`, `command`, and either `result` or `error`.

`--repo PATH` defaults to the current directory. Git is the only external executable.

## Commands

### `schema`

Print protocol discovery without reading or mutating a repository:

```text
uv run --script <skill-dir>/scripts/cli.py schema
```

### `prepare`

```text
uv run --script <skill-dir>/scripts/cli.py prepare [--scope all|staged] [context ...] [--context TEXT ...] [--repo PATH]
```

Behavior:

1. Resolve the worktree-local Git directory with `git rev-parse --absolute-git-dir` and acquire `<git-dir>/autommit/operation.lock` with exclusive creation. This allows concurrent autommit runs across distinct worktrees.
2. Recover a durable prepared receipt before considering current changes.
3. In `all` scope (default), stage uncommitted changes with `git add --all`. In `staged` scope, operate strictly on existing staged changes without sweeping in unstaged work.
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
5. Commit from a temporary UTF-8 message file. Details become `- ` body bullets.
6. Require the final commit tree to equal the prepared index tree exactly.
7. Recheck the cached diff and snapshot.
8. Fsync a prepared receipt in the worktree-local directory, advance the branch with CAS (`git update-ref REF AFTER BEFORE`), verify branch/index evidence, then remove the receipt.
9. Remove the temporary worktree. Never fall back to in-place commits.

The original worktree index becomes clean relative to the new `HEAD`; in `staged` scope, unrelated unstaged work remains in place.

## Plan Shape

```json
{
  "commits": [
    {
      "summary": "Imperative repository-style subject",
      "details": ["Concrete change detail."],
      "changes": [
        {"path": "src/example.py", "hunks": "all"},
        {"path": "tests/test_example.py", "hunks": {"type": "indices", "indices": [1, 2]}},
        {"path": "new.txt", "hunks": {"type": "lines", "start": 1, "end": 8}}
      ]
    }
  ]
}
```

Limits: 1-16 commits; 1-128 changes per commit; 0-32 details; summary <=512 characters; detail <=2,000 characters; path <=4,096 characters.

Selectors:

- `"all"`: whole tracked, binary, metadata-only, rename, or ordinary file diff
- `{"type":"indices","indices":[1]}`: unique positive 1-based regular-diff hunk indices
- `{"type":"lines","start":1,"end":8}`: inclusive positive new-file line range, selected from the zero-context diff

Use line selectors when separate commits must own disjoint changed lines inside one new or added file.

## Atomicity Shape

```json
{"decision":"accept","concerns":[],"rationale":"The snapshot implements one cohesive behavior."}
```

or:

```json
{"decision":"split","concerns":["Behavior A.","Behavior B."],"rationale":"They are independently reversible."}
```

Limits: at most 8 concerns; concern <=512 characters; rationale <=2,000 characters.

## Exit Codes

|Code|Meaning|Action|
|---|---|---|
|0|Success|Parse `result`|
|2|Usage, JSON, plan, coverage, or critic error|Correct bounded model/input data; retry only within workflow limits|
|3|Lock, snapshot, branch, index, or receipt refusal|Preserve state; report exact blocker|
|4|Git, filesystem, cleanup, or unexpected runtime failure|Preserve state and inspect evidence|
|127|Git executable unavailable|Install/fix Git before retrying|

Locks are never broken automatically. A prepared receipt is durable recovery evidence. Re-run `prepare` to recover it under the same branch and index state.
