---
disable-model-invocation: true
name: mole
description: "Use when the user asks to run Mole's mo CLI for macOS cleanup, analysis, history, status, or dry runs."
license: AGPL-3.0-or-later
---

# Using Mole from an agent

Mole (`mo`) cleans, uninstalls, analyzes, optimizes, and monitors a Mac. It is a real deletion tool on a live machine: NEVER guess, let a TUI decide, or run a destructive command before the user sees its candidate list.

## Safety rules

- MUST preview every destructive command with `--dry-run`: run it, read the result, show the user what would be removed, then offer the real command. NEVER run the real command first; the preview is the user's veto.
- The user runs destructive commands unless they explicitly request execution in the current turn. “Clean my Mac” is an explicit request; “why is my disk full” is not.
- NEVER parse a TUI frame. Interactive `mo analyze` and terminal-attached `mo status` are full-screen Go programs whose output is drawn, not printed. Use `mo analyze --json`, `mo status --json`, or `mo status --watch`.
- NEVER invent flags. For anything not listed here, run `mo <command> --help`; do not assume `--yes` or `--force` exists.
- Protection is a whitelist, not an argument. To keep a cache, use `mo clean --whitelist`; NEVER use hand-rolled `find` or raw `rm` to bypass Mole's safety layer.

## Question → command

- “What is eating my disk?” → `mo analyze --json` (whole disk) or `mo analyze <path> --json`
- “Free up space” → `mo clean --dry-run`, review, then `mo clean`
- “Remove this app completely” → `mo uninstall --dry-run`, then `mo uninstall`
- “My Mac feels slow” / broken-looking caches → `mo optimize --dry-run`, then `mo optimize`
- “Clean up my old projects” → `mo purge --dry-run`, then `mo purge`
- “Get rid of downloaded installers” → `mo installer --dry-run`, then `mo installer`
- “What did Mole delete?” → `mo history --json --limit 20`
- One CPU, memory, disk, or network snapshot → `mo status --json`
- Short diagnostic time series → `mo status --watch --interval 1s` (NDJSON; stop after enough samples)

## Agent-facing machine-readable API

Everything else is for humans.

**Disk usage**

`mo analyze --json` prints one JSON object with `path`, `overview`, and `entries[]`; each entry has `name`, `path`, `size`, `is_dir`, and `insight`. `size` is bytes. `insight: true` marks noteworthy entries such as a large iOS backup or runaway cache. Pass a path to scope analysis, e.g. `mo analyze ~/Library --json`.

**Cleanup history**

`mo history --json [--limit N]`, with N from 1-200, prints `logs` (paths to operation and deletion logs) and `sessions[]` containing `command`, `started_at`, `items`, `size`, and `actions` broken down into removed, trashed, skipped, and failed. Use the deletions log paths to answer whether Mole deleted a file; do not guess.

**Dry-run candidate paths**

`mo clean --dry-run` prints a terminal summary and writes every candidate path to `~/.config/mole/clean-list.txt`. Read that file; not terminal output; to reason about or show the exact paths a real clean would remove. This file is clean-only: `mo purge --dry-run` and `mo installer --dry-run` print candidates in the terminal and write no file.

**System status**

`mo status --json` prints one metrics snapshot and automatically selects JSON when stdout is not a TTY; pass `--json` explicitly in scripts. `mo status --watch --interval 1s` emits one complete JSON object per line from a warm collector. Bound watch duration or sample count, then terminate it after collecting the evidence requested; NEVER leave an unbounded monitor running in the background.

## Command notes

- `mo clean` also sweeps leftovers from already-deleted apps, but does not touch installed apps; use `mo uninstall` for those.
- `mo clean --external <path>` cleans macOS metadata from an external volume.
- `mo purge` removes rebuildable project artifacts: `target/`, `build/`, `dist/`, `.next/`. It deliberately does not touch network-restored directories: `node_modules/`, `Pods/`, `venv/`; local rebuild therefore recovers a purge. `mo purge --paths` configures scanned directories; `--include-empty` shows zero-size candidates.
- `mo optimize` refreshes caches and system services. It is the one destructive command whose effects are not simply files disappearing; explain its effects before running it.
- `mo update` self-updates; `mo update --nightly` installs unreleased `main`. Do not run either on a user's behalf without an explicit request.
- `--debug` on any command prints the detailed operation log. Use it when a command silently did nothing; do not enable it normally.

## Failure and recovery

`mo clean` deletions are permanent by default: cache cleanup removes files instead of moving them to Trash, so there is usually nothing to restore. The dry-run is the undo. `mo uninstall` is the exception: it routes the app and leftovers through Trash, making an uninstalled app recoverable until Trash is emptied.

`mo history --json` identifies the deletions log. Each deletion is one tab-separated line: timestamp, mode, size, status, path. If a user asks whether Mole took a file, read the actual line and answer from it. Then add the path to the whitelist with `mo clean --whitelist` so the next run leaves it alone.
