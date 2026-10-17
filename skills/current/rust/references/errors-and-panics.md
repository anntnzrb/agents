# Errors and panics

Read when writing fallible code, designing error APIs, or handling cleanup failures. [self-check]

## Concrete errors

- MUST define one concrete error enum per operation or unit of fallibility, deriving `thiserror` 2.x. [self-check]
- MUST mark public error enums `#[non_exhaustive]`. [self-check]
- MAY use a crate-wide public error struct with `kind()` only when a public library would otherwise repeat many near-identical operation enums. [self-check]
- MUST implement `Error`, `Display`, and `Debug`, retaining causal chains through `#[source]`, `#[from]`, and `Error::source()`. [thiserror; missing_debug_implementations; self-check]
- MUST use concise lowercase `Display` text without trailing punctuation, and name variants `Read` or `Parse` rather than `ReadError` or `ParseError`. [self-check]
- MUST keep private dependency error types out of public signatures and exposed fields unless the dependency is part of the public contract. A private source field can preserve its cause. [self-check]
- MUST use `From` or `#[from]` only for unambiguous conversions. When an operation adds a path or distinguishes read from write, map it explicitly into the corresponding variant with its source. [self-check]
- MUST include the path in file-system errors, through `fs-err` or explicit context. [self-check]
- MUST NOT map unrelated failures into a catch-all that loses cause or caller-actionable meaning. [map_err_ignore; self-check]
- MUST box large concrete error payloads when necessary to keep `Result` compact, preserving the concrete type and source chain. [result_large_err]
- MUST return an unconsumed owned argument in the error when failure permits retry or alternative handling. [self-check]
- MUST construct allocating errors and fallbacks lazily with `ok_or_else`, `unwrap_or_else`, or `map_or_else`. [or_fun_call; self-check]
- MAY use `anyhow`, `eyre`, or `miette` in application entrypoints, attaching context at propagation layers. Libraries retain typed errors. [self-check]
- MUST log or report an error once, where it is handled. NEVER log and then propagate the same error. [self-check]
- MUST keep `main` thin, returning `ExitCode` or `Result<(), AppError>` and mapping failures at the top level. NEVER call `process::exit` deep in code. [exit; self-check]
- MUST treat `io::ErrorKind::BrokenPipe` on standard output as success in command-line binaries. [self-check]

## Zero-panic policy

- MUST NOT use panics for non-test error handling or internal bugs. Encode the invariant in types; otherwise return an actionable `Internal` or `Bug` variant. [unwrap_used; expect_used; panic; todo; unimplemented; unreachable; panic_in_result_fn; self-check]
- MUST replace partial operations, including slice and UTF-8 byte slicing, with `.get()`, checked conversions, and typed failures. [indexing_slicing; string_slice; get_unwrap; unwrap_in_result]
- MUST inspect locked dependency APIs for hidden panic paths such as `RefCell::borrow_mut`, poisoned lock unwrapping, arithmetic, and invalid range constructors. Use fallible equivalents and handle their errors. [cargo check; arithmetic_side_effects; self-check]
- MUST distinguish caller precondition violations from internal invariant failures in error variants and documentation. Neither permits a non-test panic. [self-check]
- MAY use `debug_assert!` with a message for debug-only invariant checks. It MUST NOT replace a runtime input check or enforce an unsafe precondition that must hold in release. [missing_assert_message; self-check]
- MUST NOT recover from panics as ordinary control flow. Reserve `catch_unwind` for deliberate FFI containment, while retaining panic-free Rust logic. [self-check]
- MUST NOT panic in `Drop`. Provide explicit fallible `close(self) -> Result<(), CloseError>` or async shutdown for I/O teardown, and handle that result before drop. [panic; unwrap_used; expect_used; self-check]
- MUST NOT discard cleanup errors with `let _ =`, `.ok()`, or `map_err` that erases the source. [let_underscore_must_use; let_underscore_untyped; unused_result_ok; map_err_ignore]

The policy deliberately overrides Microsoft M-PANIC-ON-BUG and BurntSushi's allowance for proven-invariant `unwrap`. Companion panic, indexing, arithmetic, and anti-suppression gates prevent substitution of another panic path. Source evidence is in [sources.md](sources.md).
