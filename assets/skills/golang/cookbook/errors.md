# Go Errors Cookbook

Recipes: create, wrap, inspect, map errors.

## Wrapping with Context

Preserve originals for `errors.Is`/`errors.As` with `%w`; use `%w` once per `fmt.Errorf` call. Wrap each layer adding meaningful context; include operator-useful details such as file paths.

```go
func ReadConfig(path string) (*Config, error) {
    data, err := os.ReadFile(path)
    if err != nil {
        return nil, fmt.Errorf("reading config file %s: %w", path, err)
    }

    var cfg Config
    if err := toml.Unmarshal(data, &cfg); err != nil {
        return nil, fmt.Errorf("parsing config file %s: %w", path, err)
    }

    return &cfg, nil
}
```

## Sentinel Errors

Package-level values let callers match fixed conditions with `errors.Is`:

```go
var (
    ErrNotFound     = errors.New("not found")
    ErrUnauthorized = errors.New("unauthorized")
    ErrConflict     = errors.New("already exists")
)

func (r *Repo) Get(id string) (*Item, error) {
    row := r.db.QueryRow("SELECT ...", id)
    var item Item
    err := row.Scan(&item.Name)
    if errors.Is(err, sql.ErrNoRows) {
        return nil, ErrNotFound
    }
    if err != nil {
        return nil, fmt.Errorf("querying item %s: %w", id, err)
    }
    return &item, nil
}

// Caller:
if errors.Is(err, ErrNotFound) {
    http.Error(w, "not found", http.StatusNotFound)
    return
}
```

Sentinels immutable. Never use `fmt.Errorf("%w", ErrNotFound)` to add a message; create a new error and wrap the sentinel instead.

## Custom Error Types

Use a custom type for structured metadata callers handle programmatically. It MUST implement `Error() string`; use pointer receivers so `errors.As` can unwrap through the chain. Export only caller-needed fields, not logging-only fields.

```go
type ValidationError struct {
    Field   string
    Value   any
    Message string
}

func (e *ValidationError) Error() string {
    return fmt.Sprintf("validation: %s (%v): %s", e.Field, e.Value, e.Message)
}

func ValidateEmail(email string) error {
    if !strings.Contains(email, "@") {
        return &ValidationError{
            Field:   "email",
            Value:   email,
            Message: "must contain @",
        }
    }
    return nil
}

// Extracting:
var valErr *ValidationError
if errors.As(err, &valErr) {
    fmt.Printf("field %s is invalid\n", valErr.Field)
}
```

## `errors.As`

Extract a matching type from a wrapped chain:

```go
var dnsErr *net.DNSError
if errors.As(err, &dnsErr) {
    if dnsErr.IsNotFound {
        fmt.Println("host not found")
    }
    if dnsErr.IsTemporary {
        fmt.Println("temporary — retry")
    }
}

// Nested unwrapping through multiple layers works:
// fmt.Errorf("request failed: %w", fmt.Errorf("dial: %w", dnsErr))
// → errors.As extracts *net.DNSError correctly.
```

`errors.As` walks the chain, calling `Unwrap() error` on each link; it matches any chain error whose type matches the target.

## `errors.AsType` (Go 1.26+)

Extract a typed chain error directly, avoiding pointer-to-pointer:

```go
// Go 1.26+ — returns the extracted value directly
if dnsErr, ok := errors.AsType[*net.DNSError](err); ok {
    if dnsErr.IsNotFound {
        fmt.Println("host not found")
    }
}

// Works with interfaces too:
if timeout, ok := errors.AsType[interface{ Timeout() bool }](err); ok {
    fmt.Println("is timeout:", timeout.Timeout())
}
```

`errors.AsType[T]` returns `(T, bool)`. Prefer it over `errors.As` when the target is known at compile time: it avoids the error-prone pointer-to-pointer pattern and works with non-pointer types.

## `errors.Join`

Combine independent failures into one return value:

