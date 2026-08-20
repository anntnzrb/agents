# Go Tooling Cookbook

Recipes: linting, formatting, LSP, protobuf, mocking, integration tests, releases.

## golangci-lint v2

```yaml
# .golangci.yml
version: "2"

linters:
  default: standard

  enable:
    - bodyclose       # unchecked HTTP response bodies
    - gosec           # security checks
    - gofumpt         # stricter gofmt
    - modernize       # suggest modern Go idioms (Go 1.22+)
    - nilerr          # nil-error returns
    - noctx           # http.Request without context
    - perfsprint      # inefficient Sprint*/Fprint* calls
    - revive          # fast, configurable metalinter
    - testifylint     # testify anti-patterns
    - usetesting      # testing.T.Setenv vs os.Setenv
    - wastedassign    # assigned but never read

  settings:
    gofumpt:
      extra-rules: true
    revive:
      rules:
        - name: exported
          severity: warning
```

`default: standard` enables recommended linters. Add individual linters under `enable`, not `presets`, for explicit enforcement. Validate with `golangci-lint config verify`.

## gofumpt

Stricter, drop-in `gofmt` replacement:

- No empty lines at function start/end.
- Consistent import grouping with blank lines.
- Short inline declarations: `var foo int = 1` → `foo := 1`.
- Remove unnecessary trailing commas in composite literals.
- Split field lists when any field splits.

Enable in golangci-lint or run:

```bash
gofumpt -l -w .
```

Run on editor save. VS Code: `"go.formatTool": "gofumpt"` and `"editor.formatOnSave": true`. Neovim: synchronize `g:go_fmt_command` with `gofumpt`. `gofumpt` is a `gofmt` superset; gofumpt-formatted code passes gofmt.

## gopls

```bash
go install golang.org/x/tools/gopls@latest
```

For multi-module workspaces, create `go.work` at repo root:

```go
// go.work
go 1.26

use (
    ./services/api
    ./services/worker
    ./shared/lib
)
```

```bash
go work sync   # sync workspace vendor/module state
```

`go.work` lets gopls understand multiple modules without `replace` directives. It is local-only: never commit it; add it to `.gitignore`. CI builds modules independently. Recursively discover modules with `go work use -r .`.

## `go.mod` `tool` directive (Go 1.24+)

Pin tools without `tools.go` or a separate `tools` module:

```go
// go.mod
module example.com/app

go 1.26

tool (
    golang.org/x/tools/cmd/stringer
    google.golang.org/protobuf/cmd/protoc-gen-go
    github.com/golangci/golangci-lint/v2/cmd/golangci-lint
)
```

```bash
go tool golang.org/x/tools/cmd/stringer -type=Status
go tool golangci-lint run ./...
```

`tool` records exact versions in `go.mod` and checksums in `go.sum`; it replaces the `//go:build tools` plus blank-imports pattern. Declared tools are not normal module dependencies and do not affect the build graph.

## buf

`buf.gen.yaml`:

```yaml
# buf.gen.yaml
version: v2
plugins:
  - remote: buf.build/protocolbuffers/go
    out: gen
    opt:
      - paths=source_relative
  - remote: buf.build/grpc/go
    out: gen
    opt:
      - paths=source_relative
```

`buf.yaml`:

```yaml
# buf.yaml
version: v2
modules:
  - path: proto
lint:
  use:
    - STANDARD
breaking:
  use:
    - FILE
```

```bash
buf lint                      # lint proto files
buf breaking --against '.git#branch=main'  # detect breaking changes
buf generate                  # generate Go code
```

`buf` replaces `protoc` with one binary, avoiding manual plugin management. Remote plugins are pre-built and cached. In CI, compare breaking changes against the merge-base with `.git#branch=main`.

## uber-go/mock

Install and generate mocks from interfaces:

```bash
go install go.uber.org/mock/mockgen@latest
```

```go
//go:generate mockgen -destination=mocks/user_repo.go -package=mocks . UserRepository

type UserRepository interface {
    Get(ctx context.Context, id string) (*User, error)
    Create(ctx context.Context, user *User) error
}
```

```bash
go generate ./...
```

```go
import (
    "go.uber.org/mock/gomock"
    "example.com/app/mocks"
)

func TestService(t *testing.T) {
    ctrl := gomock.NewController(t)
    mockRepo := mocks.NewMockUserRepository(ctrl)

    mockRepo.EXPECT().
        Get(gomock.Any(), "123").
        Return(&User{Name: "Alice"}, nil)

    svc := NewService(mockRepo)
    user, err := svc.GetUser(context.Background(), "123")

    assert.NoError(t, err)
    assert.Equal(t, "Alice", user.Name)
}
```

