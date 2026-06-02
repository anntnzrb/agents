# Go 1.24–1.26 Cookbook

Recipes for Swiss Tables maps, generic type aliases, tool directives, testing improvements, and modernizers.

---

## Contents

- [Swiss Tables Maps (1.24)](#swiss-tables-maps-124)
- [Generic Type Aliases (1.24)](#generic-type-aliases-124)
- [go.mod Tool Directive (1.24)](#gomod-tool-directive-124)
- [testing.B.Loop (1.24)](#testingbloop-124)
- [testing/synctest (1.25)](#testingsynctest-125)
- [testing/slogtest (Go 1.21+)](#testingslogtest-go-121)
- [Container-Aware GOMAXPROCS (1.25)](#container-aware-gomaxprocs-125)
- [new(expr) (1.26)](#newexpr-126)
- [errors.AsType (1.26)](#errorsastype-126)
- [testing.T.ArtifactDir (1.26)](#testingtartifactdir-126)
- [go fix Modernizers (1.26)](#go-fix-modernizers-126)

---
## Swiss Tables Maps (1.24)

**Problem**: Go maps historically used a custom hash table with separate overflow chains. Under high collision or load-factor pressure, lookup latency degrades.

**Solution**: Go 1.24 replaced the map backend with Swiss Tables, giving better cache locality and faster lookups.

```go
// No API change — all existing map code benefits automatically
m := make(map[string]int)
m["key"] = 42
v := m["key"] // faster under the hood
```

**Tip**: The map API is unchanged. Rebuild with Go 1.24+ to get the performance improvement. Hash-based ordering of map iteration may differ from prior versions — never depend on iteration order.

---

## Generic Type Aliases (1.24)

**Problem**: How to create a short alias for a parameterized type without defining a new named type?

**Solution**: Go 1.24 allows type aliases to carry type parameters.

```go
// Before 1.24: must define a new named type
type MyMap[K comparable, V any] map[K]V

// Go 1.24+: type alias preserves identity
type Set[K comparable] = map[K]struct{}

// Interchangeable — Set[string] IS map[string]struct{}
func Add[K comparable](s Set[K], k K) {
    s[k] = struct{}{}
}

// Works directly because Set[K] is map[K]struct{}
m := make(Set[string])
m["hello"] = struct{}{}
delete(m, "hello") // delete works without conversion
```

**Tip**: Generic type aliases are interchangeable with the underlying type. Use them to shorten repetitive parameterized types. The `=` token distinguishes aliases from new named types.

---

## go.mod Tool Directive (1.24)

**Problem**: How to declare tool dependencies (linters, generators) in `go.mod` so they're versioned and reproducible?

**Solution**: The `tool` directive in `go.mod` declares tools the module needs without them being imported.

```go
// go.mod
module example.com/myapp

go 1.24

tool (
    honnef.co/go/tools/cmd/staticcheck
    golang.org/x/tools/cmd/stringer
)

require (
    golang.org/x/tools v0.30.0
    honnef.co/go/tools v0.6.0
)
```

```bash
# Install all tools from go.mod
go install tool

# Run a tool without pre-install
go tool staticcheck ./...

# Add a tool
go get -tool honnef.co/go/tools/cmd/staticcheck
```

**Tip**: `go tool` commands download and cache tool binaries under the module cache. Use `go tool <name>` to run any declared tool. Replace old `tools.go` files and `//go:build tools` patterns.

---

## testing.B.Loop (1.24)

**Problem**: The `for i := 0; i < b.N; i++` benchmark loop is boilerplate. Mispasting or resetting `b.N` silently breaks benchmarks.

**Solution**: `b.Loop()` replaces the manual loop and avoids `b.N` entirely.

```go
// Before 1.24
func BenchmarkProcess(b *testing.B) {
    data := setup()
    b.ResetTimer()
    for i := 0; i < b.N; i++ {
        Process(data)
    }
}

// Go 1.24: no b.N, no off-by-one risk
func BenchmarkProcess(b *testing.B) {
    data := setup()
    b.ResetTimer()
    for b.Loop() {
        Process(data)
    }
}
```

**Tip**: `b.Loop()` returns true exactly `b.N` times. It replaces the entire `for i := 0; i < b.N; i++` pattern. The compiler checks that `b.Loop()` is called at the top of a for-loop — misuse is a compile error.

---

## testing/synctest (1.25)

**Problem**: How to test concurrent code with deterministic, fake-time control instead of flaky `time.Sleep` races?

**Solution**: `testing/synctest` provides a test-only goroutine bubble where time is fake and concurrency is deterministic.

```go
import "testing/synctest"

func TestWithTimeout(t *testing.T) {
    synctest.Test(t, func(t testing.TB) {
        // Inside synctest bubble: time is fake
        timeout := time.After(5 * time.Second)
        ch := make(chan int)

        go func() {
            time.Sleep(3 * time.Second)
            ch <- 42
        }()

        select {
        case v := <-ch:
            if v != 42 {
                t.Errorf("got %d, want 42", v)
            }
        case <-timeout:
            t.Error("timed out")
        }
    })
}
```

**Tip**: `synctest.Test` wraps the test function in a deterministic fake-time bubble. All goroutines started inside share a single fake clock. The test runner advances time in deterministic steps — no races, no flakes. Use `synctest.Wait()` to block until all goroutines are idle. Stable since Go 1.25 (replaces the experimental `synctest.Run` from Go 1.24).


---

## testing/slogtest (Go 1.21+)

**Note**: `testing/slogtest` is not a Go 1.25 addition — it has been available since Go 1.21. It provides `slogtest.TestHandler` for validating custom `slog.Handler` implementations. It does **not** provide log capture or structured assertion for application logs. Use `slog.NewRecord` and manual inspection, or a handler that collects into a buffer, for testing application log output.
---

## Container-Aware GOMAXPROCS (1.25)

**Problem**: Go's runtime previously read `/proc/cpuinfo` for CPU count, ignoring cgroup limits, leading to too many OS threads inside containers.

**Solution**: Go 1.25 detects cgroup v2 CPU limits automatically. `runtime.GOMAXPROCS` defaults to the container's quota, not the host's core count.

```go
// Automatic — no code change needed
// In a container with 2 CPUs, GOMAXPROCS defaults to 2

// Manual override still works
runtime.GOMAXPROCS(4)
```

**Tip**: Rebuild with Go 1.25+ and the runtime respects cgroup v2 `cpu.max`. No more `GOMAXPROCS=2` env vars in Dockerfiles. Works with Kubernetes, Docker, and systemd cgroup setups.

---

## new(expr) (1.26)

**Problem**: `new(T)` only zero-initializes. To initialize a pointer-to-struct, you need a separate variable or a constructor function.

**Solution**: `new(T{...})` allocates and initializes in one expression.

```go
// Before 1.26
u := &User{Name: "Alice", Age: 30}

// Go 1.26: new(expr) — equivalent, may be clearer in some contexts
u := new(User{Name: "Alice", Age: 30})

// Works with any value expression
f := new(42)               // *int pointing to 42
s := new("hello")          // *string pointing to "hello"
ch := new(make(chan int))  // *chan int (unbuffered)
```

**Tip**: `new(expr)` is syntactic sugar for taking the address of a value expression. It never allocates on the heap unless the pointer escapes. Prefer `&T{...}` for struct literals; `new(expr)` is useful in generic code where `&` on a value expression is awkward.

---

## errors.AsType (1.26)

**Problem**: `errors.As(err, &target)` requires declaring a variable first, which is verbose for single-error-type matching.

**Solution**: `errors.AsType[T]` returns `(T, bool)` directly — no pointer-to-interface ceremony.

```go
// Before 1.26: two-step
var pathErr *os.PathError
if errors.As(err, &pathErr) {
    fmt.Println(pathErr.Path)
}

// After 1.26: one-step
if pathErr, ok := errors.AsType[*os.PathError](err); ok {
    fmt.Println(pathErr.Path)
}

// Combine with switch for multiple error types
switch {
case pathErr, ok := errors.AsType[*os.PathError](err); ok:
    fmt.Println("path:", pathErr.Path)
case valErr, ok := errors.AsType[*ValidationError](err); ok:
    fmt.Println("field:", valErr.Field)
default:
    fmt.Println("unknown error:", err)
}
```

**Tip**: `errors.AsType` works through the error chain like `errors.As`. The `if`-with-declaration form keeps the extracted value scoped to the branch.

---


## testing.T.ArtifactDir (1.26)

**Problem**: Where to write test artifacts (profiles, golden files, debug dumps) so they survive for inspection after the test?

**Solution**: `t.ArtifactDir()` always returns a per-test directory. When `go test -artifacts` is set, the directory is preserved after the test; otherwise it is cleaned up.

```go
func TestGenerate(t *testing.T) {
    dir := t.ArtifactDir()

    // Write a golden file for manual inspection
    output := filepath.Join(dir, "output.json")
    data, err := json.MarshalIndent(result, "", "  ")
    if err != nil {
        t.Fatal(err)
    }
    if err := os.WriteFile(output, data, 0o644); err != nil {
        t.Fatal(err)
    }

    t.Logf("artifacts at %s", dir)
}

func TestProfile(t *testing.T) {
    f, err := os.Create(filepath.Join(t.ArtifactDir(), "cpu.pprof"))
    if err != nil {
        t.Fatal(err)
    }
    if err := pprof.StartCPUProfile(f); err != nil {
        t.Fatal(err)
    }
    defer pprof.StopCPUProfile()
    // ... test body
}
```

**Tip**: `t.ArtifactDir()` always returns a directory — no guard needed. Set `-artifacts` with `go test` to preserve artifacts after the test run. The directory is a subdirectory of the test binary's working directory. Available since Go 1.26.

---

## go fix Modernizers (1.26)

**Problem**: Codebases accumulate legacy patterns that need updating across many files.

**Solution**: `go fix` in 1.26 includes new modernizers that rewrite old idioms to their modern equivalents.

```bash
# Preview changes
go fix -diff ./...

# Apply all applicable modernizers
go fix ./...

# Run specific modernizers only
go fix -fix=loopvar,bnloop ./...

# Available modernizers in 1.26:
#   loopvar   — remove obsolete i := i workarounds
#   bnloop    — convert for i := 0; i < b.N; i++ to b.Loop()
#   tool      — migrate tools.go files to go.mod tool directive
#   aserror   — convert errors.As patterns to errors.AsType
#   new       — convert &T{...} to new(T{...}) where idiomatic
```

**Tip**: Run `go fix -diff` first to review changes. Commit before applying so you can revert. Modernizers are safe to apply mechanically but review the diff for edge cases.
