---
name: rust
description: "Use when writing, reviewing, or refactoring Rust, Cargo.toml, clippy lints, or Rust CI and supply-chain gates."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb
---

# Rust

Strict Rust for libraries, CLIs, services, and native applications. Humans own gate configuration. Agents satisfy the gates.

## Required reads

MUST read every `Always` row in full before writing or reviewing code. MUST read each conditional row in full when its trigger appears in the task or diff; when unsure, read it. Each file is short. [self-check]

| Need | Read | When |
| --- | --- | --- |
| Typed failures and zero panics | [references/errors-and-panics.md](references/errors-and-panics.md) | Always |
| Domain types, APIs, traits, modules, and docs | [references/types-and-apis.md](references/types-and-apis.md) | Always |
| Ownership and agent failure modes | [references/ownership-and-failure-modes.md](references/ownership-and-failure-modes.md) | Always |
| Behavior and mutation checks | [references/testing.md](references/testing.md) | Always |
| Gate execution and retrofit | [references/gates-and-ci.md](references/gates-and-ci.md) | Always |
| Soundness and foreign interfaces | [references/unsafe-and-ffi.md](references/unsafe-and-ffi.md) | Task or diff touches `unsafe`, `extern`, raw pointers, `#[repr]`, or FFI |
| Scheduling and synchronization | [references/concurrency-and-async.md](references/concurrency-and-async.md) | Task or diff touches `async`, threads, locks, atomics, channels, or an async runtime |
| Untrusted data and secrets | [references/security.md](references/security.md) | Code reads files, network, environment, arguments, or deserializes external input, or runs subprocesses |
| Cargo and supply chain | [references/dependencies.md](references/dependencies.md) | Diff changes dependencies, features, or publishing settings in a `Cargo.toml` |
| Measured optimization | [references/performance.md](references/performance.md) | A benchmark or profile motivates the change |
| Reading evidence and policy overrides | [references/sources.md](references/sources.md) | Only to check provenance or resolve conflicting guidance; not a coding read |
| Protected installation templates | [assets/](assets/) | Inspecting human installation into a target repository |

- MUST let a human copy and install assets into target repositories. Agents may read assets but NEVER edit them or their installed copies. [governance-check; self-check]

## Working loop

1. MUST complete the required reads above, then inspect `Cargo.lock`, `Cargo.toml`, the toolchain pin, and installed gates. The target repository's toolchain pin and lockfile win over example values in `assets/`; report drift and never change gate policy to match it. Read each crate API's exact locked-version docs or source before using it. [self-check]
2. MUST model domain values, states, ownership, and typed failures before writing logic. [self-check]
3. MUST iterate with `cargo check`, `cargo clippy --workspace --all-targets --all-features --locked -- -D warnings`, and tests. [cargo check; clippy; nextest]
4. MUST write behavior tests that detect broken implementations. Run mutation testing only through the gate (testing.md). Improve tests for missed mutants. [cargo-mutants; scripts/cli.py gate]
5. MUST run the public `gate` command in the target workspace with the intended base. It runs the ordered checks below and stops at the first failure. [scripts/cli.py gate]
6. MUST complete every definition-of-done item before reporting success. [self-check; CI]
7. If a gate seems wrong, MUST stop and report the lint, location, and reason. NEVER suppress it, edit gate configuration, or preserve the defect behind a lint-evading rewrite. [governance-check; self-check]

## Definition of done

- [ ] MUST pass the full local gate before reporting done. When the repository has CI, MUST also obtain green CI; otherwise report CI as unrun. Report every blocked or unrun check explicitly. [scripts/cli.py gate; CI]
- [ ] MUST add no `allow` attribute, including inner, multiline, or conditional forms, and no `expect` or `unsafe` outside escape-hatch paths. [allow_attributes; governance-check]
- [ ] MUST leave tests present, enabled, and at least as strong. Add no `ignore` or conditions on existing tests or test modules, and do not reduce assertions. [ignore_without_reason; governance-check; cargo-mutants; self-check]
- [ ] MUST leave gate files, `[workspace.lints]`, `[lints]`, and `[profile.*]` unchanged. Agents may edit root `members`, `[workspace.package]`, and `[workspace.dependencies]`. [governance-check; repository rulesets]
- [ ] MUST document new public items, including `# Errors` on public functions returning `Result`. [missing_docs; missing_errors_doc]
- [ ] MUST justify new dependencies and use only needed features. [cargo-deny; cargo-machete; self-check]
- [ ] MUST have no missed mutants in changed code, or report each equivalent mutant as testing.md requires. [cargo-mutants]
- [ ] MUST report which references were read and which conditional triggers fired. [self-check]
- [ ] MUST check every applicable rule tagged `self-check` in the loaded references against the final diff. [self-check]

