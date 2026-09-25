# Claude Code harness source

Sync publishes the children of this directory into `~/.claude/`, publishes `HARNESS.md` as `~/.claude/CLAUDE.md`, and publishes `skills/current/` as `~/.claude/skills/`. The launcher installs `@anthropic-ai/claude-code` from npm and publishes the `claude` wrapper.

`CLAUDE.md` is deliberate: Claude Code reads `AGENTS.md` only as project instructions (working directory, its ancestors, and subdirectories; v2.1.277+). A user-level `~/.claude/AGENTS.md` is not read, and `AGENTS.local.md` is never read. `~/.claude/CLAUDE.md` is the only documented user-level instruction file.

`settings.json` is the managed user settings file. Sync replaces it on every run, so make durable changes here rather than in the generated home. It is also a CLIProxyAPI endpoint template: sync renders `${CLIPROXY_CLIENT_ORIGIN}` from `tools/cliproxyapi/deployment.json` and publishes the file only while the gateway's `/models` endpoint is ready; otherwise the previous generated file stays in place.

## Settings constraints

`settings.json` is the source of truth for what is set. These constraints are not visible from the file:

- `env.ANTHROPIC_BASE_URL` takes the gateway origin, not the `/v1` base URL: Claude Code appends `/v1/messages`. Bare Anthropic model IDs resolve only to the gateway's Claude OAuth credentials and need no pricing or capability overrides. Remote Control is unavailable while the base URL is not an Anthropic host.
- `env.ANTHROPIC_AUTH_TOKEN` only satisfies Claude Code's credential check; the gateway holds the Claude login and accepts any key, so no machine needs `/login`. While it is set, voice dictation is unavailable and background tasks use the main model.
- `env.DISABLE_UPDATES` is used instead of `DISABLE_AUTOUPDATER` because it also blocks `claude update` and `claude install`, so nothing but sync replaces the install.
- The 1M context window comes from the `[1m]` model suffix, not from the gateway; plain `opus` through the gateway gets 200k.
- `permissions.defaultMode` is honored only in user or managed settings (v2.1.257+), never from a repository's `.claude/settings.json`.
- `skipDangerousModePermissionPrompt` is written by Claude Code itself once the bypass dialog is accepted; tracking it keeps sync from resetting it.
- `allowedMcpServers` is used instead of `--strict-mcp-config` because wrapper default arguments precede subcommands, so `claude --strict-mcp-config mcp list` would run `mcp list` as a prompt. Built-in servers are exempt, and allowlist entries merge across settings files, so a repository's `.claude/settings.json` can still add to it.

## Deliberately unset

- `promptCacheTtl`: on a Claude subscription within included usage, the main conversation already gets the one-hour cache. Setting `"1h"` only changes paid overage, where it keeps the more expensive one-hour cache writes.
- `DISABLE_TELEMETRY`, `DO_NOT_TRACK`, `DISABLE_GROWTHBOOK`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`: each stops Claude Code fetching feature flags, which turns off reading project `AGENTS.md`, Remote Control, and the advisor tool.
- `fastMode`: faster output at a higher cost per token.
- `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`: strips credentials from Bash, which breaks skills that read API keys from the environment.

## Model and effort

Sync writes `settings.json` verbatim and keeps nothing from the generated one, so a `/model` or `/effort` choice lasts only until the next sync; change `model` or `modelSettings` here to make it stick.

## Third-party content

Nothing outside this repository should add skills, plugins, or MCP servers; `settings.json` covers what user settings can control. Two stronger locks exist only in machine-wide managed settings (`/Library/Application Support/ClaudeCode/managed-settings.json` on macOS, root-owned) and are not set: `strictKnownMarketplaces: []` blocks adding any plugin marketplace, and `blockedMarketplaces` blocks specific ones.

## Unmanaged state

Sync writes only the entries present in this directory, plus `CLAUDE.md` and `skills/`. It never touches:

- `~/.claude.json` (outside `~/.claude/`): sign-in, per-project trust, user-scope MCP servers, and global config keys such as `autoConnectIde`
- credentials: the macOS Keychain, or `~/.claude/.credentials.json` on Linux
- runtime directories: `projects/`, `sessions/`, `history.jsonl`, `plugins/`, `file-history/`, `backups/`, `cache/`, and the rest

Do not add any of these to this directory.

## Known side effects outside the runtime

- Answering "Yes, and don't ask again" in a repository writes `.claude/settings.local.json` there, and Claude Code adds `**/.claude/settings.local.json` to the global git excludes file (`core.excludesFile`, otherwise `~/.config/git/ignore`) when the repository does not already ignore it. No setting disables this.
