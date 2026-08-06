# GitHub repositories and discovery

**Covers:** `repo`, `browse`, `search repos`, `search code`, `search commits`,
`search issues`, `search prs`, `status`, `org`, `gist`, and `codespace`.

**Safe default:** inspect an explicit repository/host with structured output; keep
local checkout actions and browser opens visibly separate from remote reads.

**Write boundary:** clone creates local state; `repo create`, `repo edit`, `repo
archive`, `repo delete`, gist creation/edit/delete, org membership/settings, and
Codespaces creation/deletion are writes. Require authorization and re-read after
remote writes. Do not delete or archive as a discovery shortcut.

**Adjacent handoff:** use `core.md` for target/auth/output rules; use `git-worktrees`
for worktree lifecycle, `gh-contrib` for contribution policy, and
`collaboration.md` for issues/PRs/projects/labels.

## Repository and local context

Use an explicit target or verified checkout:

```text
gh repo view [HOST/]OWNER/REPO --json nameWithOwner,url,defaultBranchRef,isFork
```

For local context, inspect `git remote -v`, current branch, and worktree state with
read-only Git commands, then bind the intended GitHub repository explicitly. `gh
status --repo [HOST/]OWNER/REPO` summarizes issues, PRs, and notifications for a
repository; it is not a substitute for resource-specific JSON.

- `gh repo clone OWNER/REPO [directory]` writes a local checkout. Do not overwrite a
  directory or choose a worktree location when `git-worktrees` owns that lifecycle.
- `gh repo fork` creates or configures a fork and may clone it; treat both remote and
  local effects as explicit writes.
- `gh repo list OWNER` reads repositories with filters; ask for `--json` fields when
  parsing.
- `gh repo view` reads metadata. `gh repo edit` changes remote metadata and
  `gh repo delete` is destructive; confirm target and authorization immediately
  before either.

## Browse and search

`gh browse` and `gh repo view --web` open a browser. Use them only when the user asks
for a browser workflow; otherwise use a URL field or structured command output.

Search commands are remote reads. Always make scope and target explicit when the
query could cross repositories or hosts:

```text
gh search repos <query> --limit <n> --json fullName,description,url

gh search code <query> --repo OWNER/REPO --limit <n> --json repository,path,url

gh search commits <query> --repo OWNER/REPO --limit <n> --json sha,repository,commit,url

gh search issues <query> --repo OWNER/REPO --limit <n> --json number,title,state,url

gh search prs <query> --repo OWNER/REPO --limit <n> --json number,title,state,url
```

- Search APIs may be eventually consistent, rate-limited, or unavailable for an
  Enterprise host. Report incomplete results and pagination/limit choices.
- `--match`, qualifiers, and state/type filters change the result set; preserve the
  exact query and filters in a report.
- Use `--jq` only after selecting fields; do not parse human search tables.

## Organizations, gists, and Codespaces

- `gh org list` and `gh org view ORG` are reads. Organization creation, membership,
  team, repository, or settings operations are remote writes; inspect permissions
  and use the installed subcommand help before acting.
- `gh gist list`, `gh gist view ID`, and `gh gist rename ID` read or change gists.
  `gh gist create` publishes local content; inspect the exact files and visibility.
  `gh gist edit/delete` are writes, and delete is irreversible from this workflow.
- `gh codespace list --repo OWNER/REPO` and `gh codespace view` inspect Codespaces.
  `gh codespace create` provisions remote compute; `gh codespace ssh`, `code`, or
  `logs` may open an interactive client. `gh codespace stop`, `delete`, and `edit`
  change or destroy remote state; require explicit target and authorization.

Codespaces command availability and flags vary by installed CLI. Use `gh help
codespace <command>` when the reference does not state the required option. Never
copy a token from Codespaces output into a transcript.

## Failure handling

A missing repository, ambiguous host, empty search, permission error, or rate limit
is a reportable result. Re-check target and auth read-only. Do not silently broaden a
search, switch hosts, fork, clone, or open a browser to work around it.

For issue, PR, discussion, project, label, or review objects, read
`collaboration.md`; for CI and workflow state, read `automation.md`; for custom API
surfaces, read `api.md`.

## Official references

- [gh repo](https://cli.github.com/manual/gh_repo)
- [gh browse](https://cli.github.com/manual/gh_browse)
- [gh search](https://cli.github.com/manual/gh_search)
- [gh status](https://cli.github.com/manual/gh_status)
- [gh org](https://cli.github.com/manual/gh_org)
- [gh gist](https://cli.github.com/manual/gh_gist)
- [gh codespace](https://cli.github.com/manual/gh_codespace)
