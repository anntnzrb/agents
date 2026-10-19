# Ownership and failure modes

Read when resolving borrow errors, reviewing clones or lifetime bounds, or designing resource lifecycles. [self-check]

## Borrow and own deliberately

- MUST accept `&str`, `&[T]`, and `&T` instead of `&String`, `&Vec<T>`, and `&Box<T>`. Use `impl AsRef<Path>` or `impl AsRef<str>` when caller flexibility is useful. [ptr_arg; self-check]
- MUST NOT clone to escape borrow errors. [redundant_clone; unnecessary_to_owned; implicit_clone; self-check]
- MUST split borrows or structs, shorten borrows, return ownership from constructors, or use `mem::take` or `mem::replace` while leaving initialized state. [self-check]
- MUST justify each remaining clone as cheap sharing or required independent ownership. Spell reference-counted sharing as `Arc::clone(&value)` or `Rc::clone(&value)`. [clone_on_ref_ptr; self-check]
- SHOULD use `Cow<'_, T>` when the same boundary can borrow or own, and return consumed inputs on recoverable failure to avoid callers cloning in advance. [self-check]
- MUST NOT add `'static` bounds or `Box::leak` to silence lifetime errors. `T: 'static` means no non-static borrowed data, not that a value must live forever. [self-check]
- MUST separate independent lifetimes when forcing one lifetime causes needless invariance or borrow coupling. [cargo check; self-check]
- MUST prefer single ownership and `&mut` before shared mutable wrappers. Use message passing or immutable `Arc<T>` for sharing where adequate. [rc_mutex; rc_buffer; self-check]
- MUST choose interior mutability by the actual contract: `Cell` for single-threaded value replacement, fallible `RefCell` borrowing for checked local borrows, atomics for independent scalar state, and locks for compound shared state. [mutex_atomic; mutex_integer; self-check]
- MUST handle `RefCell::try_borrow` and `try_borrow_mut` failures instead of using panicking borrow methods. [self-check]
- MUST keep `Arc`, `Rc`, `Mutex`, and `RefCell` out of public signatures unless sharing or synchronization is itself the contract. [self-check]
- SHOULD represent graphs and multiple indexes with typed indices into a primary `Vec<T>`, rather than `Rc<RefCell<T>>` cycles or self-referential structs. Validate indices and use generations if removals can invalidate handles. [indexing_slicing; self-check]
- MUST implement `Deref` only for genuine smart pointers, never inheritance or arbitrary newtype forwarding. On wrappers with generic pointees, use associated functions to avoid inherent-method collisions with pointee methods. [self-check]

## Release resources explicitly

- MUST bind cleanup guards to named variables such as `let _guard = ...`. `let _ = make_guard()` drops a temporary guard immediately. [let_underscore_must_use; let_underscore_untyped; let_underscore_drop; self-check]
- MUST document custom `Drop` cleanup obligations. [self-check]
- MUST expose `close(self) -> Result<(), CloseError>` for fallible teardown, or an explicit async shutdown method for async cleanup. Keep `Drop` best-effort and nonblocking where cleanup can block an executor. [self-check]
- MUST move fields out during explicit close through `Option::take`, `mem::take`, or another sound ownership transfer. [cargo check; self-check]
- MUST flush a `BufWriter` explicitly and handle its error before drop; implicit drop-time flushing discards I/O failures. [unused_must_use; self-check]
- MUST prevent reference-counted cycles from retaining resources indefinitely. Use `Weak` back edges or index-based ownership. [self-check]
- MUST NOT use `mem::forget` or leaks to avoid cleanup. [mem_forget; self-check]
- MUST NOT rely on destructors running for security-critical completion; safe Rust can leak and aborts skip cleanup. [self-check]

## Review common agent failures

| Symptom | Required correction | Enforcer |
| --- | --- | --- |
| Clone added after a borrow error | Restructure the ownership and identify the real owner. | `redundant_clone`, `unnecessary_to_owned`, self-check |
| Shared mutable wrappers everywhere | Use single ownership, passing `&mut`, or message passing. | `rc_mutex`, `mutex_atomic`, `mutex_integer`, self-check |
| Lifetime patched with `'static` or leaks | Separate lifetimes or transfer owned data. | self-check |
| Panic, indexing, or catch-all library errors | Use a concrete operation error and fallible access. | `unwrap_used`, `expect_used`, `indexing_slicing`, self-check |
| Discarded fallible result | Propagate or handle the error with its cause. | `let_underscore_must_use`, `unused_result_ok`, `map_err_ignore` |
| Suppression or scattered unsafe | Fix the defect or stop with the exact gate failure. | `allow_attributes`, `unsafe_code`, governance-check |
| Boolean switches or wildcard enum arms | Add a domain enum and exhaustively handle its states. | `fn_params_excessive_bools`, `wildcard_enum_match_arm`, self-check |
| Giant functions or premature traits | Split responsibilities and use concrete types first. | `too_many_lines`, self-check |
| Obsolete crate API | Read the exact locked-version API and test behavior. | `cargo check`, self-check |
| Needless async or detached tasks | Use synchronous code or retain and join task handles. | `unused_async`, self-check |
| Tautological tests or fewer assertions | Assert observable behavior and catch missed mutants. | cargo-mutants, governance-check |
| Test exclusion or snapshot acceptance | Restore checks and report a blocked gate. | `ignore_without_reason`, governance-check, `INSTA_UPDATE=no`, self-check |
| Unrequested gate configuration edit | Leave gate configuration unchanged unless the user asked to install or change it; report the required work. | governance-check, repository rulesets |
| Raw arithmetic or casts | Choose checked arithmetic and typed conversions. | `arithmetic_side_effects`, `as_conversions` |

- MUST inspect automatic `cargo fix` and Clippy fixes against invariants and tests before accepting them. A generated edit is not verification. [cargo-mutants; self-check]
