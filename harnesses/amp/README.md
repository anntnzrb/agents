# Amp harness source

Sync publishes the children of this directory into `~/.config/amp/`, publishes `HARNESS.md` as `~/.config/amp/AGENTS.md`, and publishes `skills/current/` as `~/.config/amp/skills/`. The launcher installs `@ampcode/cli` from npm and publishes the `amp` wrapper.

`settings.json` is the managed user settings file. Sync replaces it on every run, so make durable changes here rather than in the generated home.

## Settings constraints

`settings.json` is the source of truth for what is set. These constraints are not visible from the file:

- `amp.updates.mode` is `warn` because `"auto"` would let Amp replace the sync-managed install, and `"disabled"` would also switch off `amp.runner.autoUpdate.enabled`.
- `amp.runner.autoUpdate.enabled` is deliberate: the launcher resolves a version only when a process starts, so without it a long-lived `amp --no-tui` runner stays on its start build. The runner restarts into a new release only once no thread is running there, keeping its ID, served directories, and flags. Where its installer writes inside a sync-managed npm cache is not yet observed; sync repairs a cache it finds incomplete or mismatched.
- `amp.remoteThreadCreation.enabled` makes each interactive TUI a runner, and it holds the per-directory lock under `~/.cache/amp/pids/`: a `--no-tui` runner started in the same directory exits 1 with `Another Amp process is already serving remote threads for <dir> (pid N)`. See [Runner services](#runner-services).
- `amp.keymap` binds bare `ctrl+c` to `prompt.clear`, which requires `ctrl+c` to start no chord: the keymap resolves longest match first, so a surviving `ctrl+c …` chord puts `ctrl+c` into chord-pending mode and the bare binding never fires (symptom: a "next shortcut" prompt and an untouched composer). Rebinding `amp.quit` is what drops the default `ctrl+c ctrl+n` and `ctrl+c ctrl+e` chords; give those `<leader>` chords if wanted back, never `ctrl+c` ones.
- `amp.tools.disable` is cost control: Amp bills non-model tools separately from model usage. Use bare tool names so the ban also covers an MCP tool of the same name; prefix with `builtin:` to ban only Amp's built-in tool. Web research stays available through the repository's skills or `curl`.

`amp.defaultVisibility` is deliberately absent: the CLI rejects it outside an Enterprise workspace (`Default visibility is only configurable in enterprise workspaces`). Without a workspace, threads are private by default; in a workspace, the default for workspace-owned projects comes from workspace settings.

Amp-native skill directories (`~/.agents/skills/`, `.agents/skills/`), the personal and workspace skill and plugin repositories, and stored remote MCP servers are outside `settings.json`; manage those from personal and workspace settings on ampcode.com.

The adapter also passes `--remote-control-terminal` as a launcher default argument, which enables the app's Terminal pane for threads this instance hosts. Sync renders default arguments before caller arguments, so `amp --no-remote-control-terminal` overrides it for a single run. The flag grants shell access to anyone who can view the thread; Amp threads are private by default.

## Runner services

A runner serves its own working directory plus every `--dir` and every checkout `--discover-dirs` finds. Only the working directory is exclusive, so start a long-lived runner from a neutral directory — one no interactive instance occupies — and add the wanted directories explicitly. A runner whose working directory is already served exits immediately, and a supervisor that restarts it on failure turns that into a crash loop; an occupied `--dir` costs nothing.

`--discover-dirs` serves Git checkouts beneath a directory and skips hidden directories, so the SSOT checkout at `~/.config/agents` needs an explicit `--dir`.

Amp reads `settings.json` or `settings.jsonc`. Sync writes `settings.json`; a `settings.jsonc` in the generated home is unmanaged and its precedence is undocumented.
