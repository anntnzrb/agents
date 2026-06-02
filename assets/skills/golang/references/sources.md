# Source Ledger

Last checked: 2026-06-02

Authoritative sources for this skill. Update this file before refreshing any skill content.
Prefer official sources; mark community/ecosystem sources explicitly.

## Go Releases & Language

| Source | URL | Type | Notes |
|---|---|---|---|
| Go 1.26 Release Notes | https://go.dev/doc/go1.26 | Official | Current stable baseline |
| Go 1.25 Release Notes | https://go.dev/doc/go1.25 | Official | |
| Go 1.24 Release Notes | https://go.dev/doc/go1.24 | Official | Swiss Tables, tool directive |
| Go 1.23 Release Notes | https://go.dev/doc/go1.23 | Official | iter.Seq stable |
| Go 1.22 Release Notes | https://go.dev/doc/go1.22 | Official | Loop vars, ServeMux routing |
| Go Release Policy | https://tip.golang.org/doc/devel/release | Official | Support window |
| Go end-of-life tracker | https://endoflife.date/go | Community | Quick version support lookup |
| Go toolchain docs | https://go.dev/doc/toolchain | Official | Toolchain directive |
| Go module layout docs | https://go.dev/doc/modules/layout | Official | Project structure guidance |

## Standard Library & Language Reference

| Source | URL | Type | Notes |
|---|---|---|---|
| pkg.go.dev (stdlib) | https://pkg.go.dev/std | Official | Package docs |
| Effective Go | https://go.dev/doc/effective_go | Official | Frozen; modernization proposal in flight |
| Go Proverbs | https://go-proverbs.github.io/ | Community | Rob Pike's proverbs, unchanged canon |
| Go Blog | https://go.dev/blog/ | Official | Release deep-dives, Swiss Tables, workspaces |
| The Go Programming Language Spec | https://go.dev/ref/spec | Official | |

## Style & Idioms

| Source | URL | Type | Notes |
|---|---|---|---|
| Uber Go Style Guide | https://github.com/uber-go/guide | Community | Living document, actively maintained |
| Go Code Review Comments | https://go.dev/wiki/CodeReviewComments | Official | |
| Russ Cox on project layout | https://github.com/golang/go/issues/45861 | Official | Rejects golang-standards/project-layout |

## Tooling

| Source | URL | Type | Notes |
|---|---|---|---|
| golangci-lint v2 docs | https://golangci-lint.run | Primary | current v2.12.x |
| golangci-lint releases | https://github.com/golangci/golangci-lint/releases | Primary | |
| gopls | https://github.com/golang/tools/tree/master/gopls | Official | LSP server |
| gofumpt | https://github.com/mvdan/gofumpt | Community | Stricter gofmt |
| buf | https://buf.build/docs | Primary | Proto toolchain |
| goreleaser v2 | https://goreleaser.com | Primary | Release automation |
| Air | https://github.com/air-verse/air | Community | Live reload |
| Taskfile | https://taskfile.dev | Community | Task runner |
| staticcheck | https://staticcheck.dev | Community | Standalone analysis |

## Testing

| Source | URL | Type | Notes |
|---|---|---|---|
| testing package | https://pkg.go.dev/testing | Official | Stdlib testing |
| testing/synctest | https://pkg.go.dev/testing/synctest | Official | Go 1.25+ stable |
| testing/slogtest | https://pkg.go.dev/testing/slogtest | Official | Go 1.25+ stable |
| testify | https://github.com/stretchr/testify | Community | Assertions/mocking (inherited projects) |
| uber-go/mock | https://go.uber.org/mock | Community | Successor to archived golang/mock |
| testcontainers-go | https://golang.testcontainers.org | Primary | Integration test containers |

## HTTP & API

| Source | URL | Type | Notes |
|---|---|---|---|
| net/http (Go 1.22+) | https://pkg.go.dev/net/http@go1.22 | Official | Method routing, path params |
| chi | https://github.com/go-chi/chi | Primary | Thin stdlib-compatible router |
| connectrpc | https://connectrpc.com/docs/go/getting-started | Primary | gRPC-compatible HTTP APIs |
| a-h/templ | https://github.com/a-h/templ | Primary | Type-safe HTML templates |
| openapi-codegen | https://github.com/oapi-codegen | Community | OpenAPI to Go code generation |

## Database & SQL

| Source | URL | Type | Notes |
|---|---|---|---|
| pgx | https://github.com/jackc/pgx | Primary | Postgres driver |
| sqlc | https://github.com/sqlc-dev/sqlc | Primary | SQL-first codegen |
| GORM | https://github.com/go-gorm/gorm | Primary | ORM (when intentionally chosen) |
| sqlx | https://github.com/jmoiron/sqlx | Community | Extensions to database/sql |

## CLI & Config

| Source | URL | Type | Notes |
|---|---|---|---|
| cobra | https://github.com/spf13/cobra | Primary | CLI framework |
| kong | https://github.com/alecthomas/kong | Primary | Declarative struct-tag CLI |
| urfave/cli v3 | https://github.com/urfave/cli | Community | Simpler alternative |
| bubbletea | https://github.com/charmbracelet/bubbletea | Primary | TUI framework |
| viper | https://github.com/spf13/viper | Primary | Config management |

## Concurrency & Error Handling

| Source | URL | Type | Notes |
|---|---|---|---|
| errgroup | https://pkg.go.dev/golang.org/x/sync/errgroup | Official | golang.org/x |
| conc | https://github.com/sourcegraph/conc | Community | Structured concurrency |
| multierr | https://github.com/uber-go/multierr | Community | Error aggregation |

## Dependency Injection

| Source | URL | Type | Notes |
|---|---|---|---|
| fx | https://github.com/uber-go/fx | Primary | Runtime DI with lifecycle |
| wire | https://github.com/google/wire | Community | Compile-time DI |

## State of Go (ecosystem surveys)

| Source | URL | Type | Notes |
|---|---|---|---|
| State of Go 2026 | https://devnewsletter.com/p/state-of-go-2026/ | Community | Annual ecosystem pulse |
