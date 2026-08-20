# Go Type Patterns

Use Go's limited type system to recover compile-time safety. Four patterns:
1. named types: primitive branding;
2. smart constructors + unexported fields: parse, don't validate;
3. sealed interfaces + `type switch` + `exhaustive`: sum types;
4. constrained generics: bounded polymorphism (Go 1.18+).

## 1. Named types

Same underlying type, distinct meaning: implicit mixing fails; explicit conversion always works. Treat named types as boundary contracts.

```go
package domain

type UserID string
type OrderID string
type EmailRaw string  // raw, unvalidated string from input

func GetUser(id UserID) User { /* ... */ }

uid := UserID("u-123")
oid := OrderID("o-456")

GetUser(uid)              // ✅ OK
GetUser(oid)              // ❌ cannot use oid (type OrderID) as UserID
GetUser("u-123")          // ❌ untyped string literal; Go DOES catch this
GetUser(UserID("u-123"))  // ✅ explicit conversion; accept it
```

Use for IDs, opaque tokens, foreign keys, and units sharing a primitive. Explicit conversion defeats branding (`UserID(orderIDAsString)`); use smart constructors for constraints beyond internal identifiers. Named types provide cheap branding; constructors provide actual invariant protection.

### Units

```go
type Milliseconds int64
type Seconds      int64

func (ms Milliseconds) ToSeconds() Seconds {
    return Seconds(ms / 1000)
}
```

Milliseconds and seconds cannot mix implicitly; convert explicitly.

## 2. Smart constructors + unexported fields

For every domain value with invariants; email, URL, phone, currency, percentage, semver, constrained ID, time range, or a value validated in three places; hide fields and construct through validation. The zero value remains reachable.

```go
package domain

import (
    "errors"
    "regexp"
    "strings"
)

var (
    ErrInvalidEmail = errors.New("invalid email")
    emailRe         = regexp.MustCompile(`^[^@\s]+@[^@\s]+\.[^@\s]+$`)
)

// Email is a parsed, lowercased, valid email address.
// The zero value is invalid; construct via NewEmail.
type Email struct {
    raw string  // unexported; cannot be set from outside the package
}

func NewEmail(s string) (Email, error) {
    s = strings.TrimSpace(strings.ToLower(s))
    if !emailRe.MatchString(s) {
        return Email{}, ErrInvalidEmail
    }
    return Email{raw: s}, nil
}

// String implements fmt.Stringer for printing.
func (e Email) String() string { return e.raw }

// MarshalJSON keeps the wire format unchanged.
func (e Email) MarshalJSON() ([]byte, error) {
    return []byte(`"` + e.raw + `"`), nil
}

// UnmarshalJSON is the parsing boundary: strict mode.
func (e *Email) UnmarshalJSON(data []byte) error {
    if len(data) < 2 || data[0] != '"' || data[len(data)-1] != '"' {
        return ErrInvalidEmail
    }
    parsed, err := NewEmail(string(data[1 : len(data)-1]))
    if err != nil {
        return err
    }
    *e = parsed
    return nil
}
```

Outside `domain`, `Email{raw: "anything"}` cannot compile. `NewEmail` validates direct construction, and `UnmarshalJSON` routes wire data through it. An `Email` parameter therefore represents a proven-valid value; internal empty checks are unnecessary.

Mitigate the reachable invalid zero value with documentation and, when needed:

```go
func (e Email) IsZero() bool { return e.raw == "" }
```

Alternatively, require correct code never to pass zero `Email` values and verify that invariant in tests.

## 3. Sealed interfaces

Go lacks sum types. An interface with an unexported method can only be satisfied by types in its package; dispatch with `type switch`, and use `exhaustive` to enforce completeness.

```go
package event

// Event is a closed sum: Created | Updated | Deleted.
// The sealed() method is unexported so external packages cannot add variants.
type Event interface {
    sealed()
    OccurredAt() time.Time
}

type Created struct {
    UserID    UserID
    Email     Email
    Timestamp time.Time
}
func (Created) sealed()                    {}
func (e Created) OccurredAt() time.Time    { return e.Timestamp }

type Updated struct {
    UserID    UserID
    Changes   map[string]any
    Timestamp time.Time
}
func (Updated) sealed()                    {}
func (e Updated) OccurredAt() time.Time    { return e.Timestamp }

type Deleted struct {
    UserID    UserID
    Reason    string
    Timestamp time.Time
}
func (Deleted) sealed()                    {}
func (e Deleted) OccurredAt() time.Time    { return e.Timestamp }
```

