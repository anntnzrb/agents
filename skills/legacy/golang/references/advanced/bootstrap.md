# Bootstrap: Project Layout, Toolchain, Taskfile, CI

## Index

Read the heading matching the task; search headings before loading unrelated detail. Create project files with repository-normal tooling, not a bundled scaffold.

## Toolchain pin

Monorepo: `go.work`; single module: `go.mod` `go 1.23`. Go 1.21+ auto-downloads the matching toolchain when local `go` is older. No `.tool-versions` / `asdf` / `mise` indirection unless shop-standard.

```bash
# Confirm a working toolchain
go env GOTOOLCHAIN   # should be "auto" or your pinned version
go version           # ≥ 1.23
```

## Required global installs

Install once per machine via `go install`:

```bash
go install mvdan.cc/gofumpt@latest
go install golang.org/x/tools/cmd/goimports@latest
go install github.com/golangci/golangci-lint/cmd/golangci-lint@v2.0.0
go install go.uber.org/nilaway/cmd/nilaway@latest
go install github.com/sqlc-dev/sqlc/cmd/sqlc@latest
go install github.com/pressly/goose/v3/cmd/goose@latest
go install go.uber.org/mock/mockgen@latest
go install github.com/go-task/task/v3/cmd/task@latest
```

Connect/protobuf projects additionally:

```bash
go install github.com/bufbuild/buf/cmd/buf@latest
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install connectrpc.com/connect/cmd/protoc-gen-connect-go@latest
```

## Project layout: canonical tree

```
myservice/
├── go.mod
├── go.sum
├── Taskfile.yml               # task runner
├── .golangci.yml              # see golangci-strict.md
├── .editorconfig
├── .gitignore
├── README.md
├── AGENTS.md                  # agent-readable project facts
├── cmd/
│   └── server/
│       └── main.go            # ONLY: parse flags, call cmd.Execute(); ≤ 50 LOC
├── internal/                  # NEVER importable from outside this module
│   ├── api/                   # transport layer (gin/connect routers)
│   │   ├── server.go          # gin engine setup, route registration
│   │   ├── middleware/
│   │   │   ├── request_id.go
│   │   │   ├── logging.go
│   │   │   └── auth.go
│   │   └── handlers/
│   │       ├── users.go
│   │       └── users_test.go
│   ├── domain/                # parse-don't-validate types, smart constructors
│   │   ├── user.go
│   │   └── email.go
│   ├── service/               # business logic, depends on domain only
│   │   └── user_service.go
│   ├── store/                 # persistence; sqlc-generated code lives here
│   │   ├── sqlc/              # sqlc-generated, do not hand-edit
│   │   ├── queries/           # *.sql files sqlc reads
│   │   └── migrations/        # goose migrations
│   ├── config/                # env-driven config (caarlos0/env)
│   │   └── config.go
│   └── obs/                   # observability: slog setup, otel, healthz
│       └── logger.go
├── pkg/                       # exportable libraries; only if you publish
│   └── …
├── proto/                     # *.proto definitions (Connect/gRPC projects)
│   └── service.proto
├── gen/                       # generated code (Connect, OpenAPI)
│   └── service/v1/
│       ├── service.pb.go
│       └── servicev1connect/
├── test/                      # cross-cutting test helpers, fixtures
└── .github/workflows/ci.yml
```

Rules:
- `cmd/<binary>/main.go` ≤ 50 LOC; move excess to `internal/cmd/`.
- `internal/` is the business code; other modules cannot import it (Go compiler-enforced).
- `pkg/` only for libraries genuinely intended for third-party import; empty until proven otherwise.
- No `utils/`, `helpers/`, `common/`, or `shared/`: **REJECT**. Name files after the concept they own.
- One package per directory.
- One responsibility per package.

## `Taskfile.yml`: entry point for every action

`go-task/task` is the cross-platform YAML Make replacement.

