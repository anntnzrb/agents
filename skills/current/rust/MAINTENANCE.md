# Rust skill maintenance

Maintainer procedure, not loaded by SKILL.md. Use when refreshing Rust guidance, tool versions, configuration schemas, or fixture verification.

## Section index

- [Start here](#start-here)
- [Stack](#stack)
- [Playbook: new stable Rust release](#playbook-new-stable-rust-release)
- [Playbook: adopting a feature that became stable](#playbook-adopting-a-feature-that-became-stable)
- [Playbook: tool releases](#playbook-tool-releases)
- [Playbook: sources and reference repositories](#playbook-sources-and-reference-repositories)
- [Playbook: extending the skill](#playbook-extending-the-skill)
- [Eval suite](#eval-suite)
- [Verify fixtures with Nix](#verify-fixtures-with-nix)
- [Verify the package](#verify-the-package)

## Start here

Numbered order for a returning maintainer:

1. Read [DECISIONS.md](DECISIONS.md) to review design choices, settled overrides, and evidence before making changes.
2. Check the stack table against current releases.
3. Run the matching playbook(s) for the update or extension.
4. Run `verify-fixtures` and the package checks.
5. Rerun the eval suite.
6. Run the final authoring review from `docs/skills.md`.

## Stack

The table names each tool or crate the skill relies on and why. It records no current versions: verify releases at refresh time through `https://crates.io/api/v1/crates/<name>`. Rust's release date comes from [RELEASES.md](https://github.com/rust-lang/rust/blob/master/RELEASES.md); verify the stable channel through `https://static.rust-lang.org/dist/channel-rust-stable.toml`, because a manifest or commit date is not necessarily the release date. A floor is the oldest version the skill's configuration or guidance works with; raise it only when the skill starts depending on a newer feature.

| Tool or crate | Role | Floor |
| --- | --- | --- |
| Rust stable | Exact toolchain pin | [assets/rust-toolchain.toml](assets/rust-toolchain.toml) |
| cargo-nextest | Required tests | |
| cargo-deny | Required supply-chain checks | 0.20, for `[bans.std-replacements]` |
| cargo-machete | Required unused-dependency checks | |
| cargo-mutants | Required mutation checks | |
| cargo-llvm-cov | Optional coverage floor | |
| cargo-semver-checks | Public libraries | |
| cargo-hack | Feature combinations | |
| cargo-audit | Optional binary audit | |
| cargo-vet | Optional imported third-party audits | |
| cargo-auditable | Release binary dependency metadata | |
| cargo-cyclonedx | Required SBOMs | |
| cargo-shear | Optional unused-dependency autofix | |
| cargo-fuzz | Untrusted-input parsers | |
| kani-verifier | Opt-in bounded proofs | |
| loom | Custom synchronization | |
| proptest | Parsers and invariants | |
| bolero | Optional unified fuzz/property/proof harness | |
| insta | Snapshot checks | |
| thiserror | Library errors | |
| anyhow | Application errors | |
| miette | Application diagnostics | |
| tokio | Concurrent I/O runtime | |
| zizmor | Workflow lint | |

## Playbook: new stable Rust release

1. Read RELEASES.md entries published after the pinned version (the pin lives in `assets/rust-toolchain.toml`).
2. List stabilized language and library features and decide for each whether a reference rule should start using it or stop forbidding it. Rules that depend on stability say "unless the pinned toolchain's release notes list it as stable", for example return-type notation.
3. Read the Clippy CHANGELOG for added, renamed, deprecated, or removed lints and update `assets/workspace-lints.toml` and both fixture `Cargo.toml` lint copies together.
4. Evaluate new restriction lints against the settled policy recorded in [DECISIONS.md](DECISIONS.md).
5. Bump the pin in `assets/rust-toolchain.toml` and the fixtures' `rust-version`.
6. Run `verify-fixtures` (it fails on unknown lints and checks the bad fixture's expected lint names in `scripts/cli.py` `EXPECTED`).
7. For a new edition, read the edition guide for rule-relevant changes (unsafe attributes, prelude, lints) and update rules that name a minimum edition.

## Playbook: adopting a feature that became stable

1. Add or change the rule in the matching reference file under `references/` with an enforcer tag.
2. If a lint enforces it, add the lint to `assets/workspace-lints.toml` and both fixture `Cargo.toml` files.
3. If it affects fixture code, update the good fixture (`tests/fixtures/good`).
4. Add an eval expectation in `evals/evals.json` when it changes agent behavior.
5. Record the decision in [DECISIONS.md](DECISIONS.md).

## Playbook: tool releases

Verify each tool against upstream updates:

- `cargo-deny`: Validate schema keys in `assets/deny.toml` against that release's documentation. Run all four check domains (advisories, bans, licenses, sources).
- `cargo-mutants`: Verify configuration keys it reads, `.cargo/mutants.toml` `exclude_re`, `--in-diff` and `--output` flags, and `mutants::skip` spelling (which `assets/governance-check.py` governs).
- `cargo-nextest`: Verify `list --message-format json` shape: re-record `tests/fixtures/inventory/nextest-base.json` and rerun `tests/test_inventory.py`.
- `cargo-machete`: Verify unused-dependency detection behavior across workspace manifests.
- `zizmor`: Verify workflow linting against the complete workflow.
- GitHub Actions: Resolve release tags to full commit SHAs using the upstream GitHub API or `git ls-remote`, keep the tag comment, and run `zizmor` on `assets/ci.yml`.

## Playbook: sources and reference repositories

1. Re-read on every refresh: Rust RELEASES.md, Clippy CHANGELOG, and `cargo-deny` and `cargo-mutants` documentation and changelogs.
2. Re-read books and long guides only for a new edition or a major policy question.
3. Re-inspect each repository in `references/sources.md` under "Reference repositories" at its current commit:
   - `uv` and `ruff`: Compare root `Cargo.toml` lint tables, `clippy.toml`, and `.cargo/deny.toml`.
   - `tokio`: Compare `.github/workflows/ci.yml` Miri and loom jobs.
   - `rust-analyzer`: Compare `xtask/src/tidy.rs`.
   - `rustls` and `ripgrep`: Compare listed options and entrypoints.
4. Update the commit hash and takeaways in `references/sources.md`. Keep the step about recording read date, access path, and decisions per source.
5. Preserve settled overrides recorded in the first Policy entry of [DECISIONS.md](DECISIONS.md). Report conflicting new evidence instead of silently reversing policy.

Maintainer-authorized skill refreshes may update bundled templates. Ordinary agents applying the Rust skill never edit bundled assets. They install assets into a target repository, or change its gate configuration, only on the user's explicit request.

## Playbook: extending the skill

Touch points per change type:

- `rule`: Edit the matching reference file under `references/` (one decision per bullet, enforcer tag). Edit `SKILL.md` for non-negotiables, routing, or the gate order. Add a [DECISIONS.md](DECISIONS.md) entry when it is a design choice. Support with `references/sources.md` or eval evidence.
- `lint`: Update `assets/workspace-lints.toml` plus `tests/fixtures/good/Cargo.toml` and `tests/fixtures/bad/Cargo.toml` copies. Add a bad-fixture case and a `scripts/cli.py` `EXPECTED` entry when the lint is a core category.
- `gate step`: Update `scripts/cli.py` `COMMANDS` and `gate()`, `tests/test_cli.py` order and stop-on-failure tests, `SKILL.md` "Gate order", `references/gates-and-ci.md` table, and `assets/ci.yml`.
- `governance policy`: Update `assets/governance-check.py`, `tests/test_governance.py` with real temporary Git repositories, `references/gates-and-ci.md`, and a `verify-fixtures` control when real tools are involved; then run an adversarial review round.
- `reference file`: Add the file under `references/`. Add a row to `SKILL.md` "Required reads" table with `Always` or an observable trigger. Include a section index when over 100 lines. Keep cross-links only as optional reading.
- `eval`: Add an entry in `evals/evals.json`, seed files under `evals/files/`, and `scripts/cli.py` `eval-setup` support.

## Eval suite

Evals live in `evals/evals.json` with seeds in `evals/files/`.

1. Create a repository with `uv run --script <skill-dir>/scripts/cli.py eval-setup --task <async|library|ffi|retrofit> --dest <temp-dir>/<name>`.
2. Run each task with fresh agents on at least two model sizes.
3. Check the expectations and the agent's actual `Read` tool calls (not its self-report).
4. Turn every repeated friction into a rule, an asset fix, or a gate fix with a [DECISIONS.md](DECISIONS.md) entry.

## Verify fixtures with Nix

Run from the repository root:

```text
nix shell nixpkgs#rustup nixpkgs#cargo-nextest nixpkgs#cargo-deny nixpkgs#cargo-machete nixpkgs#cargo-mutants nixpkgs#zizmor
uv run --script skills/current/rust/scripts/cli.py verify-fixtures
zizmor skills/current/rust/assets/ci.yml
```

`verify-fixtures` copies `assets/rust-toolchain.toml` into each temporary fixture repository, and rustup installs that pinned toolchain. The conditional unsafe check also needs nightly Miri when exercised. Nixpkgs tools can lag upstream releases, especially cargo-deny; an older version is not evidence that a schema newer than it is invalid.

- MUST record `rustc --version`, `cargo clippy --version`, `cargo fmt --version`, `cargo nextest --version`, `cargo deny --version`, `cargo machete --version`, `cargo mutants --version`, and `zizmor --version` with fixture results in the maintenance report. [self-check]
- MUST meet every floor in the stack table; install a current release in a temporary tool directory if the Nix package is older. Do not remove policy keys to accommodate an older tool. [cargo-deny; self-check]
- MUST observe the good fixture pass inventory mode, the bad fixture fail with expected lint names, and real inventory cases reject an ancestor `cfg(any())` and `[lib] test = false`. Verify temporary baseline worktrees are removed. Also verify binary-only inventory/doctest execution, a merge base with only a package-free root manifest, a merge base with lint debt, and mixed ignored/enabled doctests moved by a comment. [verify-fixtures; pytest]
- MUST check all macro-definition delimiters and whitespace forms, approved controls, ordinary tt passthroughs, unchanged symlinks, and procedural-macro package ownership when changing governance. [pytest]
- MUST keep fixture execution outside pytest. Repository pytest runs without a Rust toolchain and verifies command orchestration with a fake Cargo, inventory comparison with recorded Nextest JSON, and governance against real temporary Git repositories. [pytest]
- MUST stop any process started for verification before handoff. [self-check]
- MUST check that the good fixture's mutation summary reports few unviable mutants; a high unviable count means lint capping for mutation builds is broken. [cargo-mutants; verify-fixtures]

## Verify the package

```text
uv run --script skills/current/skill-creator/scripts/cli.py quick-validate skills/current/rust
uv run --script skills/current/skill-creator/scripts/cli.py lint
uv run --script skills/current/skill-creator/scripts/cli.py gates skills/current/rust --tests
uv run --script skills/current/rust/scripts/cli.py --help
git diff --check
```

- MUST inspect the actual output of each relevant command and report failures or missing prerequisites without marking them as passed. [self-check]
- MUST compare source-log URLs to the resource inventory and review all policy lines for named tools or `self-check` enforcers. [self-check]
- MUST keep `SKILL.md` at 150 lines or fewer and prohibit U+2013 and U+2014 in prose. [skill-creator lint; self-check]
- MUST run a fresh-workspace feature exercise, such as a validated configuration parser with a property test, against the installed templates and complete gate when behavior or policy changes. [scripts/cli.py gate; self-check]
