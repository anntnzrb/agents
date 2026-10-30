# Sources

## Section index

- [Guidelines and agent evidence](#guidelines-and-agent-evidence)
- [Compiler and Cargo](#compiler-and-cargo)
- [Safety and performance](#safety-and-performance)
- [Gate tools](#gate-tools)
- [Books and essays](#books-and-essays)
- [Reference repositories](#reference-repositories)

Read when checking provenance, refreshing the skill, or resolving conflicting advice. [self-check]

This log consolidates the full-reading evidence supplied for the skill on 2026-10-16. Each entry records the resource, read date, status, and the decisions it shaped. The book's EPUB reading supersedes the initial access failure in the essay log. Configuration-value URLs for a fixture repository and the crates.io registry are not reading resources.

## Guidelines and agent evidence

### Microsoft Pragmatic Rust Guidelines

URL: https://microsoft.github.io/rust-guidelines/
Read date: 2026-10-16. Status: read in full.

- Standard Rust types, documented APIs, and compiler checks constrain agent mistakes.
- Flat workspaces, sans-I/O domain crates, and thin adapters define ownership boundaries.
- Deliberate override: M-PANIC-ON-BUG does not apply. Non-test code retains zero panics because agents can game invariant claims.
- Deliberate override: M-ERRORS-CANONICAL-STRUCTS yields to per-operation `#[non_exhaustive]` thiserror enums. A crate-wide struct with `kind()` is acceptable only when a public library would otherwise repeat many near-identical enums.
- Boxed immutable strings save descriptor space, not 33% of string data. The 24-to-16-byte handle change matters for many small strings.

### Microsoft single-file agent guide

URL: https://microsoft.github.io/rust-guidelines/agents/all.txt
Read date: 2026-10-16. Status: read in full.

- The concatenated guide supplies the M-* identifiers used to route API, macro, async, and documentation checks.
- Reasoned `#[expect]`, structured tracing, canonical public paths, and public docs improve maintainability.
- Yield points, buffer reuse, and measured allocation changes shape the async and performance checks.
- Deliberate overrides match the Microsoft guidelines above. Zero panics wins over M-PANIC-ON-BUG. Modular operation enums win over canonical crate-wide error structs except for the narrow public-library repetition case.

### Rust API Guidelines

URL: https://rust-lang.github.io/api-guidelines/checklist.html
Read date: 2026-10-16. Status: read in full.

- Standard conversion, constructor, getter, and iterator names make APIs predictable.
- Newtypes hide representation, while trait bounds belong on operations that require them.
- Destructors never panic; blocking or fallible teardown needs an explicit alternative.
- Collection traits, sealed traits, common derives, and non-empty `Debug` are concrete API checks.
- Examples propagate with `?`, and documentation records failure and safety obligations.

### Cloudflare foundations agent guidance

URL: https://github.com/cloudflare/foundations/blob/main/AGENTS.md
Read date: 2026-10-16. Status: read in full.

- Fatal Clippy checks, Nextest, feature combinations, and OpenSSL avoidance support strict gates.
- Bounded feature-depth checks are useful subsets when the project accepts their limited scope.
- Deliberate override: boxed runtime errors and anyhow-based library runtime APIs are rejected. Libraries retain concrete typed errors.
- Deliberate override: new crates use edition 2024 rather than the guide's Rust 2021 target.

### BeautifulRust

URL: https://github.com/morganlinton/BeautifulRust (commit `40db61c6fee84bd121cf288755f0e2f22a50e995`)
Read date: 2026-10-30. Status: read in full (skills, lints, benchmark).

- The porting skill supplies the port-tests-first procedure, construct mapping, proportionality limits, and porting notes in porting.md.
- Characterization tests before refactoring and quirk preservation shape the refactor rules.
- `max-fn-params-bools = 0` and `string_add` turn single bool switches and `+` string building into lint failures.
- Deliberate override: its `expect_used = "allow"`, panic-on-bug policy, and local `#[expect]` suppressions are rejected; zero panics and escape-hatch-only expectations remain.
- Its cross-agent benchmark shows the largest gains on review and porting tasks, and one regression caused by an ambiguous reference example.

### RustEvo

URL: https://github.com/SYSUSELab/RustEvo
Read date: 2026-10-16. Status: read in full.

- API-evolution tasks demonstrate that model memory is insufficient for current crate usage.
- Behavioral changes can preserve compilation while breaking correctness, motivating behavior tests as well as `cargo check`.
- Version-specific retrieved documentation improves results, supporting the locked-version documentation requirement.

## Compiler and Cargo

### Clippy lint index

URL: https://rust-lang.github.io/rust-clippy/master/index.html
Read date: 2026-10-16. Status: read in full.

- The source redirects to the canonical Clippy master index at https://clippy.rust-lang.org/master/index.html.
- Deny groups require curated restriction additions; enabling all restriction lints introduces contradictory requirements.
- `cfg_not_test`, `non_zero_suggestions`, and `ignore_without_reason` reinforce anti-gaming and domain-type policy after pinned-toolchain validation.
- Master documentation can describe unreleased lints. The installed 1.99.1 lint inventory wins over the research log.
- Broad public-enum and union-representation restriction additions are deliberately excluded; policy checks cover the required error and FFI cases.

### Clippy configuration

URL: https://doc.rust-lang.org/clippy/lint_configuration.html
Read date: 2026-10-16. Status: read in full.

- Test exemption keys confine permitted test panics and indexing without allowing debug leftovers.
- `avoid-breaking-exported-api = false` keeps public APIs subject to configured checks.
- Method restrictions can enforce project-specific clock and unbounded-channel rules, while generic policy remains a self-check until configured by a human.
- Compiler MSRV comes from `Cargo.toml`; duplicating it in Clippy config creates drift.

### rustc lints

URL: https://doc.rust-lang.org/rustc/lints/index.html
Read date: 2026-10-16. Status: read in full.

- Lint levels distinguish deny from forbid; pure crates use forbid for unsafe code.
- `unfulfilled_lint_expectations` catches obsolete expectations after a defect disappears.
- `unsafe_op_in_unsafe_fn` keeps unsafe operations explicit even inside unsafe functions.
- `unused_crate_dependencies`, `unused_results`, and `single_use_lifetimes` have costs unsuitable for the baseline; cargo-machete handles unused dependencies.

### Cargo manifest lint tables

URL: https://doc.rust-lang.org/cargo/reference/manifest.html#the-lints-section
Read date: 2026-10-16. Status: read in full.

- Tool-specific lint tables distinguish rustc from Clippy settings.
- Lower-priority groups permit curated individual overrides, so deny groups use priority -1.
- Cargo caps dependency lints separately from the local package, supporting command-local fatal workspace checks.

### Cargo workspace lint inheritance

URL: https://doc.rust-lang.org/cargo/reference/workspaces.html#the-lints-table
Read date: 2026-10-16. Status: read in full.

- Root workspace lint declarations need explicit member inheritance.
- A member with `[lints] workspace = true` cannot combine it with local manifest lint overrides.
- Crate attributes can tighten pure-crate unsafe policy while justified exceptions remain restricted to approved paths.

### Edition 2024 guide

URL: https://doc.rust-lang.org/edition-guide/rust-2024/index.html
Read date: 2026-10-16. Status: read in full.

- Unsafe extern blocks and unsafe export attributes make foreign obligations explicit.
- References to mutable statics are rejected; safe synchronization or justified raw access replaces them.
- Environment mutation is unsafe because process-wide thread synchronization cannot be assumed.
- Resolver 3, formatting style, temporary scopes, and lifetime capture require version-specific migration checks.
- `Future` and `IntoFuture` belong to the edition's prelude.

### Rust releases

URL: https://github.com/rust-lang/rust/blob/master/RELEASES.md
Read date: 2026-10-16. Status: read in full.

- Release coverage in the reading log spans the relevant stable history through 1.99.1.
- Rust 1.99.1's release date is 2026-10-15. The 2026-10-13 commit or manifest date is not its release date.
- Return-type notation is not stable in the pinned toolchain.
- Stabilized `LazyLock`, `core::error::Error`, reasoned expectations, and raw-reference syntax replace older dependencies and unsafe idioms.

## Safety and performance

### ANSSI Secure Rust Guidelines

URL: https://anssi-fr.github.io/rust-guide/
Read date: 2026-10-16. Status: read in full.

- Checked arithmetic and preserved build profiles prevent release-only overflow behavior.
- Unsafe modules require lifecycle, aliasing, and raw-ownership arguments beyond local syntax checks.
- FFI uses portable C types, raw input pointers, checked integer conversions, and paired allocation ownership.
- Destructors cannot guarantee security-critical completion, and they never panic.
- Direct and transitive dependency vetting remains necessary even when application code is safe Rust.

### The Rustonomicon

URL: https://doc.rust-lang.org/nomicon/
Read date: 2026-10-16. Status: read in full.

- Unsafe soundness depends on all code that can affect private module invariants.
- Safe leaks mean memory safety must not rely on a destructor running.
- References require validity immediately; uninitialized storage belongs in `MaybeUninit` with raw field access.
- Unsafe collections preserve initialized-prefix and allocation invariants during unwinding, including panicking user callbacks.
- Zero-sized types, variance, and pointer provenance require explicit treatment in custom owners.

### Rust Atomics and Locks

URL: https://marabos.nl/atomics/
Read date: 2026-10-16. Status: read in full.
Read via the site's redirect to https://mara.nl/atomics/.

- Acquire/Release publication establishes the required happens-before relationship; Relaxed does not publish other data.
- Independent counters and non-publishing flags can use Relaxed with a documented argument.
- Standard locks and channels precede custom synchronization, whose interleavings require loom tests.
- Condition variables need predicate loops, and compare-exchange loops must tolerate spurious failure.
- SeqCst is not a substitute for understanding the protocol, overriding the handoff's original default-ordering advice.

### The Rust Performance Book

URL: https://nnethercote.github.io/perf-book/
Read date: 2026-10-16. Status: read in full.

- Representative release benchmarks and profiles precede optimization.
- Buffer reuse, pre-sizing, safe iteration, and measured layout changes often remove allocation and bounds costs.
- `BufWriter` needs explicit checked flushes because its destructor discards flush errors.
- Batch output should lock once, and expensive logging arguments should be avoided when disabled.
- The boxed-string saving is 8 bytes of handle on 64-bit targets, not a general data-memory percentage or universal size threshold.

## Gate tools

### cargo-deny

URL: https://embarkstudios.github.io/cargo-deny/
Read date: 2026-10-16. Status: read in full.

- Advisories, bans, licenses, and sources are separate failure domains, all required by the gate.
- Version 0.20 configuration uses current keys, excluding removed advisory and license options.
- `[bans.std-replacements]` with documented `scope` and `level` checks crates superseded by the standard library.
- Duplicate versions remain warnings that need review, while source exceptions and advisory ignores remain human-owned.
- Optional workspace and build-script policy can strengthen the graph without agents broadening trust to pass a check.

### cargo-mutants

URL: https://mutants.rs
Read date: 2026-10-16. Status: read in full.

- `--in-diff` reads a unified diff file, correcting the handoff's abbreviated command.
- Missed mutations indicate missing behavioral checks; baseline failures, timeouts, and unviable changes are different outcomes.
- Nextest integration does not execute doctests, so doctests need a separate gate and ordinary tests must catch relevant mutations.
- Skips, regex filters, baseline overrides, and synthetic-mutation lint configuration need protected governance, not agent discretion.
- In-place mutation runs belong only in disposable environments because they modify source files during execution.

### cargo-nextest

URL: https://nexte.st
Read date: 2026-10-16. Status: read in full.

- Process-isolated unit and integration execution supports fast workspace checks.
- Doctests are excluded, requiring separate `cargo test --doc` execution with all features and a locked dependency graph. The gate selects library packages so binary-only workspaces remain applicable.
- Repository profiles live under `.config/nextest.toml`, which belongs to the protected configuration boundary.
- Fail-fast behavior, partitions, and reporting are project configuration choices rather than reasons to skip tests.

### Kani

URL: https://github.com/model-checking/kani
Read date: 2026-10-16. Status: read in full.

- Bounded proof harnesses complement tests for small critical logic.
- `#[cfg(kani)]` separates proofs from normal builds, and custom cfg declarations require compatible human-owned lint configuration.
- Explicit unwind bounds and reviewed assumptions prevent incomplete or vacuous verification claims.
- Harnesses using dev-dependencies run through `cargo kani --tests`, and concrete counterexamples can become regression tests.

## Books and essays

### Effective Rust

URL: https://effective-rust.com/
Read date: 2026-10-16. Status: read in full.

- Newtypes and `From` or `TryFrom` encode distinctions and conversions.
- Public dependency types need deliberate API exposure and compatibility management.
- Default trait methods reduce required primitives, and equality and hashing laws need coordinated implementations.
- Additive features, minimal visibility, deterministic tests, and dependency review keep workspaces composable.
- No-panic destructors and allocator-matched FFI cleanup reinforce explicit ownership rules.

### Rust Design Patterns

URL: https://rust-unofficial.github.io/patterns/
Read date: 2026-10-16. Status: read in full.

- Split structs and use `mem::take` or `mem::replace` to solve borrow conflicts instead of cloning.
- Return consumed inputs on recoverable errors and freeze initialization-only mutation afterward.
- `Deref` is for pointer semantics, and unsafe belongs behind narrow module boundaries.
- Deliberate override: the global `RUSTFLAGS="-D warnings"` recipe is rejected. Clippy receives `-- -D warnings` only for its invocation.

### Rust for Rustaceans

URL: https://rust-for-rustaceans.com/
Read date: 2026-10-16. Status: provided by user (EPUB, read in full).

- Separate ownership and lifetimes rather than apply accidental `'static` bounds or clone around borrow errors.
- Auto-traits leak through private fields and opaque returns, so public promises need compile-time assertions.
- Non-generic inner functions reduce repeated monomorphization, and index-based graphs avoid shared-owner cycles.
- Explicit fallible close methods and named drop guards preserve resource lifecycles.
- `MaybeUninit`, raw references, and state publication after initialized writes preserve unsafe validity during unwinding.
- The supplied errata correct pointer and opaque-type assumptions: `Option<*mut T>` has no nullable-pointer niche guarantee, and `c_void` is not zero-sized.

### How to Test

URL: https://matklad.github.io/2021/05/31/how-to-test.html
Read date: 2026-10-16. Status: read in full.

- Black-box behavior, data-driven cases, and sans-I/O cores decouple tests from implementation.
- Shared `#[track_caller]` check helpers centralize useful failure reports.
- Unjoined background tasks destroy deterministic test lifecycles.
- Deliberate override: plain assertions without messages are rejected. `missing_assert_message` remains required.

### Large Rust Workspaces

URL: https://matklad.github.io/2021/08/22/large-rust-workspaces.html
Read date: 2026-10-16. Status: read in full.

- Virtual workspace roots and flat `crates/*` layouts expose crate boundaries.
- Crate and directory names match, preserving conventional `src/lib.rs` structure.
- Internal unpublished crates use version `0.0.0`, and repeated automation can live in an `xtask`.

### Parse, don't validate

URL: https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/
Read date: 2026-10-16. Status: read in full.

- Parsing returns evidence in a refined value, while unit-returning validation discards that evidence.
- Strong parameter types make core operations total and remove repeated partial checks.
- Boundary parsing precedes core execution, preventing scattered validation of raw primitives.

### Modular Errors in Rust

URL: https://sabrina.jewson.net/blog/errors/
Read date: 2026-10-16. Status: read in full.
The original host failed DNS resolution. Read the live replacement at https://sabrinajewson.org/blog/errors and cross-checked the official source mirror at https://raw.githubusercontent.com/SabrinaJewson/sabrinajewson.github.io/main/src/blog/errors.md.

- Error types belong near each unit of fallibility rather than in a monolithic crate-wide enum.
- Cause chains, caller inspection, encapsulation, and non-exhaustive evolution need to coexist.
- `From` is appropriate only for unambiguous conversions that do not erase operation-specific meaning.
- Concise `Display` messages and boxed large concrete payloads keep errors useful and compact.
- This modular design deliberately takes precedence over Microsoft's default canonical error struct, with the narrow public-library repetition exception documented above.

### Using unwrap() in Rust is Okay

URL: https://blog.burntsushi.net/unwrap/
Read date: 2026-10-16. Status: read in full.
Read the canonical live mirror reached by redirect at https://burntsushi.net/unwrap/.

- Caller preconditions and internal invariants are distinct failure categories.
- Panics lack operational context suitable for callers and end users.
- An unwrap-only ban invites substitutions such as empty `expect` messages or indexing, motivating companion checks.
- Deliberate override: even proven-invariant `unwrap` remains forbidden in non-test code. Encode the invariant in types or return a concrete error to resist agent gate gaming.

### Async Rust

URL: https://oreil.ly/async-rust
Read date: 2026-10-17. Status: provided by user (EPUB, read in full).

- Concurrency and race-hazard unit tests must run under multi-threaded runtime flavors, as single-threaded cooperative executors mask data races and interleaving defects.
- Dedicated signal handling tasks isolated from blocking worker queues ensure graceful shutdowns complete reliably under saturation.
- Custom future poll implementations accessing shared state must use nonblocking `try_lock()` and register wakers to avoid stalling runtime worker threads.
- Deliberate overrides: the book's tolerance for mutex lock-unwrapping, detached background tasks, runtime environment variable mutation, and global mutable channel handles is rejected in favor of zero panics, structured lifecycles, and dependency injection.

### Zero To Production in Rust

URL: https://www.zero2prod.com/
Read date: 2026-10-17. Status: provided by user (EPUB, read in full).

- Log errors only when handled; never emit duplicate error logs at propagation sites when bubbling errors upstream with `?`.
- Bind integration test network services to port 0 and isolate database tests using freshly migrated, unique logical databases per test run.
- Propagate tracing span context into worker threadpools explicitly when offloading CPU-intensive tasks with `spawn_blocking`.
- Treat persistent database storage as an external boundary across time, using fallible parsing for domain types instead of panicking on historical records.
- Prevent authentication timing attacks by running constant-time dummy password hashing when an account identity does not exist.

## Reference repositories

### rust-lang/rust-analyzer

URL: https://github.com/rust-lang/rust-analyzer
Inspected: 2026-10-17 at commit 70e0c46be740a471bcc95f2be290f4bbfdcffd87.

- Never add `#[should_panic]` tests; non-test code does not panic, so tests assert `Result` and `Option` values.
- Add check-mode tests for generated code that fail when generated output is stale.
- Set an explicit working directory for subprocesses.

### astral-sh/uv

URL: https://github.com/astral-sh/uv
Inspected: 2026-10-17 at commit 00c97356501aafa781b287d38feffe17f0dfa71f.

- Include the path in file-system errors through `fs-err` or explicit context.
- Redact credentials in URLs and secrets in `Debug`, `Display`, and logs.
- Inside private modules, mark crate-internal items `pub(crate)` to satisfy `unreachable_pub`.

### astral-sh/ruff

URL: https://github.com/astral-sh/ruff
Inspected: 2026-10-17 at commit 8d122c1fd2b8f16d494ff8a8f8ee6f264bba7ceb.

- Include the path in file-system errors through `fs-err` or explicit context.
- Redact credentials in URLs and secrets in `Debug`, `Display`, and logs.
- Inside private modules, mark crate-internal items `pub(crate)` to avoid tripping `unreachable_pub`.

### tokio-rs/tokio

URL: https://github.com/tokio-rs/tokio
Inspected: 2026-10-17 at commit cdd9dae3aa5056e23dc4d5bc4f852ab8fbf27aff.

- Run Miri with `-Zmiri-disable-isolation -Zmiri-strict-provenance` and exclude tests calling foreign code with `#[cfg_attr(miri, ignore = "<reason>")]`.
- Assert intended `!Send` or `!Sync` contracts at compile time, for example with static assertions.
- Report to a human when loom tests need `cfg(loom)` declared in the workspace `unexpected_cfgs` check-cfg list.

### rustls/rustls

URL: https://github.com/rustls/rustls
Inspected: 2026-10-17 at commit bb2165fa87ef23fb7d12a28c086f078b4f5d412a.

- Put options and constructors that weaken verification behind an explicitly named `dangerous` API.
- Require callers to opt into verification bypasses explicitly at each call site rather than providing silent fallbacks.

### BurntSushi/ripgrep

URL: https://github.com/BurntSushi/ripgrep
Inspected: 2026-10-17 at commit 3fce3b5bb0236da2df6d99672afb8a719642eca7.

- Treat `io::ErrorKind::BrokenPipe` on standard output as success in command-line binaries.
- Confine `anyhow` error handling to application entrypoints, keeping library APIs strictly on concrete typed errors.