```go
func Render(e event.Event) string {
    switch v := e.(type) {
    case event.Created:
        return fmt.Sprintf("created %s with %s", v.UserID, v.Email)
    case event.Updated:
        return fmt.Sprintf("updated %s: %v", v.UserID, v.Changes)
    case event.Deleted:
        return fmt.Sprintf("deleted %s (reason: %s)", v.UserID, v.Reason)
    default:
        panic(fmt.Sprintf("unhandled event variant: %T", v))
    }
}
```

The `default` panic is the `assertNever`/`assert_never` analogue, reachable when a new variant lacks a switch case. Treat `exhaustive` as compulsory:

```yaml
# .golangci.yml
linters:
  enable: [exhaustive]
linters-settings:
  exhaustive:
    check:
      - switch
      - map
    default-signifies-exhaustive: false
```

Adding `event.Suspended` without updating `Render` becomes a lint error; the closest Go equivalent to Rust match exhaustiveness.

Gotchas:
- `sealed()` MUST be unexported; `Sealed()` permits external implementations.
- Choose value receivers + value cases, or pointer receivers + pointer cases. Mixing `*Created` and `Created` can silently miss.
- `interface{}`/`any` is not sealed: zero-method interfaces accept anything. A sealed interface needs at least `sealed()`.

## 4. Constrained generics

Go 1.18+. Use for genuinely generic algorithms, not merely to accept anything.

```go
import "cmp"

// Ordered constraint includes all ordered types (int, float, string, …).
func Max[T cmp.Ordered](a, b T) T {
    if a > b { return a }
    return b
}

// Custom constraint
type Stringer interface {
    String() string
}

func Join[T Stringer](items []T, sep string) string {
    parts := make([]string, len(items))
    for i, item := range items {
        parts[i] = item.String()
    }
    return strings.Join(parts, sep)
}
```

`cmp.Ordered` (Go 1.21+), `cmp.Compare`, `slices`, and `maps` cover common constraints. Generics provide parametric polymorphism (same algorithm, different types); interfaces provide behavioral polymorphism (different implementations behind a contract). For multiple accepted types, prefer an interface. For `any` returns, prefer a sealed interface + `type switch`; `any` returns are an anti-pattern beyond public APIs.

## 5. Type assertions

```go
// Bad: panics on failure
e := evt.(event.Created)

// Good: comma-ok form, always
if e, ok := evt.(event.Created); ok {
    // use e
}

// Use errors.As for error chains
var pgErr *pgconn.PgError
if errors.As(err, &pgErr) {
    // pgErr is the wrapped pg error
}
```

Use comma-ok assertions; bare assertions panic on failure. `errcheck` and `errorlint` reject bare type assertions on `error`; use `errors.As`. See `error-handling.md`.

## 6. Pointers vs values

- Mutex-bearing types MUST never be copied; use `*T` everywhere.
- For large (> 64 bytes), read-only types, measure value vs pointer; default to pointer for large values.
- Receiver choice MUST be consistent: all methods use `T` or all use `*T`; `staticcheck` catches mixed-receiver bugs.
- `nil` pointer means absence; zero value means “not set yet”. Choose ONE convention per type and document it.

## 7. `any` / `interface{}`

Almost never use in domain code. Acceptable:
- genuinely heterogeneous JSON (prefer `json.RawMessage` + targeted parsing);
- `fmt.Sprintf` arguments, where variadic `any` is unavoidable;
- generic-container internals before the user-facing API.

Do not use `any` in handler, service, or store signatures. `func Handle(payload any) error` signals a sealed interface is needed.

## Sources

- "Parse, don't validate": Alexis King: https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/
- exhaustive linter: https://github.com/nishanths/exhaustive
- Generics constraints: https://go.dev/blog/intro-generics
- cmp.Ordered: https://pkg.go.dev/cmp
