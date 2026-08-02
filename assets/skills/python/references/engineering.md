# Python Engineering Checks

Use this reference when selecting models, error paths, resource lifecycles, abstractions, or test seams. Respect the repository's runtime, checker, libraries, and public contract before applying these defaults.

## Typed Boundaries and Models

- Parse untrusted JSON, environment values, CLI input, files, and RPC/API payloads once at their boundary. Convert to typed domain values before core logic.
- Keep raw payloads, validators, retries, I/O, logging, and process exits at the edge unless they are the domain being modeled.
- Model distinct concepts with distinct types only when mixing them would cause a real bug. Use `NewType` for branded primitives, tagged unions for finite outcomes, and `TypedDict` when a value must remain a dict.
- Prefer an immutable dataclass for internal value objects and `Protocol` for a capability seam. Use a validation model at an external boundary when the repository already uses one or needs its features.
- Make impossible states difficult to represent. Handle tagged outcomes exhaustively when the project target and checker support it.

## Errors, Ownership, and Concurrency

- Choose a typed result/union when the immediate caller must decide between expected outcomes. Use a specific exception when an error needs to propagate to a boundary handler.
- Include enough context to act on an error. Do not catch broadly or replace invalid data with fallback values that hide the cause.
- Give files, clients, connections, locks, streams, and task groups a clear owner. Use context managers or explicit lifecycle hooks so cleanup survives exceptions and cancellation.
- At async and I/O boundaries, specify cancellation, timeout, retry, and cleanup behavior. Do not create untracked background work or leave a resource open for a later caller to guess about.

## Small, Coherent Design

- Inspect existing patterns first. Reuse the first adequate standard-library feature, installed dependency, or local helper.
- Add a dependency, abstraction, parser, normalization layer, cache, or defensive branch only for a concrete caller, boundary, or failure mode.
- Keep the functional core separate from imperative effects when that clarifies ownership and tests; do not force layers into a small change that has no seam to protect.
- Treat a large file, parameter bundle, negative-name maze, broad catch, or redundant post-action verification as a review trigger. Fix it only when the task or a concrete risk justifies the change.

## Behavioral Tests

- Test observable outputs, state transitions, wire contracts, and error behavior. Do not freeze private constants, incidental formatting, prose, or one implementation path.
- Keep tests deterministic and isolated. Prefer real values, temporary paths, in-memory fakes, or wire-level fakes before mocks.
- Mock only an external edge that is genuinely unavailable or prohibitively expensive. Assert the behavior at the boundary, not the mock's incidental call choreography.
- Add a regression test when a plausible bug path would otherwise return. For parser and transformer code, add property tests only for meaningful invariants such as round-trips, idempotence, and lossless conversion.

## Review Pass

Before handoff, answer:

1. Is every untrusted value parsed at one boundary into a useful type?
2. Can the caller tell which errors are expected, and does every resource have an owner?
3. Does each new layer, dependency, or branch have a concrete reason to exist?
4. Do tests prove the user-visible behavior and failure path that changed?
