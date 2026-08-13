# Go Programmer

**Precedence:** This is an opinionated recipe library, not universal policy. Repository instructions, `go`/`toolchain` directives, configured gates, existing dependencies, and nearby working code override these defaults.

Production Go in 2026: **boring on purpose; strict by tooling; illegal states unrepresentable by convention.**

## Philosophy and non-negotiables

Go lacks sum types (use `interface{}` + type-switch), compiler exhaustiveness checks (use the `exhaustive` linter), `Option<T>` (use `nil`, including the nil-interface/nil-concrete trap), `Result<T, E>` (use `(T, error)` without compiler-enforced unwrapping), and coercion-proof newtypes (`type UserID string` remains carelessly literal-convertible).

Where the language is weak, the linter bundle is the type checker and code patterns are the type system. Treat `golangci-lint v2` configured by `golangci-strict.md` as `tsc --strict`/`basedpyright`; treat `nilaway` and `go test -race` as Miri.

1. **Parse, do not validate, at every boundary:** parse HTTP/RPC/CLI/config into a domain struct built only by `New*(...)` smart constructors; no validation inside the domain. See `data-modeling.md`.
2. **`(T, error)` everywhere:** library code MUST NOT panic; NEVER use bare `_ = err`; wrap errors with `%w`; assert with `errors.Is`/`errors.As`; use typed error structs for caller-branchable errors. See `error-handling.md`.
3. **Sealed variants:** model sum types with a sealed unexported method; dispatch with a `type switch`; let `exhaustive` check completeness. See `type-patterns.md`.
4. **`context.Context` first:** always first parameter; NEVER call `context.Background()` in leaf functions; every goroutine needs context-driven shutdown; domain code MUST NOT call `time.Now()`—inject a clock. See `concurrency.md`.
5. **Generate external contracts:** use `sqlc` for DB, `oapi-codegen` for OpenAPI servers/clients, and `protoc-gen-go` + `protoc-gen-connect-go` for RPC; hand-written marshalling is a regression. See `sqlc-pgx.md`, `grpc-connect.md`.

## Hard rules — tooling

- Go version: **MUST 1.23+** (range-over-func, iter package, stable slog); NEVER `<1.22`.
- Module: `go modules` + `go work` for monorepos; NEVER dep or GOPATH layouts.
- Format: **`gofumpt`** (stricter `gofmt`) + `goimports -local <module>`; NEVER bare `gofmt`.
- Linter: **`golangci-lint v2`** with `golangci-strict.md`; NEVER bare `go vet`.
- Nil checker: **`nilaway`** (Uber; stable since 2024) in CI; NEVER rely on hope.
- Vet bundle: `go vet` + `fieldalignment` + `shadow`; NEVER rely on “tests cover it”.
- Tests: `go test -race -shuffle=on -count=1`; NEVER use `-count` cache or omit race.
- Goroutine leaks: `go.uber.org/goleak` in `TestMain`; NEVER accept “looks fine”.
- Mock: `go.uber.org/mock` (gomock successor); NEVER hand-written stubs.
- DB: `sqlc` + `jackc/pgx/v5`; NEVER `database/sql` + `gorm`.
- HTTP: **`gin-gonic/gin`** (de facto, ~48% of Go API repos); `go-chi/chi` for minimalist HTTP, `connectrpc/connect-go` for RPC. NEVER `echo` (smaller ecosystem), `fiber` (fasthttp, non-stdlib), or `gorilla/mux` (maintenance mode).
- RPC: **`connectrpc/connect-go`** (gRPC-compatible, HTTP/1.1-friendly, browser-friendly); NEVER hand-roll `grpc-go` unless specifically needing bidi streaming that Connect lacks.
- Validation: `go-playground/validator/v10` at HTTP boundaries, `bufbuild/protovalidate-go` for proto, smart constructors for domain; NEVER ad-hoc `if len(s) == 0` chains.
- Config: `caarlos0/env/v11` (struct-tag env); NEVER `viper` unless file+env+flag merging is actually needed.
- Logging: **`log/slog`** (stdlib, Go 1.21+); NEVER `logrus`, `zap`, or `zerolog` (superseded).
- CLI: `spf13/cobra`; NEVER hand-roll `os.Args` parsing beyond 2 flags.
- TUI: `charm.land/bubbletea/v2` + `bubbles/v2` + `lipgloss/v2`; see `bubbletea-v2.md` for CJK/IME; NEVER bubbletea v1 when IME is needed.

