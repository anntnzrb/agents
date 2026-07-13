---
name: golang
description: "Develop and debug Go: .go modules, concurrency, HTTP, CLI, databases, errors, and tests."
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Go Development

Go: Go 1.26 stable, golangci-lint v2, slog, typed errors, idiomatic concurrency, practical tests, small packages. Stdlib-first, framework-optional.

## Activation Triggers

- `.go`, `go.mod`, `go.sum`, `go.work`
- Go-specific terms: goroutine, channel, context, struct, interface, errgroup, synctest, testcontainers
- Go libraries: chi, cobra, kong, pgx, sqlc, slog, fx, bubbletea, connectrpc
- Concurrency patterns, structured logging, HTTP routing, CLI tooling, database access, integration testing

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

- Respect the `go` directive in go.mod first. Target Go 1.26 for new applications; libraries pin the minimum version they need.
- Use stdlib when it is sufficient: `net/http` (Go 1.22+), `log/slog`, `slices`, `maps`, `errors`, `testing`, `iter`.
- Add third-party libraries only when they solve a concrete problem stdlib does not: chi for sub-routing composition, pgx for postgres-specific features, sqlc for type-safe SQL codegen, testcontainers for integration tests.
- Accept interfaces, return structs. Define interfaces at the consumer, not the provider.
- Compose small single-responsibility packages. Use `internal/` for private code, `cmd/` for binaries.
- Keep JSON/API/env/CLI data at boundaries; validate once with typed structs; convert inward.
- Never use `interface{}` — use `any`. Never use archived `golang/mock` — use `uber-go/mock` or hand-written fakes.
- Prefer explicit error paths: `fmt.Errorf("context: %w", err)` wrapping, `errors.Is`, `errors.Join`, `errors.AsType` (Go 1.26+).
- Context is control flow, not data storage. Pass as first argument. Never store in structs.

## Quality Gate Essentials

- **New projects:** golangci-lint v2 (`linters.default: standard` + `modernize`, `gosec`, `bodyclose`), go vet, go test (`-race -count=1 -shuffle=on ./...`).
- **Inherited projects:** preserve existing gates unless changing them is part of the task.
- **Baseline commands:**
  ```bash
  golangci-lint run ./...
  go vet ./...
  go test -race -count=1 -shuffle=on ./...
  ```
- Concurrency-heavy code: add `testing/synctest` (Go 1.25+) for deterministic tests.
- Integration-heavy code: testcontainers-go + build tags (`//go:build integration`).
- Fuzz entry points: `go test -fuzz=FuzzXxx -fuzztime=30s ./...`.

## Required follow-up reads

You MUST load only the references needed by the task:

| Need | Read | When |
|---|---|---|
| Modern features by Go version | `cookbook/modern.md` | New project setup, version upgrade, feature discovery |
| Go 1.22-1.23 features | `cookbook/modern-1.22-1.23.md` | Loop vars, ServeMux routing, range-over-func, rand/v2 |
| Go 1.24-1.26 features | `cookbook/modern-1.24-1.26.md` | Swiss Tables, tool directive, synctest, new(expr), AsType |
| Concurrency, goroutines, channels | `cookbook/concurrency.md` | Any goroutine/channel/errgroup/synctest task |
| Error handling, wrapping, sentinels | `cookbook/errors.md` | Error wrapping, Is/As/AsType, Join, custom types |
| Iterators, range-over-func | `cookbook/iterators.md` | iter.Seq/Seq2, stdlib iterator consumers, custom iterators |
| Generics best practices | `cookbook/generics.md` | Generic types, constraints, when to avoid |
| JSON/API/CLI boundaries | `cookbook/correctness.md` | Validation, typed boundaries, invariants, nil-safety |
| HTTP services, routing, middleware | `cookbook/http-services.md` | ServeMux, chi, middleware chains, graceful shutdown |
| Testing, table-driven, testify, benchmarks | `cookbook/testing.md` | Unit tests, benchmarks, fuzzing, integration test setup |
| Patterns: DI, options, interfaces | `cookbook/patterns.md` | Constructor injection, functional options, repository |
| Tooling: lint, format, build, CI | `cookbook/tooling.md` | golangci-lint config, gofumpt, buf, goreleaser, testcontainers |
| Go conventions, project layout, quick decisions | `reference.md` | Syntax, layout, anti-patterns, routing table, CLI ref |
| Update/audit the Go skill itself | `references/update-playbook.md` | When asked to refresh, audit, or update the skill for new Go releases |
| Source ledger for Go/tooling claims | `references/sources.md` | When auditing sources, release notes, or updating the skill |

## Must / Must Not

- MUST use `slog` for structured logging in new code when `go >= 1.21` (not `log`).
- MUST wrap errors with `fmt.Errorf("context: %w", err)` and check with `errors.Is`. Use `errors.AsType[T]` when `go >= 1.26`; use `errors.As` for older `go` directives.
- MUST use `any` (not `interface{}`), `os.ReadFile` (not `ioutil.ReadFile`).
- MUST use `go mod tidy` after any dependency change.
- MUST pass `context.Context` as the first parameter; never store it in structs.
- MUST define interfaces where they're consumed; keep them small (1-3 methods).
- MUST NOT ignore returned errors (linter gate: errcheck).
- MUST NOT use archived `golang/mock` — use `uber-go/mock` or hand-written fakes.
- MUST NOT use `src/` layout — module root is the project root.
- MUST NOT use experimental/GOEXPERIMENT-only features as default practice.
- MUST NOT carry raw `map[string]any` or `json.RawMessage` through core logic.
