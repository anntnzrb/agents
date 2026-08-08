---
name: rust-script
description: Create and debug Cargo single-file Rust scripts, rust-script fallback, and embedded manifests.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

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
- explicit Cargo invocation across supported platforms
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

## Engineering Discipline

- Keep scripts boring: parse external input once, return contextual errors, and add dependencies or abstractions only for a concrete script need.
- Use the standard library for a small script; add `anyhow` for ergonomic contextual errors or `clap` when argument parsing outgrows a few flags.
- Do not add async, a framework, or a production-service stack by default. Use async only for concurrent I/O that benefits from it.
- Treat `unsafe`, FFI, manual `Send`/`Sync`, and custom lock-free code as an escalation out of script scope; move the risky core to a normal Cargo package and prove it there.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Cargo script runbook | `references/cargo-script-workflow.md` | Building or debugging a Cargo-native script |
| Supported command surface | `references/command-support-matrix.md` | Before uncommon Cargo commands |
| Exact error recovery | `references/error-catalog.md` | A known command fails |
| Current stabilization state | `references/upstream-status.md` | Behavior may have changed upstream |
| Stable fallback | `references/rust-script-fallback.md` | Nightly is unavailable or rejected |
| Minimal scripts, frontmatter, verification, and sources | `references/contracts-and-verification.md` | Creating or validating a Cargo-native script |
| Error, type, async, test, or unsafe design inside a script | `references/scripting-engineering.md` | Applying Rust engineering checks without turning a script into a service |
| Opinionated production-Rust patterns | `references/advanced/rust/README.md`, then its matching reference | A script is becoming package-scale or needs deep async, CLI, web, type-state, test, concurrency, or safety guidance; repository policy and toolchain constraints take precedence |
| Undefined-behavior investigation | `references/advanced/rust-ub/README.md`, then its matching reference | Auditing unsafe code with Miri, sanitizers, Loom, or the UB taxonomy |
| Cross-language code-smell or logging review | `references/advanced/engineering/code-smells.md`, `references/advanced/engineering/logging.md` | Reviewing structure or observability beyond Rust-specific mechanics |
| Legacy `rust-script` CLI | `reference/cli.md` | Exact fallback flags or environment variables are needed |
| Starter source | `templates/script.rs`, `templates/async.rs` | Creating a matching script |

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
