# GitHub CLI core behavior

**Covers:** invocation, target selection, hosts, authentication, environment, output,
configuration, prompts, aliases, completion, help, and exit handling.

**Safe default:** read-only, explicit target, noninteractive, structured output, and
credentials supplied only by the user's already-configured auth environment.

**Write boundary:** any remote mutation, account change, push, merge, extension
install, or credential change needs explicit user authorization immediately before it.
After an authorized write, re-read the affected resource.

**Adjacent handoff:** route command-family details to the family references from
`SKILL.md`; route custom HTTP work to `api.md`.

## Invocation and target

The general shape is:

```text
gh <command> [<subcommand> ...] [flags]
```

- Use an explicit `[HOST/]OWNER/REPO` with `--repo` whenever the command supports it
- A verified local checkout may supply repository context, but confirm its remote and
  host first; a directory name is not a repository identity.
- Use `--hostname <host>` for commands that expose host selection. For `gh api`, the
  endpoint's `{owner}` and `{repo}` placeholders resolve from the selected repository.
- `GH_HOST` sets the default GitHub Enterprise host. `GH_REPO` supplies a default
  repository in `HOST/OWNER/REPO` form. Set either only when the value is known and
  safe for this operation; explicit flags are easier to audit.
- For multiple remotes, inspect them and select the intended remote/host explicitly
  Never infer the write target from whichever remote appears first.

Read-only preflight for a live request:

```text
gh --version
gh auth status
# If a target is known:
gh repo view [HOST/]OWNER/REPO --json nameWithOwner,url,defaultBranchRef
```

Use `gh auth status --hostname <host>` when the host is known. Do not make a login,
logout, token refresh, protocol change, or account switch part of an unrequested task.

## Authentication and secrets

- `gh auth status` reports accounts and host health. An auth problem is evidence to
  report, not a reason to print or solicit a token in a command example.
- Scripting environments can use `GH_TOKEN` or `GITHUB_TOKEN` for `github.com`; use
  `GH_ENTERPRISE_TOKEN` for a GitHub Enterprise host. Let the configured auth chain
  choose precedence; do not duplicate secrets into command-line arguments.
- Never put tokens in `--header`, `--raw-field`, URLs, shell history, prompts, logs,
  eval fixtures, saved transcripts, or generated artifacts.
- `GH_PROMPT_DISABLED=1` makes missing prompts fail instead of blocking. Use it for
  automation and verification. It does not authorize a write or make a command safe.

## Interaction controls

Treat these as side effects, not ordinary reads:

- `--web`, `gh browse`, and flags that open a browser;
- editor prompts and interactive issue/PR forms;
- pagers and colorized/TUI output;
- commands that wait for user input or attach to a live terminal

Prefer command flags for complete noninteractive input. Set `GH_EDITOR`, `GIT_EDITOR`,
`VISUAL`, or `EDITOR` only when the user explicitly wants an editor; use `GH_BROWSER`
or `BROWSER` only when a browser launch is intended. Set `GH_PAGER` or `PAGER` to a
known noninteractive choice for scripts. Preserve the user's environment; do not
silently disable their normal UI in an interactive task.

## Output and parsing

Prefer structured output in this order:

1. `--json <fields>` on commands that support it;
2. `--jq '<filter>'` to select or reshape JSON;
3. `--template '<go-template>'` for a stable text rendering

Discover fields with `--json` without a field list, then request only the fields the
task needs. Parse stdout as data and stderr as diagnostics. Do not use human tables,
colors, URLs opened by a browser, or log text as a machine-readable contract.

For `gh api`, use `--jq` or `--template` at the CLI boundary when only selected values
are needed. Use `--include` only when headers/status are part of the question; use
`--verbose` only for a deliberately authorized diagnostic because it can expose
request details.

Read `gh help formatting` for jq functions and Go-template helpers when a command's
reference does not settle the syntax.

## Help, aliases, config, completion

- Use `gh help <command>` as the installed CLI's authoritative flag lookup when this
  skill or an on-demand reference may have drifted.
- Use `gh help formatting` for JSON/jq/template behavior and `gh help exit-codes`
  for general exit semantics. `gh help environment` documents environment variables.
- `gh alias list` is read-only discovery. Treat `gh alias set` and `gh alias delete`
  as local configuration writes; require authorization before changing aliases.
- `gh config list` is read-only. `gh config set` changes local behavior; require
  authorization and record the changed key/value without exposing credentials.
- `gh completion -s <shell>` prints completion scripts. Do not install or source one
  as a side effect unless requested; inspect output separately from stderr.

## Exit codes and failure handling

The documented general codes are:

|Code|Meaning|Handling|
|---:|---|---|
|`0`|Success|Parse the promised stdout and re-read after writes|
|`1`|Failure|Preserve stderr/state; inspect command-specific help|
|`2`|User cancellation|Treat as no-op/cancelled, not as permission to retry|
|`4`|Authentication required|Report target/host auth blocker without revealing secrets|

Subcommands may add meanings. Check the command reference and installed help before
interpreting a nonzero result. A partial response, timeout, 404, or conflict is
state to inspect. Do not force, retry a mutation, switch repositories, or fall back
to another command family without evidence and authorization.

## Read-before-write / re-read-after-write

Before a remote write, capture enough read-only state to identify the target, current
revision/status, permissions, and relevant parent object. State the exact mutation,
its target, and expected effect; obtain authorization at that boundary. Afterward,
re-read the resource with structured fields and report the resulting URL/number/state.
If the write fails or is interrupted, preserve the response and do not assume it was
rolled back.

## Authoritative manuals

- [CLI manual](https://cli.github.com/manual/gh)
- [Environment variables](https://cli.github.com/manual/gh_help_environment)
- [Formatting](https://cli.github.com/manual/gh_help_formatting)
- [Exit codes](https://cli.github.com/manual/gh_help_exit-codes)
- [Configuration](https://cli.github.com/manual/gh_config)
