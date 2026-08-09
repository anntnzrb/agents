# Rust Script Engineering Checks

Read this when code inside a Cargo-native or `rust-script` file needs more than a trivial transformation. These checks preserve single-file script ergonomics; they do not prescribe a service stack.

## Safe, small script core

- Parse CLI, environment, files, and network data at the edge into the values the script uses. Return `Result` from fallible work; never use `unwrap()` or `expect()` for external input, I/O, parsing, or process state
- Use `std::result::Result` plus a concrete error when that stays clear. Add `anyhow` when a one-off binary needs error context; add `thiserror` only when callers need typed errors. Do not create a bespoke error hierarchy for a disposable script
- Use newtypes for IDs, units, offsets, or paths only if swapping them could cause a real failure. Match enums you own exhaustively; use a documented fallback only for an external non-exhaustive enum
- Borrow input when it makes a helper easier to reuse, but do not contort a one-shot script into allocation theater. Make allocations and cloning intentional in loops or large-input paths

## I/O and async

- Use `clap` when positional arguments, flags, validation, help, or subcommands outgrow a few standard-library flags. Otherwise keep parsing local and explicit
- Use async only for concurrent I/O. Bound external calls with timeouts, propagate task failures, and do not detach work whose result or cleanup matters
- Keep blocking CPU work out of async tasks. Prefer one simple sequential flow unless concurrent I/O has a measurable or user-visible reason
- Give temporary files, handles, subprocesses, and cancellation paths explicit cleanup ownership. Use `tempfile` or RAII rather than ad-hoc cleanup branches

## Tests and unsafe escalation

- Verify scripts with the existing Cargo-script `check`, `test`, and run commands. Add focused unit tests for parsers or transformations with plausible regressions; use temporary directories and local test servers for deterministic external edges
- Use property tests only for a parser/transform with a meaningful invariant or a prior edge-case failure. Do not add snapshot tooling merely to freeze output text
- Do not introduce `unsafe`, FFI, manual `Send`/`Sync`, raw-pointer parsing, or custom lock-free code to a script by default. If inherited code contains them, isolate the risky core in a normal Cargo package before relying on Miri, sanitizers, or loom; Cargo script mode does not make that audit workflow a stable default
- For that package, document every `unsafe` block's invariant in a `// SAFETY:` comment, expose a safe wrapper, add a targeted test, run Miri, and use loom for custom atomics or lock-free interleavings. FFI also needs boundary validation and sanitizer coverage where Miri cannot execute the foreign side
