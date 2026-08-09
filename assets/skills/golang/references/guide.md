# Go Quick Reference

Keep this file for fast decisions while coding. Load cookbooks for tutorials and deep patterns.

## Version and toolchain policy

- New applications: target `go 1.26` in go.mod
- Libraries: set `go` to the oldest version supporting your API; add `toolchain go1.26.3` for build reproducibility
- Go releases February and August. The two most recent major releases receive security patches
- Update to latest minor patch before any major tooling change
- Sources: `go.dev/doc/go1.26`, `endoflife.date/go`, `go.dev/doc/toolchain`

## Stable Modern Go Feature Table (1.22 → 1.26)

| Version | Feature | Since |
|---|---|---|
| 1.22 | Loop variable per-iteration semantics | go.mod `go 1.22+` |
| 1.22 | Range over integers: `for i := range 10` | 1.22 |
| 1.22 | Enhanced ServeMux: method routing, path params | 1.22 |
| 1.22 | `math/rand/v2` | 1.22 |
| 1.23 | Stable `iter.Seq[V]`, `iter.Seq2[K,V]` | 1.23 |
| 1.23 | Stdlib iterator consumers: `slices.Collect`, `maps.Keys` | 1.23 |
| 1.24 | Generic type aliases: `type Alias[T any] = ...` | 1.24 |
| 1.24 | Swiss Tables map implementation (~60% faster) | 1.24 |
| 1.24 | `go.mod` `tool` directive (replaces tools.go) | 1.24 |
| 1.24 | Build cache for `go run`/`go tool` | 1.24 |
| 1.24 | `testing.B.Loop` — benchmark loop that doesn't prevent inlining | 1.24 |
| 1.25 | `testing/synctest` stable — deterministic concurrent tests | 1.25 |
| 1.25 | Container-aware GOMAXPROCS | 1.25 |
| 1.25 | go.mod `ignore` directive | 1.25 |
| 1.25 | `go doc -http` | 1.25 |
| 1.25 | New vet analyzers: waitgroup, hostport | 1.25 |
| 1.26 | `new(expr)`: `p := new(Person{Name: "alice"})` | 1.26 |
| 1.26 | `errors.AsType[T]()` — generic type-safe error extraction | 1.26 |
| 1.26 | Green Tea GC default (10-40% GC overhead reduction) | 1.26 |
| 1.26 | `slog.NewMultiHandler` — fan-out logging | 1.26 |
| 1.26 | Self-referential generic constraints | 1.26 |
| 1.26 | `go fix` modernizers: auto-migrates old patterns | 1.26 |
| 1.26 | `crypto/hpke` per RFC 9180 | 1.26 |
| 1.26 | ~30% cgo overhead reduction | 1.26 |

## CLI Quick Reference

### Module management

```bash
go mod init <module>
go mod tidy
go get pkg@latest
go mod download
go mod why <pkg>
```

### Build & run

```bash
go build ./...
go run .
go install ./cmd/...@latest
go tool <name>               # Go 1.24+ tool directive
go generate ./...
```

### Testing

```bash
go test -race -count=1 -shuffle=on ./...
go test -v -run=TestName ./...
go test -fuzz=FuzzXxx -fuzztime=30s ./...
go test -bench=. -benchmem ./...
go test -coverprofile=c.out ./... && go tool cover -html=c.out
```

### Static analysis

```bash
golangci-lint run ./...
go vet ./...
```

### Workspaces (multi-module local dev)

```bash
go work init ./mod1 ./mod2
go work use ./mod3
go work sync
# Do NOT commit go.work. Set GOWORK=off in CI.
```

## Project Layout

Small projects: flat.

```text
project/
├── main.go
├── handler.go
├── service.go
├── go.mod
└── go.sum
```

Growing projects: `cmd/` + `internal/`.

```text
project/
├── cmd/myapp/main.go          # thin bootstrap
├── internal/config/
├── internal/handler/
├── internal/service/
├── go.mod
└── go.sum
```

Domain-driven structure (when complexity warrants):

```text
project/
├── cmd/myapp/main.go          # wiring
├── internal/users/
│   ├── domain.go              # types, interfaces, errors
│   ├── service.go             # business logic
│   └── repository.go          # data access interface
├── internal/postgres/         # pg implementation
├── internal/http/             # HTTP adapters
├── go.mod
└── go.sum
```

Rules:

- `cmd/` — one directory per binary, each a thin bootstrap
- `internal/` — compiler-enforced private packages. Business logic goes here
- `pkg/` — optional, only for intentionally public, importable library code
- `src/` — anti-pattern (GOPATH relic). Never use
- `go.work` — local multi-module development only. `.gitignore` it

## Tooling Defaults

