# GitHub CLI extensions and agent surfaces

**Covers:** `extension`, `agent-task`, `skill`, `copilot`, aliases, completion, and
preview-only tooling.

**Safe default:** discover installed capabilities read-only, inspect publisher/source
and version, and use noninteractive help. Treat preview/third-party surfaces as
version-sensitive and optional.

**Write boundary:** extension install/upgrade/remove, task submission/cancellation,
skill installation, Copilot/account configuration, alias/config changes, and
completion installation are mutations. Require explicit authorization. Never expose
tokens, prompts, private task content, or account data.

**Adjacent handoff:** use `core.md` for auth/config/output/exit rules, `stack-commands.md`
for stack capability gates, `skill-creator` for authoring/validating local agent
skills, and `go`/`do` for delegation rather than `gh agent-task` unless explicitly
requested.

## Capability discovery

Before invoking a third-party or focused surface, inspect what is installed:

```text
gh extension list
gh skill list
```

These are read-only discovery commands. Do not auto-install, upgrade, remove, or
select a publisher based only on a command name. Check repository owner, release/tag
or commit pin, version, permissions, and whether the surface is preview. If `gh skill
list` is unavailable, use `gh help skill` and report that the capability cannot be
verified; do not invent its output.

The installed environment may auto-install an extension when a missing command's help
is requested. In particular, do not use `gh stack --help` as a harmless probe: check
`gh extension list` first and use explicit installation policy instead.

## Extensions

`gh extension list`, `search`, and `view` are discovery/read operations when supported.
Install only after explicit authorization:

```text
gh extension install OWNER/REPO [--pin TAG_OR_COMMIT]
```

Prefer a reviewed immutable tag/commit pin. Treat publisher/repository ownership,
requested permissions, release provenance, and local installation path as part of
the authorization decision. `gh extension upgrade`, `remove`, and `uninstall` alter
local tooling; inspect current version and dependents first. Re-run `gh extension
list` after an authorized change and report the installed version.

An extension can execute arbitrary local code and may perform remote writes. Do not
pipe credentials or secrets to it. Read its installed `gh <extension> --help` only
after discovery and authorization if it could trigger setup; do not assume help is
side-effect-free for missing commands.

## `gh agent-task`, `gh skill`, and Copilot

- `gh agent-task` is a task/orchestration surface whose flags, availability, and
  account permissions may change. Inspect `gh help agent-task` only when the command
  is present; separate task creation, cancellation, and result reads. Creation or
  cancellation needs explicit authorization. Use `go`/`do` for local delegation by
  default.
- `gh skill` is preview/subject-to-change where the installed manual says so. List
  installed skills before invoking one; do not install or trust a skill from an
  unreviewed publisher. Route local skill creation, structure validation, evals, and
  packaging to `skill-creator`, not to a recursive implementation here.
- `gh copilot` is preview/subject-to-change where the installed manual says so and
  may send repository or prompt content to a remote service. Inspect `gh help
  copilot`, account scope, privacy, and billing/permission implications before use.
  Do not send secrets, private prompts, or unapproved source. Treat configuration and
  account changes as writes.

A missing command, preview 404, or denied permission is an availability result. Do
not silently substitute a different agent, install an extension, or claim equivalent
behavior.

## Aliases and completion

`gh alias list` and `gh completion -s SHELL` print local read/output. `gh alias set`,
`gh alias delete`, and installing/sourcing completion scripts change local shell or
CLI behavior. Require authorization and keep generated output separate from command
execution. Aliases can hide mutations; expand and inspect them before relying on one
in a plan.

## Failure handling

Preserve local configuration and installed versions after a failed extension/task
operation. Re-read discovery state and command exit. Never auto-upgrade, remove a
partially installed extension, retry a task, or switch providers to hide an error.

## Official references

- [gh extension](https://cli.github.com/manual/gh_extension)
- [gh agent-task](https://cli.github.com/manual/gh_agent-task)
- [gh skill](https://cli.github.com/manual/gh_skill)
- [gh copilot](https://cli.github.com/manual/gh_copilot)
- [gh alias](https://cli.github.com/manual/gh_alias)
- [gh completion](https://cli.github.com/manual/gh_completion)
