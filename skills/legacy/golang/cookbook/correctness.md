# Correctness Cookbook

Recipes for input validation, boundary defense, and typed data flow in Go.

---

## Contents

- [Parse at the Boundary, Validate Immediately](#parse-at-the-boundary-validate-immediately)
- [Strict JSON Decoding](#strict-json-decoding)
- [Struct Tags for Validation](#struct-tags-for-validation)
- [Validating Environment Variables](#validating-environment-variables)
- [Mapping DB Errors to Domain Errors](#mapping-db-errors-to-domain-errors)
- [Nil Receiver Methods](#nil-receiver-methods)
- [Pointers vs Values for Optional Fields](#pointers-vs-values-for-optional-fields)
- [Invariants in Constructors](#invariants-in-constructors)
- [CLI Flag Validation](#cli-flag-validation)
- [API Response Validation](#api-response-validation)

---
## Parse at the Boundary, Validate Immediately

**Problem**: How to keep untrusted data (JSON, env vars, CLI flags, HTTP params) from polluting core logic?

**Solution**:

```go
// Layer 1: raw input struct: matches the wire format exactly
type userRequest struct {
    Name  string `json:"name"`
    Email string `json:"email"`
    Age   int    `json:"age"`
}

// Layer 2: domain type: validated, normalized, no surprises
type User struct {
    Name  string
    Email string
    Age   int
}

func (r userRequest) toDomain() (*User, error) {
    if r.Name == "" {
        return nil, fmt.Errorf("name is required")
    }
    if r.Email == "" || !strings.Contains(r.Email, "@") {
        return nil, fmt.Errorf("invalid email: %q", r.Email)
    }
    if r.Age < 0 || r.Age > 150 {
        return nil, fmt.Errorf("age out of range: %d", r.Age)
    }
    return &User{
        Name:  strings.TrimSpace(r.Name),
        Email: strings.ToLower(r.Email),
        Age:   r.Age,
    }, nil
}
```

**Tip**: Never pass `map[string]any` or raw request structs into business logic. Parse, validate, convert; all at the edge.

---

## Strict JSON Decoding

**Problem**: How to catch typos and unknown fields in JSON input instead of silently ignoring them?

**Solution**:

```go
func decodeUser(r io.Reader) (*User, error) {
    var req userRequest
    dec := json.NewDecoder(r)
    dec.DisallowUnknownFields()
    if err := dec.Decode(&req); err != nil {
        return nil, fmt.Errorf("decoding request: %w", err)
    }
    // Verify no trailing data
    if err := dec.Decode(&struct{}{}); err != io.EOF {
        return nil, fmt.Errorf("unexpected data after JSON body")
    }
    return req.toDomain()
}
```

**Tip**: `DisallowUnknownFields` catches misspelled keys. Also check `dec.More()` to reject multiple JSON objects or trailing garbage.

---

## Struct Tags for Validation

**Problem**: How to validate struct fields concisely without hand-writing every check?

**Solution**:

```go
import "github.com/go-playground/validator/v10"

var validate = validator.New()

type CreateUserRequest struct {
    Name  string `json:"name"  validate:"required,min=1,max=200"`
    Email string `json:"email" validate:"required,email"`
    Age   int    `json:"age"   validate:"gte=0,lte=150"`
    Role  string `json:"role"  validate:"oneof=admin user viewer"`
}

func handleCreate(w http.ResponseWriter, r *http.Request) {
    var req CreateUserRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        http.Error(w, "invalid JSON", http.StatusBadRequest)
        return
    }
    if err := validate.Struct(req); err != nil {
        // err is validator.ValidationErrors: extract field-level messages
        http.Error(w, err.Error(), http.StatusBadRequest)
        return
    }
    // req is now valid: convert to domain
}
```

**Tip**: Register `validate` once as a package-level variable. It caches struct metadata and is safe for concurrent use.

---

## Validating Environment Variables

**Problem**: How to load and validate configuration from environment variables at startup?

**Solution**:

```go
type Config struct {
    Port    int           `env:"PORT"    validate:"required,gte=1024,lte=65535"`
    DBURL   string        `env:"DB_URL" validate:"required,url"`
    Timeout time.Duration `env:"TIMEOUT"`
}

func LoadConfig() (*Config, error) {
    var cfg Config
    if err := envconfig.Process("", &cfg); err != nil {
        return nil, fmt.Errorf("loading env config: %w", err)
    }
    if err := validate.Struct(cfg); err != nil {
        return nil, fmt.Errorf("validating config: %w", err)
    }
    if cfg.Timeout == 0 {
        cfg.Timeout = 30 * time.Second
    }
    return &cfg, nil
}
```

**Tip**: Validate at startup and exit immediately on failure. Never defer config validation; a misconfigured process should not start.

---

## Mapping DB Errors to Domain Errors

**Problem**: How to translate database-specific errors into meaningful domain errors without leaking implementation details?

**Solution**:

```go
var (
    ErrNotFound       = errors.New("resource not found")
    ErrConflict       = errors.New("resource already exists")
    ErrInternal       = errors.New("internal error")
)

func (r *UserRepo) GetByID(ctx context.Context, id string) (*User, error) {
    var u User
    err := r.db.QueryRowContext(ctx, "SELECT ...", id).Scan(&u.Name, &u.Email)
    switch {
    case errors.Is(err, sql.ErrNoRows):
        return nil, ErrNotFound
    case err != nil:
        return nil, fmt.Errorf("querying user %s: %w", id, ErrInternal)
    }
    return &u, nil
}

func (r *UserRepo) Insert(ctx context.Context, u *User) error {
    _, err := r.db.ExecContext(ctx, "INSERT INTO ...", u.Name, u.Email)
    if isUniqueViolation(err) {
        return ErrConflict
    }
    if err != nil {
        return fmt.Errorf("inserting user: %w", ErrInternal)
    }
    return nil
}
```

**Tip**: Define domain errors at the package level. Callers check `errors.Is(err, ErrNotFound)` without knowing about SQL. Wrap the original error when logging.

---

## Nil Receiver Methods

**Problem**: Should methods on pointer receivers handle nil receivers gracefully?

**Solution**:

```go
type User struct {
    Name  string
    Email string
}

// Safe: returns empty string for nil receiver
func (u *User) DisplayName() string {
    if u == nil {
        return "unknown"
    }
    return u.Name
}

// Unsafe: panics on nil. Only call when nil is logically impossible.
func (u *User) EmailDomain() string {
    _, domain, _ := strings.Cut(u.Email, "@")
    return domain
}
```

**Tip**: Most nil-receiver panics happen because a function returning `(*T, error)` was called without checking the error. Always check `err != nil` before touching the pointer. Handle nil receivers only when nil is a meaningful state in your domain model.

---

## Pointers vs Values for Optional Fields

**Problem**: How to represent optional fields where absence differs from zero-value?

**Solution**:

```go
// Use pointer when nil ≠ zero-value
type UpdateRequest struct {
    Name  *string `json:"name"`   // nil = not provided, "" = clear
    Age   *int    `json:"age"`    // nil = not provided, 0 = set to zero
    Email *string `json:"email"`  // nil = not provided, "" = clear
}

func applyUpdate(u *User, req UpdateRequest) {
    if req.Name != nil {
        u.Name = *req.Name
    }
    if req.Age != nil {
        u.Age = *req.Age
    }
    if req.Email != nil {
        u.Email = strings.ToLower(*req.Email)
    }
}
```

**Tip**: Use pointer fields for PATCH semantics only. For required fields in a CREATE endpoint, use plain values; absence is a validation error, not a semantic distinction.

---

## Invariants in Constructors

**Problem**: How to guarantee that a type is always in a valid state after construction?

**Solution**:

```go
type Order struct {
    items []OrderItem
    total int // cached, must stay in sync
}

func NewOrder(items []OrderItem) (*Order, error) {
    if len(items) == 0 {
        return nil, fmt.Errorf("order must have at least one item")
    }
    total := 0
    for _, item := range items {
        if item.Price < 0 {
            return nil, fmt.Errorf("item %q has negative price", item.Name)
        }
        total += item.Price
    }
    return &Order{items: items, total: total}, nil
}

// Methods trust the invariant: no defensive checks needed
func (o *Order) Total() int { return o.total }
```

**Tip**: Unexported fields + constructor validation = invariant enforced. Export fields only when the zero-value of the struct is a valid state.

---

## CLI Flag Validation

**Problem**: How to validate CLI arguments before passing them into application logic?

**Solution**:

```go
func main() {
    var (
        input  = flag.String("input", "", "input file path")
        count  = flag.Int("count", 1, "number of iterations")
    )
    flag.Parse()

    if *input == "" {
        fmt.Fprintln(os.Stderr, "-input is required")
        os.Exit(2)
    }
    if *count < 1 || *count > 100 {
        fmt.Fprintln(os.Stderr, "-count must be between 1 and 100")
        os.Exit(2)
    }

    if err := run(*input, *count); err != nil {
        fmt.Fprintf(os.Stderr, "error: %v\n", err)
        os.Exit(1)
    }
}
```

**Tip**: Use `flag` for simple CLIs, `cobra` for subcommands. Either way, validate flags in `main` before calling into logic that assumes valid inputs.

---

## API Response Validation

**Problem**: How to verify that external API responses match expectations before acting on them?

**Solution**:

```go
type githubRelease struct {
    TagName string `json:"tag_name"`
    Assets  []struct {
        Name string `json:"name"`
        URL  string `json:"browser_download_url"`
    } `json:"assets"`
}

func fetchRelease(ctx context.Context, tag string) (*githubRelease, error) {
    resp, err := httpGet(ctx, "https://api.github.com/repos/x/y/releases/tags/"+tag)
    if err != nil {
        return nil, fmt.Errorf("fetching release: %w", err)
    }
    defer resp.Body.Close()

    if resp.StatusCode != http.StatusOK {
        return nil, fmt.Errorf("API returned status %d", resp.StatusCode)
    }

    var rel githubRelease
    dec := json.NewDecoder(resp.Body)
    dec.DisallowUnknownFields()
    if err := dec.Decode(&rel); err != nil {
        return nil, fmt.Errorf("decoding API response: %w", err)
    }
    if rel.TagName == "" {
        return nil, fmt.Errorf("API returned release with empty tag_name")
    }
    // Convert to internal representation
    return &rel, nil
}
```

**Tip**: Treat external API responses as untrusted input. Use `DisallowUnknownFields` and validate mandatory fields after decoding; APIs change silently.

