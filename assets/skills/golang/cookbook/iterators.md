# Iterators Cookbook

Recipes for Go's range-over-func iterators (`iter.Seq`, `iter.Seq2`) added in Go 1.23+.

---

## Contents

- [Range Over a Function](#range-over-a-function)
- [Iterating with Keys (iter.Seq2)](#iterating-with-keys-iterseq2)
- [Consuming Iterators with Stdlib](#consuming-iterators-with-stdlib)
- [Filtering Iterators](#filtering-iterators)
- [Mapping Iterators](#mapping-iterators)
- [Pull-Style Consumption (iter.Pull)](#pull-style-consumption-iterpull)
- [Pull2 for Key-Value Iterators](#pull2-for-key-value-iterators)
- [Lazy Pipeline (Filter + Map + Take)](#lazy-pipeline-filter--map--take)
- [When NOT to Use Iterators](#when-not-to-use-iterators)
- [Interop: Converting Slices and Maps to Iterators](#interop-converting-slices-and-maps-to-iterators)

---
## Range Over a Function

**Problem**: How to make a custom data structure iterable with `for range`?

**Solution**:

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

**Tip**: The `yield` function returns `false` when the caller breaks, returns, or the loop body panics. Always check its return value and stop iterating — it avoids wasted work.

---

## Iterating with Keys (iter.Seq2)

**Problem**: How to iterate over key-value pairs from a custom collection?

**Solution**:

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

**Tip**: Naming convention: `All()` returns an iterator over all elements. For filtered views, use descriptive method names like `Filtered(…)`, `Keys()`, `Values()`.

---

## Consuming Iterators with Stdlib

**Problem**: How to collect iterator values into a slice, map, or use them with standard library functions?

**Solution**:

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

**Tip**: `slices.Collect` allocates a new slice. Use `slices.AppendSeq` if you already have a buffer. `maps.Keys` and `maps.Values` are lazy — they don't allocate intermediates.

---

## Filtering Iterators

**Problem**: How to create a filtered view of an iterator without allocating a new collection?

**Solution**:

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

**Tip**: Filter is lazy — elements are evaluated one at a time as the caller pulls. No intermediate slice is allocated.

---

## Mapping Iterators

**Problem**: How to transform each element of an iterator without an intermediate collection?

**Solution**:

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

**Tip**: Chain Map and Filter together for pipeline-style data processing. Each step is lazy — the full chain runs one element at a time.

---

## Pull-Style Consumption (iter.Pull)

**Problem**: How to consume an iterator imperatively with next/done rather than `for range`?

**Solution**:

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

**Tip**: Always `defer stop()` to release resources — the iterator function may hold state that needs cleanup. `Pull` converts the push style into pull style; `Pull2` is the equivalent for `Seq2`.

---

## Pull2 for Key-Value Iterators

**Problem**: How to pull key-value pairs from a Seq2 iterator imperatively?

**Solution**:

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

**Tip**: `Pull2` returns `(func() (K, V, bool), func())`. The `next` function returns a third `bool` that is `false` when the iterator is exhausted.

---

## Lazy Pipeline (Filter + Map + Take)

**Problem**: How to build a composable lazy pipeline of iterator transformations?

**Solution**:

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

**Tip**: Each adapter allocates a closure but no intermediate data. The pipeline processes one element fully through all stages before moving to the next.

---

## When NOT to Use Iterators

**Problem**: Iterators are elegant — should I use them everywhere?

**Solution**:

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

Use iterators when:
- You have a custom data structure that benefits from lazy iteration (tree, graph, generator)
- You are composing transformation pipelines (filter, map, take)
- You need to expose collection contents without exposing the underlying representation
- You are interop with functions that accept `iter.Seq`

Skip iterators when:
- You have a plain slice, map, or array — use `for range` directly
- The logic is simple and adding an iterator adds indirection without benefit
- Performance is critical and the closure allocation overhead matters (measure first)

**Tip**: Iterators are a public API concern. Use them to hide implementation details (e.g., a `Set` backed by a map). Don't refactor private loops into iterators unless they simplify the code.

---

## Interop: Converting Slices and Maps to Iterators

**Problem**: How to pass slices and maps to functions that expect `iter.Seq` or `iter.Seq2`?

**Solution**:

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

**Tip**: `slices.Values`, `slices.All`, `slices.Backward`, `maps.All`, `maps.Keys`, `maps.Values` — use these to bridge concrete collections into the iterator world without allocation.

