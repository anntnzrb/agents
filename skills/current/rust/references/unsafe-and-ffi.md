# Unsafe and FFI

Read before changing unsafe code, foreign bindings, raw ownership, or safe code that maintains an unsafe module's invariants. [self-check]

## Soundness boundary

- MUST confine unsafe operations to small adapter modules or crates in escape-hatch paths in `.gate/escape-hatch-paths`. Other crates use `#![forbid(unsafe_code)]`. [unsafe_code; governance-check]
- MUST keep every safe entrypoint sound for all valid callers. Review all safe code that can mutate the unsafe module's private state, not only the unsafe block. [Miri; self-check]
- MUST reserve unsafe contracts for undefined-behavior hazards, not arbitrary business preconditions or privilege checks. [self-check]
- MUST put exactly one unsafe operation in each block, with a `// SAFETY:` comment explaining why every precondition holds at that call site. [multiple_unsafe_ops_per_block; undocumented_unsafe_blocks; unnecessary_safety_comment; self-check]
- MUST use explicit unsafe blocks inside unsafe functions and document caller obligations under `# Safety` on unsafe functions and traits. [unsafe_op_in_unsafe_fn; missing_safety_doc; unnecessary_safety_doc]
- MUST run gate step 9 (Miri) on executable pure-Rust unsafe paths. Do not run a bare `cargo +nightly miri test`. [Miri; self-check]
- MUST keep tests of pure-Rust logic in FFI crates runnable under Miri; mark only tests that call foreign code with `#[cfg_attr(miri, ignore = "Miri cannot execute foreign functions")]`. [Miri; governance-check]
- MUST guard foreign calls in doctests with a hidden `# #[cfg(not(miri))]` line, only inside escape-hatch paths, so the doctest still compiles under Miri. [Miri; governance-check]
- MUST justify every manual `unsafe impl Send` or `Sync` with a safety argument and a Miri or loom test. [undocumented_unsafe_blocks; Miri; loom; self-check]

## Memory validity and unwind safety

- MUST use `MaybeUninit<T>` for uninitialized storage. Use `&raw const` or `&raw mut` to form raw field pointers without creating references to uninitialized or unaligned memory. [Miri; self-check]
- MUST prove complete initialization before `assume_init`, including valid bit patterns for `bool`, `char`, enums, and references. Reading uninitialized bytes as an integer is also invalid. [Miri; self-check]
- MUST NOT create null, dangling, unaligned, or alias-violating references, even temporarily. Packed fields require raw unaligned reads or writes rather than references. [Miri; self-check]
- MUST NOT cast or transmute `&T` into `&mut T`. Use a sound `UnsafeCell` abstraction for shared interior mutation. [invalid_reference_casting; Miri; self-check]
- MUST keep raw pointer arithmetic within its allocation and prove bounds, provenance, alignment, lifetime, and aliasing before dereference. [Miri; self-check]
- MUST write initialized elements before publishing lengths or state that permits dropping or reading them. Keep the visible length a valid initialized prefix throughout unwinding. [Miri; self-check]
- MUST restore a safe state before invoking user code, including `Clone`, `Default`, comparisons, and callbacks that can panic despite this skill's policy. [Miri; self-check]
- MUST handle zero-sized types separately in custom allocators or collections, using aligned non-null dangling pointers where appropriate rather than allocating a zero-size layout. [Miri; self-check]
- MUST model custom pointer ownership, variance, and drop obligations with the appropriate `PhantomData`. NEVER rely on a destructor being invoked for memory safety. [Miri; self-check]
- MUST pair raw ownership transfers exactly once with the matching reclaim operation. NEVER call `Box::from_raw`, `Arc::from_raw`, or equivalent on an arbitrary foreign allocation. [Miri; self-check]
- MUST give `ManuallyDrop` values a documented release path without double-drop or use-after-drop. [Miri; self-check]

## Foreign interfaces

- MUST put safe wrappers in `<project>-ffi`, the only crate with allowlisted unsafe, and expose only a safe API. [unsafe_code; governance-check; self-check]
- MUST add `<project>-sys` for raw declarations only when no maintained bindings crate provides them; the FFI layer translates representations while domain logic stays in the core. [self-check]
- SHOULD use maintained bindings, `bindgen`, `cbindgen`, or platform bindings such as `objc2`, rather than hand-maintained declarations. Keep native build requirements explicit and reproducible. A few hand-written declarations are acceptable when no maintained bindings exist and bindgen is unavailable; report the choice. [cargo check; self-check]
- MUST use ABI-compatible primitives and `#[repr(C)]` or valid `#[repr(transparent)]` aggregates, matching layout and calling convention on both sides. Use portable `core::ffi::c_*` aliases for C integers. [improper_ctypes; improper_ctypes_definitions; self-check]
- MUST receive foreign pointers as `*const T` or `*mut T`, not Rust references. Check nullness and alignment and establish allocation validity, bounds, lifetime, and exclusivity before reference conversion. Null and alignment checks alone do not prove validity. [Miri; self-check]
- MUST receive foreign enum-like values as integers and use checked conversion. NEVER accept arbitrary foreign bits directly as Rust enums or `bool`. [self-check]
- MUST use distinct opaque handle types for distinct foreign resources instead of interchangeable `*mut c_void`. `c_void` is not zero-sized. [cargo check; self-check]
- MUST NOT expect `Option<*mut T>` to share a nullable pointer's ABI. Use raw nullable pointers, or an ABI-guaranteed `Option<NonNull<T>>` representation when appropriate. [self-check]
- MUST represent nullable foreign function pointers with `Option<unsafe extern "C" fn(...)>` when the function has unsafe preconditions, and check `None` before calling. [cargo check; self-check]
- MUST keep allocation and deallocation on the same side, with paired creation and destruction functions or caller-provided buffers. Wrap foreign allocations in a safe owner that invokes their matching release API. [self-check]
- MUST NOT pass Rust types with `Drop` by value to C. Expose dedicated C-compatible APIs using opaque pointers. [self-check]
- MUST prevent unwinding across a non-unwind ABI. Contain Rust unwinding at the boundary with `catch_unwind` when needed, or use `extern "C-unwind"` only under a deliberate compatible contract. Neither permits adding panics to Rust logic. [self-check]
- MUST use `unsafe extern` blocks, `#[unsafe(no_mangle)]`, and the other unsafe attributes that edition 2024 requires. [cargo check]
- MUST NOT create references to `static mut`. Prefer safe synchronization; raw static access still requires a sound invariant. [static_mut_refs; self-check]
- MUST preserve Rust aliasing rules across callbacks and foreign mutation, including exclusive access for resources that foreign code mutates. [Miri; self-check]
- MUST isolate DLL mutable state and allocation ownership instead of sharing Rust globals across library boundaries. [self-check]
- SHOULD provide documented raw-handle escape hatches on safe wrappers when a concrete interoperation need exists, preserving ownership and lifetime obligations. [self-check]

Miri cannot execute most native FFI. Its passing tests do not establish soundness of foreign code. The [heavier verification table](gates-and-ci.md#heavier-verification) includes sanitizer checks for those paths.
