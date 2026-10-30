# Rust skill decisions

Maintainer reference. Each entry states the current decision, why it holds, and the evidence that forced it. Change a decision only with new evidence, and update its entry.

## Section index

- [Policy](#policy)
- [Layout and reads](#layout-and-reads)
- [Gate](#gate)
- [Governance](#governance)
- [Assets](#assets)

## Policy

### Settled policy overrides

- Decision: Enforce zero panics in non-test code, concrete library errors, per-operation non-exhaustive error enums, no `#[allow]`, reasoned test assertions, command-local fatal warnings instead of global `RUSTFLAGS`, and the newest stable edition.
- Why: Language models game invariant claims, unwrap variants, and lint suppressions to force green builds instead of handling failures. The gate is the specification.
- Evidence: `references/sources.md` settled overrides rejecting Microsoft M-PANIC-ON-BUG and BurntSushi unwrap guidance; *Rust for Rustaceans*.

### User-requested gate installation

- Decision: Agents install the bundled assets into a target repository when the user asks to create a Rust project or to install the gates, following the install procedure in `references/gates-and-ci.md`. Without that request, gate configuration stays unchanged, and agents never edit bundled assets.
- Why: The threat is an agent weakening its own judge to get green, not a user-requested installation. A human-only rule made agents refuse explicit scaffold requests, even when the skill author gave the instruction.
- Evidence: Agent transcripts that refused to copy assets into a new workspace; `assets/governance-check.py` still rejects gate-file changes in the reviewed diff, so the installation commit becomes the trusted base.

### Exact toolchain pin

- Decision: Require an exact toolchain pin in `assets/rust-toolchain.toml`, treating the asset value as an example that repository maintainers configure.
- Why: A floating compiler channel introduces unexpected new lints on unrelated code changes, blocking agents on gate checks that appear erroneous.
- Evidence: Rust official releases; eval transcripts showing agents reading the toolchain pin.

## Layout and reads

### Virtual workspace layout

- Decision: Use a virtual workspace with flat `crates/*` members for new projects. The layout defines crate roles (`<project>-core` for domain logic, `<project>-ffi` for foreign interfaces, and `<project>` for a CLI binary or facade), and crates exist only when their boundary exists; the good fixture provides the verified example.
- Why: A single uniform repository structure eliminates agent layout debates; directory names strictly match package names.
- Evidence: matklad *Large Rust Workspaces*; astral-sh/uv and astral-sh/ruff reference repositories; `async`, `ffi`, and `library` tasks in `evals/evals.json`.

### Required reads routing

- Decision: Structure documentation with Always references, conditional references triggered only by observable task features or diff signals, `references/sources.md` excluded from coding reads, reference files nested at most one level deep, and section indexes on files over 100 lines.
- Why: Models ignore optional documentation, fail to traverse deeply nested directory hierarchies, and preview truncated files.
- Evidence: Anthropic skill authoring best practices; eval transcripts confirming all Always references were read in full.

## Gate

### Ordered gate execution and doctests

- Decision: Execute ordered gate checks stopping immediately at the first failure, running doctests per package with a library target rather than workspace-wide.
- Why: Workspace-wide `cargo test --doc --workspace` fails on binary-only crates; ordered fail-fast execution provides immediate feedback.
- Evidence: `verify-fixtures` binary-only control fixture.

### Mutation testing on diff with capped lints and isolated target directory

- Decision: Run mutation testing strictly on the diff using `cargo-mutants`, capping lints via compiler wrapper configuration and isolating the mutation build target directory.
- Why: Denied workspace lints caused body-replacement mutants to fail during compilation as unviable rather than caught by tests; sharing a build target directory polluted subsequent gate steps with stale mutated artifacts.
- Evidence: `retrofit` and `async` tasks in `evals/evals.json` demonstrating unviable mutants without lint capping; `ffi` task in `evals/evals.json` exposing stale build artifacts. `assets/ci.yml` `mutants` job applies the same wrapper and target directory; cargo-mutants 27.0.0 does not cap lints by default.

### Equivalent mutants reporting and human exclusion

- Decision: Require agents to report equivalent mutants with evidence instead of altering code to dodge them; only humans may add exclusion regexes to `exclude_re` in `.cargo/mutants.toml`.
- Why: Distorting clear code to defeat mutation testing obscures intent and degrades maintainability; blocking agents unconditionally without an escape mechanism halts automated progress.
- Evidence: `library` and `ffi` tasks in `evals/evals.json`.

### Target-package Miri execution

- Decision: Run Miri on any change for workspace packages containing files in merge-base escape-hatch paths, configuring the Miri flags and proptest case count that the gate sets, allowing `#[cfg_attr(miri, ignore = "...")]` only on foreign-calling tests within those paths.
- Why: Unsafe scopes extend past the changed lines, so selection is per package; Miri cannot execute foreign C symbols or OS network sockets; safe crates do not need Miri execution.
- Evidence: `ffi` task in `evals/evals.json`; tokio CI Miri workflows; adversarial review of the gate.

## Governance

### Compiled test inventory comparison

- Decision: Enforce test preservation by comparing compiled test inventories emitted by `cargo nextest list --message-format json` against the merge base rather than scanning source files with regexes.
- Why: Source regex checks failed against test renames, parent module `#[cfg]` gates, and Cargo target discovery changes.
- Evidence: Adversarial review of the gate.

### Lint capping via RUSTC_WORKSPACE_WRAPPER

- Decision: Cap lints during test inventory compilation using `RUSTC_WORKSPACE_WRAPPER` rather than modifying `RUSTFLAGS`.
- Why: Repositories undergoing retrofit begin with existing lint debt that blocks inventory compilation; setting `RUSTFLAGS` overrides repository target rustflags and can inadvertently deactivate cfg-gated tests.
- Evidence: `retrofit` task in `evals/evals.json`; `verify-fixtures` lint-debt control fixture.

### Empty merge base allowlist

- Decision: Validate a greenfield or empty merge base by verifying a Git tree containing no symlinks, no submodules, no nested `Cargo.toml` files, and a root manifest limited strictly to `[workspace]` and `[profile.*]` top-level keys.
- Why: Cargo workspace globs, legacy `[project]` manifest tables, and sparse checkout filters bypassed path-based checks; an explicit allowlist fails closed against evasion attempts.
- Evidence: Adversarial review of the gate; `verify-fixtures` greenfield control fixture.

### Approved escape-hatch paths

- Decision: Confine `#[expect]`, `unsafe`, `cfg(miri)` forms including `cfg!`, `mutants::skip`, `include!`, `#[path]`, and custom build scripts (`build.rs`) to escape-hatch paths listed in `.gate/escape-hatch-paths`, and reject `#[should_panic]` everywhere.
- Why: Each hatch represents a demonstrated way to get around gates or weakening test verification; non-test code never panics, eliminating any legitimate role for `#[should_panic]`.
- Evidence: Adversarial review of the gate; rust-lang/rust-analyzer `xtask/src/tidy.rs`.

### Governance backstop and residual risk

- Decision: Treat `governance-check.py` as an automated backstop to repository branch rulesets and CODEOWNERS, documenting residual risks explicitly.
- Why: Static text and token scanning cannot converge to full rustc semantic analysis; procedural macros and complex configurations require human authorization boundaries.
- Evidence: `references/gates-and-ci.md` Residual risk section.

## Assets

### Clippy lint configuration for module structure and visibility

- Decision: Allow `redundant_pub_crate` and deny `mod_module_files` in `assets/workspace-lints.toml`.
- Why: `redundant_pub_crate` conflicts directly with the rustc `unreachable_pub` lint; `mod_module_files` enforces the standard Rust 2018 module structure of `foo.rs` alongside `foo/` rather than legacy `foo/mod.rs`.
- Evidence: `async`, `library`, and `ffi` tasks in `evals/evals.json`; astral-sh/uv and astral-sh/ruff configuration files.

### Zero bool parameters and no string addition

- Decision: Set `max-fn-params-bools = 0` in `assets/clippy.toml` and deny `string_add` in `assets/workspace-lints.toml`.
- Why: Clippy's default threshold of three let single behavior-switch bools pass, so the enum rule was self-check only. The lint skips trait implementations, closures, and non-Rust ABIs, so foreign trait signatures stay legal.
- Evidence: BeautifulRust `lints/clippy.toml`; Clippy `clippy_lints/src/excessive_bools.rs`.

### Scoped standard library replacements in supply-chain checks

- Decision: Avoid global bans on `once_cell` or `lazy_static` in `assets/deny.toml`, scoping `[bans.std-replacements]` to workspace dependencies.
- Why: Blanket ecosystem bans reject popular, actively maintained third-party dependencies like `tracing` that rely on those crates transitively.
- Evidence: `async` task in `evals/evals.json` (tracing dependency); cargo-deny probe.

### License check bypass for internal crates

- Decision: Configure `assets/deny.toml` to skip license validation on internal crates declaring `publish = false`, while requiring human-supplied license expressions and repository metadata for publishable crates.
- Why: Agents must never hallucinate or invent intellectual property metadata or upstream repository URLs.
- Evidence: `async`, `ffi`, `retrofit`, and `library` tasks in `evals/evals.json`.
