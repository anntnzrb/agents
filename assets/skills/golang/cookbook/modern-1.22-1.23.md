# Go 1.22–1.23 Cookbook

Recipes for loop variable semantics, range-over-int, ServeMux routing, math/rand/v2, and iterators.

---

## Loop Variable Semantics (1.22+)

**Problem**: In Go ≤1.21, loop variables are reused across iterations, causing subtle bugs with goroutines and closures.

**Solution**: Go 1.22+ gives each iteration its own variable. No more `item := item` workaround.

```go
// Before 1.22 — BUG: all goroutines see the last value
for _, item := range items {
    go func() {
        process(item) // wrong
    }()
}

// Go 1.22+ — correct without extra copy
for _, item := range items {
    go func() {
        process(item) // each goroutine gets its own item
    }()
}
```

**Tip**: When a module declares `go 1.22` or later, the new semantics apply. A module with `go 1.22` requires a Go ≥1.22 toolchain — the old semantics are not available on a compatible toolchain. Libraries should bump the `go` line when they are ready to require Go 1.22+ for all consumers.

---

## Range over Integer

**Problem**: How to loop N times without an unused index variable?

**Solution**: `for range n` iterates from 0 to n-1.

```go
// Before 1.22
for i := 0; i < n; i++ {
    process()
}

// Go 1.22+
for range n {
    process()
}
```

**Tip**: `n` must be an integer expression (or constant). Negative values iterate zero times. Use `for range len(slice)` as a concise form.

---

## Enhanced ServeMux Routing

**Problem**: How to build HTTP APIs with method-based routing and path parameters without a third-party router?

**Solution**: Go 1.22+ `http.ServeMux` supports `METHOD /path` patterns, wildcards, and path-value extraction.

```go
mux := http.NewServeMux()

// Method-based routing
mux.HandleFunc("GET /users/{id}", func(w http.ResponseWriter, r *http.Request) {
    id := r.PathValue("id")
    fmt.Fprintf(w, "user %s", id)
})

mux.HandleFunc("POST /users/{id}", func(w http.ResponseWriter, r *http.Request) {
    id := r.PathValue("id")
    // create logic
})

// Wildcard matching
mux.HandleFunc("GET /files/{path...}", func(w http.ResponseWriter, r *http.Request) {
    path := r.PathValue("path")
    http.ServeFile(w, r, path)
})

// Exact match takes precedence over wildcard
mux.HandleFunc("GET /users/me", meHandler)
```

**Tip**: `{name}` matches a single path segment; `{name...}` matches the remainder of the path. Use `r.PathValue("name")` to extract values. A pattern ending in `/` acts as a subtree prefix match.

---

## math/rand/v2

**Problem**: `math/rand` has confusing seeding and poor statistical quality for many applications.

**Solution**: `math/rand/v2` provides a cleaner API with better defaults and no global source.

```go
import "math/rand/v2"

// Create a local generator
rng := rand.New(rand.NewPCG(1, 2))

// Common operations
n := rng.IntN(100)           // [0, 100)
f := rng.Float64()           // [0.0, 1.0)
perm := rng.Perm(10)         // random permutation of [0,10)

// Cryptographic: use crypto/rand
import "crypto/rand"
```

**Tip**: Drop the old `math/rand` entirely. `rand/v2` uses a PCG generator by default, is automatically seeded, and `IntN`, `UintN`, and `Float64` replace the old `Intn`, `Int31n`, etc. methods.

---

## iter.Seq and iter.Seq2

**Problem**: How to write custom iterators that work with `for range`?

**Solution**: Go 1.23 stabilised the `iter` package. Return `iter.Seq[V]` or `iter.Seq2[K, V]` from a function to make it rangeable.

```go
import "iter"

// Single-value iterator
func Count(n int) iter.Seq[int] {
    return func(yield func(int) bool) {
        for i := range n {
            if !yield(i) {
                return
            }
        }
    }
}

// Two-value iterator
func Enumerate[T any](s []T) iter.Seq2[int, T] {
    return func(yield func(int, T) bool) {
        for i, v := range s {
            if !yield(i, v) {
                return
            }
        }
    }
}

// Usage
for v := range Count(5) {
    fmt.Println(v) // 0, 1, 2, 3, 4
}

for i, v := range Enumerate([]string{"a", "b"}) {
    fmt.Println(i, v) // 0 a, 1 b
}
```

**Tip**: Check `yield`'s return value — returning `false` stops the loop (`break`). Always return from the iterator function after `yield` returns false.

---

## Pull Iterators

**Problem**: How to step through an iterator manually instead of with `for range`?

**Solution**: Use `iter.Pull` to convert a push iterator into a pull-style next/stop pair.

```go
next, stop := iter.Pull(Count(3))
defer stop()

for v, ok := next(); ok; v, ok = next() {
    fmt.Println(v) // 0, 1, 2
}

// Pull2 for two-value iterators
next2, stop2 := iter.Pull2(Enumerate([]string{"x", "y"}))
defer stop2()

for k, v, ok := next2(); ok; k, v, ok = next2() {
    fmt.Println(k, v) // 0 x, 1 y
}
```

**Tip**: Always call `stop()` when done — it releases resources. `defer stop()` is the standard pattern.

---

## Stdlib Iterator Integration (slices, maps)

**Problem**: How to iterate over stdlib collections using the new iterator protocol?

**Solution**: `slices.All`, `maps.All`, and related functions return iterators.

```go
import (
    "slices"
    "maps"
)

items := []string{"foo", "bar", "baz"}

// Range over index and value
for i, v := range slices.All(items) {
    fmt.Println(i, v)
}

// Range over values only
for v := range slices.Values(items) {
    fmt.Println(v)
}

// Backward iteration
for i, v := range slices.Backward(items) {
    fmt.Println(i, v) // 2 baz, 1 bar, 0 foo
}

// Map iteration
m := map[string]int{"a": 1, "b": 2}
for k, v := range maps.All(m) {
    fmt.Println(k, v)
}

// Collect iterators back into slices/maps
collected := slices.Collect(slices.Values(items))
```

**Tip**: Use `slices.Collect` to drain an iterator into a slice, and `maps.Collect` to drain a `Seq2` into a map. These functions replace ad-hoc accumulation loops.

---

## Iterator Chaining with Filter/Map

**Problem**: How to filter, transform, or combine iterators without intermediate allocations?

**Solution**: Compose iterators manually from the `iter` package primitives.

```go
// Filter an iterator inline
func Filter[V any](seq iter.Seq[V], pred func(V) bool) iter.Seq[V] {
    return func(yield func(V) bool) {
        for v := range seq {
            if pred(v) && !yield(v) {
                return
            }
        }
    }
}

// Map/transform an iterator
func Map[V, W any](seq iter.Seq[V], fn func(V) W) iter.Seq[W] {
    return func(yield func(W) bool) {
        for v := range seq {
            if !yield(fn(v)) {
                return
            }
        }
    }
}

// Usage
evens := Filter(slices.Values([]int{1, 2, 3, 4}), func(n int) bool {
    return n%2 == 0
})
squared := Map(evens, func(n int) string {
    return fmt.Sprintf("%d²", n)
})
for s := range squared {
    fmt.Println(s) // 2², 4²
}
```

**Tip**: Write iterator combinators inline when you need them — they are small and self-contained. For common patterns (Filter, Map, Concat), define package-level helpers once and reuse them across the codebase.
