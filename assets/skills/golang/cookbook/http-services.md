# HTTP Services Cookbook

Recipes for building HTTP services with Go 1.22+ stdlib routing, middleware, testing, and observability.

---

## Contents

- [Go 1.22+ ServeMux Routing](#go-122-servemux-routing)
- [Building a REST Endpoint](#building-a-rest-endpoint)
- [Middleware Chain with `chi`](#middleware-chain-with-chi)
- [Request-Scoped Context Values](#request-scoped-context-values)
- [Structured Logging with `log/slog`](#structured-logging-with-logslog)
- [Health Check Endpoint](#health-check-endpoint)
- [Timeout Middleware](#timeout-middleware)
- [Rate Limiting with `golang.org/x/time/rate`](#rate-limiting-with-golangorgxtimerate)
- [HTTP Handler Testing with `httptest`](#http-handler-testing-with-httptest)
- [Client Testing with `httptest.NewServer`](#client-testing-with-httptestnewserver)
- [Graceful Shutdown](#graceful-shutdown)

---
## Go 1.22+ ServeMux Routing

**Problem**: How to define routes with HTTP method and path parameters using only the standard library?

**Solution**:

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

**Tip**: Path patterns use `{name}` for single-segment params and `{name...}` for multi-segment wildcards. `r.PathValue` returns `""` when the param is absent — validate it.

---

## Building a REST Endpoint

**Problem**: How to structure a complete REST resource with validation, domain logic, and JSON responses?

**Solution**:

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

**Tip**: Keep handlers thin — parse/validate input, call the service/repo, write the response. Business logic lives in the service layer, not in HTTP handlers.

---

## Middleware Chain with `chi`

**Problem**: How to compose middleware and mount sub-routers with clean separation of concerns?

**Solution**:

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

**Tip**: chi's `Route` and `Group` create sub-routers that inherit parent middleware. chi is compatible with the `net/http` handler interface — any `http.Handler` middleware works with it.

---

## Request-Scoped Context Values

**Problem**: How to carry request-scoped data (request ID, authenticated user) through handler call chains?

**Solution**:

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

**Tip**: Don't use `string` directly as a context key — it risks collisions with other packages. Use an unexported custom type. Context values are for request-scoped data only, never for dependency injection.

---

## Structured Logging with `log/slog`

**Problem**: How to add structured, level-based logging to HTTP handlers?

**Solution**:

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

**Tip**: Use `slog.NewJSONHandler` in production for machine-readable logs. Use `slog.NewTextHandler` during development. The `slog.SetDefault` call makes `slog.Info` et al. use your configured logger everywhere.

---

## Health Check Endpoint

**Problem**: How to expose a liveness/readiness endpoint that checks downstream dependencies?

**Solution**:

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

**Tip**: Separate liveness (is the process alive?) from readiness (can it serve traffic?). A minimal liveness check just returns 200; readiness checks downstream deps. Use different paths (`/healthz`, `/readyz`).

---

## Timeout Middleware

**Problem**: How to enforce a per-request deadline so slow handlers don't hold connections open?

**Solution**:

```go
func TimeoutMiddleware(timeout time.Duration) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        msg := fmt.Sprintf("request timed out after %s", timeout)
        return http.TimeoutHandler(next, timeout, msg)
    }
}
```

**Tip**: Use `http.TimeoutHandler` from the standard library — it handles the goroutine lifecycle, context cancellation, and response body races correctly. For chi users, `middleware.Timeout` wraps this and provides the same guarantees.


---

## Rate Limiting with `golang.org/x/time/rate`

**Problem**: How to limit requests per client or globally to protect the service?

**Solution**:

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

**Tip**: `rate.Limiter` implements the token-bucket algorithm. `Allow()` is non-blocking — it returns `false` immediately when the bucket is empty. For a global limit, use a single limiter without the per-key map. Periodically clean up idle limiters to avoid unbounded memory growth.

---

## HTTP Handler Testing with `httptest`

**Problem**: How to test an HTTP handler without starting a real server?

**Solution**:

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

**Tip**: Use `req.SetPathValue` to set path parameters for Go 1.22+ routed handlers. `httptest.NewRecorder` captures the full response including status, headers, and body.

---

## Client Testing with `httptest.NewServer`

**Problem**: How to test an HTTP client against a fake server that returns controlled responses?

**Solution**:

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

**Tip**: `httptest.NewServer` starts a real HTTP server on a random port. Use the returned `server.URL` as the client base URL. Always `defer server.Close()`. For TLS testing, use `httptest.NewTLSServer`.


---

## Graceful Shutdown

**Problem**: How to shut down an HTTP server gracefully, letting in-flight requests finish?

**Solution**:

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

**Tip**: `server.Shutdown(ctx)` drains active connections without interrupting them. The `signal.NotifyContext` creates a context that cancels on SIGINT/SIGTERM. Use a separate `context.WithTimeout` for the shutdown deadline so the process doesn't hang indefinitely.