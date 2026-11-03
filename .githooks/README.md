# Git hooks

These hooks enforce sync quality gates and selected repository checks without
an external hook manager.

Requirements:
- Bun (sync gates)
- `uv` (repository CI scripts)

Enable them once after cloning:

```sh
git config --local core.hooksPath .githooks
```

The hooks run `bun install --frozen-lockfile` in `sync/` on every invocation, so
`sync/node_modules/` follows `sync/bun.lock` without rewriting tracked files.

Local integration into `main` and normal direct pushes follow the
[repository integration policy](../docs/ci.md#integrate-and-publish-a-change).
These hooks validate changes without moving branches or switching worktrees.

Quality gates (`sync/package.json` scripts):
- `pre-commit`: runs `git diff --cached --check`, followed by `bun run check` (TypeScript, Effect diagnostics, Oxlint, Oxfmt check).
- `pre-push`: runs `bun run gates` (the static checks plus `bun test`), then `ci.py local` from the repository root against `origin/main`; see [Run checks locally](../docs/ci.md#run-checks-locally).
- The `autommit` skill runs `pre-commit` once on the full staged snapshot before planning, then creates each commit in a temporary worktree with hooks disabled. The `pre-push` hook still runs.
