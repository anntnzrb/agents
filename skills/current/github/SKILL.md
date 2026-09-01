---
disable-model-invocation: true
name: github
description: "Use when GitHub CLI, repositories, issues, pull requests, Actions, releases, APIs, or stacked PRs are involved."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# GitHub CLI

Use when a task names `gh`, GitHub CLI, a GitHub remote surface, or stacked pull requests. Route to the smallest owning reference.

## Preflight live operations

1. Run `gh --version` before relying on installed capabilities.
2. Establish the target with explicit `[HOST/]OWNER/REPO` for `--repo`, or verify the local repository and remote. NEVER guess from the current directory.
3. Check `gh auth status` for the selected host. Use `GH_HOST` or `GH_REPO` only when values are known, safe, and intentional. Use `gh help <command>` for missing flags or version differences.
4. Separate read stdout from stderr. Prefer `--json <fields>`, then `--jq` or `--template`; discover fields with the command's bare `--json` form.

## Safety gates

- Treat `--web`, `browse`, browser/editor/pager launches, prompts, and TUI commands as interactive side effects. Prefer noninteractive flags and state user actions.
- Require explicit user authorization immediately before external writes to issues, pull requests, projects, repositories, secrets, variables, releases, API mutations, pushes, merges, extension installs, or account changes.
- NEVER print, persist, or echo tokens, credentials, key material, or auth headers.
- After every authorized write, re-read the resulting resource and report failures.
- Route `gh api` through `references/api.md`. Parameters can change its default GET to POST; make method and mutation intent explicit.
- Treat documented exit codes and command-specific failures as evidence. After failure, do not retry destructively, force, prune, merge, or fall back silently.

## Route by intent; required follow-up

Read the listed reference whenever its trigger applies. Use `references/core.md` before any command family when router rules are insufficient.

- Shared invocation, hosts, auth, aliases, config, completion, output, prompts, exits → `references/core.md`.
- Repository discovery, cloning, browsing, search, gists, organizations, or Codespaces → `references/repositories.md`; keep local Git/worktree actions local.
- Issues, pull requests, discussions, projects, reviews, or labels → `references/collaboration.md`; ordinary contribution policy → `gh-contrib`.
- Actions, workflows, caches, secrets, or variables → `references/automation.md`; keep account and repository writes gated.
- Releases, artifact attestations, rulesets, keys, or licenses → `references/release-security.md`; preserve key and permission boundaries.
- REST, GraphQL, pagination, previews, or custom endpoints; any `gh api` surface → `references/api.md`; use `gh api` only with explicit target and method.
- Extensions, agent tasks, skills, Copilot, or preview-only tooling → `references/agent-platform.md`; check installed capability before invoking.
- Planning a dependent-PR chain or deciding whether work belongs in one stack → `references/stack-design.md` for invariants, layer design, and ownership.
- Publishing a branch, creating a PR, or linking a PR to a stack → `references/stacked-pr-workflow.md` for the branch/PR-to-stack handoff.
- Executing or planning `gh stack`, or stack-aware integration → `references/stack-commands.md` for commands, capability gates, merge/API semantics, and CI state.
- Stack failure, partial landing, divergence, lock, interop, or recovery → `references/stack-troubleshooting.md`; preserve state and NEVER auto-repair.

## Stacked PR boundary

For explicit stack intent, read all three stack references (`references/stack-design.md`, `references/stacked-pr-workflow.md`, and `references/stack-commands.md`) before branch or PR mutation. If the focused `github/gh-stack` agent skill is installed and active, defer to it; otherwise use local references. Check `gh extension list` and `gh skill list`; NEVER auto-install either. Missing capability, 404, or stack exit 9 means availability/rollout failure, not permission to silently use ordinary PR commands.

Ownership: `git-worktrees` owns worktree lifecycle; `commit` owns staging and history; `gh-contrib` owns contribution policy and ordinary PR review; `hunk` owns Hunk sessions; `go`/`do` own delegation. This skill owns GitHub CLI routing and stack-specific remote state only.
