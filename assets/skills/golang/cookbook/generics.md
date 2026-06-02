# Generics Cookbook

Recipes for writing generic Go code: data structures, functional utilities, constraints, and knowing when generics help vs. hurt.

---

## Contents

- [Generic Filter](#generic-filter)
- [Generic Map/Transform](#generic-maptransform)
- [Generic Set Type](#generic-set-type)
- [Numeric Constraints with `~int` / `~float64`](#numeric-constraints-with-int--float64)
- [`cmp.Ordered` for Total-Order Types](#cmpordered-for-total-order-types)
- [Self-Referential Constraints (Go 1.26+)](#self-referential-constraints-go-126)
- [stdlib `slices` Helpers](#stdlib-slices-helpers)
- [stdlib `maps` Helpers](#stdlib-maps-helpers)
- [Generic Repository Pattern](#generic-repository-pattern)
- [Type Inference in Practice](#type-inference-in-practice)
- [When NOT to Use Generics](#when-not-to-use-generics)

---
## Generic Filter

**Problem**: How to filter a slice by a predicate without repeating the loop for every type?

**Solution**:

```go
import "slices"

func Filter[S ~[]E, E any](s S, keep func(E) bool) S {
    return slices.DeleteFunc(s, func(e E) bool { return !keep(e) })
}

// Usage
nums := []int{1, 2, 3, 4, 5}
evens := Filter(nums, func(n int) bool { return n%2 == 0 })
// evens = []int{2, 4}
```

**Tip**: Build on `slices.DeleteFunc` — it reuses the backing array and avoids a second allocation. The `~[]E` constraint lets callers pass named slice types.

---

## Generic Map/Transform

**Problem**: How to transform each element of a slice into a new type?

**Solution**:

```go
func Map[In, Out any](s []In, f func(In) Out) []Out {
    out := make([]Out, len(s))
    for i, v := range s {
        out[i] = f(v)
    }
    return out
}

// Usage
names := []string{"alice", "bob"}
uppers := Map(names, strings.ToUpper)
// uppers = []string{"ALICE", "BOB"}
```

**Tip**: Pre-allocate the output slice to the exact size — `make([]Out, len(s))` avoids grow-amortization overhead in the loop.

---

## Generic Set Type

**Problem**: How to build a set data structure without writing one for each element type?

**Solution**:

```go
type Set[T comparable] map[T]struct{}

func NewSet[T comparable](vals ...T) Set[T] {
    s := make(Set[T], len(vals))
    for _, v := range vals {
        s[v] = struct{}{}
    }
    return s
}

func (s Set[T]) Has(v T) bool {
    _, ok := s[v]
    return ok
}

func (s Set[T]) Add(v T) {
    s[v] = struct{}{}
}

func (s Set[T]) Delete(v T) {
    delete(s, v)
}

// Usage
seen := NewSet[string]()
seen.Add("foo")
fmt.Println(seen.Has("foo")) // true
```

**Tip**: `map[T]struct{}` is the idiomatic Go set — `struct{}` carries zero bytes of storage per key. The `comparable` constraint covers all valid map key types.

---

## Numeric Constraints with `~int` / `~float64`

**Problem**: How to write a function that works across numeric types including custom named types?

**Solution**:

```go
import "golang.org/x/exp/constraints"

// Or define your own for a specific domain:
type Number interface {
    ~int | ~int8 | ~int16 | ~int32 | ~int64 |
        ~uint | ~uint8 | ~uint16 | ~uint32 | ~uint64 |
        ~float32 | ~float64
}

func Sum[T Number](vals []T) T {
    var total T
    for _, v := range vals {
        total += v
    }
    return total
}

type MyInt int
nums := []MyInt{1, 2, 3}
total := Sum(nums) // MyInt(6)
```

**Tip**: The `~` prefix accepts both the underlying type and named types derived from it. Without `~`, `Sum` would reject `MyInt`.

---

## `cmp.Ordered` for Total-Order Types

**Problem**: How to write a min/max or comparison function that works on all orderable types?

**Solution**:

```go
import "cmp"

func Min[T cmp.Ordered](a, b T) T {
    if a < b {
        return a
    }
    return b
}

// Usage on any ordered type:
minInt := Min(3, 7)       // 3
minStr := Min("abc", "xyz") // "abc"
```

**Tip**: `cmp.Ordered` covers `~int*`, `~uint*`, `~float*`, and `~string`. Use it instead of hand-rolling a constraint union. The `cmp` package also provides `cmp.Compare` and `cmp.Or`.

---

## Self-Referential Constraints (Go 1.26+)

**Problem**: How to write a generic interface where methods reference the implementing type itself?

**Solution**:

```go
// An interface where Equals takes another value of the same concrete type.
type Equaler[T any] interface {
    comparable
    Equals(T) bool
}

func Dedup[T Equaler[T]](items []T) []T {
    seen := make(map[T]struct{}, len(items))
    out := items[:0]
    for _, item := range items {
        if _, ok := seen[item]; !ok {
            seen[item] = struct{}{}
            out = append(out, item)
        }
    }
    return out
}

type ID string

func (id ID) Equals(other ID) bool { return id == other }

func main() {
    ids := []ID{"a", "b", "a", "c"}
    unique := Dedup(ids) // []ID{"a", "b", "c"}
}
```

**Tip**: Self-referential constraints use a type parameter on the interface (`Equaler[T any]`) and the constraint `T Equaler[T]` — the implementing type must satisfy the interface with itself as the argument. No special `Self` token is needed; this is standard Go generics since 1.18.

---

## stdlib `slices` Helpers

**Problem**: What generic slice operations does the standard library already provide?

**Solution**:

```go
import "slices"

// Check containment
slices.Contains([]string{"a", "b"}, "a")          // true

// Insert at position
slices.Insert([]int{1, 4}, 1, 2, 3)               // []int{1, 2, 3, 4}

// Remove elements matching predicate
slices.DeleteFunc([]int{1, 2, 3, 4}, func(n int) bool { return n%2 == 0 }) // []int{1, 3}

// Sort
slices.Sort([]string{"c", "a", "b"})               // []string{"a", "b", "c"}

// Binary search
pos, found := slices.BinarySearch([]int{1, 3, 5}, 3) // 1, true

// Clone (shallow copy)
copy := slices.Clone(original)

// Compact consecutive duplicates
slices.Compact([]int{1, 1, 2, 2, 3})               // []int{1, 2, 3}

// Pooled sorting with a custom less function
slices.SortFunc(records, func(a, b Record) int {
    return cmp.Compare(a.Priority, b.Priority)
})

// Clone with garbage-collector-friendly trimming
trimmed := slices.Clip(s)
```

**Tip**: Check `slices` and `maps` first — many operations you'd write generics for have been shipped since Go 1.21.

---

## stdlib `maps` Helpers

**Problem**: What generic map operations does the standard library provide?

**Solution**:

```go
import "maps"

// Clone (shallow)
copy := maps.Clone(original)

// Copy all entries
maps.Copy(dst, src)

// Delete entries matching predicate
maps.DeleteFunc(m, func(k string, v int) bool { return v == 0 })

// Collect from an iterator
entries := maps.Collect(slices.All([]string{"a", "b"}))

// Keys / Values as slices
keys := slices.Collect(maps.Keys(m))
vals := slices.Collect(maps.Values(m))

// Insert an iterator's entries
maps.Insert(dst, maps.All(src))
```

**Tip**: `maps.Keys` and `maps.Values` return iterators — wrap with `slices.Collect` to materialize a slice, or range directly in a `for k := range maps.Keys(m)` loop.

---

## Generic Repository Pattern

**Problem**: How to reuse CRUD logic across entity types without code generation?

**Solution**:

```go
type Repository[T any, ID comparable] interface {
    Get(ctx context.Context, id ID) (T, error)
    Create(ctx context.Context, entity T) error
    Update(ctx context.Context, id ID, entity T) error
    Delete(ctx context.Context, id ID) error
}

// Concrete implementation that delegates to storage:
type GenericRepo[T any, ID comparable] struct {
    store  Storer
    newT   func() *T // allocates a zero-value T for scanning
    table  string
    idCol  string
}

// Usage: create a typed repo in one line
type User struct { ID string; Name string }
userRepo := &GenericRepo[User, string]{table: "users", idCol: "id", ...}
```

**Tip**: A generic repo is useful for plumbing layers (e.g., a thin HTTP CRUD wrapper). For domain-rich repositories, prefer hand-written, type-specific interfaces — the business methods differ per entity and generics add indirection without value.

---

## Type Inference in Practice

**Problem**: When must I spell out type arguments and when can Go infer them?

**Solution**:

```go
func First[T any](s []T) T { return s[0] }

// Inference works when the type arg appears in a regular parameter:
first := First([]int{1, 2, 3}) // T inferred as int — no [int] needed

// Inference does NOT work when T only appears in the return or in constraints:
func Zero[T any]() T { var z T; return z }
z := Zero[int]() // must spell it out

// Partial inference with a constrained constructor:
func NewSet[T comparable](vals ...T) Set[T] { ... }

// Both work because T appears in the variadic parameter:
s1 := NewSet(1, 2, 3)        // T inferred as int
s2 := NewSet[int]()          // explicit when no args
```

**Tip**: Prefer inference when the compiler allows it — less noise for readers. Explicit type arguments are only required when a type parameter has no function-argument bearing it.

---

## When NOT to Use Generics

**Problem**: Generics are powerful — when do they make code worse?

**Solution**:

**1. Interface polymorphism already covers the need.**
```go
// DON'T: generic wrapper just to call a method
func CallString[T fmt.Stringer](v T) string { return v.String() }

// DO: use the interface directly
func CallString(v fmt.Stringer) string { return v.String() }
```

**2. Trivial wrappers over a single stdlib call.**
```go
// DON'T: adds no value beyond the stdlib function itself
func Contains[T comparable](s []T, v T) bool { return slices.Contains(s, v) }
```

**3. Performance-sensitive code where monomorphization overhead matters.**
Each distinct type argument may produce a separate instantiation. For hot paths, benchmark the generic version against a concrete one.

**4. The set of types is small and known.**
```go
// DON'T: write a generic when only 2-3 types ever use it
// DO: write the two concrete functions — simpler to read and test
```

**Tip**: Ask: "Does this abstraction reduce duplication across many types, or am I adding a type parameter where an interface already suffices?" If the answer is "interface", skip generics.