```yaml
version: '3'

vars:
  BINARY: server
  PKG: ./cmd/server

tasks:
  default:
    deps: [fmt, lint, test]

  fmt:
    desc: Format all Go files
    cmds:
      - gofumpt -w .
      - goimports -w -local "$(go list -m)" .

  lint:
    desc: Run all linters
    cmds:
      - golangci-lint run --timeout 5m ./...
      - nilaway -include-pkgs "$(go list -m)/..." ./...

  test:
    desc: Run tests with race detector
    cmds:
      - go test -race -shuffle=on -count=1 ./...

  test-cover:
    desc: Coverage report
    cmds:
      - go test -race -shuffle=on -count=1 -coverprofile=coverage.out ./...
      - go tool cover -html=coverage.out -o coverage.html

  build:
    desc: Build the binary
    cmds:
      - go build -trimpath -ldflags="-s -w" -o bin/{{.BINARY}} {{.PKG}}

  run:
    desc: Run the server locally
    deps: [build]
    cmds:
      - ./bin/{{.BINARY}}

  gen:
    desc: Run all code generators
    cmds:
      - task: gen:sqlc
      - task: gen:mocks
      - task: gen:proto

  gen:sqlc:
    cmds:
      - sqlc generate
    sources:
      - internal/store/queries/*.sql
      - internal/store/sqlc.yaml
    generates:
      - internal/store/sqlc/*.go

  gen:mocks:
    cmds:
      - go generate ./...

  gen:proto:
    cmds:
      - buf generate
    sources:
      - proto/**/*.proto
      - buf.yaml
      - buf.gen.yaml

  migrate:up:
    cmds:
      - goose -dir internal/store/migrations postgres "$DATABASE_URL" up

  migrate:down:
    cmds:
      - goose -dir internal/store/migrations postgres "$DATABASE_URL" down

  ci:
    desc: Everything CI does, locally
    deps: [fmt, lint, test, build]
```

`task` with no args runs format + lint + test, parallel where possible; `task ci` runs the full pipeline.

## `go.mod` template

```go
module github.com/your-org/myservice

go 1.23

require (
    github.com/caarlos0/env/v11 v11.2.2
    github.com/gin-gonic/gin v1.10.1
    github.com/go-playground/validator/v10 v10.22.1
    github.com/google/uuid v1.6.0
    github.com/jackc/pgx/v5 v5.7.6
    golang.org/x/sync v0.18.0
)
```

List direct dependencies only; `go mod tidy` populates indirects.

## `.editorconfig`

```ini
root = true

[*]
indent_style = tab
indent_size = 4
end_of_line = lf
charset = utf-8
trim_trailing_whitespace = true
insert_final_newline = true

[*.{yml,yaml,json,md}]
indent_style = space
indent_size = 2
```

## `.gitignore`

```gitignore
bin/
coverage.out
coverage.html
*.test
*.prof

# IDE
.idea/
.vscode/
*.swp

# Local env
.env
.env.local

# Secrets
*.pem
*.key
```

## CI: minimal GitHub Actions

`.github/workflows/ci.yml`:

```yaml
name: ci
on:
  pull_request:
  push:
    branches: [main]

jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version: '1.23'
          cache: true

      - name: Install tools
        run: |
          go install mvdan.cc/gofumpt@latest
          go install github.com/golangci/golangci-lint/cmd/golangci-lint@v2.0.0
          go install go.uber.org/nilaway/cmd/nilaway@latest
          go install github.com/go-task/task/v3/cmd/task@latest

      - name: Format check
        run: gofumpt -l . | (! grep .)

      - name: Lint
        run: golangci-lint run --timeout 5m ./...

      - name: Nilaway
        run: nilaway ./...

      - name: Test
        run: go test -race -shuffle=on -count=1 ./...

      - name: Build
        run: go build -trimpath ./...
```

CI order is format → lint → nilaway → test → build; fail fast on cheap checks.

## `AGENTS.md`: agent-readable project facts

Every new project gets root `AGENTS.md`: machine-friendly, short, declarative, no marketing prose. Example:

```markdown
# AGENTS.md

Go 1.23+ HTTP service for {one-line purpose}.

## Commands
- `task`: fmt + lint + test
- `task build`: produce ./bin/server
- `task gen`: regenerate sqlc + mocks + proto

## Architecture
- `cmd/server/main.go`: entrypoint, ≤50 LOC
- `internal/api/`: gin handlers + middleware
- `internal/domain/`: smart-constructor types, no I/O
- `internal/store/sqlc/`: generated; never hand-edit

## Conventions
- `slog` for all logs; never `log.*`, never `fmt.Println`
- `context.Context` first arg for every public function
- Errors wrapped with `%w`; check with `errors.Is/As`
- 250 pure LOC ceiling per file: split before adding lines
```

`cmd/new-project.go` writes `AGENTS.md` with project-specific values filled in.

## Sources

- Go modules reference: https://go.dev/ref/mod
- go-task: https://taskfile.dev
- golangci-lint v2: https://golangci-lint.run/docs/configuration/
- Standard project layout debate: https://go.dev/doc/modules/layout (NOT `golang-standards/project-layout`; community, not official)
