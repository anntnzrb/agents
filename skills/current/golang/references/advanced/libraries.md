# Go 2026 Library Defaults

`stdlib` default; add a dependency only when a rule below gives a reason. Read only the heading matching the task.

## HTTP framework

`gin` default; `chi` minimalist; `net/http` no-dependency option.

Gin rationale: largest middleware/examples/SO ecosystem; CLIProxyAPI uses it in production for OpenAI/Gemini/Claude proxying, SSE, and WebSocket upgrades; `gin.Context` simplifies request-scoped middleware composition. This is ecosystem/reference-code preference, not technical superiority.

```go
import "github.com/gin-gonic/gin"

func main() {
    r := gin.New()
    r.Use(gin.Recovery(), middleware.RequestLogger(), middleware.RequestID())
    r.GET("/healthz", func(c *gin.Context) { c.JSON(200, gin.H{"ok": true}) })
    _ = r.Run(":8080")
}
```

Choose `chi` when handlers must be `net/http`-compatible or the service is small and does not need Gin binding helpers. Choose `net/http` directly when `<10` routes and zero auth complexity; Go 1.22 method+path `ServeMux` patterns remove most historical framework motivation.

NEVER use `gorilla/mux` (effectively maintenance), `fiber` (`fasthttp` is not stdlib-compatible; middleware ecosystems split), or `echo` (smaller ecosystem, no real current advantage).

## RPC

Default: `connectrpc/connect-go`; use Connect, not raw `grpc-go`, unless a measured reason applies. Connect is gRPC-wire-compatible and supports HTTP/1.1, HTTP/2, and Connect protocol: one server, gRPC/gRPC-Web/Connect-Web browser clients. Streaming, interceptors, deadlines, and errors are first-class. Buf (`buf generate`, `buf lint`, `buf breaking`) is preferred over `protoc`.

Debugging can use `curl -H "Content-Type: application/json" -d ...`; `grpcurl` is not required.

```go
// Server
mux := http.NewServeMux()
mux.Handle(elizav1connect.NewElizaServiceHandler(&elizaServer{}))
_ = http.ListenAndServe(":8080", h2c.NewHandler(mux, &http2.Server{}))

// Client
client := elizav1connect.NewElizaServiceClient(
    http.DefaultClient,
    "http://localhost:8080",
)
res, err := client.Say(ctx, connect.NewRequest(&elizav1.SayRequest{Sentence: "hi"}))
```

Use raw `grpc-go` only for server-streaming from multiple services through one gRPC mux or strict gRPC-only environments (for example, Envoy with gRPC reflection or Istio strict-gRPC).

## Database

Default stack: `pgx/v5` + `sqlc` + `goose`.

```bash
go get github.com/jackc/pgx/v5
go install github.com/sqlc-dev/sqlc/cmd/sqlc@latest
go install github.com/pressly/goose/v3/cmd/goose@latest
```

- `pgx/v5`: faster, more type-safe, and more PostgreSQL coverage than `database/sql + lib/pq`; use `pgxpool` for pooling. Avoid `database/sql` driver mode: it loses pgx batch, COPY, and listen/notify.
- `sqlc`: type-safe Go from `.sql`; prefer it over hand-written SQL plus hand-written struct mapping, a major source of subtle DB bugs.
- `goose`: small, CLI-first migrations with no global state.

NEVER use `gorm` (active record, slow, reflection in hot paths, encourages N+1) or `ent` (heavy, opinionated graph layer), unless you specifically want a graph-shaped data model.

## Validation

Three boundaries:

|Layer|Tool|Pattern|
|---|---|---|
|HTTP (`gin`/`chi`/`net/http`)|`go-playground/validator/v10` via struct tags|`binding:"required,email,min=3"`|
|RPC (protobuf)|`bufbuild/protovalidate-go`|`(buf.validate.field).string.min_len = 3` in `.proto`|
|Domain|Smart constructor + unexported fields|`NewEmail(s) (Email, error)`|

