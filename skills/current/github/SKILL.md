---
name: github
description: "Use when managing GitHub via gh CLI, issues, PRs, Actions, releases, or stacked PRs; not for contribution guidelines."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# GitHub CLI

Use when a task names `gh`, GitHub CLI, a GitHub remote surface, or stacked pull requests. Route to the smallest owning reference.

This skill supplies command recipes and operating rules. `ship` owns task scope, destination, PR grouping, verification, and delivery sequencing.

## Preflight live operations

1. Run `gh --version` before relying on installed capabilities.
2. Establish the target with explicit `[HOST/]OWNER/REPO` for `--repo`, or verify the local repository and remote. NEVER guess from the current directory.
3. Check `gh auth status` for the selected host. Use `GH_HOST` or `GH_REPO` only when values are known, safe, and intentional. Use `gh help <command>` for missing flags or version differences.
4. Separate read stdout from stderr. Prefer `--json <fields>`, then `--jq` or `--template`; discover fields with the command's bare `--json` form.

## Safety gates

- Treat `--web`, `browse`, browser/editor/pager launches, prompts, and TUI commands as interactive side effects. Prefer noninteractive flags and state user actions.
- Before external writes, confirm that the user's request authorizes the target and operation. Honor scoped authorization already established by `ship`; do not ask again for each necessary command. Ask for writes beyond that scope, required project approvals, and tool installation or upgrades not already authorized.
- NEVER print, persist, or echo tokens, credentials, key material, or auth headers.
- After every authorized write, re-read the resulting resource and report failures.
- Route `gh api` through `references/api.md`. Parameters can change its default GET to POST; make method and mutation intent explicit.
- Treat documented exit codes and command-specific failures as evidence. After failure, do not retry destructively, force, prune, merge, or fall back silently.

## Route by intent; required follow-up

Read the listed reference whenever its trigger applies. Use `references/core.md` before any command family when router rules are insufficient.

| Need | Read | When |
| --- | --- | --- |
| Shared invocation, hosts, auth, aliases, config, completion, output, prompts, exits | `references/core.md` | Any command family the router does not cover |
| Repository discovery, cloning, browsing, search, gists, organizations, or Codespaces | `references/repositories.md` | Remote repository work; keep local Git/worktree actions local |
| Issues, pull requests, discussions, projects, reviews, or labels | `references/collaboration.md` | Collaboration commands |
| Actions, workflows, caches, secrets, or variables | `references/automation.md` | Automation commands; keep account and repository writes gated |
| Releases, artifact attestations, rulesets, keys, or licenses | `references/release-security.md` | Release or security commands; preserve key and permission boundaries |
| REST, GraphQL, pagination, previews, or custom endpoints | `references/api.md` | Any `gh api` surface; use `gh api` only with explicit target and method |
| Extensions, agent tasks, skills, Copilot, or preview-only tooling | `references/agent-platform.md` | Before invoking; check installed capability first |
| Invariants, layer design, and ownership of a dependent-PR chain | `references/stack-design.md` | Planning a chain or deciding whether work belongs in one stack |
| Branch/PR-to-stack handoff | `references/stacked-pr-workflow.md` | Publishing a branch, creating a PR, or linking a PR to a stack |
| Commands, capability gates, merge/API semantics, and CI state | `references/stack-commands.md` | Executing or planning `gh stack`, or stack-aware integration |
| Stack failure, partial landing, divergence, lock, interop, or recovery | `references/stack-troubleshooting.md` | A stack fails; preserve state and NEVER auto-repair |

## Stacked PR boundary

Stacks are optional. Ordinary PRs and ordinary dependent PR chains do not require `gh-stack`, `gh skill`, or native stack association. Suggest native stacks when dependent concerns would benefit from separate reviews. If the extension is absent, recommend official `github/gh-stack` and follow `references/agent-platform.md` for authorized installation; continue ordinary work when stack adoption is not required. Do not install the upstream agent skill into sync-managed homes.

For requested native stacks or known native membership, read `references/stack-design.md`, `references/stacked-pr-workflow.md`, and `references/stack-commands.md` before mutation. Check `gh extension list` before invoking the extension. Missing capability, 404, or stack exit 9 limits that stack operation; it does not block unrelated ordinary PR work. Preserve existing membership and report the unavailable operation instead of silently unstacking or using an ordinary merge.

Ownership: `git-worktrees` owns worktree lifecycle; `autommit` owns staging and history. This skill owns GitHub CLI routing and stack-specific remote state only.
