---
disable-model-invocation: true
name: golang
description: "Use when Go, .go files, go.mod, concurrency, HTTP, CLIs, databases, errors, or Go tests are involved."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Go Development

Go 1.26 stable; golangci-lint v2; slog; typed errors; idiomatic concurrency; practical tests; small packages; stdlib-first, framework-optional.

## Activation Triggers

- `.go`, `go.mod`, `go.sum`, `go.work`
- Go terms: goroutine, channel, context, struct, interface, errgroup, synctest, testcontainers
- Libraries: chi, cobra, kong, pgx, sqlc, slog, fx, bubbletea, connectrpc
- Concurrency, structured logging, HTTP routing, CLI, database access, integration testing

## Workflow

```text
1. DETECT    -> go.mod version/go.work structure, toolchain directive, package layout, golangci-lint config, test gates
2. ROUTE     -> load the required follow-up docs for the task domain
3. MODEL     -> typed structs, small interfaces, domain errors, discriminated states at boundaries
4. COMPOSE   -> small packages, constructor injection, functional options, stdlib-first decisions
5. VALIDATE  -> parse JSON/env/CLI/API/db input once at the edge; typed values inward
6. VERIFY    -> repo-appropriate gate: golangci-lint -> go vet -> go test -race -count=1 ./...
```

## Core Principles

- Respect `go.mod`'s `go` directive first. New applications target Go 1.26; libraries pin their required minimum.
- Prefer sufficient stdlib: `net/http` (Go 1.22+), `log/slog`, `slices`, `maps`, `errors`, `testing`, `iter`.
- Add third-party libraries only for concrete problems stdlib cannot solve: chi for sub-routing composition, pgx for PostgreSQL-specific features, sqlc for type-safe SQL codegen, testcontainers for integration tests.
- Accept interfaces, return structs; define interfaces at consumers, not providers.
- Compose small single-responsibility packages; `internal/` is private code, `cmd/` contains binaries.
- Keep JSON/API/env/CLI data at boundaries; validate once into typed structs; convert inward.
- Use `any`, never `interface{}`. Never use archived `golang/mock`; use `uber-go/mock` or hand-written fakes.
- Prefer explicit errors: `fmt.Errorf("context: %w", err)` wrapping, `errors.Is`, `errors.Join`, `errors.AsType` (Go 1.26+).
- Context is control flow, not storage: first argument; never store in structs.

## Engineering Discipline

- Give values distinct named types when accidental interchange is a real bug; keep external raw data at boundaries.
- When invariants matter, make invalid states hard to construct; do not add constructors, type states, or abstraction layers without a concrete failure mode.
- Make ownership explicit at I/O and concurrency boundaries: one clear owner each for cancellation, timeout, close/cleanup, and error propagation.
- Test observable behavior deterministically. Prefer real values, in-memory fakes, and `httptest` before mocks; inject clocks, randomness, or I/O only when behavior needs control.

## Quality Gate Essentials

- New projects: golangci-lint v2 (`linters.default: standard` + `modernize`, `gosec`, `bodyclose`), go vet, and go test (`-race -count=1 -shuffle=on ./...`).
- Inherited projects: preserve existing gates unless changing them is part of the task.
- Baseline commands:
  ```bash
  golangci-lint run ./...
  go vet ./...
  go test -race -count=1 -shuffle=on ./...
  ```
- Concurrency-heavy: add `testing/synctest` (Go 1.25+) for deterministic tests.
- Integration-heavy: testcontainers-go plus `//go:build integration` build tags.
- Fuzz entry points: `go test -fuzz=FuzzXxx -fuzztime=30s ./...`.

## Required follow-up reads

MUST load only references needed by the task:

- `cookbook/modern.md`: modern features by Go version; new setup, version upgrade, feature discovery.
- `cookbook/modern-1.22-1.23.md`: loop vars, ServeMux routing, range-over-func, rand/v2.
- `cookbook/modern-1.24-1.26.md`: Swiss Tables, tool directive, synctest, new(expr), AsType.
- `cookbook/concurrency.md`: concurrency, goroutines, channels; any goroutine/channel/errgroup/synctest task.
- `cookbook/errors.md`: error wrapping, Is/As/AsType, Join, sentinels, custom types.
- `cookbook/iterators.md`: iterators, range-over-func, `iter.Seq`/`Seq2`, stdlib iterator consumers, custom iterators.
- `cookbook/generics.md`: generic types, constraints, when to avoid.
- `cookbook/correctness.md`: JSON/API/CLI validation, typed boundaries, invariants, nil-safety.
- `references/design-review.md`: design/review of types, states, ownership, or tests; semantic mix-ups, invalid states, over-abstraction, cleanup ambiguity, brittle tests.
- `references/advanced/README.md`, then matching reference: opinionated stack recipes or deep implementation patterns for detailed backend, RPC, database, CLI, TUI, concurrency, or strict-tooling work; repository policy and existing tooling take precedence.
- `references/advanced/engineering/code-smells.md` and `references/advanced/engineering/logging.md`: cross-language code-smell or logging review beyond Go-specific mechanics.
- `cookbook/http-services.md`: HTTP services, routing, middleware; ServeMux, chi, middleware chains, graceful shutdown.
- `cookbook/testing.md`: testing, table-driven tests, testify, benchmarks, fuzzing, integration setup.
- `cookbook/patterns.md`: DI, options, interfaces; constructor injection, functional options, repository.
- `cookbook/tooling.md`: lint, format, build, CI; golangci-lint config, gofumpt, buf, goreleaser, testcontainers.
- `references/guide.md`: Go conventions, project layout, quick decisions; syntax, layout, anti-patterns, routing table, CLI reference.
- `references/update-playbook.md`: update/audit this skill for new Go releases.
- `references/sources.md`: source ledger for Go/tooling claims; auditing sources, release notes, or updating this skill.

## Must / Must Not

- MUST use `slog` for structured logging in new code when `go >= 1.21`, not `log`.
- MUST wrap errors with `fmt.Errorf("context: %w", err)` and check with `errors.Is`; use `errors.AsType[T]` when `go >= 1.26`, `errors.As` for older `go` directives.
- MUST use `any`, not `interface{}`, and `os.ReadFile`, not `ioutil.ReadFile`.
- MUST run `go mod tidy` after every dependency change.
- MUST pass `context.Context` first; never store it in structs.
- MUST define small (1-3 method) interfaces where consumed.
- MUST NOT ignore returned errors (errcheck linter gate).
- MUST NOT use archived `golang/mock`; use `uber-go/mock` or hand-written fakes.
- MUST NOT use `src/` layout; module root is project root.
- MUST NOT use experimental/GOEXPERIMENT-only features as default practice.
- MUST NOT carry raw `map[string]any` or `json.RawMessage` through core logic.
