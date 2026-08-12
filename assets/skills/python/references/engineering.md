# Python Engineering Checks

Apply when choosing models, error paths, resource lifecycles, abstractions, or test seams. Repository runtime, checker, libraries, and public contract > these defaults.

## Typed Boundaries and Models

- Untrusted JSON, environment values, CLI input, files, RPC/API payloads: parse once at boundary → typed domain values before core logic.
- Raw payloads, validators, retries, I/O, logging, process exits: keep at edge unless domain being modeled.
- Distinct concepts: distinct types only when mixing could cause a real bug; `NewType` → branded primitives; tagged unions → finite outcomes; `TypedDict` → values that must remain dicts.
- Internal value objects: prefer immutable dataclass. Capability seam: `Protocol`. External boundary: validation model when repository already uses one or needs its features.
- Make impossible states difficult to represent. Handle tagged outcomes exhaustively when project target and checker support it.

## Errors, Ownership, and Concurrency

- Typed result/union when immediate caller must decide between expected outcomes; specific exception when error must propagate to a boundary handler.
- Errors: enough actionable context. NEVER catch broadly or replace invalid data with fallback values that hide the cause.
- Files, clients, connections, locks, streams, task groups: clear owner. Context managers or explicit lifecycle hooks: cleanup survives exceptions and cancellation.
- Async/I/O boundaries: specify cancellation, timeout, retry, cleanup. NEVER create untracked background work or leave a resource open for a later caller to guess about.

## Small, Coherent Design

- Inspect existing patterns first; reuse first adequate standard-library feature, installed dependency, or local helper.
- Add a dependency, abstraction, parser, normalization layer, cache, or defensive branch only for a concrete caller, boundary, or failure mode.
- Separate functional core from imperative effects when that clarifies ownership and tests; NEVER force layers into a small change with no seam to protect.
- Large file, parameter bundle, negative-name maze, broad catch, redundant post-action verification: review trigger. Fix only when task or concrete risk justifies it.

## Behavioral Tests

- Test observable outputs, state transitions, wire contracts, error behavior. NEVER freeze private constants, incidental formatting, prose, or one implementation path.
- Tests: deterministic and isolated. Prefer real values, temporary paths, in-memory fakes, or wire-level fakes before mocks.
- Mock only an external edge genuinely unavailable or prohibitively expensive. Assert boundary behavior, not mock incidental call choreography.
- Add regression test when plausible bug path would otherwise return. Parser/transformer property tests: only meaningful invariants such as round-trips, idempotence, lossless conversion.

## Review Pass

Before handoff, answer:
1. Every untrusted value parsed at one boundary into a useful type?
2. Caller can tell expected errors; every resource has an owner?
3. Concrete reason for each new layer, dependency, or branch?
4. Tests prove changed user-visible behavior and failure path?
