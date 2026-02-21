# rust-script Fallback (Stable Path)

Use this only when user cannot use nightly `cargo -Zscript`.

## What it is

- Crate: `rust-script`
- Maintained successor lineage from older `cargo-script`
- Runs Rust scripts with doc-comment embedded cargo manifest and caching

## Typical commands

```sh
rust-script script.rs
rust-script --test script.rs
rust-script --force script.rs
rust-script --clear-cache
rust-script -e '1 + 1'
rust-script -l '|line| line.to_uppercase()'
```

## Embedded deps pattern

```rust
#!/usr/bin/env rust-script
//! ```cargo
//! [dependencies]
//! serde = { version = "1", features = ["derive"] }
//! ```

fn main() {
    println!("ok");
}
```

## Tradeoffs vs Cargo-native scripts

Pros:
- stable toolchain workflow
- simple one-binary install UX

Cons:
- not the official Cargo-native script path
- semantics differ from Cargo-native `-Zscript` behavior
- migration needed later if user standardizes on Cargo-native mode

## Migration hint

From `rust-script` to Cargo-native script:
- switch shebang to `cargo -Zscript` (or `cargo +nightly -Zscript` when using rustup selector workflow)
- migrate manifest to frontmatter (`---cargo` block)
- replace `rust-script`-specific env assumptions with standard Cargo script behavior

## Live project links

- crate: `https://crates.io/crates/rust-script`
- repo: `https://github.com/fornwall/rust-script`
- historical predecessor: `https://crates.io/crates/cargo-script`