```go
// HTTP boundary
type CreateUserReq struct {
    Email    string `json:"email" binding:"required,email"`
    Username string `json:"username" binding:"required,alphanum,min=3,max=32"`
}

// Domain: once a value is of type Email it is provably valid
type Email struct{ raw string }
func NewEmail(s string) (Email, error) {
    if !emailRegex.MatchString(s) { return Email{}, ErrInvalidEmail }
    return Email{raw: strings.ToLower(s)}, nil
}
func (e Email) String() string { return e.raw }
```

Parse raw boundary input into the domain type once. Inside the domain, no further validation: unexported fields and the constructor prove validity.

## Logging

Default: stdlib `log/slog` (stdlib since 1.21, stable since 1.23). Structured performance is on par with zerolog and well ahead of logrus; major OpenTelemetry, Datadog, and Honeycomb exporters implement `slog.Handler`.

```go
import "log/slog"

logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
    Level:     slog.LevelInfo,
    AddSource: true,
}))
slog.SetDefault(logger)

slog.InfoContext(ctx, "request handled",
    slog.String("path", r.URL.Path),
    slog.Int("status", 200),
    slog.Duration("elapsed", elapsed),
)
```

New code: ban `logrus`, `zap`, `zerolog`; existing projects may keep them, but new files use `slog`. Use `sloglint` from `golangci-strict.md`; prefer `slog.String(...)` over `slog.Any(...)`.

## CLI

Default: `cobra` + `pflag` + `slog`; Cobra is the de facto framework.

```bash
go install github.com/spf13/cobra-cli@latest
cobra-cli init mytool
cobra-cli add server
```

`viper` is optional for file+env+flag merging. Prefer `caarlos0/env/v11` for env-only 12-factor configuration; use Viper only when file-based config is genuinely needed.

## TUI

Default: `charm.land/bubbletea/v2` RC + `bubbles v2` + `lipgloss v2`; NEVER v1.

- `tea.View{Cursor: *tea.Cursor, ...}`: real-cursor positioning.
- Textareas: `SetVirtualCursor(false)` lets the terminal own the cursor; required for CJK IME (Korean Hangul, Japanese kana→kanji, Chinese pinyin).
- Mouse: `MouseClickMsg`, `MouseMotionMsg`, `MouseReleaseMsg`, replacing v1 coarse `MouseMsg`.

If text input and CJK users are both in scope, v1 is broken: it cannot correctly position the IME candidate window.

## HTTP client

Default: `net/http.Client` with tuned `http.Transport`; stdlib provides HTTP/2 by default and connection pooling, but configure timeouts.

```go
client := &http.Client{
    Timeout: 30 * time.Second,
    Transport: &http.Transport{
        MaxIdleConns:        200,
        MaxIdleConnsPerHost: 40,
        IdleConnTimeout:     90 * time.Second,
        DisableCompression:  false,
        ForceAttemptHTTP2:   true,
    },
}
```

Retry/backoff: add `github.com/hashicorp/go-retryablehttp` as a small wrapper. NEVER use `resty` (magic, hides headers, wrong-default risk). `req` is acceptable but adds dependency surface for marginal benefit over stdlib + retry wrapper.

## JSON

Default: stdlib `encoding/json` (substantially improved since Go 1.21).

Measured hot-path bottleneck only: `goccy/go-json` (~3× faster, drop-in API):

```go
import json "github.com/goccy/go-json"
// drop-in replacement: same API
```

Production proxies doing thousands of RPS of JSON traversal: `bytedance/sonic` (~5× faster; requires amd64/arm64). For large-payload partial-tree mutation without full unmarshal, CLIProxyAPI uses `tidwall/gjson` + `tidwall/sjson`; this is a different optimization.

## Concurrency primitives

Use stdlib plus stdlib-quality `golang.org/x/sync` packages (outside `std`) only:

