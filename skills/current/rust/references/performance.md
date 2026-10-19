# Performance

Read when a benchmark or profile identifies a performance problem, or when reviewing allocation and I/O behavior. [self-check]

## Measure the change

- MUST obtain a representative `divan` or `criterion` benchmark or a profile identifying the hot spot before optimizing. Compare release builds with the same workload and toolchain. [divan; criterion; self-check]
- MUST record the workload, baseline, changed result, and measurement conditions. Keep setup, I/O, and random generation outside the measured loop unless they are the workload. [self-check]
- MUST use `std::hint::black_box` where needed to prevent dead-code elimination, without inventing a universal speed threshold for benchmarks or optimization targets. [self-check]
- MUST prefer algorithmic and layout improvements before unsafe access or forced inlining. Verify the actual bottleneck after the change. [self-check]
- MUST leave installed profiles unchanged unless the user asks to change them. Read [profiles.toml](../assets/profiles.toml) for the supplied build settings. [governance-check]
- MAY use `panic = "abort"` only in human-configured binaries that never rely on unwinding. [governance-check; self-check]
- SHOULD evaluate `mimalloc` for long-running multithreaded services against a representative workload. [self-check]
- MUST restrict fast non-cryptographic hashers such as `foldhash` or `FxHash` to maps whose keys cannot be adversarial. [self-check]
- MUST keep CPU-specific flags compatible with the deployment fleet. NEVER assume `target-cpu=native` is portable. [self-check]

## Allocate and move less

- MUST pre-size collections when size is known and reuse allocated buffers with `clear()` or `clone_from` in measured repeated work. [self-check]
- SHOULD shrink substantial excess capacity after building long-lived collections, or convert immutable sequences to boxed slices. [self-check]
- MUST avoid needless pointer layers such as `Box<Box<T>>` and use contiguous or index-based storage when profiling shows pointer chasing is costly. [self-check]
- SHOULD box a disproportionately large enum variant when measured layout or move cost justifies indirection. [large_enum_variant; self-check]
- MUST extract a non-generic inner function when a generic wrapper causes substantial duplicated type-independent code through monomorphization. [self-check]
- MUST prefer safe iterator and checked slice operations over `get_unchecked` to eliminate bounds checks. A performance claim never waives adapter and Miri requirements. [indexing_slicing; unsafe_code; Miri; self-check]
- SHOULD use lazy allocating fallback construction so success paths avoid allocating errors or defaults. [or_fun_call; self-check]
- MAY outline a measured cold error path with `#[cold]` when a benchmark confirms the benefit. [self-check]
- MUST profile large async state before boxing futures or buffers, and preserve cancellation behavior. [self-check]

## Batch I/O and diagnostics

- MUST use buffering for repeated small I/O. [self-check]
- MUST lock stdout or stderr once around repeated batch writes and propagate write failures from the output adapter. [self-check]
- MUST avoid expensive diagnostic argument construction when the tracing level is disabled. Use enabled checks or deferred computation for costly values. [self-check]
- MUST measure batching, contention, and queue bounds before introducing custom synchronization or parallelism. [self-check]
