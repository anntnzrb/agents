# HTTP Services Cookbook

Go 1.22+ standard-library routing, middleware, testing, and observability recipes.

## Go 1.22+ ServeMux Routing

```go
mux := http.NewServeMux()

// Method + path routing (Go 1.22+)
mux.HandleFunc("GET /users", listUsers)
mux.HandleFunc("POST /users", createUser)

// Path parameters
mux.HandleFunc("GET /users/{id}", getUser)
mux.HandleFunc("PUT /users/{id}", updateUser)
mux.HandleFunc("DELETE /users/{id}", deleteUser)

// Wildcard: matches everything under /static/
mux.HandleFunc("GET /static/", serveStatic)

// Reading path values in a handler:
func getUser(w http.ResponseWriter, r *http.Request) {
    id := r.PathValue("id")
    // ...
}
```

`{name}` matches one segment; `{name...}` matches multiple. `r.PathValue` returns `""` when absent; validate it.

## Building a REST Endpoint

```go
type UserHandler struct {
    repo   UserRepository
    logger *slog.Logger
}

func (h *UserHandler) Register(mux *http.ServeMux) {
    mux.HandleFunc("GET /users/{id}", h.Get)
    mux.HandleFunc("POST /users", h.Create)
}

func (h *UserHandler) Get(w http.ResponseWriter, r *http.Request) {
    id := r.PathValue("id")
    if id == "" {
        writeJSON(w, http.StatusBadRequest, map[string]string{"error": "missing id"})
        return
    }

    user, err := h.repo.Get(r.Context(), id)
    if err != nil {
        h.logger.Error("get user", "id", id, "error", err)
        writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
        return
    }
    if user == nil {
        writeJSON(w, http.StatusNotFound, map[string]string{"error": "not found"})
        return
    }

    writeJSON(w, http.StatusOK, user)
}

func (h *UserHandler) Create(w http.ResponseWriter, r *http.Request) {
    var user User
    if err := json.NewDecoder(r.Body).Decode(&user); err != nil {
        writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid JSON"})
        return
    }

    if user.Name == "" {
        writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"error": "name required"})
        return
    }

    if err := h.repo.Create(r.Context(), &user); err != nil {
        h.logger.Error("create user", "error", err)
        writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "internal"})
        return
    }

    writeJSON(w, http.StatusCreated, user)
}

func writeJSON(w http.ResponseWriter, status int, v any) error {
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(status)
    return json.NewEncoder(w).Encode(v)
}
```

Keep handlers thin: parse/validate, call service/repository, write response; business logic belongs in the service layer.

## Middleware Chain with `chi`

```go
import "github.com/go-chi/chi/v5"

func main() {
    r := chi.NewRouter()

    // Global middleware
    r.Use(middleware.RequestID)
    r.Use(middleware.RealIP)
    r.Use(LoggingMiddleware(logger))
    r.Use(middleware.Recoverer)
    r.Use(middleware.Timeout(30 * time.Second))

    // Public routes
    r.Group(func(r chi.Router) {
        r.Get("/health", healthCheck)
    })

    // Authenticated routes
    r.Group(func(r chi.Router) {
        r.Use(AuthMiddleware)

        r.Route("/users", func(r chi.Router) {
            r.Get("/", listUsers)
            r.Post("/", createUser)
            r.Route("/{id}", func(r chi.Router) {
                r.Get("/", getUser)
                r.Put("/", updateUser)
            })
        })
    })

    log.Fatal(http.ListenAndServe(":8080", r))
}
```

`Route` and `Group` sub-routers inherit parent middleware. chi implements the `net/http` handler interface; any `http.Handler` middleware works.

## Request-Scoped Context Values

```go
type ctxKey string

const (
    requestIDKey ctxKey = "requestID"
    userKey      ctxKey = "user"
)

// Middleware injects values:
func RequestIDMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        id := r.Header.Get("X-Request-ID")
        if id == "" {
            id = uuid.New().String()
        }
        ctx := context.WithValue(r.Context(), requestIDKey, id)
        next.ServeHTTP(w, r.WithContext(ctx))
    })
}

// Handler extracts values:
func handler(w http.ResponseWriter, r *http.Request) {
    reqID, _ := r.Context().Value(requestIDKey).(string)
    slog.Info("handling request", "requestID", reqID)
}

// Typed accessor (safer):
func RequestID(ctx context.Context) string {
    id, _ := ctx.Value(requestIDKey).(string)
    return id
}
```

Use an unexported custom context-key type, not `string` (collision risk). Context values are request-scoped only, never dependency injection.

## Structured Logging with `log/slog`

```go
import "log/slog"

func LoggingMiddleware(logger *slog.Logger) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            start := time.Now()
            wr := &responseWriter{ResponseWriter: w, status: http.StatusOK}

            next.ServeHTTP(wr, r)

            logger.Info("request",
                "method", r.Method,
                "path", r.URL.Path,
                "status", wr.status,
                "duration", time.Since(start),
                "remote_addr", r.RemoteAddr,
            )
        })
    }
}

// responseWriter captures the status code:
type responseWriter struct {
    http.ResponseWriter
    status int
}

func (rw *responseWriter) WriteHeader(code int) {
    rw.status = code
    rw.ResponseWriter.WriteHeader(code)
}

// Configure globally:
func main() {
    logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
        Level: slog.LevelInfo,
    }))
    slog.SetDefault(logger)
}
```

Use `slog.NewJSONHandler` for machine-readable production logs and `slog.NewTextHandler` during development. `slog.SetDefault` routes package-level `slog.Info` calls through the configured logger.

## Health Check Endpoint

