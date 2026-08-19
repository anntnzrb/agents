# Go Patterns Cookbook

## Functional Options

Flexible constructors with optional configuration: define `Option func(*Server)`, initialize defaults, then apply options in caller order; options override only explicitly set fields and compose without signature changes.

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

## Functional Options with Validation

Validate each option in its own domain; return errors to catch misconfiguration at startup rather than runtime.

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

## Constructor Injection

Accept interfaces, return structs. Define interfaces at the consumer, not implementation package, to keep them small/relevant. Do not inject `context.Context`; pass it as each method’s first parameter.

```go
type UserService struct {
    repo   UserRepository
    logger *slog.Logger
}

func NewUserService(repo UserRepository, logger *slog.Logger) *UserService {
    return &UserService{repo: repo, logger: logger}
}

// Interface defined at the consumer: not the implementation package
type UserRepository interface {
    Get(ctx context.Context, id string) (*User, error)
    Save(ctx context.Context, user *User) error
}

```

## Dependency Injection with uber-go/fx

`fx` resolves dependencies by type. Use `fx.Annotate` named groups/tags for multiple implementations. Manual constructor injection is usually simpler; use `fx` when the graph exceeds 10+ constructors.

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

## fx Lifecycle Hooks

`OnStart` runs in dependency order; `OnStop` runs in reverse. Each hook receives a context with the startup/shutdown timeout.

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

## Structured Logging with slog

Use `slog.NewJSONHandler` in production (parseable), `slog.NewTextHandler` in development (readable). Pass loggers as constructor dependencies; never use a package-level global logger.

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

## slog HandlerOptions and Context-Aware Logging

`HandlerOptions.Level` controls level; `WithAttrs` adds static attributes. `ReplaceAttr` can redact secrets or reformat timestamps; `AddSource` includes file/line in development. `slog.LogAttrs` is most efficient because it avoids `any` allocation for attribute values. Stdlib handlers do **not** automatically extract context values: pass attributes explicitly or install a handler that reads `ctx`.

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

## Small Interfaces and Composition

Prefer focused 1-2-method interfaces: larger interfaces weaken abstractions. Define them at the consumer; compose small interfaces into broader contracts at the call site. Depend only on what the handler needs.

```go
// Small, focused interfaces: 1-2 methods each
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

## Repository Pattern

Abstract data access behind a testable interface. Always accept `context.Context` first. Translate database-specific errors such as `sql.ErrNoRows` to domain sentinel errors so callers need not import the driver.

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
