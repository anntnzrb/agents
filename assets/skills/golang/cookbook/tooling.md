# Tooling Cookbook

Recipes for Go tooling: linting, formatting, LSP setup, protobuf, mocking, integration testing, and releases.

---

## Contents

- [golangci-lint v2 Configuration](#golangci-lint-v2-configuration)
- [gofumpt for Stricter Formatting](#gofumpt-for-stricter-formatting)
- [gopls — Official Go LSP](#gopls--official-go-lsp)
- [`go.mod` `tool` Directive (Go 1.24+)](#gomod-tool-directive-go-124)
- [buf for Protocol Buffers](#buf-for-protocol-buffers)
- [uber-go/mock for Mock Generation](#uber-gomock-for-mock-generation)
- [When to Prefer Hand-Written Fakes](#when-to-prefer-hand-written-fakes)
- [testcontainers-go for Integration Tests](#testcontainers-go-for-integration-tests)
- [Singleton Containers for Speed](#singleton-containers-for-speed)
- [goreleaser v2 Basic Configuration](#goreleaser-v2-basic-configuration)

---
## golangci-lint v2 Configuration

**Problem**: How to set up comprehensive linting with a modern golangci-lint v2 config?

**Solution**:

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

**Tip**: `default: standard` enables the recommended set. Add linters individually in `enable` rather than using `presets` — explicit opt-in makes it clear what's enforced. Run `golangci-lint config verify` to validate your config.

---

## gofumpt for Stricter Formatting

**Problem**: `gofmt` leaves some formatting decisions ambiguous. How to enforce stricter rules?

**Solution**:

`gofumpt` is a drop-in replacement for `gofmt` that enforces additional rules:

- No empty lines at the start or end of a function
- Consistent grouping of imports with blank lines
- Short inline var declarations (`var foo int = 1` → `foo := 1`)
- Removal of unnecessary trailing commas in composite literals
- Field lists always split across lines when any field does

Enable it in golangci-lint (as above) or run standalone:

```bash
gofumpt -l -w .
```

**Tip**: Configure your editor to run `gofumpt` on save. In VS Code, set `"go.formatTool": "gofumpt"` and use `"editor.formatOnSave": true`. In Neovim, synchronize `g:go_fmt_command` with `gofumpt`. `gofumpt` is a superset of `gofmt` — any `gofumpt`-formatted code passes `gofmt`.

---

## gopls — Official Go LSP

**Problem**: How to set up the Go language server for IDE features across multi-module workspaces?

**Solution**:

Install gopls:

```bash
go install golang.org/x/tools/gopls@latest
```

For multi-module workspaces, create a `go.work` file at the repo root:

```go
// go.work
go 1.26

use (
    ./services/api
    ./services/worker
    ./shared/lib
)
```

Run:

```bash
go work sync   # sync workspace vendor/module state
```

**Tip**: `go.work` lets gopls understand multiple modules without `replace` directives. It is local-only — never commit `go.work` to version control (add to `.gitignore`). For CI, build each module independently. Use `go work use -r .` to recursively discover modules.

---

## `go.mod` `tool` Directive (Go 1.24+)

**Problem**: How to pin tool versions without a `tools.go` file or a separate `tools` module?

**Solution**:

Add a `tool` directive to `go.mod`:

```
// go.mod
module example.com/app

go 1.26

tool (
    golang.org/x/tools/cmd/stringer
    google.golang.org/protobuf/cmd/protoc-gen-go
    github.com/golangci/golangci-lint/v2/cmd/golangci-lint
)
```

Then run tools with `go tool`:

```bash
go tool golang.org/x/tools/cmd/stringer -type=Status
go tool golangci-lint run ./...
```

**Tip**: The `tool` directive records exact versions in `go.mod` and checksums in `go.sum`. It replaces the old `tools.go` pattern (a `//go:build tools` file with blank imports). Tools declared here are not normal module dependencies — they don't affect the build graph.

---

## buf for Protocol Buffers

**Problem**: How to lint, generate, and detect breaking changes in protobuf schemas?

**Solution**:

`buf.gen.yaml` for code generation:

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

`buf.yaml` for lint and breaking change detection:

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

Commands:

```bash
buf lint                      # lint proto files
buf breaking --against '.git#branch=main'  # detect breaking changes
buf generate                  # generate Go code
```

**Tip**: `buf` replaces `protoc` with a single binary — no manual plugin management. The `remote` plugins are pre-built and cached. For breaking change detection in CI, compare against the merge-base: `buf breaking --against '.git#branch=main'`.

---

## uber-go/mock for Mock Generation

**Problem**: How to generate testify-compatible mocks from Go interfaces automatically?

**Solution**:

Install:

```bash
go install go.uber.org/mock/mockgen@latest
```

Annotate the interface file:

```go
//go:generate mockgen -destination=mocks/user_repo.go -package=mocks . UserRepository

type UserRepository interface {
    Get(ctx context.Context, id string) (*User, error)
    Create(ctx context.Context, user *User) error
}
```

Generate:

```bash
go generate ./...
```

Use the mock:

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

**Tip**: Call `ctrl.Finish()` (via `defer ctrl.Finish()`) to verify all expected calls were made. Use `gomock.Any()` for arguments you don't care about. Prefer hand-written fakes when the interface is small (1-2 methods) and the mock would obscure test intent — a simple stub struct is often clearer.

---

## When to Prefer Hand-Written Fakes

**Problem**: Generated mocks with ordered expectations can produce brittle tests. When is a hand-written fake better?

**Solution**:

```go
// A hand-written fake — no generation, no expectation matching:
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

// Test — no EXPECT() setup, just populate state:
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

**Tip**: Use generated mocks when you need to assert call counts, argument values, and call ordering against interfaces with 3+ methods. Use hand-written fakes for simple interfaces, stateful backends (like a fake DB), or when test readability matters more than call-level verification.

---

## testcontainers-go for Integration Tests

**Problem**: How to run integration tests against real databases without manual setup?

**Solution**:

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

**Tip**: Use `testcontainers.WithReuse()` for development — the container stays running across test runs. In CI, skip reuse to guarantee clean state. Always call `container.Terminate(ctx)` (or `testcontainers.CleanupContainer(t, container)`) to remove the container after the test.

---

## Singleton Containers for Speed

**Problem**: Starting a new container per test is slow. How to share one container across all tests in a package?

**Solution**:

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

**Tip**: Share the container across all tests in a package with `TestMain`. Each test connects to a separate database or schema to maintain isolation. For truly parallel test packages, use separate containers per package.

---

## goreleaser v2 Basic Configuration

**Problem**: How to automate cross-compiled Go releases for multiple platforms?

**Solution**:

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

**Tip**: `CGO_ENABLED=0` produces statically linked binaries — they run on any distro of the target OS. `-trimpath` removes absolute filesystem paths from binaries for reproducible builds. `-s -w` strips the symbol table and DWARF debug info, reducing binary size by ~30%.
