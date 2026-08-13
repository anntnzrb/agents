# Iterators Cookbook

Go 1.23+ range-over-function iterators: `iter.Seq`, `iter.Seq2`.

## Range over a function

Custom types implement `for range` with `iter.Seq[V]` (`func(yield func(V) bool)`):

```go
// iter.Seq[V] is func(yield func(V) bool)
func (s *Set[T]) All() iter.Seq[T] {
    return func(yield func(T) bool) {
        for _, v := range s.items {
            if !yield(v) {
                return // caller broke early
            }
        }
    }
}

// Usage:
for v := range s.All() {
    fmt.Println(v)
}
```

`yield` returns `false` when the caller breaks, returns, or the loop body panics. MUST check it and stop to avoid wasted work.

## Key-value iteration

`iter.Seq2[K, V]` is `func(yield func(K, V) bool)`:

```go
// iter.Seq2[K, V] is func(yield func(K, V) bool)
func (m *OrderedMap[K, V]) All() iter.Seq2[K, V] {
    return func(yield func(K, V) bool) {
        for _, entry := range m.entries {
            if !yield(entry.Key, entry.Value) {
                return
            }
        }
    }
}

// Usage:
for k, v := range m.All() {
    fmt.Println(k, v)
}
```

Convention: `All()` iterates all elements; filtered views use descriptive names such as `Filtered(…)`, `Keys()`, `Values()`.

## Stdlib consumption

```go
import (
    "iter"
    "slices"
    "maps"
)

// Collect into a slice
seq := mySet.All()
all := slices.Collect(seq)          // []T

// Append to existing slice
more := slices.AppendSeq(existing, seq)

// Collect Seq2 into a map
pairs := myMap.All()
m := maps.Collect(pairs)            // map[K]V

// Keys and values from a map
for k := range maps.Keys(myMap) {   // iter.Seq[K]
    fmt.Println(k)
}
for v := range maps.Values(myMap) { // iter.Seq[V]
    fmt.Println(v)
}

// Sort iterator output
sorted := slices.Sorted(maps.Values(myMap))

// Split a string (Go 1.24+)
for word := range strings.SplitSeq("a b c", " ") {
    fmt.Println(word)
}
```

`slices.Collect` allocates a new slice; use `slices.AppendSeq` with an existing buffer. `maps.Keys` and `maps.Values` are lazy and allocate no intermediates.

## Filtering

Lazy, allocation-free (no intermediate slice) filtered view:

```go
func Filter[V any](seq iter.Seq[V], pred func(V) bool) iter.Seq[V] {
    return func(yield func(V) bool) {
        for v := range seq {
            if pred(v) && !yield(v) {
                return
            }
        }
    }
}

// Usage:
for v := range Filter(items.All(), func(v int) bool { return v > 0 }) {
    fmt.Println(v)
}
```

Elements evaluate one at a time as the caller pulls.

## Mapping

Lazy transformation without an intermediate collection:

```go
func Map[In, Out any](seq iter.Seq[In], fn func(In) Out) iter.Seq[Out] {
    return func(yield func(Out) bool) {
        for v := range seq {
            if !yield(fn(v)) {
                return
            }
        }
    }
}

// Usage:
names := Map(users.All(), func(u User) string { return u.Name })
for name := range names {
    fmt.Println(name)
}
```

Map and Filter can form a pipeline; each stage remains lazy and processes one element at a time.

## Pull-style consumption

`iter.Pull` converts push-style `Seq` consumption to imperative next/done consumption. MUST `defer stop()` to release iterator state/resources. `iter.Pull2` is the `Seq2` equivalent.

```go
seq := mySet.All()
next, stop := iter.Pull(seq)
defer stop()

for {
    v, ok := next()
    if !ok {
        break
    }
    if done := process(v); done {
        return
    }
}
```

## Pull2

```go
seq2 := myMap.All()
next, stop := iter.Pull2(seq2)
defer stop()

for {
    k, v, ok := next()
    if !ok {
        break
    }
    fmt.Println(k, v)
}
```

`Pull2` returns `(func() (K, V, bool), func())`; `next`'s third result is `false` on exhaustion.

## Lazy Filter + Map + Take pipeline

```go
func Take[V any](seq iter.Seq[V], n int) iter.Seq[V] {
    return func(yield func(V) bool) {
        count := 0
        for v := range seq {
            if count >= n {
                return
            }
            if !yield(v) {
                return
            }
            count++
        }
    }
}

// Pipeline: top 3 active users by name
active := Filter(users.All(), func(u User) bool { return u.Active })
names := Map(active, func(u User) string { return u.Name })
top := Take(names, 3)

for name := range top {
    fmt.Println(name)
}
```

Each adapter allocates a closure but no intermediate data; each element passes through the full pipeline before the next.

## When to use iterators

Use for:
- Custom structures benefiting from lazy iteration (tree, graph, generator).
- Filter/map/take transformation pipelines.
- Public APIs exposing contents without underlying representation (for example, a `Set` backed by a map).
- Interoperation with functions accepting `iter.Seq`.

Skip for:
- Plain slices, maps, or arrays; use `for range` directly.
- Simple logic where indirection adds no benefit.
- Performance-critical paths where closure allocation matters; measure first.

Iterators are primarily a public-API concern. Do not refactor private loops unless iterators simplify the code.

```go
// BAD — overhead for a trivial loop
for v := range slices.Values([]int{1, 2, 3}) {
    fmt.Println(v)
}

// GOOD — just range over the slice directly
for _, v := range []int{1, 2, 3} {
    fmt.Println(v)
}

// BAD — wrapping a []byte for no reason
for b := range iterBytes(data) { ... }

// GOOD — iterate directly
for _, b := range data { ... }
```

## Collection interop

Use these allocation-free bridges from concrete collections to `iter.Seq`/`iter.Seq2`: `slices.Values`, `slices.All`, `slices.Backward`, `maps.All`, `maps.Keys`, `maps.Values`.

```go
// Slice/array/map values to Seq
items := []string{"a", "b", "c"}
for v := range slices.Values(items) { // iter.Seq[string]
    fmt.Println(v)
}

// Slice to Seq2 (index, value)
for i, v := range slices.All(items) { // iter.Seq2[int, string]
    fmt.Println(i, v)
}

// Map to Seq2
m := map[string]int{"a": 1, "b": 2}
for k, v := range maps.All(m) { // iter.Seq2[string, int]
    fmt.Println(k, v)
}

// Backward iteration
for i, v := range slices.Backward(items) {
    fmt.Println(i, v)
}
```
