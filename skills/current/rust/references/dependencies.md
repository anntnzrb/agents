# Dependencies

Read before adding or updating crates, changing features, building a public library, or publishing a release. [self-check]

## Ground versions and minimize the graph

- MUST inspect the exact version in `Cargo.lock` and read that version's docs or source before using its API. Test behavior changes as well as signature changes. [cargo check; self-check]
- MUST justify each new crate: the standard library is inadequate, the crate is maintained, and its adoption and risk fit the task. [self-check]
- MUST prefer `std::sync::LazyLock` or `OnceLock` to `lazy_static` or `once_cell`, and `std::io::IsTerminal` to `atty`, in direct dependencies. Transitive use by maintained crates is acceptable. [cargo-deny std-replacements]
- MUST use `default-features = false` and enable only needed features. Human-owned cargo-deny policy can additionally enforce default-feature and workspace-dependency constraints. [cargo-deny where configured; self-check]
- MUST declare shared dependencies once under `[workspace.dependencies]` and inherit with `workspace = true` in members. [cargo metadata; self-check]
- MUST register internal crates in workspace members and use workspace dependencies rather than duplicate independent declarations. [cargo metadata; self-check]
- MUST NOT add wildcard versions, unapproved Git dependencies, or path dependencies outside the workspace. Local path-boundary review remains a self-check. [cargo-deny; self-check]
- MUST commit `Cargo.lock` for libraries and applications and use `--locked` on build, test, documentation, and supply-chain commands that support it. [cargo --locked; self-check]
- MUST create and update `Cargo.lock` only through Cargo commands, never by hand. [cargo --locked]
- MUST keep the exact `rust-toolchain.toml` pin consistent with the human-owned Nix toolchain when Nix is used. Report pin drift; edit protected files only on the user's request. [governance-check; self-check]
- MUST fill package description, keywords, and categories for crates meant for publication. [cargo_common_metadata]
- MUST take `license`, `repository`, `homepage`, and `readme` values for crates meant for publication from the task or the existing manifest. When they are missing, stop and report them as human-owned inputs; NEVER invent them. Applications and internal crates that are not published set `publish = false` and need none of them. [cargo_common_metadata; cargo-deny; self-check]

## Supply chain

- MUST pass `cargo deny --locked check` for advisories, bans, licenses, and sources, and `cargo machete` for unused dependencies. [cargo-deny; cargo-machete]
- MUST review duplicate-version warnings. Keep cargo-deny's multiple-version level at `warn` rather than imposing a global deny. [cargo-deny; self-check]
- MUST NOT add advisory ignores, license exceptions, source allowlists, or build-script bypasses. Report the exact diagnostic for human resolution. [governance-check; self-check]
- MUST inspect maintenance and unsafe usage in direct and transitive dependencies when accepting a new dependency. A count of unsafe lines is evidence for review, not a soundness proof. [cargo-deny; self-check]
- SHOULD use `cargo tree -i <crate>` to explain an unexpected transitive dependency and schedule outdated-dependency review through the project's existing automation. [cargo tree; self-check]
- MUST use cargo-deny 0.20 or newer, which `[bans.std-replacements]` requires. [cargo-deny]
- MUST use only keys documented for the installed cargo-deny release. [cargo-deny]
- MUST let a human configure any necessary Git exception with an immutable revision and the documented `required-git-spec` setting. Agents do not broaden source trust. [cargo-deny; governance-check; self-check]
- MUST NOT use `unused_crate_dependencies` as the unused-dependency gate; multi-target false positives are handled by using cargo-machete instead. [cargo-machete; self-check]

## Features and compatibility

- MUST make features additive and test feature combinations with `cargo hack check --feature-powerset`. A bounded `--depth 1` or `--depth 2` run is a project-approved subset, not proof of the full powerset. [cargo-hack; self-check]
- MUST set a public library's `rust-version` and test the declared MSRV in CI. Edition 2024 virtual workspaces explicitly select resolver `"3"`. [cargo check; self-check]
- MUST run `cargo semver-checks` before library releases and preserve promised auto-traits as part of compatibility. [cargo-semver-checks; cargo test]
- MUST keep public dependencies stable for a stable public library, and hide private dependency details behind owned types. [cargo-semver-checks; self-check]
- MUST explicitly document and re-export a dependency type when that type is deliberately part of the public API. [rustdoc; self-check]
- MUST pin companion proc-macro and runtime crate versions together so generated code matches the library. [cargo check; self-check]
- MAY use the semver trick during a planned major migration: release an old-major minor that depends on the new major and re-exports unchanged types to preserve their identity across diamond dependencies. [cargo-semver-checks; self-check]
- MUST verify `no_std` support on a bare-metal target without std, rather than infer it from a crate attribute. [cargo check --no-default-features; self-check]

## Release artifacts

- SHOULD use crates.io trusted publishing with short-lived OIDC credentials when the project publishes crates. Verify the current crates.io setup before configuring it. [self-check]
- SHOULD build distributed binaries with `cargo auditable build` and inspect them with `cargo audit bin` when the project requires embedded dependency metadata. [cargo-auditable; cargo-audit]
- MUST generate an SBOM with `cargo cyclonedx` when the release contract requires one. [cargo-cyclonedx]
- MAY use cargo-vet when the project imports and maintains real third-party audits. An empty audit policy is not verification. [cargo-vet; self-check]