|Need|Use|
|---|---|
|Goroutine group + error propagation|`golang.org/x/sync/errgroup`|
|Semaphore|`golang.org/x/sync/semaphore`|
|Single-flight dedup|`golang.org/x/sync/singleflight`|
|Typed lazy init|`sync.OnceValue` / `sync.OnceFunc` (Go 1.21+; replaces `sync.Once` for typed values)|
|Atomic counter|`atomic.Int64` (Go 1.19+; not old func-style atomics)|
|Channel fanout|`chan T` + `errgroup` for shutdown|

## Time

Default: stdlib plus `benbjohnson/clock` in tests. NEVER call `time.Now()` directly in domain code; inject `Clock` for deterministic tests and no `time.Sleep` flakiness.

```go
type Clock interface { Now() time.Time }
// Production
var realClock Clock = clockImpl{}
// Test
fake := clock.NewMock()
fake.Set(time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC))
```

## IDs

Default: `google/uuid`, UUID v7; use v4 when leaking creation time is a privacy concern. v7 is sortable/time-ordered, random, and 128-bit.

```go
import "github.com/google/uuid"
id := uuid.Must(uuid.NewV7())  // sortable, time-ordered, 128-bit
```

Short URL-safe sortable IDs (~12 bytes): `rs/xid` (Kubernetes-style).

## Crypto

Use stdlib `crypto/*` for everything except passwords. Password default: `alecthomas/argon2id`; Argon2id is the 2026 standard and OWASP recommendation since 2023. bcrypt remains acceptable.

```go
import "github.com/alecthomas/argon2id"
hash, err := argon2id.CreateHash("password", argon2id.DefaultParams)
```

## Data

Default stack: `apache/arrow-go/v18` + `marcboeker/go-duckdb` + `gonum`.

|Need|Use|
|---|---|
|Tabular CSV/Parquet/JSON|DuckDB-Go bindings; zero-copy Arrow integration|
|In-memory frame|Arrow + custom code; no pandas equivalent needed|
|Numerical|`gonum.org/v1/gonum`|
|Stats|`gonum/stat`|

For heavy data work, use a Polars/DuckDB pipeline, expose Parquet or Arrow, and consume it from Go.

## Testing

|Need|Use|
|---|---|
|Assertions|`stretchr/testify/require` fail-fast; `assert` only in table-driven loops|
|Snapshots/golden|`hexops/autogold/v2`, auto-updates with `-update`|
|Property-based|`pgregory.net/rapid` or stdlib `testing/quick`|
|Mocks|`go.uber.org/mock` (gomock successor)|
|Outbound HTTP mocks|`h2non/gock`|
|Inbound HTTP|stdlib `httptest`|
|Integration containers|`testcontainers/testcontainers-go`|
|Goroutine leaks|`go.uber.org/goleak`|
|Benchmarks|stdlib `testing.B` + `perf.dev/benchstat`|

## Config

Default: `caarlos0/env/v11`; pure 12-factor, with struct-tag defaults, required markers, and parsing for `time.Duration`, slices, and maps. Use Viper only for file-based config.

```go
type Config struct {
    Port        int           `env:"PORT" envDefault:"8080"`
    DatabaseURL string        `env:"DATABASE_URL,required"`
    Timeout     time.Duration `env:"TIMEOUT" envDefault:"30s"`
}

var cfg Config
if err := env.Parse(&cfg); err != nil { log.Fatal(err) }
```

## New-dependency checklist

Before `go get`:

1. Maintained: latest tag within 12 months and active owner?
2. Stdlib-compatible types (`io.Reader`, `context.Context`, `http.Handler`)? Custom `Connection`/`Request` types are a yellow flag.
3. `init()` side effects? **REJECT**; they ruin testability.
4. `log.Fatal`/`panic` outside true programmer-error paths? **REJECT**.
5. `context.Context` first argument? If not, **REJECT**; cancellation is non-negotiable.
6. Overlap with existing `go.mod` dependency? Pick one.
