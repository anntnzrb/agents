---
name: github
description: Use GitHub CLI (`gh`) for repositories, issues, pull requests, Actions, releases, APIs, extensions, and stacked PRs.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

---

# GitHub CLI

Use this skill when the task names `gh`, GitHub CLI, a GitHub remote surface, or
stacked pull requests. Route to the smallest reference that owns the command family.

## Preflight live operations

1. Run `gh --version` before relying on installed command capabilities.
2. Establish the target with an explicit `[HOST/]OWNER/REPO` for `--repo`, or verify
   the local repository and its remote. Do not guess from the current directory.
3. Check `gh auth status` for the selected host. Use `GH_HOST` or `GH_REPO` only when
   their values are known, safe, and intentional. Use `gh help <command>` for flags
   missing from a reference or when the installed version may differ.
4. Keep read stdout separate from stderr. Prefer `--json <fields>`, then `--jq` or
   `--template`; discover fields with the command's bare `--json` form.

## Safety gates

- Treat `--web`, `browse`, browser/editor/pager launches, prompts, and TUI commands
  as interactive side effects. Prefer noninteractive flags and state user actions.
- Require explicit user authorization immediately before external writes: issues,
  pull requests, projects, repositories, secrets, variables, releases, API
  mutations, pushes, merges, extension installs, and account changes.
- Never print, persist, or echo tokens, credentials, key material, or auth headers.
- After every authorized write, re-read the resulting resource and report failures.
- Route `gh api` through `references/api.md`. Parameters can switch its default GET
  to POST; make method and mutation intent explicit.
- Interpret documented exit codes and command-specific failures as evidence. Do not
  retry destructively, force, prune, merge, or fall back silently after a failure.

## Route by intent

| Intent | Read next | Handoff |
| --- | --- | --- |
| Shared invocation, auth, output, config, prompts, exits | `references/core.md` | Use before any family when unsure |
| Repository, browse, search, gist, org, Codespaces | `references/repositories.md` | Keep local Git/worktree actions local |
| Issue, PR, discussion, project, review, label | `references/collaboration.md` | Ordinary contribution policy → `gh-contrib` |
| Actions, workflow, cache, secret, variable | `references/automation.md` | Keep account and repository writes gated |
| Release, attestation, ruleset, key, license | `references/release-security.md` | Preserve key and permission boundaries |
| REST, GraphQL, pagination, custom endpoint | `references/api.md` | Use `gh api` only with explicit target/method |
| Extension, agent task, skill, Copilot, preview | `references/agent-platform.md` | Check installed capability before invoking |
| Dependent stacked PR chain design | `references/stack-design.md` | Worktree/staging/contribution handoffs apply |
| Branch/PR-to-stack handoff | `references/stacked-pr-workflow.md` | Publishing a branch, creating a PR, or linking a PR to a stack |
| `gh stack` execution or integration | `references/stack-commands.md` | Use installed help and current docs |
| Stack failure, divergence, lock, recovery | `references/stack-troubleshooting.md` | Preserve state; never auto-repair |

## Stacked PR boundary

Route explicit stack intent to all three stack references before branch or PR mutation.
If the focused `github/gh-stack` agent skill is installed and active, defer to it;
otherwise use the local references. Check `gh extension list` and `gh skill list`;
never auto-install either. A missing capability, 404, or stack exit 9 is an
availability/rollout failure, not permission to silently use ordinary PR commands.

Preserve specialist ownership: `git-worktrees` owns worktree lifecycle, `commit`
owns staging and history, `gh-contrib` owns contribution policy and ordinary PR
review, `hunk` owns Hunk sessions, and `go`/`do` own delegation. This skill owns
GitHub CLI routing and stack-specific remote state only.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Shared invocation, hosts, auth, aliases, config, completion, output, prompts, and exits | `references/core.md` | Before any `gh` command family when the router rules are insufficient |
| Repositories, browsing, search, gists, organizations, and codespaces | `references/repositories.md` | Repository discovery, cloning, browsing, search, gist, org, or Codespaces work |
| Issues, pull requests, discussions, projects, and labels | `references/collaboration.md` | Any collaboration object, review, project, or label workflow |
| Actions, workflows, caches, secrets, and variables | `references/automation.md` | CI, workflow dispatch, cache, secret, or variable work |
| Releases, attestations, rulesets, keys, and licenses | `references/release-security.md` | Release, artifact-attestation, repository-rules, key, or license work |
| REST, GraphQL, pagination, previews, and custom endpoints | `references/api.md` | `gh api` or an API surface not covered by a command |
| Stack invariants, layer design, and ownership | `references/stack-design.md` | Planning a dependent-PR chain or deciding whether work belongs in one stack |
| Branch/PR-to-stack handoff | `references/stacked-pr-workflow.md` | Publishing a branch, creating a PR, or linking a PR to a stack |
| `gh stack` commands, capability gates, merge/API semantics, and CI state | `references/stack-commands.md` | Executing or planning any stack command or stack-aware integration |
| Stack conflicts, divergence, locks, interop, and recovery | `references/stack-troubleshooting.md` | A stack operation fails, partially lands, diverges, or uses another local manager |
| Extensions, agent tasks, skills, Copilot, and preview surfaces | `references/agent-platform.md` | `gh extension`, `gh agent-task`, `gh skill`, `gh copilot`, or preview-only tooling |
