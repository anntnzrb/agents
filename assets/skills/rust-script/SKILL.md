---
name: rust-script
description: Expert guide for Cargo single-file Rust scripts (`-Zscript`) and fallback `rust-script` usage. Use when users ask about Rust scripting, shebang scripts, embedded Cargo manifests/frontmatter, `--manifest-path` for script files, command support/limits, migration from Python/TypeScript scripts, or debugging Cargo script errors and stabilization status.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# rust-script

Operate Rust scripting with Cargo-native scripts first, `rust-script` fallback second.

## Default Mode

Use Cargo script mode:

```sh
<CARGO_SCRIPT_CMD> path/to/script.rs -- arg1 arg2
```

Use this for:

- single-file scripts with compile-time guarantees
- shebang executables
- dependency management in embedded manifest frontmatter
- script workflows close to regular Cargo projects

Use `rust-script` only when user explicitly needs stable-only scripting ergonomics.

## Choose `<CARGO_SCRIPT_CMD>`

Set command prefix by toolchain model:

- Rustup-managed toolchains:
  - `CARGO_SCRIPT_CMD='cargo +nightly -Zscript'`
- Nightly cargo already in PATH (common in Nix):
  - `CARGO_SCRIPT_CMD='cargo -Zscript'`

Detection hint:

- if `cargo -Zscript ...` works, prefer it
- if `cargo +nightly` errors with `no such command: +nightly`, do not use `+nightly`

## Fast Decision Tree

1. User asks for Rust scripting + accepts nightly:

- choose `<CARGO_SCRIPT_CMD>`
- prefer frontmatter manifest (`---cargo ... ---`)

2. User wants stable-only and no nightly:

- use `rust-script` fallback
- explain tradeoff vs Cargo-native scripts

3. User asks about publishing/installing script file directly:

- explain current limitation (`package`/`publish` unsupported; `install --path file.rs` unsupported)
- suggest converting to normal package (`cargo new --bin`)

## Core Rules

- Always pass `-Zscript` before script path.
- For extensionless executable scripts, call with path (`./tool`), not bare token (`tool`).
- For script args that look like Cargo flags, use `--` separator when needed.
- Prefer explicit edition in frontmatter to avoid default-edition warning churn.
- Treat Cargo scripts as single-file bin packages, not workspace members.

## Minimal Working Patterns

### Pattern A: run by path

```sh
<CARGO_SCRIPT_CMD> ./hello.rs
```

### Pattern B: shebang script

```rust
#!/usr/bin/env -S cargo -Zscript
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

- optional shebang on first line
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

## Load On Demand

Read references only as needed:

- `references/cargo-script-workflow.md`: end-to-end runbook and command recipes.
- `references/command-support-matrix.md`: supported vs unsupported commands.
- `references/error-catalog.md`: exact error -> fix mappings.
- `references/upstream-status.md`: stabilization/tracking status.
- `references/rust-script-fallback.md`: stable fallback mode (`rust-script` crate).

## Agent Operating Procedure

1. Detect user intent:

- Cargo-native script mode or `rust-script` fallback.

2. Validate command shape:

- `-Zscript` position, path form, `--manifest-path` usage.

3. Apply known limits:

- block unsupported flows early (`package`, `publish`, `install --path file.rs`, path dependency on script).

4. Provide fix-ready command:

- return exact corrected command, no vague advice.

5. If behavior seems new/regressed:

- check `references/upstream-status.md`
- then confirm live state with `gh issue view`.

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
