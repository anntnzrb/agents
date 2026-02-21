# Command Support Matrix

Scope: single-file packages with embedded manifest (`-Zscript`).

## Supported

Via `--manifest-path <script.rs>`:
- `check`
- `build`
- `test`
- `clean`
- `generate-lockfile`
- `metadata`
- `read-manifest`
- `run`
- `tree`
- `update`
- `verify-project`
- `pkgid` (requires lockfile where needed)
- `fix` (including edition migration path)
- `add`
- `remove`

Direct manifest-command form:
- `<CARGO_SCRIPT_CMD> ./script.rs`

## Unsupported / Rejected

- `cargo package --manifest-path script.rs`
- `cargo publish --manifest-path script.rs`
- `cargo install --path script.rs` (expects directory with `Cargo.toml`)
- `path` dependency pointing to script file (`single file packages cannot be used as dependencies`)

## Manifest Field Restrictions

Disallowed in embedded manifests:
- `[workspace]`
- `[lib]`
- `[[bin]]`
- `[[example]]`
- `[[test]]`
- `[[bench]]`
- `package.workspace`
- `package.build`
- `package.metabuild`
- `package.links`
- `package.autolib`
- `package.autobins`
- `package.autoexamples`
- `package.autotests`
- `package.autobenches`
- `package.default-run`

## Name/Sanitization Notes

- package name defaults from sanitized file stem
- problematic stems can sanitize to fallback names (example: numeric-only names)
- reserved/conflicting names can still fail validation (`deps` bin-name conflict)

## Workspace Interaction

- surrounding workspace is not full script workspace support
- script command behavior intentionally isolates script package model

## Editor/Tooling Caveat

- rust-analyzer support is still tracked and incomplete vs final stabilized UX
