# Types and APIs

Read before changing domain models, signatures, traits, modules, crates, or public documentation. [self-check]

## Encode the domain

- MUST give distinct domain values distinct newtypes with private fields and validating constructors returning `Result<Self, E>`. [self-check]
- MUST parse boundary input into refined types instead of returning `Result<(), E>` and discarding the validation proof. [self-check]
- MUST separate boundary parsing from core execution on validated values. Strengthen parameter types before making core operations partial. [self-check]
- MUST use enums for mutually exclusive states, typestate for lifecycle transitions, and `NonZero*` or non-empty wrappers for structural invariants. [non_zero_suggestions; self-check]
- MUST replace `bool` parameters and three-state `Option<bool>` with named enums or separate methods. Trait implementations keep the trait's signature. [fn_params_excessive_bools; struct_excessive_bools; self-check]
- MUST use integer newtypes or `bitflags` for independent combinable flags, rather than Rust enums that cannot represent every bit combination. [self-check]
- MUST match owned enums exhaustively without wildcard arms. For external `#[non_exhaustive]` enums, handle known variants explicitly and give the required fallback meaningful behavior. [wildcard_enum_match_arm; match_wildcard_for_single_variants; self-check]
- MUST derive or implement `Debug` on public types, with non-empty output that redacts secrets. [missing_debug_implementations; self-check]
- MUST implement `Clone`, equality, hashing, `Default`, or `Display` where meaningful on public types. [self-check]
- MUST treat `Copy` as a public compatibility commitment and derive it only when the type is intended to remain trivially copyable. [cargo semver-checks; self-check]
- MUST add `#[must_use = "reason"]` when discarding a pure result, builder, or state transition is a bug. [must_use_candidate; return_self_not_must_use; self-check]
- MUST name constants and timeouts with units and explain their origin or constraint. [self-check]
- MUST choose names that identify the concept, avoiding vague `Manager`, `Helper`, `Common`, and `Data` suffixes. [self-check]
- SHOULD use `Box<str>` or `Box<[T]>` for long-lived immutable sequences when capacity is no longer needed; on 64-bit targets, `Box<str>` is 16 bytes where `String` is 24, which saves little unless the program holds many small strings. [self-check]

## Design the API

- MUST follow Rust casing, modifier-noun word order, and the `as_`, `to_`, and `into_` naming conventions. [nonstandard_style; self-check]
- MUST name getters after their fields and provide iterators as `iter`, `iter_mut`, and `into_iter`. [self-check]
- MUST use inherent `new`, `with_capacity`, or `from_*` constructors and put conversions on the most specific type. Prefer `From` and `TryFrom` implementations over direct `Into` implementations. [from_over_into; self-check]
- MUST return results in a tuple or struct instead of out-parameters, and keep related functions' parameter ordering consistent. [self-check]
- MUST validate complex builders in `build() -> Result<T, E>`. Use a builder beyond roughly three optional parameters. [too_many_arguments; self-check]
- MUST choose concrete types first, generics only for at least two real implementations, and `dyn Trait` only for runtime-selected plugins. Avoid visibly nested abstractions. [self-check]
- MUST put essential operations in inherent methods; traits express abstraction rather than organize namespaces. Use regular module functions instead of dummy namespace structs. [self-check]
- MUST keep visibility minimal, normally private or `pub(crate)`, and expose one canonical public path per item. NEVER add glob re-exports or prelude modules. Inside private modules, mark crate-internal items `pub(crate)`; plain `pub` there trips `unreachable_pub`. [unreachable_pub; wildcard_imports; self-check]
- MUST import dependencies from their defining crates. If a dependency type is deliberately public, expose an explicit documented re-export rather than force consumers to guess compatible versions. [self-check]
- MUST provide sensible defaults and test an ordinary public API use without hidden mandatory setup. [cargo test --doc; self-check]
- SHOULD put options that weaken verification behind an explicitly named `dangerous` API. [self-check]

## Traits and collections

- MUST put trait bounds on the `impl` blocks or functions that need them, rather than duplicate bounds on struct definitions unless the field type requires them. [self-check]
- MUST seal traits that outside code must not implement using a private supertrait. [self-check]
- MUST provide secondary trait methods as defaults derived from a minimal set of primitive methods. [self-check]
- SHOULD consolidate repeated complex bounds into a composite trait when the existing signatures repeat the same contract. [self-check]
- MUST test compile-time `Send + Sync` promises for public types intended to cross threads. Include promised `Unpin` or `Sized` bounds, and assert public futures are `Send` when callers use multithreaded runtimes. [cargo test; self-check]
- SHOULD assert intended `!Send` or `!Sync` contracts at compile time, for example with `static_assertions::assert_not_impl_any!`. [cargo check]
- MUST keep `Eq`, `PartialEq`, `Ord`, `PartialOrd`, and `Hash` consistent, including `a == b` implying equal hashes. Derive them together when possible. [proptest; self-check]
- MUST preserve default comparison methods unless a benchmark justifies an override and property tests prove the comparison laws. [proptest; self-check]
- MUST use iterator chains, `enumerate()`, and `.get()` in place of index loops and manual counters. [needless_range_loop; explicit_counter_loop; indexing_slicing]
- MUST implement `IntoIterator` for owned, shared, and mutable collection forms where meaningful, plus `FromIterator` and `Extend`. [self-check]
- SHOULD accept `impl RangeBounds<T>` for range-taking APIs when it improves caller ergonomics. [self-check]
- MUST pre-size collections when their size is known, using fallible reservation where allocation failure is part of the contract. [self-check]
- MUST sort hash collection output or use `BTreeMap` or `IndexMap` when order affects output, serialization, or tests. `HashMap` and `HashSet` remain valid for unordered lookup. [iter_over_hash_type; self-check]

