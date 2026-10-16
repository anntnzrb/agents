# Claude Code harness source

Sync publishes this directory into `~/.claude/`, `HARNESS.md` as `~/.claude/CLAUDE.md`, and `skills/current/` as `~/.claude/skills/`. `settings.json` is the source of truth for what is set; this page lists only the traps and deliberate omissions the file cannot express.

## Traps

- Sync replaces the generated `settings.json` on every run, so a `/model`, `/effort`, or any other in-app change lasts only until the next sync. Change this directory instead. The file is a gateway template: sync renders `${CLIPROXY_CLIENT_ORIGIN}` and skips publishing while the gateway's `/models` endpoint is not ready.
- The instruction file is published as `CLAUDE.md` because Claude Code does not read a user-level `~/.claude/AGENTS.md`.
- `env.ANTHROPIC_BASE_URL` takes the gateway origin, not the `/v1` base URL: Claude Code appends `/v1/messages`.
- `env.ANTHROPIC_AUTH_TOKEN` is a placeholder; the gateway holds the Claude login and accepts any key. Do not run `/login`.
- The 1M context window comes from the `[1m]` model suffix; plain `opus` through the gateway gets 200k.
- `env.ENABLE_TOOL_SEARCH` depends on the gateway passing `tool_reference` through. If MCP tool calls start failing, remove it.
- Every model a subagent names must be in the gateway's `/models` catalog; otherwise the subagent fails with `unknown provider for model`.
- `agents/explore.md` replaces the built-in `Explore` agent so it honors `CLAUDE_CODE_SUBAGENT_MODEL`. The override loses the built-in's CLAUDE.md skipping, so keep `omitClaudeMd` in it.
- `skipDangerousModePermissionPrompt` is written by Claude Code itself; removing it brings the bypass dialog back after the next sync.
- Raising `env.BASH_DEFAULT_TIMEOUT_MS` or `env.BASH_MAX_TIMEOUT_MS` lengthens how long a foreground Bash command blocks the main agent before it moves to the background.
- Claude Code never moves a Bash command whose first word is `sleep` to the background; it stops it at the timeout. The `Bash` `PreToolUse` hook denies those commands for that reason; other forms such as `cd dir; sleep 20` background normally and stay allowed.
- A `Monitor` command must exit on its own: one that never ends, such as `tail -f`, holds the T3 Code thread in Working after the wait is over.
- The `SessionStart` hook omits `resume` on purpose: T3 Code resumes the Claude process after every idle release, model change, or server restart, and the resumed transcript already holds the `t3c` skill.
- The `WebSearch` and `WebFetch` hooks exempt the built-in `claude-code-guide` agent, which cannot load skills.
- Sync never manages `~/.claude.json`, credentials, or runtime directories such as `projects/` and `sessions/`. Do not add them to this directory.

## Deliberately unset

- `permissions.deny` for `WebSearch` or `WebFetch`: it removes the tools outright; the hooks only point to the stronger skills.
- `DISABLE_AUTOUPDATER`: `env.DISABLE_UPDATES` also blocks `claude update` and `claude install`, so only sync replaces the install.
- `CLAUDE_CODE_SUBAGENT_MODEL_FORCE`: it stops the main agent from passing a stronger `model` on an Agent call.
- `promptCacheTtl`: a subscription already gets the one-hour cache for the main conversation; the setting only changes paid overage, where one-hour writes cost more.
- `DISABLE_TELEMETRY`, `DO_NOT_TRACK`, `DISABLE_GROWTHBOOK`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`: each stops feature-flag fetching, which turns off reading project `AGENTS.md`, Remote Control, and the advisor tool.
- `fastMode`: faster output at a higher cost per token.
- `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`: strips credentials from Bash, which breaks skills that read API keys from the environment.
- `allowedMcpServers` and `--strict-mcp-config`: either blocks the server a host such as T3 Code passes with `--mcp-config`, with only a startup warning, so the host's tools silently disappear.