CI gate:

```bash
gofumpt -l . && \
  golangci-lint run ./... && \
  nilaway ./... && \
  go test -race -shuffle=on -count=1 ./...
```

A failing command means the change is not done. The bundle is intended for a clean-run guarantee; see `golangci-strict.md` for per-linter rationale and deliberate `nolint:` policy.

## Hard rules — code references

Read the relevant reference for canonical patterns:

- Types/data — `type-patterns.md`, `data-modeling.md`: branded named types, smart constructors with unexported fields, sealed sum types.
- Errors — `error-handling.md`: sentinel vs typed struct, `errors.Is`/`errors.As`, `%w`, no library panics, `errorlint` ruleset.
- Concurrency — `concurrency.md`: `context.Context`, `errgroup`, `sync.OnceValue`, `goleak`, `-race`, channel-selection rules.
- HTTP backend — `backend-stack.md`: `gin` skeleton, middleware order, SSE/streaming with `http.Flusher`, structured `slog`, graceful shutdown; distilled from the CLIProxyAPI codebase, a real OpenAI/Gemini/Claude API proxy.
- RPC — `grpc-connect.md`: Connect vs grpc-go, codegen, protovalidate, streaming.
- DB — `sqlc-pgx.md`: compile-time-safe SQL with sqlc + pgx pool, goose migrations, CI testcontainers.
- CLI — `cobra-stack.md`: cobra layout, slog, signal shutdown, fang-style colored help.
- TUI — `bubbletea-v2.md`: v2 model, `SetVirtualCursor(false)` + `tea.View{Cursor}` for CJK IME, and why v1 breaks Korean/Japanese/Chinese input.
- Testing — `testing.md`: table-driven tests, `require` vs `assert`, `autogold` snapshots, `gopter` property tests, integration `testcontainers`, `goleak` leak checks.
- Bootstrap — `bootstrap.md`: `new-project.go`, `cmd/`/`internal/`/`pkg/` layout, Taskfile, CI.
- Strict config — `golangci-strict.md`: canonical `.golangci.yml`, full linter whitelist, per-linter rationale.
- One-liners — `one-liners.md`: `go run` scripts with `//go:build ignore`, `gorun`-style invocation.

## 250 pure-LOC ceiling

A `.go` file over 250 pure LOC (non-blank, non-comment) is architecturally broken. Go’s many-small-files-per-package model makes this natural: split by responsibility and keep one cohesive type plus its methods per file.

`cmd/server/main.go` commonly violates this. Refactor so `main.go` only wires `os.Args` → `cmd.Execute()`; everything else belongs in `internal/`.

## Existing non-strict projects

When editing an existing `.go` file that does not follow these rules, write new code in the repository’s established style unless the task explicitly requests a focused refactor. Keep branch-scope cleanup separate from feature work.

## Activation

Activate this skill when writing or modifying any `.go`, `go.mod`, `go.sum`, `.golangci.yml`, `Taskfile.yml`, or codegen spec: `*.proto`, `*.sql` next to `sqlc.yaml`, or `openapi.yaml` next to `oapi-codegen.yaml`. One-off scripts receive the same strict treatment; use `//go:build ignore` + `go run` for production hygiene with throwaway ergonomics.

The references contain the recipes. **Read them before writing code; reread them when the model drifts. The post-write architectural review loop is non-negotiable.**
