# Amp harness source

Sync publishes the children of this directory into `~/.config/amp/`, publishes `HARNESS.md` as `~/.config/amp/AGENTS.md`, and publishes `skills/current/` as `~/.config/amp/skills/`. The launcher installs `@ampcode/cli` from npm and publishes the `amp` wrapper.

`settings.json` is the managed user settings file. Sync replaces it on every run, so make durable changes here rather than in the generated home.

## Managed settings

| Setting | Reason |
| --- | --- |
| `amp.updates.mode: "warn"` | Sync installs the newest npm release on every launch, so Amp's version is always current. `warn` reports a newer release without letting Amp replace the sync-managed install, which `"auto"` would do. |
| `amp.remoteThreadCreation.enabled: true` | Makes each interactive TUI a runner, so threads can be created in its working directory from the web and desktop apps. Only `amp --no-tui` processes hold the per-directory lock under `~/.cache/amp/pids/`; interactive TUIs do not, so several TUIs can run in one directory. Two `--no-tui` runners in the same directory contend, and the second exits with `Another Amp process is already serving remote threads for <dir>`. The runner ID does not affect this. |
| `amp.git.commit.ampThread.enabled: false` | Keeps the `Amp-Thread-ID:` trailer out of commits so history follows this repository's `<harness>: ...` convention. |
| `amp.git.commit.coauthor.enabled: false` | Keeps the `Co-authored-by: Amp` trailer out of commits. |
| `amp.skills.disableClaudeCodeSkills: true` | Stops Amp loading skills from `.claude/skills/`, `~/.claude/skills/`, and `~/.claude/plugins/cache/`, so only this repository's published skills are in play. |
| `amp.tools.disable` | Cost control. Amp bills non-model tools separately from model usage, and the pricing page names web search explicitly. Web research stays available through the repository's own skills (`firecrawl`, `brave-search`, `omp-search`, `reddit`, `x-research`, `youtube`), which use the owner's credentials, or through `curl` in `shell_command`. |

`amp.defaultVisibility` is deliberately absent: the CLI rejects it outside an Enterprise workspace (`Default visibility is only configurable in enterprise workspaces`). Without a workspace, threads are private by default; in a workspace, the default for workspace-owned projects comes from workspace settings.

Amp-native skill directories (`~/.agents/skills/`, `.agents/skills/`), the personal and workspace skill and plugin repositories, and stored remote MCP servers are outside `settings.json`; manage those from personal and workspace settings on ampcode.com.

The adapter also passes `--remote-control-terminal` as a launcher default argument, which enables the app's Terminal pane for threads this instance hosts. Sync renders default arguments before caller arguments, so `amp --no-remote-control-terminal` overrides it for a single run. The flag grants shell access to anyone who can view the thread; Amp threads are private by default.

Disabled tools:

- `web_search` — the documented non-model tool that consumes Amp credits.
- `read_web_page` — the other Amp-hosted web tool. The docs do not name it as a billable non-model tool, so this is a conservative choice; page content also bills as model input tokens.
- `painter` — paid image generation (GPT Image 2), which is not language-model inference.

Use bare tool names so the ban also covers a tool of the same name provided by an MCP server. Prefix with `builtin:` to ban only Amp's built-in tool and allow an MCP replacement.

Amp reads `settings.json` or `settings.jsonc`. Sync writes `settings.json`; a `settings.jsonc` in the generated home is unmanaged and its precedence is undocumented.
