# Gates and CI

## Section index

- [Execute the installed gate](#execute-the-installed-gate)
- [Install assets](#install-assets)
- [Gate configuration protection](#gate-configuration-protection)
- [Governance enforcement](#governance-enforcement)
- [Lint and build constraints](#lint-and-build-constraints)
- [Retrofit checklist](#retrofit-checklist)
- [Heavier verification](#heavier-verification)
- [Residual risk](#residual-risk)

Read before running the full gate, installing gates, auditing a Rust repository, or reporting missing gate installation work. [self-check]

## Execute the installed gate

- MUST run `uv run --script <skill-dir>/scripts/cli.py gate --base <base-ref> --path <workspace>` with the intended review base. [scripts/cli.py gate]
- MUST let the gate run step 8: it writes the diff to `<temp-dir>/diff.patch`, caps lints through a rustc workspace wrapper, and builds mutants in an isolated target directory. NEVER substitute a bare `cargo mutants` run; the CI `mutants` job applies the same wrapper and target directory. [cargo-mutants; scripts/cli.py gate; CI]
- MUST stop at the first failing step, repair code or tests, and rerun the gate. If the gate appears wrong, report its diagnostic, location, and reason. NEVER suppress it or change configuration. [scripts/cli.py gate; governance-check; self-check]
- MUST use the gate to include tracked changes and untracked, non-ignored files in mutation, Miri, and governance checks. The gate builds textual diffs without modifying the index. [scripts/cli.py gate; governance-check]
- MUST NOT use `--no-verify`, skip flags, mutation exclusions, or environment overrides to weaken verification. [self-check]

The ordered gate is:

| Step | Check | Enforcer |
| --- | --- | --- |
| 1 | `cargo fmt --all --check` | rustfmt |
| 2 | `cargo clippy --workspace --all-targets --all-features --locked -- -D warnings` | Clippy |
| 3 | `cargo nextest run --workspace --all-features --locked` | Nextest |
| 4 | Bundled `assets/governance-check.py --doctests`, using the CLI's interpreter | rustdoc tests |
| 5 | `RUSTDOCFLAGS="-D warnings" cargo doc --no-deps --workspace --locked` | rustdoc |
| 6 | `cargo deny --locked check` | cargo-deny |
| 7 | `cargo machete` | cargo-machete |
| 8 | Mutation testing on the diff (`cargo mutants --in-diff`), run by the gate with capped lints and an isolated target directory | cargo-mutants |
| 9 | `uv run --script <trusted-base-checker> <base-ref> --inventory` | governance-check |
| 10 | `MIRIFLAGS="-Zmiri-disable-isolation -Zmiri-strict-provenance"` `PROPTEST_CASES=16` `cargo +nightly miri test --all-features -p <package in an escape-hatch path>` | Miri |

`<trusted-base-checker>` is a temporary copy of `<base-ref>:.gate/governance-check.py`, read with `git show`. The installed file's direct invocation is `uv run --script .gate/governance-check.py <base-ref> --inventory`; the trusted-base copy prevents a change from rewriting its own judge.

The CLI defaults to `--base origin/main` and `--path` set to the current directory. The path must name an existing workspace directory. Exit codes match SKILL.md. A missing tool detected inside a child checker returns 1 through the CLI because the child command failed.

The standalone checker defaults its base to `origin/main`. Exit codes match SKILL.md. `--doctests` selects library packages through Cargo metadata and returns success without a doctest command for a binary-only workspace. The local gate uses the bundled helper for this step; CI runs `uv run --script .gate/governance-check.py --doctests`.

- MUST run Miri on executable unsafe logic in an approved escape-hatch path. Step 10 selects packages by path, which is a trigger, not a soundness proof. [Miri; self-check]
- MUST expect gate step 10 to run Miri, on any change, for every workspace package containing files in escape-hatch paths. The gate sets the Miri flags and proptest case count. [scripts/cli.py gate; Miri]
- MUST pass the local gate before reporting done. When the repository has CI, obtain green CI too. Otherwise report CI as unrun. Report every blocked or unrun check explicitly. [CI; self-check]

## Install assets

The [assets directory](../assets/) contains templates for workspace lints, Clippy, rustfmt, cargo-deny, the toolchain, profiles, governance, and CI. Configuration files own their exact values.

Install them when the user asks to create a Rust project or to install, copy, or scaffold the gates. The request is the authorization. Install each asset's content byte for byte. NEVER weaken, trim, or reorder its policy.

| Asset | Installed copy |
| --- | --- |
| `clippy.toml`, `rustfmt.toml`, `deny.toml`, `rust-toolchain.toml` | Repository root, same name |
| `governance-check.py` | `.gate/governance-check.py` |
| `workspace-lints.toml`, then `profiles.toml` | Appended to the root `Cargo.toml` |
| `ci.yml` | `.github/workflows/ci.yml` |

1. Create the workspace layout from [types-and-apis.md](types-and-apis.md#modules-and-workspaces) and set `[lints] workspace = true` in every member `Cargo.toml`.
2. Copy the assets as the table shows. Keep the toolchain pin from `rust-toolchain.toml`. Rustup installs that toolchain on first use.
3. Create `.gate/escape-hatch-paths` only when the user names approved paths. Without it, no path is approved.
4. Generate `Cargo.lock`, then commit the installation alone, before any solution or feature code. Governance treats gate files changed in the reviewed diff as violations, and the gate reads `.gate/governance-check.py` from the base.
5. Run the gate with `--base <installation-commit>`. A repository without a remote has no `origin/main`. Report every missing tool by name, and NEVER skip its step.

## Gate configuration protection

- NEVER edit bundled assets. [governance-check; self-check]
- MUST leave `.github/`, `.gate/`, `.cargo/`, `.config/`, cargo-deny files, Clippy and rustfmt files, and toolchain files unchanged after installation unless the user asks for a specific change. Lint tables and build profiles in every `Cargo.toml` are protected too. NEVER change them to make a gate pass. [governance-check]
- MUST restrict `#[expect(..., reason = "...")]` and `unsafe` to paths already approved in `.gate/escape-hatch-paths`. NEVER broaden that allowlist. [allow_attributes; unfulfilled_lint_expectations; governance-check; self-check]
- MUST NOT remove test files, lose test functions or assertions, or add ignored tests. [ignore_without_reason; governance-check]
- MUST review test strength beyond compiled test identities and line-based assertion counts; compiled identities and assertion counts can both stay unchanged while assertions weaken. [cargo-mutants; self-check]
- MUST report test-file renames or unusual test syntax rejected by the checker rather than bypass the protected-file or deletion policy. [governance-check; self-check]
- MUST have humans establish default-branch pull-request requirements, required checks, no agent-token bypass, and CODEOWNERS or equivalent path restrictions. Local hooks remain convenience checks. [repository rulesets; self-check]
- MUST have CI execute the base branch's governance checker, with enough Git history to resolve the base. [CI; self-check]
- MUST pin every GitHub Action to a full commit SHA with its tag in a trailing comment and run `zizmor` on the workflow. Pin updates remain human-owned. [zizmor; governance-check; self-check]

## Governance enforcement

Governance reads the proposed diff and fails closed on governed content it cannot decode.

- MUST add no `allow` attribute, including inner, multiline, or nested `cfg_attr` forms. The allowlist grants no exception. [governance-check]
- MUST use `expect` and `unsafe` only in escape-hatch paths. The checker scans complete changed attributes in current source content. [governance-check]
- MUST treat `cfg_attr(miri, ...)`, `cfg(miri)`, and `cfg(not(miri))` as escape hatches allowed only in approved paths, and `#[should_panic]` as rejected test weakening. [governance-check]
- MUST treat `.cargo/mutants.toml`, `mutants.toml`, and `#[mutants::skip]` as gate controls: the files are human-owned and the attribute is allowed only in escape-hatch paths. [governance-check]
- MUST preserve every trusted compiled test identity and ignored state. Inventory comparison catches conditional ancestors, renamed tests, macro-generated ignores, and Cargo test-discovery changes. Cheap attribute checks remain early errors. [governance-check --inventory]
- MUST preserve discovered test files and protected gate paths when moving or renaming files. Root and nested `.gitattributes` and `.gitmodules` are protected too. [governance-check]
- MUST preserve semantic `[lints]`, `[workspace.lints]`, and `[profile]` values in every `Cargo.toml`. Invalid TOML fails closed. Inventory mode resolves every proposed workspace member with `cargo metadata --no-deps --format-version 1 --locked` and requires `[lints] workspace = true` in every member. Plain mode checks changed manifests and reports skipped member resolution. [governance-check]

Governance is a backstop to repository rulesets and CODEOWNERS on gate files, not a complete Rust analyzer.

Inventory mode compares compiled test identities and library doctest listings against the merge base. A merge base with no symlink, submodule, or package manifest has an empty inventory and is not built.

Plain mode does not establish compiled test preservation. CI runs --inventory.

Humans approve removed or renamed test identities in the merge base's `.gate/test-inventory-allowlist.toml`. Escape-hatch paths also come from that merge base. New or edited approvals in a proposed change cannot authorize that change. Use exact identities from the failure diagnostic:

```toml
[removed-or-renamed]
identities = ["nextest:package:binary:module::test_name"]
```

- MUST keep added or changed `macro_rules!` definitions containing a literal `#` or metavariable attribute-construction shape (`$name ! [...]` or `$name [...]`) inside escape-hatch paths. All whitespace and definition delimiters are recognized; unbounded token trees fail closed. Bare invocation-side `#` tokens also require an approved path. Ordinary tt passthrough macros remain permitted. [governance-check]
- MUST keep every changed path belonging to a package with `proc-macro = true` inside escape-hatch paths. [governance-check]
- MUST have a human allowlist every existing or new symlink in the proposed tree: tracked links, links in submodule working trees, symlinked parent directories, and untracked, non-ignored links. Ignored build output such as a `nix build` `result` link is not proposed. Unchanged source links can expose changed non-Rust target content. [governance-check]
- MUST treat the merge base's `.gate/governance-check.py` as authoritative for gate step 9 governance checks; the local gate runs bundled `assets/governance-check.py --doctests` for step 4, while target repositories install `.gate/governance-check.py` from the template. [governance-check]
- MUST treat a missing `.gate/escape-hatch-paths` as approving no paths: every escape hatch is then rejected and gate step 10 selects no packages. [governance-check; scripts/cli.py gate]

Binary-only packages have no doctest command.

## Lint and build constraints

- MUST inherit workspace lints with `[lints] workspace = true` without adding local manifest overrides. Tighten pure crates with `#![forbid(unsafe_code)]`. [cargo check]
- MUST retain deny groups for `all`, `pedantic`, `nursery`, and `cargo`, plus the curated restriction lints. NEVER enable the entire restriction group. [Clippy; self-check]
- MUST report missing `cfg_not_test`, `non_zero_suggestions`, or `ignore_without_reason` from the curated policy; the user owns the lint tables. [Clippy; self-check]
- MUST NOT add global `RUSTFLAGS="-D warnings"` or crate-level `#![deny(warnings)]`. Use Clippy's command-local `-- -D warnings` and rustdoc's scoped flags. [self-check]
- MUST keep duplicate dependency versions at cargo-deny `warn` and review their diagnostics. NEVER replace the unused-dependency gate with `unused_crate_dependencies`. [cargo-deny; cargo-machete; self-check]
- MUST retain stable rustfmt options and the `style_edition` in `rustfmt.toml`, exact toolchain pinning, lockfiles, and checked-overflow profiles. [rustfmt; cargo --locked; governance-check; self-check]
- MUST NOT disable overflow checks or debug assertions in dev or test profiles. [governance-check; self-check]
- MUST recognize that `Instant::duration_since` saturates; it is not a panic-on-clock-skew API. Review actual unchecked time subtraction instead. [unchecked_time_subtraction; self-check]
- MUST NOT globally ban `HashMap`, `HashSet`, `AtomicU64`, or `std::thread::spawn`. Apply determinism, target, and lifecycle rules to their uses. [iter_over_hash_type; self-check]

## Retrofit checklist

The agent audits and fixes Rust code. Protected configuration changes only when the user asks for them; otherwise report them.

- [ ] MUST inventory workspace lint inheritance, toolchain and Nix agreement, lockfiles, and every current CI command. [cargo metadata; self-check]
- [ ] MUST report missing suppression, unsafe-documentation, one-operation-per-block, ignored-result, checked-arithmetic, and anti-gaming gates, or install them from the assets when the user asked for installation. [Clippy; self-check]
- [ ] MUST remove unnecessary `#[allow]` by fixing code. Where an exception is essential, report the needed escape-hatch path before using a reasoned `#[expect]`. [allow_attributes; governance-check; self-check]
- [ ] MUST verify domain crates forbid unsafe and adapters match the existing escape-hatch allowlist. [unsafe_code; governance-check]
- [ ] MUST report absent cargo-deny, cargo-machete, mutation, doctest, documentation, and required CI checks. [scripts/cli.py gate; self-check]
- [ ] MUST add behavior and `proptest` coverage for parsers and framing boundaries, then resolve missed mutants. [proptest; cargo-mutants]
- [ ] MUST verify action SHA pins and workflow lint results, reporting protected workflow edits for a human. [zizmor; self-check]
- [ ] MUST verify default-branch required checks and bot bypass restrictions from repository settings, not infer protection from a shared baseline file or a hook. [repository rulesets; self-check]
- [ ] MUST report any missing CODEOWNERS or equivalent gate-file protection. [self-check]
- [ ] MUST run the full installed gate and required CI after the installation and code fixes. [scripts/cli.py gate; CI]
- [ ] MUST NOT migrate the crate layout during a gate retrofit. The root manifest holds protected tables, and moving files renames test identities; propose the migration as a separate human-approved change. [governance-check; self-check]
- [ ] MAY change public APIs to remove panics and dropped errors, for example returning `Option` or `Result` or replacing a `bool` parameter with an enum; list every API change in the report. [self-check]

## Heavier verification

| Tool | Use when | Command or contract |
| --- | --- | --- |
| Miri | Any pure-Rust unsafe path Miri can execute | `cargo +nightly miri test` |
| loom | Custom synchronization or atomics | `RUSTFLAGS="--cfg loom" cargo test --release` against loom-specific tests |
| Kani | Small critical arithmetic, parsers, or unsafe structures need bounded proofs | `cargo kani`, or `cargo kani --tests` for harnesses using dev-dependencies |
| Verus or Creusot | Project explicitly funds full functional correctness proofs | Project-specific proof command |
| cargo-fuzz | Untrusted-input parsers | `cargo +nightly fuzz run <target> -- -max_total_time=300` |
| Sanitizers | Native C or C++ linked through FFI | `RUSTFLAGS="-Zsanitizer=address" cargo +nightly test` on a supported configured target |
| ThreadSanitizer | Native races require runtime instrumentation | Project-configured nightly TSan command |

- MUST use Miri for executable unsafe paths and loom for custom synchronization. Kani and full proof systems require a project decision. [Miri; loom; self-check]
- MUST gate Kani harnesses under `#[cfg(kani)]`, declare the custom cfg through human-owned `unexpected_cfgs` configuration, and provide explicit `#[kani::unwind(N)]` loop bounds. [Kani; cargo check; self-check]
- MUST examine Kani assumptions and unwind bounds for vacuous or incomplete proofs. Use concrete counterexamples to add regression tests. [Kani; cargo test; self-check]
- MUST keep model-checking and sanitizer flags local to their verification jobs. These flags are not permission to override normal gates. [CI; self-check]
- MUST have a human configure optional library MSRV and semver jobs, feature powersets, no-std target builds, coverage floors, scheduled fuzzing, and runner hardening when relevant. [CI; self-check]
- MUST treat coverage as a floor alongside mutation results. NEVER trade surviving mutants for a higher coverage number. [cargo llvm-cov; cargo-mutants]
- MUST have a human configure mutation performance settings such as a dedicated profile, lint capping for synthetic mutations, or in-place runs only in disposable CI. Agents do not change filters or profiles to obtain green results. [governance-check; self-check]

## Residual risk

Governance analyzes text and Cargo metadata; it is not a Rust compiler or a sandbox. It backs up repository rulesets and CODEOWNERS and does not replace them. Known residual gaps: an identical governed attribute moved between items in the same file, unsafe code that a non-compliant merge base already contains outside approved paths, and arbitrary build-script or procedural-macro behavior inside approved paths. Human review of approved paths and protected-file changes closes these gaps.
