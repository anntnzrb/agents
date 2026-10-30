# Testing

Read before writing or reviewing tests, interpreting mutants, or adding verification for a Rust change. [self-check]

## Test the contract

- MUST test observable behavior through a public contract. Tests must still make sense if the implementation becomes a black box. [self-check]
- MUST pin current behavior with characterization tests before refactoring code that lacks behavior tests. [cargo test; self-check]
- MUST NOT restate constants, mirror implementation branches, or add assertion-free tests for coverage. Assert ordering, failure behavior, state transitions, and round-trip properties. [cargo-mutants; self-check]
- NEVER add `#[should_panic]` tests. Non-test code does not panic, so tests assert `Result` and `Option` values. [governance-check]
- MUST give every assertion a useful failure message, including assertions in shared test helpers. [missing_assert_message]
- MUST return `()` from tests and assert with messages; `Result`-returning tests trip `panic_in_result_fn`. [panic_in_result_fn; missing_assert_message]
- SHOULD centralize repeated API interaction in a `#[track_caller] fn check(...)` helper, with data-driven inputs and expected outputs. [self-check]
- MUST add `proptest` for parsers, codecs, inverses, and domain invariants. Include invalid inputs and shrinking-friendly strategies. [self-check]
- NEVER hardcode proptest case counts with `ProptestConfig::with_cases`; keep the default configuration so the gate's `PROPTEST_CASES` applies. [self-check]
- MUST test custom comparison and hashing laws, including equal values producing equal hashes and ordering transitivity. [proptest]
- MUST use deterministic tests with injected time and randomness, fixed seeds where applicable, and no wall-clock sleeps for synchronization. [disallowed_methods where configured; self-check]
- MUST use paused runtime time (`#[tokio::test(start_paused = true)]`, `tokio::time::advance`) only in tests without real I/O, because auto-advance fires timers while sockets wait. [self-check]
- MUST configure short timeouts and wait on events for tests over loopback sockets. [self-check]
- MUST prefer real in-memory values and handwritten fakes behind narrow traits for stateful external dependencies. Keep pure logic sans-I/O. [self-check]
- MUST bind test servers to port 0 and read the assigned port from `local_addr()`. [self-check]
- MUST give each test that touches external state its own instance: a unique database or schema, temporary directory, or port. [self-check]
- MUST keep unit tests in `#[cfg(test)] mod tests` beside the code and integration tests under a single `tests/it/main.rs` binary whose modules are declared `#[cfg(test)] mod <name>;`. [tests_outside_test_module; self-check]
- MUST keep existing integration test files under their current names during a retrofit, adding a file-level `#![cfg(test)]`, so their test identities survive. Put new integration tests under `tests/it`. [tests_outside_test_module; governance-check]
- MUST feature-gate exported fakes and test utilities behind `test-util` so ordinary production builds do not enable test shortcuts. [self-check]
- MUST assert promised public-type `Send + Sync` bounds and promised future `Send` bounds at compile time. Test other auto-trait commitments such as `Unpin` when public. [cargo test]
- MUST retain and join all concurrent work before each test ends. [self-check]
- MUST run concurrency and race tests on a multithreaded runtime, such as `#[tokio::test(flavor = "multi_thread")]`. [self-check]
- MUST add a check-mode test for generated code that fails when the generated output is stale. [cargo test; self-check]

## Mutation and anti-gaming

- MUST read mutation results from the CI `mutants` job; the local gate does not run mutants. When the repository has no CI, report mutation testing as unrun. [cargo-mutants; CI]
- MUST have no missed mutants in changed code. Improve the behavior test that should detect each missed mutation. NEVER delete the mutated code merely to obtain green output. [cargo-mutants; self-check]
- MUST kill each missed mutant with a behavior test. When a mutant is equivalent because code is redundant, such as a dead branch or a constructor that duplicates `Default`, delete the redundancy. Otherwise report its exact cargo-mutants name; only a human may exclude it through `exclude_re` in the protected `.cargo/mutants.toml`. NEVER rewrite non-redundant code solely to dodge a mutant, and NEVER add `#[mutants::skip]` outside escape-hatch paths. [cargo-mutants; governance-check]
- MAY remove `#[ignore]` from an existing test that passes, because that strengthens it; newly ignored tests remain rejected. [governance-check]
- MUST cover logic inside macro invocations such as `select!` with explicit behavior tests; cargo-mutants does not mutate macro bodies. [cargo-mutants; self-check]
- MUST inspect unviable mutations, timeouts, and baseline failures rather than claim they establish test quality. A nonzero result blocks completion. [cargo-mutants; self-check]
- MUST NOT add mutation skip attributes, exclusion regexes, file filters, or baseline-skip flags to evade verification. If a mutant is equivalent, follow the equivalent-mutant rule above. [self-check]
- MUST NOT delete tests, add `#[ignore]` even with a reason, reduce assertions, or subtly weaken expected behavior. The governance check rejects lost or newly ignored tests. [ignore_without_reason; governance-check; cargo-mutants; self-check]
- MUST NOT hide production defects under `#[cfg(not(test))]` or use conditional compilation to remove slow tests from type-checking. Keep slow tests compiled and follow the human-approved runtime schedule. [cfg_not_test; governance-check; self-check]
- MUST check snapshots with `INSTA_UPDATE=no cargo insta test --check`. NEVER auto-accept or rewrite expected snapshots to match a failing implementation. [cargo insta; self-check]
- MUST run doctests separately from Nextest through the gate's bundled `--doctests` helper. It runs `cargo test --doc --all-features --locked` with `--package` for each library package and does nothing for binary-only workspaces. Mutants run through Nextest also need ordinary tests for behavior otherwise covered only by doctests. [cargo test --doc; cargo-mutants]
- MUST use `?` in runnable rustdoc examples instead of `unwrap()`. [cargo test --doc; self-check]

## Verification by risk

- MUST run Miri for executable pure-Rust unsafe paths and loom for custom synchronization. Neither is a replacement for behavioral tests. [Miri; loom]
- MUST exclude a test from Miri only with `#[cfg_attr(miri, ignore = "<reason>")]` or a file-level `#![cfg(not(miri))]` inside escape-hatch paths, such as tests that call foreign code. Scale iterations down under `cfg(miri)` instead of skipping loops. [governance-check; Miri]
- MUST run the repository's human-installed fuzz target for a changed untrusted-input parser with a time bound, such as `cargo +nightly fuzz run <target> -- -max_total_time=300`, and convert minimized failures into deterministic regression tests. If no fuzz target exists, report fuzzing as missing human-owned setup instead of creating one under protected paths. [cargo-fuzz; cargo test; self-check]
- MUST test claimed `no_std` support on a target lacking std, for example `cargo check --no-default-features --target thumbv7m-none-eabi --locked`. `#![no_std]` alone does not prove the dependency graph avoids std. [cargo check]
- MUST use a coverage floor only as a complement to mutation testing, never as proof that assertions detect broken behavior. [cargo llvm-cov; cargo-mutants; self-check]
