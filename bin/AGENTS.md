# AGENTS.md

This holds automation scripts used to manage and sync these AI Agent configs. Keep changes here, not in synced tool homes, because sync will overwrite tool-home copies.

## Full gate

- `cargo -Zscript check --manifest-path bin/sync.rs`
- `cargo -Zscript test --manifest-path bin/sync.rs`
- `cargo -Zscript doc --manifest-path bin/sync.rs --no-deps`