```go
func validateAll(ctx context.Context, items []Item) error {
    var errs []error
    for _, item := range items {
        if err := validate(item); err != nil {
            errs = append(errs, fmt.Errorf("item %s: %w", item.ID, err))
        }
    }
    if len(errs) > 0 {
        return errors.Join(errs...)
    }
    return nil
}

// Caller can still check individual errors:
if err := validateAll(ctx, items); err != nil {
    var valErr *ValidationError
    if errors.As(err, &valErr) {
        // handles individual validation error
    }
    // errors.Is also works if at least one joined error matches
    if errors.Is(err, ErrNotFound) {
        // ...
    }
}
```

`errors.Is` and `errors.As` recurse into joined errors. Joining `[ErrNotFound, ErrConflict]` makes `errors.Is(err, ErrNotFound)` match.

## Mapping Across Layers

Translate across architectural boundaries; each layer wraps, never rewrites:

```go
// === Repository layer (DB errors → domain errors) ===
func (r *UserRepo) GetByID(ctx context.Context, id string) (*User, error) {
    var user User
    err := r.db.QueryRowContext(ctx, "SELECT ...", id).Scan(&user.ID, &user.Name)
    switch {
    case errors.Is(err, sql.ErrNoRows):
        return nil, ErrNotFound
    case err != nil:
        return nil, fmt.Errorf("user repo get %s: %w", id, err)
    }
    return &user, nil
}

// === Service layer (domain errors + context) ===
func (s *UserService) GetUser(ctx context.Context, id string) (*User, error) {
    user, err := s.repo.GetByID(ctx, id)
    if err != nil {
        return nil, fmt.Errorf("getting user %s: %w", id, err)
    }
    return user, nil
}

// === HTTP handler layer (domain errors → HTTP status) ===
func (h *UserHandler) GetUser(w http.ResponseWriter, r *http.Request) {
    user, err := h.svc.GetUser(r.Context(), chi.URLParam(r, "id"))
    if err == nil {
        writeJSON(w, http.StatusOK, user)
        return
    }
    switch {
    case errors.Is(err, ErrNotFound):
        http.Error(w, "not found", http.StatusNotFound)
    case errors.Is(err, ErrUnauthorized):
        http.Error(w, "unauthorized", http.StatusUnauthorized)
    default:
        slog.Error("unexpected error", "err", err)
        http.Error(w, "internal error", http.StatusInternalServerError)
    }
}
```

Repository returns domain sentinels; service adds operation context; handler maps to status codes.

## Pattern Selection

|Situation|Pattern|
|---|---|
|Caller needs to match a fixed condition|Sentinel error (`var ErrX = errors.New(...)`)|
|Caller needs to extract structured data|Custom error type + `errors.As` / `errors.AsType`|
|Caller only logs or surfaces to user|`fmt.Errorf("context: %w", err)`|
|Multiple independent failures to report|`errors.Join`|
|Error originates from a 3rd-party library|Wrap and convert to your own sentinel or type|
|Error is fatal, no recovery possible|Unwrap chain unchanged, or return directly|

Start with wrapped `fmt.Errorf`; add a sentinel only for caller branching; add a custom type only when callers need structured fields.

## Stack Traces

Capture a stack at the error origin with `runtime/debug.Stack`, or use structured `slog` logging with caller information.

```go
import (
    "fmt"
    "runtime/debug"
)

func deepOperation() error {
    // Capture stack at the error origin
    stack := string(debug.Stack())
    return fmt.Errorf("deep failure\n%s", stack)
}

// Better approach: log the stack at the handler boundary
func handler() {
    if err := doWork(); err != nil {
        slog.Error("operation failed", "err", err, "stack", string(debug.Stack()))
    }
}
```

Prefer stdlib `fmt.Errorf` wrapping for chains. Capture stacks at the logging boundary (handler/middleware), not every error site. Reserve `github.com/pkg/errors` for inherited codebases already depending on it; it is in maintenance mode and not recommended for new code.

## Deferred Cleanup Errors

Use a named return error to capture deferred cleanup errors; override only when the main operation succeeded, otherwise preserve the primary error. Use `errors.Join` when both matter.

```go
func processFile(path string) (err error) {
    f, err := os.Open(path)
    if err != nil {
        return fmt.Errorf("opening %s: %w", path, err)
    }
    defer func() {
        if closeErr := f.Close(); closeErr != nil && err == nil {
            err = fmt.Errorf("closing %s: %w", path, closeErr)
        }
    }()

    // ... use f ...
    return nil
}
```
