# OpenCode plugins

## CLIProxyAPI model variants

`cliproxy.ts` creates variants from the ordered reasoning efforts in the shared model catalog. Unknown effort names pass through unchanged. The `max` variant maps to the last advertised effort. Model options and variants in `opencode.jsonc` override generated values.

`opencode.jsonc` assigns the `high` variant to `build` and the portable `max` variant to `general` and `explore`.

## Manual continuation

`tmap.ts` changes a single-period, text-only user turn to `Continue.`. It hides the synthetic text in the TUI and adds a system-priority notice that tells the model to resume unfinished work.
