# Cargo Script Contracts and Verification

Read this reference when creating or validating a Cargo-native script.

## Minimal Working Patterns

### Pattern A: run by path

```sh
<CARGO_SCRIPT_CMD> ./hello.rs
```

### Pattern B: embedded manifest script

```rust
---cargo
[package]
edition = "2024"

[dependencies]
anyhow = "1"
---

fn main() {
    println!("ok");
}
```

### Pattern C: command on script manifest

```sh
<CARGO_SCRIPT_CMD> check --manifest-path ./tool.rs
<CARGO_SCRIPT_CMD> test --manifest-path ./tool.rs
<CARGO_SCRIPT_CMD> add --manifest-path ./tool.rs clap --features derive
<CARGO_SCRIPT_CMD> remove --manifest-path ./tool.rs clap
```

## Frontmatter Contract

Accepted shape:

- optional blank lines
- opening fence: `---` (or more dashes)
- optional infostring: `cargo` (or empty)
- TOML body
- closing fence with matching dash count

Rejected:

- mismatched fence dash count
- unsupported infostring attributes
- multiple frontmatter blocks
- disallowed manifest fields for single-file packages

If a frontmatter parse error appears, inspect fence integrity first.

## Verification Checklist

For new script setups, verify:

```sh
<CARGO_SCRIPT_CMD> check --manifest-path ./script.rs
<CARGO_SCRIPT_CMD> run --manifest-path ./script.rs -- --help
<CARGO_SCRIPT_CMD> tree --manifest-path ./script.rs
```

For dependency editing:

```sh
<CARGO_SCRIPT_CMD> add --manifest-path ./script.rs serde --features derive
<CARGO_SCRIPT_CMD> remove --manifest-path ./script.rs serde
```

## Primary Sources

- Cargo unstable docs (`-Zscript`):
  `https://doc.rust-lang.org/nightly/cargo/reference/unstable.html#script`
- Tracking issue:
  `https://github.com/rust-lang/cargo/issues/12207`
- RFCs:
  `https://github.com/rust-lang/rfcs/blob/master/text/3502-cargo-script.md`
  `https://github.com/rust-lang/rfcs/blob/master/text/3503-frontmatter.md`
