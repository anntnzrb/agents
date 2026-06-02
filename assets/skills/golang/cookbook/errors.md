# Errors Cookbook

Recipes for creating, wrapping, inspecting, and mapping errors in Go.

---

## Contents

- [Wrapping Errors with Context](#wrapping-errors-with-context)
- [Sentinel Errors](#sentinel-errors)
- [Custom Error Types](#custom-error-types)
- [errors.As for Type Extraction](#errorsas-for-type-extraction)
- [errors.AsType (Go 1.26+)](#errorsastype-go-126)
- [errors.Join for Multiple Errors](#errorsjoin-for-multiple-errors)
- [Mapping Errors Across Layers](#mapping-errors-across-layers)
- [When to Use Each Error Pattern](#when-to-use-each-error-pattern)
- [Preserving Stack Traces](#preserving-stack-traces)
- [Error Handling in Defer](#error-handling-in-defer)

---
## Wrapping Errors with Context

**Problem**: How to add context to an error while preserving the original for callers to inspect?

**Solution**:

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

**Tip**: Use `%w` once per `fmt.Errorf` call. Wrap at every layer that adds meaningful context — the file path above helps the operator, not just the programmer.

---

## Sentinel Errors

**Problem**: How to define package-level error values that callers can check with `errors.Is`?

**Solution**:

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

**Tip**: Sentinel errors are immutable. Never `fmt.Errorf("%w", ErrNotFound)` to add a message — create a new error and wrap the sentinel instead.

---

## Custom Error Types

**Problem**: How to attach structured metadata to errors for programmatic handling?

**Solution**:

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

**Tip**: Custom error types must implement `Error() string`. Use pointer receivers so `errors.As` can unwrap through the chain. Do not export fields that are just for logging — export only what callers need.

---

## errors.As for Type Extraction

**Problem**: How to extract a specific error type from a wrapped chain?

**Solution**:

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

**Tip**: `errors.As` walks the chain and calls `Unwrap() error` on each link. It matches any error in the chain whose type matches the target.

---

## errors.AsType (Go 1.26+)

**Problem**: How to extract a typed error from a chain without a pointer-to-pointer dance?

**Solution**:

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

**Tip**: `errors.AsType[T]` returns `(T, bool)`. Prefer it over `errors.As` when the target is known at compile time — it avoids the error-prone pointer-to-pointer pattern and works with non-pointer types.

---

## errors.Join for Multiple Errors

**Problem**: How to combine multiple errors into one return value?

**Solution**:

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

**Tip**: `errors.Is` and `errors.As` recurse into joined errors. An error joined from `[ErrNotFound, ErrConflict]` matches `errors.Is(err, ErrNotFound)`.

---

## Mapping Errors Across Layers

**Problem**: How to translate errors cleanly when crossing architectural boundaries?

**Solution**:

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

**Tip**: Repository returns domain sentinels. Service adds operation context. Handler maps to status codes. Each layer wraps, never rewrites.

---

## When to Use Each Error Pattern

**Problem**: Which error pattern should I use for this situation?

**Solution**:

| Situation | Pattern |
|---|---|
| Caller needs to match a fixed condition | Sentinel error (`var ErrX = errors.New(...)`) |
| Caller needs to extract structured data | Custom error type + `errors.As` / `errors.AsType` |
| Caller only logs or surfaces to user | `fmt.Errorf("context: %w", err)` |
| Multiple independent failures to report | `errors.Join` |
| Error originates from a 3rd-party library | Wrap and convert to your own sentinel or type |
| Error is fatal, no recovery possible | Unwrap chain unchanged, or return directly |

**Tip**: Start with wrapped `fmt.Errorf`. Add a sentinel only when a caller needs to branch on it. Add a custom type only when callers need structured fields.

---

## Preserving Stack Traces

**Problem**: How to capture a stack trace at the error origin for debugging?

**Solution**: Use `runtime/debug.Stack` to capture a stack trace at the error origin, or rely on structured logging with `slog` to attach caller information.

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

**Tip**: Prefer stdlib `fmt.Errorf` wrapping for error chains. Capture stack traces with `runtime/debug.Stack` at the logging boundary (handler/middleware), not at every error site. Reserve `github.com/pkg/errors` only for maintaining inherited codebases that already depend on it — it is in maintenance mode and not recommended for new code.

---

## Error Handling in Defer

**Problem**: How to capture or handle errors from deferred cleanup functions?

**Solution**:

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

**Tip**: Name the return error (`err error`) to capture the close error. Only override if the main operation succeeded — otherwise prefer the primary error. Use `errors.Join` if both errors matter.