```go
type HealthChecker struct {
    checks map[string]func(context.Context) error
}

func (h *HealthChecker) Add(name string, check func(context.Context) error) {
    h.checks[name] = check
}

func (h *HealthChecker) Handler() http.HandlerFunc {
    return func(w http.ResponseWriter, r *http.Request) {
        results := make(map[string]string, len(h.checks))
        healthy := true

        for name, check := range h.checks {
            if err := check(r.Context()); err != nil {
                results[name] = err.Error()
                healthy = false
            } else {
                results[name] = "ok"
            }
        }

        status := http.StatusOK
        if !healthy {
            status = http.StatusServiceUnavailable
        }
        writeJSON(w, status, map[string]any{
            "status":  results,
            "healthy": healthy,
        })
    }
}

// Usage:
hc := &HealthChecker{checks: make(map[string]func(context.Context) error)}
hc.Add("database", db.PingContext)
hc.Add("redis", redisClient.Ping)
mux.HandleFunc("GET /health", hc.Handler())
```

Separate liveness (process alive; minimal response 200) from readiness (downstream dependencies); use distinct paths such as `/healthz` and `/readyz`.

## Timeout Middleware

```go
func TimeoutMiddleware(timeout time.Duration) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        msg := fmt.Sprintf("request timed out after %s", timeout)
        return http.TimeoutHandler(next, timeout, msg)
    }
}
```

`http.TimeoutHandler` handles goroutine lifecycle, context cancellation, and response-body races. chi's `middleware.Timeout` wraps it with the same guarantees.

## Rate Limiting with `golang.org/x/time/rate`

```go
import "golang.org/x/time/rate"

type RateLimiter struct {
    mu       sync.Mutex
    limiters map[string]*rate.Limiter
    rate     rate.Limit
    burst    int
}

func NewRateLimiter(rps float64, burst int) *RateLimiter {
    return &RateLimiter{
        limiters: make(map[string]*rate.Limiter),
        rate:     rate.Limit(rps),
        burst:    burst,
    }
}

func (rl *RateLimiter) Middleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        key := r.RemoteAddr // or client ID, API key, etc.

        rl.mu.Lock()
        limiter, ok := rl.limiters[key]
        if !ok {
            limiter = rate.NewLimiter(rl.rate, rl.burst)
            rl.limiters[key] = limiter
        }
        rl.mu.Unlock()

        if !limiter.Allow() {
            w.Header().Set("Retry-After", "1")
            http.Error(w, "rate limit exceeded", http.StatusTooManyRequests)
            return
        }

        next.ServeHTTP(w, r)
    })
}
```

`rate.Limiter` uses token buckets; `Allow()` is non-blocking and immediately returns `false` when empty. A global limit uses one limiter without the per-key map. Periodically remove idle limiters to prevent unbounded memory growth.

## HTTP Handler Testing with `httptest`

```go
func TestGetUser(t *testing.T) {
    repo := &stubUserRepo{
        users: map[string]User{"1": {ID: "1", Name: "Alice"}},
    }
    handler := &UserHandler{repo: repo, logger: slog.Default()}

    req := httptest.NewRequest("GET", "/users/1", nil)
    req.SetPathValue("id", "1") // inject path param
    w := httptest.NewRecorder()

    handler.Get(w, req)

    resp := w.Result()
    assert.Equal(t, http.StatusOK, resp.StatusCode)

    var user User
    json.NewDecoder(resp.Body).Decode(&user)
    assert.Equal(t, "Alice", user.Name)
}

func TestCreateUser_Validation(t *testing.T) {
    handler := &UserHandler{repo: &stubUserRepo{}, logger: slog.Default()}

    body := strings.NewReader(`{"name":""}`)
    req := httptest.NewRequest("POST", "/users", body)
    w := httptest.NewRecorder()

    handler.Create(w, req)

    assert.Equal(t, http.StatusUnprocessableEntity, w.Result().StatusCode)
}
```

`req.SetPathValue` supplies Go 1.22+ route parameters; `httptest.NewRecorder` captures status, headers, and body without starting a server.

## Client Testing with `httptest.NewServer`

```go
func TestClient_FetchUser(t *testing.T) {
    // Fake server returns controlled responses
    server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        switch r.URL.Path {
        case "/users/1":
            writeJSON(w, http.StatusOK, User{ID: "1", Name: "Alice"})
        case "/users/999":
            w.WriteHeader(http.StatusNotFound)
        default:
            w.WriteHeader(http.StatusInternalServerError)
        }
    }))
    defer server.Close()

    client := NewClient(server.URL)

    user, err := client.FetchUser(context.Background(), "1")
    assert.NoError(t, err)
    assert.Equal(t, "Alice", user.Name)

    _, err = client.FetchUser(context.Background(), "999")
    assert.Error(t, err)
}
```

`httptest.NewServer` starts a real server on a random port; use `server.URL` as the base URL and always `defer server.Close()`. Use `httptest.NewTLSServer` for TLS.

## Graceful Shutdown

```go
func runServer(ctx context.Context, srv *http.Server) error {
    errCh := make(chan error, 1)
    go func() {
        if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
            errCh <- err
        }
    }()

    select {
    case err := <-errCh:
        return err
    case <-ctx.Done():
    }

    shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
    defer cancel()
    return srv.Shutdown(shutdownCtx)
}

func main() {
    srv := &http.Server{Addr: ":8080", Handler: mux}

    ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
    defer stop()

    if err := runServer(ctx, srv); err != nil {
        log.Fatalf("server error: %v", err)
    }
}
```

`server.Shutdown(ctx)` drains active connections without interrupting them. `signal.NotifyContext` cancels on SIGINT/SIGTERM. Use a separate `context.WithTimeout` for the shutdown deadline to prevent indefinite hangs.
