# Go Generics Cookbook

Data structures, functional utilities, constraints, stdlib helpers, repositories, inference, and generics tradeoffs.

## Generic Filter

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

Use `slices.DeleteFunc`: it reuses the backing array and avoids a second allocation. `~[]E` admits named slice types.

## Generic Map/Transform

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

Pre-allocate exactly with `make([]Out, len(s))`; this avoids grow-amortization overhead.

## Generic Set Type

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

`map[T]struct{}` is idiomatic: `struct{}` carries zero bytes per key. `comparable` covers all valid map-key types.

## Numeric Constraints with `~int` / `~float64`

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

`~` admits the underlying type and named types derived from it; without `~`, `Sum` rejects `MyInt`.

## `cmp.Ordered` for Total-Order Types

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

`cmp.Ordered` covers `~int*`, `~uint*`, `~float*`, and `~string`; prefer it over a hand-rolled union. `cmp` also provides `cmp.Compare` and `cmp.Or`.

## Self-Referential Constraints (Go 1.26+)

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

Self-reference: interface type parameter `Equaler[T any]`, constraint `T Equaler[T]`; the implementing type satisfies the interface with itself as argument. No special `Self` token; standard Go generics since 1.18.

## stdlib `slices` Helpers

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

Check `slices` and `maps` first: many operations that invite custom generics shipped since Go 1.21.

## stdlib `maps` Helpers

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

`maps.Keys` and `maps.Values` return iterators: use `slices.Collect` to materialize slices, or range directly with `for k := range maps.Keys(m)`.

## Generic Repository Pattern

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

Useful for plumbing layers such as a thin HTTP CRUD wrapper. For domain-rich repositories, prefer hand-written type-specific interfaces: business methods differ per entity, so generics add indirection without value.

## Type Inference in Practice

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

Prefer inference when allowed. Explicit type arguments are required only when a type parameter has no function-argument bearing it.

## When NOT to Use Generics

1. Interface polymorphism already suffices:

```go
// DON'T: generic wrapper just to call a method
func CallString[T fmt.Stringer](v T) string { return v.String() }

// DO: use the interface directly
func CallString(v fmt.Stringer) string { return v.String() }
```

2. Trivial wrappers over one stdlib call:

```go
// DON'T: adds no value beyond the stdlib function itself
func Contains[T comparable](s []T, v T) bool { return slices.Contains(s, v) }
```

3. Performance-sensitive code where monomorphization overhead matters: each distinct type argument may produce a separate instantiation; benchmark generic against concrete code on hot paths.

4. Small, known type sets: when only 2-3 types use it, write concrete functions; they are simpler to read and test.

Ask: does the abstraction reduce duplication across many types, or add a type parameter where an interface suffices? If interface, skip generics.
