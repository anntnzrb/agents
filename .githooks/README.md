# Git hooks

These hooks enforce the sync application's local quality gates without an
external hook manager.

Enable them once after cloning:

```sh
git config --local core.hooksPath .githooks
```

The Rust workspace has no local runtime dependency install. Run its checks
directly from the repository root:

```sh
cargo fmt --manifest-path sync/Cargo.toml --all -- --check
cargo clippy --locked --manifest-path sync/Cargo.toml --workspace --all-targets -- --deny warnings
cargo test --locked --manifest-path sync/Cargo.toml --workspace
```

The hooks run these commands automatically. They never rewrite tracked source
files.
