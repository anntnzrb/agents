# Concurrency and async

Read when changing threads, tasks, locks, atomics, channels, futures, or shutdown. [self-check]

## Scheduling and lifecycles

- MUST use async for concurrent I/O, not CPU-only batch work or functions without concurrent I/O. [unused_async; self-check]
- MUST move blocking file or network calls and long compute work to `tokio::task::spawn_blocking` or a dedicated thread. NEVER block an executor with `std::thread::sleep`. [disallowed_methods; self-check]
- MUST carry the current `tracing` span into `spawn_blocking` closures, for example with `Span::current().in_scope`. [self-check]
- MUST keep each future's uninterrupted work below roughly 1 ms between yields. Split bounded cooperative work with yield points; move substantial computation off executor workers. [self-check]
- MUST NOT hold synchronous lock guards or `RefCell` borrows across `.await`. Limit lexical guard scopes. [await_holding_lock; await_holding_refcell_ref]
- MUST establish a consistent acquisition order when multiple locks are needed, and release locks before callbacks or long work. Data-race freedom does not prove deadlock freedom. [loom; self-check]
- MUST keep ownership of every spawned thread or task through a `JoinHandle`, `JoinSet`, or task tracker, and join or cancel it on shutdown. NEVER fire and forget. [self-check]
- MUST make `tokio::select!` branches cancellation-safe, or document why dropping an in-progress branch loses no required work or state. [self-check]
- MUST define shutdown and cancellation behavior, including the fact that a started blocking task may continue after its async handle is cancelled. [self-check]
- MUST listen for shutdown signals on a dedicated task that does no blocking work. [self-check]
- MUST put timeouts on network I/O and use bounded queues and channels with explicit backpressure. [disallowed_methods where configured; self-check]
- SHOULD retry external calls with bounded exponential backoff and jitter, and stop retrying non-transient errors. [self-check]
- SHOULD make shared service-client handles cheaply `Clone` through an internal `Arc`, without exposing synchronization wrappers in unrelated API signatures. [clone_on_ref_ptr; self-check]
- SHOULD prefer `async fn` when no additional return-future contract is needed. For trait futures requiring `Send`, use `trait_variant` or explicit `-> impl Future<Output = T> + Send`. [cargo check; self-check]
- MUST NOT use return-type notation unless the pinned toolchain's release notes list it as stable. [cargo check; self-check]
- MUST profile large async frames before boxing futures or local state to reduce moves and stack pressure. [self-check]
- MUST obey the poll contract in custom futures: arrange a wakeup before returning `Pending`, and never poll again after `Ready` unless that future explicitly supports it. [cargo test; self-check]
- MUST use `pin-project-lite` or `Box::pin` for pin projection in hand-written futures instead of unsafe projection. [unsafe_code; self-check]
- MUST NOT block inside `Future::poll`; use non-blocking attempts such as `try_lock`, register the waker, and return `Poll::Pending`. [self-check]

## Synchronization and orderings

- MUST prefer standard `Mutex`, channels, `OnceLock`, or `LazyLock` over custom synchronization. [self-check]
- MUST use Acquire/Release when publishing data and Relaxed only for independent counters or flags that publish nothing. Explain every ordering at its call site. [loom; self-check]
- MUST NOT use `SeqCst` as a substitute for a synchronization argument. Even a total atomic order does not repair an incorrect protocol. [loom; self-check]
- MUST add a loom model test for any custom synchronization, including custom atomics. Tests only on x86 can conceal ordering failures visible on weaker architectures. [loom]
- MUST report to a human when loom tests need `cfg(loom)` declared in the workspace `unexpected_cfgs` check-cfg list; agents do not edit lint tables. [unexpected_cfgs; governance-check]
- SHOULD use `compare_exchange_weak` in retry loops, handling spurious failure by retrying. [self-check]
- MUST use a valid compare-exchange failure ordering: never Release or AcqRel. Choose the success and failure orderings from the actual publication protocol. [invalid_atomic_ordering; loom; self-check]
- MUST document ABA and lifetime protection when compare-exchange manipulates reusable pointers or handles. [loom; self-check]
- MUST pair a custom reference counter's Release decrement with Acquire synchronization before final destruction when that is the chosen protocol. Prefer standard `Arc` to implementing a counter. [loom; Miri; self-check]
- MUST wait on condition variables in a predicate loop, rechecking after every wakeup. [cargo test; self-check]
- MUST NOT ban `AtomicU64` or `std::thread::spawn` globally. Apply target constraints and join handles to actual uses. [cargo check; self-check]

The ordering policy follows *Rust Atomics and Locks*, chapter 3, and supersedes generic advice to default to SeqCst. See [sources.md](sources.md).
