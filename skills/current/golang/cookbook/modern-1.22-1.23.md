# Go 1.22-1.23 Cookbook

## Loop variables (1.22+)

Go ≤1.21 reuses loop variables across iterations, causing goroutine/closure bugs. Go 1.22+ gives each iteration its own variable; no `item := item` workaround.

```go
// Before 1.22: BUG: all goroutines see the last value
for _, item := range items {
    go func() {
        process(item) // wrong
    }()
}

// Go 1.22+: correct without extra copy
for _, item := range items {
    go func() {
        process(item) // each goroutine gets its own item
    }()
}
```

A module declaring `go 1.22` or later uses the new semantics and requires a Go ≥1.22 toolchain; old semantics are unavailable on a compatible toolchain. Libraries should bump the `go` line when ready to require Go 1.22+ for all consumers.

## Range over integers

`for range n` loops 0..n-1 without an unused index.

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

`n`: integer expression or constant; negative values iterate zero times. `for range len(slice)` is a concise form.

## ServeMux routing (1.22+)

`http.ServeMux` supports method-based `METHOD /path` patterns, wildcards, and path-value extraction, enabling HTTP APIs without a third-party router.

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

`{name}` matches one path segment; `{name...}` matches the remainder. Extract values with `r.PathValue("name")`. A pattern ending `/` is a subtree-prefix match.

## `math/rand/v2`

`math/rand` has confusing seeding and poor statistical quality for many applications. `math/rand/v2` provides a cleaner API, better defaults, and no global source.

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

Drop old `math/rand`. `rand/v2` uses a PCG generator by default, is automatically seeded, and replaces old `Intn`, `Int31n`, etc. with `IntN`, `UintN`, and `Float64`.

## `iter.Seq` and `iter.Seq2` (1.23)

Go 1.23 stabilised the `iter` package. A function returning `iter.Seq[V]` or `iter.Seq2[K, V]` becomes rangeable.

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

Check `yield`'s return: `false` stops the loop (`break`); always return from the iterator function after `yield` returns false.

## Pull iterators

`iter.Pull` converts a push iterator to a pull-style `next`/`stop` pair.

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

Always call `stop()` when done; it releases resources. Standard pattern: `defer stop()`.

## Stdlib iterator integration

`slices.All`, `maps.All`, and related functions return iterators.

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

Use `slices.Collect` to drain an iterator into a slice and `maps.Collect` to drain a `Seq2` into a map; they replace ad-hoc accumulation loops.

## Iterator chaining: Filter/Map

Compose iterators manually from `iter` primitives to filter, transform, or combine without intermediate allocations.

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

Write small, self-contained combinators inline when needed. Define package-level helpers once for common patterns such as Filter, Map, and Concat, then reuse them across the codebase.
