# Develop the sync application

The sync application is a native Rust Cargo workspace under `sync/`. See [Repository layout](../repository-layout.md) for the module map. For the shared-skill workflow, see [Manage shared skills](../skills.md).

## Run sync from source

From the repository root, run sync via Cargo:

```bash
cargo run --manifest-path sync/Cargo.toml --package app -- sync
```

To bypass freshness windows and force a catalog refresh:

```bash
cargo run --manifest-path sync/Cargo.toml --package app -- sync --refresh-models
```

## Run the full checks

Run the format checks, clippy lints, and test suite:

```bash
cargo fmt --manifest-path sync/Cargo.toml --all -- --check
cargo clippy --locked --manifest-path sync/Cargo.toml --workspace --all-targets -- --deny warnings
cargo test --locked --manifest-path sync/Cargo.toml --workspace
```
## Run a focused test

Pass the test filter to Cargo:

```bash
cargo test --manifest-path sync/Cargo.toml --package app-core test_name
```

Add the narrowest regression test that covers the changed sync contract.

Add process-level integration coverage when a change creates a generated target or crosses a runtime boundary. Use harness names and paths as fixtures or adapter boundaries.

Keep tests of harness implementations and harness-local behavior beside their source under `harnesses/`.

## Write useful tests

- Test one behavior at the lowest layer that observes it. Do not repeat the same scenario in unit and process-level suites.
- Test shared code once, beside the shared module. Do not copy identical tests into every consumer; a consumer test covers only its own wiring.
- Assert observable behavior and contracts, not fixtures, mocks, or implementation details.
- Add a test only when it can fail on a real regression. Delete tests that duplicate coverage or re-prove what another test already covers.
- Keep skill and harness tests beside their owning source. `sync/` tests cover sync behavior only.

## Change sync behavior

1. Find the owning module under `sync/crates/`.
2. Add or update the focused test.
3. Make the smallest implementation change.
4. Run the focused test.
5. Run `cargo fmt --manifest-path sync/Cargo.toml --all -- --check`, `cargo clippy --locked --manifest-path sync/Cargo.toml --workspace --all-targets -- --deny warnings`, and `cargo test --locked --manifest-path sync/Cargo.toml --workspace`.
6. Run `git diff --check` from the repository root.
7. Update the related page under `docs/sync/` when the change affects commands, paths, lifecycle, platforms, or generated behavior.

Keep these contracts intact:

- Keep CLI entrypoints consistent with `agentium sync` and `agentium launch <name> -- <arguments>`.
- Keep wrapper generation inside the sync application.
- Validate external files and network data at their boundary.
- Keep filesystem operations safe to retry.
- Preserve unmanaged files unless recorded ownership permits cleanup.

## Change harness configuration

1. Edit the matching source under `harnesses/`.
2. Run `cargo run --manifest-path sync/Cargo.toml --package app -- sync` from the repository root.
3. Inspect the generated root derived from the adapter's `homeSegments` and `runtimeSubdir` fields.
4. Run the wrapper with `--version`.

Keep harness-specific tests and documentation beside the owning source under `harnesses/`. Do not place them in `docs/`.

Do not edit a generated harness home. Sync replaces managed files on the next run.

## Add a harness adapter

1. Add the adapter to `sync/crates/app-core/src/harness_adapters.rs`.
2. Add its source directory under `harnesses/<harness>/`.
3. Add wrapper tests for every supported platform.
4. Add integration coverage for generated files and hooks.
5. Run the full checks.
6. Update the [Harness adapter reference](harnesses.md) only when the adapter changes the shared workflow or requires a harness-specific user action.

Store launcher metadata in the adapter. Do not repeat package names, target homes, or hook rules in user configuration.

Do not add a supported-harness roster to the documentation. `HARNESS_ADAPTERS` owns that list.

## Build the executable

Build the release executable with Cargo:

```bash
cargo build --release --locked --manifest-path sync/Cargo.toml --package app
```

This writes the compiled executable to `sync/target/release/agentium`.

## Runtime boundary

Generated wrappers resolve the native `agentium` binary by checking `AGENTIUM_BIN`, `~/.local/share/agentium/bin/agentium`, or `PATH`. The binary reads the current harness and configuration files from the host's `~/.config/agents/` tree, so those files can change without rebuilding the binary.

The sync engine itself is compiled native code and does not require Node, npm, Git, GitHub CLI, tar, or uv. Bun remains necessary only at harness package and extension dependency boundaries when an adapter or hook executes npm packages or Bun scripts.

## Release and publication

Native Agentium releases are built and published automatically via the GitHub Actions workflow at `.github/workflows/publish-package.yml`.

### Publication workflow

The workflow checks code on pushes to `main` and on tags matching `agentium-v*`. Release builds run for matching tags, building native binaries across matrix targets:

- `aarch64-apple-darwin` (macOS ARM64)
- `x86_64-apple-darwin` (macOS x86_64)
- `x86_64-unknown-linux-gnu` (Linux x86_64)
- `aarch64-unknown-linux-gnu` (Linux ARM64)

### Release artifacts

For each target, the release job packages `agentium-<version>-<target>.tar.gz` and a matching `.sha256` checksum file, then creates or updates the corresponding GitHub Release.