Use `defer ctrl.Finish()` to verify expected calls. Use `gomock.Any()` for irrelevant arguments. Prefer hand-written fakes for 1-2-method interfaces when mocks obscure intent.

## Hand-written fakes

Prefer fakes over generated mocks when ordered expectations would make tests brittle; use generated mocks for call counts, argument values, and ordering on interfaces with 3+ methods. Use fakes for simple interfaces, stateful backends such as fake DBs, or when readability outweighs call-level verification.

```go
// A hand-written fake: no generation, no expectation matching:
type FakeUserRepo struct {
    users map[string]*User
    err   error
}

func (f *FakeUserRepo) Get(ctx context.Context, id string) (*User, error) {
    if f.err != nil {
        return nil, f.err
    }
    return f.users[id], nil
}

func (f *FakeUserRepo) Create(ctx context.Context, user *User) error {
    if f.err != nil {
        return f.err
    }
    f.users[user.ID] = user
    return nil
}

// Test: no EXPECT() setup, just populate state:
func TestService(t *testing.T) {
    fake := &FakeUserRepo{users: map[string]*User{
        "1": {ID: "1", Name: "Alice"},
    }}
    svc := NewService(fake)
    user, err := svc.GetUser(context.Background(), "1")
    assert.NoError(t, err)
    assert.Equal(t, "Alice", user.Name)
}
```

## testcontainers-go

Run integration tests against real databases without manual setup:

```go
import (
    "github.com/testcontainers/testcontainers-go"
    "github.com/testcontainers/testcontainers-go/modules/postgres"
    "github.com/testcontainers/testcontainers-go/wait"
)

func TestWithPostgres(t *testing.T) {
    ctx := context.Background()

    container, err := postgres.Run(ctx,
        "postgres:17-alpine",
        postgres.WithDatabase("testdb"),
        postgres.WithUsername("test"),
        postgres.WithPassword("test"),
        testcontainers.WithWaitStrategy(
            wait.ForLog("database system is ready to accept connections").
                WithOccurrence(2),
        ),
    )
    require.NoError(t, err)
    defer container.Terminate(ctx)

    connStr, err := container.ConnectionString(ctx)
    require.NoError(t, err)

    db, err := sql.Open("pgx", connStr)
    require.NoError(t, err)
    defer db.Close()

    // Run migrations, then test...
}
```

`testcontainers.WithReuse()` keeps a container across development test runs; skip reuse in CI for clean state. Always call `container.Terminate(ctx)` or `testcontainers.CleanupContainer(t, container)`.

## Singleton containers

Share one container across a package with `TestMain`; isolate tests with separate databases or schemas. Use separate containers for truly parallel test packages.

```go
var (
    pgContainer *postgres.PostgresContainer
    pgConnStr   string
)

func TestMain(m *testing.M) {
    ctx := context.Background()
    container, err := postgres.Run(ctx,
        "postgres:17-alpine",
        postgres.WithDatabase("testdb"),
        postgres.WithUsername("test"),
        postgres.WithPassword("test"),
        testcontainers.WithWaitStrategy(
            wait.ForLog("database system is ready").
                WithOccurrence(2),
        ),
    )
    if err != nil {
        log.Fatalf("start postgres: %v", err)
    }
    pgContainer = container

    pgConnStr, err = container.ConnectionString(ctx)
    if err != nil {
        log.Fatalf("connection string: %v", err)
    }

    code := m.Run()

    // Cleanup
    container.Terminate(ctx)
    os.Exit(code)
}

// Each test gets a fresh schema within the shared container:
func TestCreateUser(t *testing.T) {
    db := connectDB(t, pgConnStr)
    setupSchema(t, db)
    defer db.Close()
    // ...
}
```

## goreleaser v2

Cross-compiled Go releases:

```yaml
# .goreleaser.yml
version: 2

builds:
  - id: default
    main: ./cmd/myapp
    binary: myapp
    goos:
      - linux
      - darwin
      - windows
    goarch:
      - amd64
      - arm64
    env:
      - CGO_ENABLED=0
    flags:
      - -trimpath
    ldflags:
      - -s -w
      - -X main.version={{ .Version }}

archives:
  - formats: [tar.gz]
    format_overrides:
      - goos: windows
        formats: [zip]

checksum:
  name_template: "checksums.txt"

changelog:
  sort: asc
  filters:
    exclude:
      - "^docs:"
      - "^ci:"
```

`CGO_ENABLED=0` produces statically linked binaries runnable on any target-OS distro. `-trimpath` removes absolute filesystem paths for reproducible builds. `-s -w` strips symbols and DWARF, reducing binary size by ~30%.
