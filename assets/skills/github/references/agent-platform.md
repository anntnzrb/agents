# GitHub CLI extensions and agent surfaces

Scope: `extension`, `agent-task`, `skill`, `copilot`, aliases, completion, preview-only tooling.

Default: discover capabilities read-only; inspect publisher/source and version; use noninteractive help. Preview/third-party surfaces version-sensitive and optional.

Writes: extension install/upgrade/remove/uninstall, task creation/submission/cancellation, skill installation, Copilot/account configuration, alias/config changes, and completion installation/sourcing. MUST have explicit authorization. NEVER expose tokens, prompts, private task content, or account data.

Handoffs: `core.md` for auth/config/output/exit; `stack-commands.md` for stack gates; `skill-creator` for local skill authoring/validation; `go`/`do` for delegation instead of `gh agent-task` unless explicitly requested.

## Discovery

Before invoking a third-party or focused surface, inspect installed capabilities:

```text
gh extension list
gh skill list
```

These commands are read-only. MUST NOT auto-install, upgrade, remove, or select a publisher from a command name alone. Check repository owner, release/tag or commit pin, version, permissions, and preview status. If `gh skill list` is unavailable, use `gh help skill`; report capability unverifiable and do not invent output.

A missing-command help request may auto-install an extension. NEVER use `gh stack --help` as a harmless probe; check `gh extension list` first and follow explicit installation policy.

## Extensions

`gh extension list`, `search`, and `view` are discovery/read operations when supported. Install only with explicit authorization:

```text
gh extension install OWNER/REPO [--pin TAG_OR_COMMIT]
```

Prefer a reviewed immutable tag/commit pin. Authorization must consider publisher/repository ownership, requested permissions, release provenance, and local installation path. Before authorized `gh extension upgrade`, `remove`, or `uninstall`, inspect current version and dependents; afterward rerun `gh extension list` and report installed version.

Extensions can execute arbitrary local code and perform remote writes. NEVER pipe credentials or secrets to one. Read installed `gh <extension> --help` only after discovery and authorization when setup could trigger; do not assume missing-command help is side-effect-free.

## `gh agent-task`, `gh skill`, and Copilot

- `gh agent-task`: flags, availability, and account permissions can change. Inspect `gh help agent-task` only when command is present. Separate task creation, cancellation, and result reads. Creation/cancellation MUST be explicitly authorized; use `go`/`do` for local delegation by default.
- `gh skill`: preview/subject to change as stated by installed manual. List installed skills before invocation. NEVER install or trust a skill from an unreviewed publisher. Route local skill creation, structure validation, evals, and packaging to `skill-creator`, not recursive implementation here.
- `gh copilot`: preview/subject to change as stated by installed manual; may send repository or prompt content remotely. Before use inspect `gh help copilot`, account scope, privacy, billing, and permission implications. NEVER send secrets, private prompts, or unapproved source. Treat configuration/account changes as writes.

Missing command, preview 404, or denied permission: availability result. NEVER silently substitute another agent, install an extension, or claim equivalent behavior.

## Aliases and completion

`gh alias list` and `gh completion -s SHELL` print local read/output. `gh alias set`, `gh alias delete`, and installing/sourcing completion scripts change local shell or CLI behavior: require authorization and keep generated output separate from command execution. Aliases can hide mutations; expand and inspect them before relying on one in a plan.

## Failure handling

After failed extension/task operation, preserve local configuration and installed versions; reread discovery state and command exit. NEVER auto-upgrade, remove a partially installed extension, retry a task, or switch providers to hide an error.

## Official references

- [gh extension](https://cli.github.com/manual/gh_extension)
- [gh agent-task](https://cli.github.com/manual/gh_agent-task)
- [gh skill](https://cli.github.com/manual/gh_skill)
- [gh copilot](https://cli.github.com/manual/gh_copilot)
- [gh alias](https://cli.github.com/manual/gh_alias)
- [gh completion](https://cli.github.com/manual/gh_completion)
