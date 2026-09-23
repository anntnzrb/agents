# Claude Code harness source

Sync publishes the children of this directory into `~/.claude/`, publishes `HARNESS.md` as `~/.claude/CLAUDE.md`, and publishes `skills/current/` as `~/.claude/skills/`. The launcher installs `@anthropic-ai/claude-code` from npm and publishes the `claude` wrapper.

`CLAUDE.md` is deliberate: Claude Code reads `AGENTS.md` only as project instructions (working directory, its ancestors, and subdirectories; v2.1.277+). A user-level `~/.claude/AGENTS.md` is not read, and `AGENTS.local.md` is never read. `~/.claude/CLAUDE.md` is the only documented user-level instruction file.

`settings.json` is the managed user settings file. Sync replaces it on every run, so make durable changes here rather than in the generated home. It is also a CLIProxyAPI endpoint template: sync renders `${CLIPROXY_CLIENT_ORIGIN}` from `tools/cliproxyapi/deployment.json` and publishes the file only while the gateway's `/models` endpoint is ready; otherwise the previous generated file stays in place.

## Managed settings

| Setting | Reason |
| --- | --- |
| `env.ANTHROPIC_BASE_URL: "${CLIPROXY_CLIENT_ORIGIN}"` | Routes every model request through the CLIProxyAPI gateway's Anthropic Messages endpoint. Claude Code appends `/v1/messages`, so it takes the gateway origin, not the `/v1` base URL. Bare Anthropic model IDs such as `claude-opus-5-5` resolve only to the gateway's Claude OAuth credentials; Claude Code recognizes them natively, so pricing and capabilities need no overrides; the 1M context window comes from the `[1m]` model suffix, not from the gateway. Remote Control is unavailable while the base URL is not an Anthropic host. |
| `env.ANTHROPIC_AUTH_TOKEN: "keyless"` | Makes the gateway the credential: the gateway holds the Claude login, so no machine needs `/login`, and a saved claude.ai login is ignored. The gateway accepts any client key; the value only satisfies Claude Code's credential check. Voice dictation is unavailable while it is set, and background tasks use the main model. |
| `env.DISABLE_UPDATES: "1"` | Sync owns the installed version: it installs the newest npm release on every launch. Blocks Claude Code's background updater and the manual `claude update` and `claude install`, so nothing but sync replaces the install. Stricter than `DISABLE_AUTOUPDATER`. |
| `env.CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL: "1"` | Stops Claude Code registering (cloning) the official plugin marketplace into `~/.claude/plugins/` on its own. Add marketplaces deliberately with `/plugin`. |
| `env.CLAUDE_CODE_IDE_SKIP_AUTO_INSTALL: "1"` | Stops Claude Code installing its extension into VS Code or JetBrains when launched from their terminals. |
| `env.CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR: "1"` | Returns Bash to the project directory after every command, so a `cd` in one command cannot make later commands run in the wrong place. |
| `env.CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY: "20"` | Runs up to 20 read-only tools and subagents in parallel instead of 10. More throughput per turn at the same token cost; uses more local CPU and can reach rate limits sooner. |
| `model: "opus[1m]"` | Default model for new sessions: Opus with the 1M context window. Plain `opus` through the gateway gets 200k. |
| `modelSettings` | Per-model settings keyed by canonical model ID; `effortLevel` sets that model's default reasoning effort. |
| `theme: "dark"` | Interface theme, tracked here rather than left to `/config`. |
| `permissions.defaultMode: "bypassPermissions"` | Sessions start in bypass mode, the same as `--dangerously-skip-permissions`, but also for sessions not started through the wrapper (IDE, desktop). Honored only in user or managed settings since v2.1.257, never from a repository's `.claude/settings.json`. |
| `skipDangerousModePermissionPrompt: true` | Skips the bypass-mode confirmation dialog. Claude Code writes this key itself after the dialog is accepted once; tracking it here keeps sync from resetting it. |
| `syncClaudeAiSkills: false` | Stops Claude Code downloading the claude.ai account's skills into `~/.claude/skills/synced/`. Skills come only from `skills/current/` in this repository; sync prunes anything else under `~/.claude/skills/`. |
| `syncClaudeAiPlugins: false` | Stops Claude Code downloading the claude.ai account's plugins into `~/.claude/plugins/synced/`. |
| `allowedMcpServers: []` | Blocks every MCP server not listed here, wherever it is defined: `~/.claude.json`, a project's `.mcp.json`, plugins, `--mcp-config`, and claude.ai. Built-in servers (Claude in Chrome, the IDE server) are exempt. To use an MCP server, define it and allowlist it from this repository. This is a setting rather than the `--strict-mcp-config` flag because wrapper default arguments precede subcommands, and `claude --strict-mcp-config mcp list` runs `mcp list` as a prompt instead of the subcommand. Allowlist entries merge across settings files, so a repository's `.claude/settings.json` can still add to it. |
| `disableClaudeAiConnectors: true` | Stops Claude Code fetching and connecting the MCP connectors configured on claude.ai. |
| `autoMemoryEnabled: false` | Stops Claude writing its own memory files under `~/.claude/projects/<project>/memory/` and loading them into context. Instructions come from `HARNESS.md`, project files, and skills only. |
| `attribution.commit: ""` | Keeps the `Co-Authored-By: Claude …` trailer out of commits so history follows this repository's `<harness>: ...` convention. |
| `attribution.pr: ""` | Keeps the generated-by line out of pull request descriptions. |
| `attribution.sessionUrl: false` | Drops the session link from commits and pull requests. |

## Deliberately unset

- `promptCacheTtl`: on a Claude subscription within included usage, the main conversation already gets the one-hour cache. Setting `"1h"` only changes paid overage, where it keeps the more expensive one-hour cache writes.
- `DISABLE_TELEMETRY`, `DO_NOT_TRACK`, `DISABLE_GROWTHBOOK`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`: each stops Claude Code fetching feature flags, which turns off reading project `AGENTS.md`, Remote Control, and the advisor tool.
- `fastMode`: faster output at a higher cost per token.
- `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`: strips credentials from Bash, which breaks skills that read API keys from the environment.

## Model and effort

`model` and `modelSettings` (per-model `effortLevel`) are managed here like every other key. Sync writes this file verbatim and keeps nothing from the generated one, so a `/model` or `/effort` choice lasts only until the next sync; change it here to make it stick.

## Third-party content

Nothing outside this repository should add skills, plugins, or MCP servers. The settings above cover what user settings can control. Two stronger locks exist only in machine-wide managed settings (`/Library/Application Support/ClaudeCode/managed-settings.json` on macOS, root-owned) and are not set: `strictKnownMarketplaces: []` blocks adding any plugin marketplace, and `blockedMarketplaces` blocks specific ones.

## Unmanaged state

Sync writes only the entries present in this directory, plus `CLAUDE.md` and `skills/`. It never touches:

- `~/.claude.json` (outside `~/.claude/`): sign-in, per-project trust, user-scope MCP servers, and global config keys such as `autoConnectIde`
- credentials: the macOS Keychain, or `~/.claude/.credentials.json` on Linux
- runtime directories: `projects/`, `sessions/`, `history.jsonl`, `plugins/`, `file-history/`, `backups/`, `cache/`, and the rest

Do not add any of these to this directory.

## Known side effects outside the runtime

- Answering "Yes, and don't ask again" in a repository writes `.claude/settings.local.json` there, and Claude Code adds `**/.claude/settings.local.json` to the global git excludes file (`core.excludesFile`, otherwise `~/.config/git/ignore`) when the repository does not already ignore it. No setting disables this.
