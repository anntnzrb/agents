# autommit

`/autommit` runs an unattended local atomic commit workflow.

- Plans commits from the staged snapshot with the active Pi session model.
- If nothing is staged, it stages all worktree changes first; when changes are
  already staged, it commits that snapshot as-is and leaves unstaged changes
  untouched.
- Splits the snapshot into independently reversible commits when the planner
  or the atomicity critic decides that is appropriate; otherwise creates a
  single commit.
- Publishes atomically: commits are prepared in a temporary worktree and the
  branch ref is advanced only when the prepared tree matches the staged
  index. A receipt under the Git common directory recovers interrupted runs.
- Partial file selection uses 1-based hunk indices or inclusive new-file line
  ranges.

## Context

Pass free-form context for the planner as positional arguments or with
`--context <text>` (repeatable):

```
/autommit upgrade dependencies --context "keep formatting out of scope"
```

The planner also receives recent commit subjects and the repository's
`AGENTS.md` files as bounded, advisory style and policy evidence. That
evidence is treated as untrusted input and governs commit naming and
grouping only.

## Model

The command uses the active session model and its thinking level.
Provider-side strict JSON-schema tool sampling is used when the provider
supports it; local schema validation with retries remains the authoritative
gate, so models without strict-tool support still work. Nested model usage is
not included in Pi session usage totals.

## Differences from the OMP version

- Uses the active session model instead of a dedicated commit-role model.
- No inter-commit dependency graph or conventional type/scope machinery.
- Repository policy and commit style are discovered locally (`AGENTS.md` plus
  recent commit subjects) rather than through an interactive agent session.