## Modules and workspaces

Every new project uses one layout, from its first crate. Existing repositories keep their layout during a gate retrofit; see the retrofit checklist in [gates-and-ci.md](gates-and-ci.md#retrofit-checklist). [tests/fixtures/good](../tests/fixtures/good/) is a verified instance; copy its manifest shape.

```text
<repo>/
├── Cargo.toml            # virtual root: [workspace], [workspace.package], [workspace.dependencies], [workspace.lints], [profile.*]
├── Cargo.lock
└── crates/
    ├── <project>-core/   # library: pure domain logic and parsing
    ├── <project>-ffi/    # only with FFI: safe wrappers, the one crate with allowlisted unsafe
    └── <project>/        # thin binary or public facade over the libraries
```

- MUST use the root manifest shape of tests/fixtures/good; the root holds no `[package]`. [cargo metadata; self-check]
- MUST put each crate in flat `crates/<package-name>/`, so the directory name equals the package name. [cargo metadata; self-check]
- MUST keep domain logic and parsing in sans-I/O `<project>-core` with `#![forbid(unsafe_code)]`. Generic I/O utilities accept `Read` or `Write` rather than a concrete file. [unsafe_code; self-check]
- MUST keep `src/main.rs` thin: parse input, call libraries, and map results to exit codes. Logic in a binary target is unreachable from integration tests and doctests. [self-check]
- MUST confine unsafe to `<project>-ffi`, plus `<project>-sys` raw declarations when no maintained bindings exist. Every other crate uses `#![forbid(unsafe_code)]`. [unsafe_code; governance-check]
- MUST add a crate only for a real boundary: a binary beside the core, FFI, or a second entry point. A library-only project is one crate, `crates/<project>/`, held to the core rules. [self-check]
- MUST register internal crates in `[workspace.dependencies]` with `path` and `version = "0.0.0"`; a path-only entry is a wildcard to cargo-deny. Centralize dependencies and lints. Members inherit through `workspace = true`. [cargo metadata; self-check]
- MUST set internal unpublished workspace crates to `publish = false` and `version = "0.0.0"`. [cargo metadata; self-check]
- MUST use `foo.rs` with `foo/` submodules, rather than `foo/mod.rs`. [mod_module_files]
- MUST split modules by responsibility without one-function file sprawl or monolithic files. [self-check]
- SHOULD use a workspace `xtask` for repeated multi-step automation rather than scattered shell scripts. [self-check]
- MUST keep features additive, without mutually exclusive or disabling features. [cargo hack check --feature-powerset; self-check]
- MUST NOT store runtime state in mutable globals. Reserve `LazyLock` and `OnceLock` for truly process-wide immutable values. [self-check]

## Macros and diagnostics

- MUST use a function or generic instead of a macro when adequate. Prefer `macro_rules!` to a proc macro for mechanical substitution. [self-check]
- MUST keep macro syntax faithful to emitted items and control flow, without hidden returns or silently emitted names. [self-check]
- MUST use `$crate::` for defining-crate paths and canonical `::core::` or `::alloc::` paths where needed. Re-export macro runtime helpers through a hidden `_private` module. [cargo test; self-check]
- MUST test item macros with attributes, visibility, complex types, and supported invocation positions. [cargo test; self-check]
- MUST keep proc-macro expansion logic in a normal testable implementation crate and pin companion macro versions to the runtime library. [cargo test; self-check]
- MUST use structured `tracing` fields for diagnostics, without `dbg!`, `println!`, or `eprintln!`. Real CLI output belongs in an allowlisted output module with a justified expectation if needed. [dbg_macro; print_stdout; print_stderr; governance-check]

## Public documentation

- MUST document every public item and give every module `//!` documentation. Start with a single-line summary of about 15 words. [missing_docs; self-check]
- MUST include `# Errors` for public `Result` functions, `# Safety` for unsafe contracts, and runnable `# Examples`. A `# Panics` contract must not normalize non-test panics. [missing_errors_doc; missing_safety_doc; self-check]
- MUST use `?` rather than `unwrap()` in examples and verify through the gate's library-package doctest helper. See [gates-and-ci.md](gates-and-ci.md#execute-the-installed-gate) for the command. [cargo test --doc; self-check]
- MUST link related items, use `#[doc(inline)]` on intentional re-exports, and hide implementation helpers from public rustdoc. [rustdoc; self-check]
- MUST explain rationale and current contracts in comments, without design-journey or changelog prose. [self-check]
