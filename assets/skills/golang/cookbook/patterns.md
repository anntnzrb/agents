# Patterns Cookbook

Recipes for common Go design patterns: functional options, dependency injection, logging, and more.

---

## Contents

- [Functional Options](#functional-options)
- [Functional Options with Validation](#functional-options-with-validation)
- [Constructor Injection](#constructor-injection)
- [Dependency Injection with uber-go/fx](#dependency-injection-with-uber-gofx)
- [fx Lifecycle Hooks](#fx-lifecycle-hooks)
- [Structured Logging with slog](#structured-logging-with-slog)
- [slog HandlerOptions and Context-Aware Logging](#slog-handleroptions-and-context-aware-logging)
- [Small Interfaces and Composition](#small-interfaces-and-composition)
- [Repository Pattern](#repository-pattern)

---
## Functional Options

**Problem**: How to create flexible constructors with optional configuration?

**Solution**:

```go
type Server struct {
    host    string
    port    int
    timeout time.Duration
}

type Option func(*Server)

func WithHost(host string) Option {
    return func(s *Server) { s.host = host }
}

func WithPort(port int) Option {
    return func(s *Server) { s.port = port }
}

func WithTimeout(d time.Duration) Option {
    return func(s *Server) { s.timeout = d }
}

func NewServer(opts ...Option) *Server {
    s := &Server{
        host:    "localhost",
        port:    8080,
        timeout: 30 * time.Second,
    }
    for _, opt := range opts {
        opt(s)
    }
    return s
}

// Usage
server := NewServer(
    WithHost("0.0.0.0"),
    WithPort(9000),
)
```

**Tip**: Set sensible defaults before applying options. Options only override what's explicitly set. This pattern composes well — callers add options without changing signatures.

---

## Functional Options with Validation

**Problem**: How to validate option values and return configuration errors?

**Solution**:

```go
type Option func(*Config) error

func WithPort(port int) Option {
    return func(c *Config) error {
        if port < 1 || port > 65535 {
            return fmt.Errorf("invalid port: %d", port)
        }
        c.port = port
        return nil
    }
}

func WithTimeout(d time.Duration) Option {
    return func(c *Config) error {
        if d <= 0 {
            return fmt.Errorf("timeout must be positive, got %v", d)
        }
        c.timeout = d
        return nil
    }
}

func NewConfig(opts ...Option) (*Config, error) {
    c := &Config{port: 8080, timeout: 30 * time.Second}
    for _, opt := range opts {
        if err := opt(c); err != nil {
            return nil, err
        }
    }
    return c, nil
}
```

**Tip**: Return errors from option functions for validation. This catches misconfigurations at startup instead of at runtime. Each option validates its own domain — keep validation logic colocated with the option.

---

## Constructor Injection

**Problem**: How to make code testable and explicit about its dependencies?

**Solution**:

```go
type UserService struct {
    repo   UserRepository
    logger *slog.Logger
}

func NewUserService(repo UserRepository, logger *slog.Logger) *UserService {
    return &UserService{repo: repo, logger: logger}
}

// Interface defined at the consumer — not the implementation package
type UserRepository interface {
    Get(ctx context.Context, id string) (*User, error)
    Save(ctx context.Context, user *User) error
}

```

**Tip**: Accept interfaces, return structs. Define interfaces where they are consumed, not where they are implemented. This keeps interfaces small and relevant. Do not inject `context.Context` — pass it as the first parameter to methods.

---

## Dependency Injection with uber-go/fx

**Problem**: How to wire up complex dependency graphs automatically?

**Solution**:

```go
import "go.uber.org/fx"

func main() {
    fx.New(
        fx.Provide(
            NewConfig,
            NewLogger,
            NewDatabase,
            NewUserRepository,
            NewUserService,
            NewHTTPServer,
        ),
        fx.Invoke(func(server *HTTPServer) {
            // Server starts automatically
        }),
    ).Run()
}

// Constructors receive dependencies automatically
func NewUserService(repo UserRepository, log *slog.Logger) *UserService {
    return &UserService{repo: repo, logger: log}
}
```

**Tip**: fx resolves dependencies by type. Use `fx.Annotate` with named groups or tags when multiple implementations of the same type exist. For most applications, manual constructor injection is simpler and clearer — reach for fx when the dependency graph grows beyond 10+ constructors.

---

## fx Lifecycle Hooks

**Problem**: How to manage startup and shutdown of resources in fx?

**Solution**:

```go
func NewDatabase(lc fx.Lifecycle) *sql.DB {
    db := connectDB()

    lc.Append(fx.Hook{
        OnStart: func(ctx context.Context) error {
            return db.PingContext(ctx)
        },
        OnStop: func(ctx context.Context) error {
            return db.Close()
        },
    })

    return db
}
```

**Tip**: OnStart hooks run in dependency order; OnStop hooks run in reverse order. Each hook receives a context with the startup/shutdown timeout.

---

## Structured Logging with slog

**Problem**: How to produce structured, machine-readable logs without third-party libraries?

**Solution**:

```go
import "log/slog"

func main() {
    logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))

    logger.Info("server started",
        "port", 8080,
        "env", os.Getenv("ENV"),
    )

    // Attributed errors
    logger.Error("database connection failed",
        "dsn", dsn,
        "retries", 3,
        slog.Any("err", err),
    )

    // Log groups for related fields
    logger.Info("request completed",
        slog.Group("request",
            "method", r.Method,
            "path", r.URL.Path,
        ),
        slog.Group("response",
            "status", status,
            "duration", time.Since(start),
        ),
    )
}
```

**Tip**: Use `slog.NewJSONHandler` for production (parseable), `slog.NewTextHandler` for development (readable). Pass loggers as constructor dependencies — never use a package-level global logger.

---

## slog HandlerOptions and Context-Aware Logging

**Problem**: How to control log levels, add static attributes, and propagate context values to logs?

**Solution**:

```go
// Handler with custom level and static attributes
handler := slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
    Level: slog.LevelInfo,
    ReplaceAttr: func(groups []string, a slog.Attr) slog.Attr {
        if a.Key == "time" {
            a.Value = slog.StringValue(a.Value.Time().UTC().Format(time.RFC3339))
        }
        return a
    },
})

logger := slog.New(handler.WithAttrs([]slog.Attr{
    slog.String("service", "api"),
    slog.String("version", version),
}))

// Extract attributes from context
func handleRequest(logger *slog.Logger, r *http.Request) {
    ctx := r.Context()
    logger.InfoContext(ctx, "handling request")
    // Note: stdlib handlers do NOT automatically extract context values.
    // Pass attributes explicitly or install a custom handler that reads from ctx.
}

// Injecting request-scoped fields into context without passing logger around
func logMiddleware(logger *slog.Logger, next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        ctx := context.WithValue(r.Context(), requestIDKey, generateID())
        r = r.WithContext(ctx)

        logger.LogAttrs(ctx, slog.LevelInfo, "request started",
            slog.String("request_id", requestIDFrom(ctx)),
            slog.String("method", r.Method),
        )
        next.ServeHTTP(w, r)
    })
}
```

**Tip**: `slog.LogAttrs` is the most efficient way to log — it avoids `any` allocation for attribute values. Use `HandlerOptions.AddSource` to include file/line in development. Use `HandlerOptions.ReplaceAttr` to redact secrets or reformat timestamps.

---

## Small Interfaces and Composition

**Problem**: How to design interfaces that are easy to implement, mock, and compose?

**Solution**:

```go
// Small, focused interfaces — 1-2 methods each
type Reader interface {
    Read(p []byte) (n int, err error)
}

type Writer interface {
    Write(p []byte) (n int, err error)
}

type Closer interface {
    Close() error
}

// Compose for broader contracts
type ReadWriteCloser interface {
    Reader
    Writer
    Closer
}

// Consumer-side example
type UserFetcher interface {
    Fetch(ctx context.Context, id string) (*User, error)
}

// A handler depends only on what it needs
func NewHandler(fetcher UserFetcher, logger *slog.Logger) *Handler {
    return &Handler{fetcher: fetcher, logger: logger}
}
```

**Tip**: The bigger the interface, the weaker the abstraction. Prefer 1-2 methods per interface. Compose small interfaces into larger ones at the call site when needed. Define interfaces where they are consumed, not where they are implemented.

---

## Repository Pattern

**Problem**: How to abstract data access behind a clean, testable interface?

**Solution**:

```go
type UserRepository interface {
    Get(ctx context.Context, id string) (*User, error)
    List(ctx context.Context, filter UserFilter) ([]*User, error)
    Create(ctx context.Context, user *User) error
    Update(ctx context.Context, user *User) error
    Delete(ctx context.Context, id string) error
}

type postgresUserRepo struct {
    db *sql.DB
}

func NewUserRepository(db *sql.DB) UserRepository {
    return &postgresUserRepo{db: db}
}

func (r *postgresUserRepo) Get(ctx context.Context, id string) (*User, error) {
    var user User
    err := r.db.QueryRowContext(ctx,
        "SELECT id, name, email FROM users WHERE id = $1", id,
    ).Scan(&user.ID, &user.Name, &user.Email)
    if errors.Is(err, sql.ErrNoRows) {
        return nil, ErrNotFound
    if err != nil {
        return nil, fmt.Errorf("querying user %s: %w", id, err)
    }
    return &user, nil
}
```

**Tip**: Always accept `context.Context` as the first parameter. Translate database-specific errors (`sql.ErrNoRows`) to domain-level sentinel errors so callers don't import the database driver.