## Non-negotiables

- MUST NOT panic in non-test code: no `unwrap`, `expect`, `panic!`, `todo!`, `unimplemented!`, `unreachable!`, slice indexing, or string slicing. Use fallible APIs and typed errors. [unwrap_used; expect_used; panic; todo; unimplemented; unreachable; indexing_slicing; string_slice; panic_in_result_fn; unwrap_in_result; get_unwrap; self-check]
- MUST return concrete `Result<T, E>` errors in libraries. NEVER use `String`, `Box<dyn Error>`, or `anyhow` as library error types. [self-check]
- MUST NOT silence lints with `#[allow]`. Exceptions use `#[expect(lint, reason = "...")]` only in escape-hatch paths. [allow_attributes; allow_attributes_without_reason; unfulfilled_lint_expectations; governance-check]
- MUST confine unsafe code to escape-hatch paths. Other crates use `#![forbid(unsafe_code)]`. [unsafe_code; governance-check]
- MUST handle results and retain causes. NEVER discard errors with `let _ =`, `.ok()`, or cause-erasing `map_err`. [let_underscore_must_use; let_underscore_untyped; unused_result_ok; map_err_ignore; unused_must_use; let_underscore_drop]
- MUST use intentional `checked_*`, `saturating_*`, or `wrapping_*` arithmetic. Document saturation and wrapping. [arithmetic_side_effects; unchecked_time_subtraction; self-check]
- MUST use `TryFrom` or `From` for conversions. [as_conversions; as_underscore; self-check]
- MUST NOT edit gate files, delete or ignore tests, reduce assertions, or bypass hooks with `--no-verify`. [governance-check; repository rulesets; self-check]
- MUST parse untrusted input into validated types at boundaries. Core logic receives those types. [self-check]
- MUST verify APIs against locked-version documentation, including behavior changes that still compile. [cargo check; self-check]

## Small examples

Illustrative fragments. `LoadError::Missing` is a concrete error variant; `send` takes ownership of its argument; `WriteMode` is a domain enum.

```rust
// Bad: panic. Good: typed failure. [unwrap_used]
let value = input.unwrap();
let value = input.ok_or(LoadError::Missing)?;
```

```rust
// Bad: clone a value that is never used again. Good: move it. [redundant_clone; self-check]
send(payload.clone());
send(payload);
```

```rust
// Bad: opaque switch. Good: domain enum. [fn_params_excessive_bools; self-check]
save(path, true);
save(path, WriteMode::Atomic);
```

## Public entrypoint

```text
uv run --script <skill-dir>/scripts/cli.py gate [--base REF] [--path DIR]
uv run --script <skill-dir>/scripts/cli.py verify-fixtures
```

`<skill-dir>` is the installed skill directory. `--path` defaults to the current directory and must name an existing workspace directory. `--base` defaults to `origin/main`. `verify-fixtures` checks the bundled good and bad crates, including compiled test inventories. Governance rejects lost or newly ignored tests.

Exit codes: 0 success, 1 gate or runtime failure, 2 argument errors including a nonexistent `--path`, and 127 a directly missing executable or file. Invalid governed configuration and failed child commands return 1.

Gate order:

1. `cargo fmt --all --check`
2. `cargo clippy --workspace --all-targets --all-features --locked -- -D warnings`
3. `cargo nextest run --workspace --all-features --locked`
4. `cargo test --doc --all-features --locked` for each package with a library target; the gate runs it through bundled `assets/governance-check.py --doctests`
5. `RUSTDOCFLAGS="-D warnings" cargo doc --no-deps --workspace --locked`
6. `cargo deny --locked check`
7. `cargo machete`
8. Mutation testing on the diff (`cargo mutants --in-diff`), which the gate runs with capped lints and an isolated target directory
9. `uv run --script <trusted-base-checker> <base> --inventory`
10. When the diff is non-empty, `cargo +nightly miri test --all-features -p <package>` for each workspace package containing an escape-hatch path, with the Miri flags and proptest case count that gates-and-ci.md step 10 defines

`<trusted-base-checker>` is a temporary copy of `<base>:.gate/governance-check.py`, which runs gate step 9 governance inventory. Read [gates-and-ci.md](references/gates-and-ci.md) for inventory baselines and the installed helper's invocation.