| Tool | Default | Notes |
|---|---|---|
| Linter | golangci-lint v2 | `linters.default: standard` + `modernize`, `gosec`, `bodyclose`, `errcheck` |
| Formatter | gofumpt (via golangci-lint) | Stricter gofmt. Enable `extra-rules: true` |
| LSP | gopls | Official. Install: `go install golang.org/x/tools/gopls@latest` |
| Proto | buf | Native Go; no system protoc needed |
| Release | goreleaser v2 | Cross-compilation without extra tooling for pure Go |
| Task runner | Taskfile or just | Optional; not required |
| Hot reload | Air | `go install github.com/air-verse/air@latest` |
| Mock gen | uber-go/mock or hand fakes | Never use archived golang/mock |

### golangci-lint v2 config

```yaml
version: "2"
linters:
  default: standard
  enable:
    - modernize
    - gosec
    - bodyclose
    - errcheck
    - govet
    - errorlint
    - gofumpt
    - prealloc
  settings:
    gofumpt:
      extra-rules: true
```

## Library Routing Table

| Domain | First Choice | Upgrade When |
|---|---|---|
| HTTP routing | stdlib `net/http` (Go 1.22+) | `go-chi/chi` when sub-routing/middleware composition needs grow |
| HTTP client | stdlib `net/http` | `go-resty/resty` for retries/hooks |
| Logging | `log/slog` | `uber-go/zap` only when allergic to allocs |
| SQL (typed) | `sqlc-dev/sqlc` | Codegen over ORM |
| Postgres driver | `jackc/pgx` | Preferred over database/sql+pq |
| ORM (if desired) | `go-gorm/gorm` | Only when ORM is intentional; prefer sqlc+pgx |
| Integration tests | `testcontainers/testcontainers-go` | Real containers, not mocks |
| CLI | `spf13/cobra` | `alecthomas/kong` for struct-tag declarative, `urfave/cli` for simplicity |
| TUI | `charmbracelet/bubbletea` | Interactive terminal UIs |
| Config | `spf13/viper` | `knadh/koanf` for lighter footprint |
| DI (manual) | Constructor injection | Fx (lifecycle) at scale |
| Validation | `go-playground/validator` | Struct tag validation |
| Concurrency | errgroup + stdlib | `sourcegraph/conc` for pool/stream patterns |
| Errors | stdlib `errors` + `fmt.Errorf` | `go.uber.org/multierr` for batch error collection |
| Mocks | uber-go/mock or hand fakes | Replaces archived golang/mock |
| HTML templates | `a-h/templ` | Type-safe template codegen |
| gRPC / Connect | `connectrpc.com/connect` | gRPC-compatible HTTP APIs |
| Proto | `bufbuild/buf` | Replaces protoc |

## Error Handling Patterns

```go
// Wrap with context
if err := doThing(); err != nil {
    return fmt.Errorf("doing thing: %w", err)
}

// Check sentinel
if errors.Is(err, ErrNotFound) { ... }

// Extract typed error (Go 1.26+)
if valErr, ok := errors.AsType[*ValidationError](err); ok {
    fmt.Println(valErr.Field)
}

// Pre-1.26 fallback
var valErr *ValidationError
if errors.As(err, &valErr) { ... }

// Combine errors
return errors.Join(err1, err2)

// Sentinel definition
var ErrNotFound = errors.New("not found")
```

## Naming Quick Reference

```go
// Unexported: camelCase
var maxRetries = 3

// Exported: PascalCase
var DefaultTimeout = 30 * time.Second

// Acronyms: all-caps or all-lower
type HTTPClient struct{}
type userID string

// Interfaces: single-method -er suffix
type Reader interface { Read(p []byte) (n int, err error) }
```

## Anti-Patterns

| Avoid | Do Instead |
|---|---|
| `interface{}` | `any` |
| `ioutil.ReadFile` | `os.ReadFile` |
| `sort.Slice` | `slices.Sort` |
| `math/rand` | `math/rand/v2` |
| `log` package | `log/slog` |
| `tools.go` blank import | `go.mod` `tool` directive (Go 1.24+) |
| `src/` layout | Flat or `cmd/`+`internal/` |
| `golang/mock` (archived) | `uber-go/mock` or hand fakes |
| `context.Context` in structs | Pass as first parameter |
| Ignoring returned errors | Always handle; use `errcheck` linter |
| Gin as default router | stdlib `net/http` (Go 1.22+) → chi |
| GORM as default DB layer | sqlc+pgx → GORM only if ORM needed |
| Large interfaces (5+ methods) | 1-3 method interfaces, compose when needed |
| Mutable global state | Constructor injection, `internal/` packages |
| Raw `map[string]any` through core | Validate at boundary, convert to typed struct |
| `for i := 0; i < b.N; i++` in benchmarks | `for b.Loop()` (Go 1.24+) |
| `errors.As` + old-style var | `errors.AsType[T]()` (Go 1.26+) |
| Naive `time.After` in select loops | `time.NewTimer` + `Reset()` |
| `json.Decoder` for untrusted streaming | Validate payload size; consider `io.LimitReader` |
