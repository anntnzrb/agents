# Go 1.24-1.26 Cookbook

## Swiss Tables Maps (1.24)

Go 1.24 replaced the map backend with Swiss Tables: better cache locality and faster lookups. No API change; existing map code benefits automatically after rebuilding with Go 1.24+. Hash-based iteration order may differ; NEVER depend on map iteration order.

```go
// No API change: all existing map code benefits automatically
m := make(map[string]int)
m["key"] = 42
v := m["key"] // faster under the hood
```

## Generic Type Aliases (1.24)

Go 1.24 supports type aliases with type parameters. Generic aliases preserve identity and are interchangeable with their underlying type; `=` distinguishes an alias from a new named type. Use them to shorten repetitive parameterized types.

```go
// Before 1.24: must define a new named type
type MyMap[K comparable, V any] map[K]V

// Go 1.24+: type alias preserves identity
type Set[K comparable] = map[K]struct{}

// Interchangeable: Set[string] IS map[string]struct{}
func Add[K comparable](s Set[K], k K) {
    s[k] = struct{}{}
}

// Works directly because Set[K] is map[K]struct{}
m := make(Set[string])
m["hello"] = struct{}{}
delete(m, "hello") // delete works without conversion
```

## go.mod Tool Directive (1.24)

`go.mod` `tool` declares versioned, reproducible tool dependencies (linters, generators) without imports. `go tool` downloads and caches declared binaries in the module cache; use `go tool <name>` to run any declared tool. Replace old `tools.go` and `//go:build tools` patterns.

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

## testing.B.Loop (1.24)

`b.Loop()` replaces `for i := 0; i < b.N; i++`, avoiding `b.N`, boilerplate, off-by-one risk, and silent errors from mispasting or resetting `b.N`. It returns true exactly `b.N` times. The compiler requires it at the top of a `for` loop; misuse is a compile error.

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

## testing/synctest (1.25)

`testing/synctest` provides a test-only goroutine bubble with fake time and deterministic concurrency, replacing flaky `time.Sleep` races. `synctest.Test` wraps the test in one fake clock shared by all inner goroutines; the runner advances time in deterministic steps, eliminating races and flakes. `synctest.Wait()` blocks until all goroutines are idle. Stable since Go 1.25; replaces experimental Go 1.24 `synctest.Run`.

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

## testing/slogtest (Go 1.21+)

Not a Go 1.25 addition: available since Go 1.21. `slogtest.TestHandler` validates custom `slog.Handler` implementations; it does NOT capture logs or provide structured assertions for application logs. For application output, use `slog.NewRecord` with manual inspection or a buffer-collecting handler.

## Container-Aware GOMAXPROCS (1.25)

Go 1.25 detects cgroup v2 CPU limits automatically; `runtime.GOMAXPROCS` defaults to the container quota rather than host core count. Rebuild with Go 1.25+. It respects cgroup v2 `cpu.max`, including Kubernetes, Docker, and systemd cgroups; Dockerfiles no longer need `GOMAXPROCS=2` environment settings. Manual override remains available.

```go
// Automatic: no code change needed
// In a container with 2 CPUs, GOMAXPROCS defaults to 2

// Manual override still works
runtime.GOMAXPROCS(4)
```

## new(expr) (1.26)

Go 1.26 adds `new(expr)`: allocate and initialize from one value expression. It is syntactic sugar for taking the address of that expression and allocates on the heap only if the pointer escapes. Prefer `&T{...}` for struct literals; `new(expr)` can help generic code where `&` on a value expression is awkward.

```go
// Before 1.26
u := &User{Name: "Alice", Age: 30}

// Go 1.26: new(expr): equivalent, may be clearer in some contexts
u := new(User{Name: "Alice", Age: 30})

// Works with any value expression
f := new(42)               // *int pointing to 42
s := new("hello")          // *string pointing to "hello"
ch := new(make(chan int))  // *chan int (unbuffered)
```

## errors.AsType (1.26)

`errors.AsType[T]` returns `(T, bool)` directly, avoiding the variable and pointer-to-interface ceremony of `errors.As(err, &target)`. It traverses the error chain like `errors.As`; `if`-declaration scope keeps the extracted value branch-local.

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

## testing.T.ArtifactDir (1.26)

`t.ArtifactDir()` always returns a per-test directory for profiles, golden files, and debug dumps. With `go test -artifacts`, it is preserved after the test; otherwise it is cleaned up. No guard is needed. The directory is under the test binary's working directory.

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

Available since Go 1.26. Set `-artifacts` with `go test` to preserve artifacts after the run.

## go fix Modernizers (1.26)

Go 1.26 `go fix` includes modernizers that rewrite legacy idioms. Run `go fix -diff` first; commit before applying so changes can be reverted. Modernizers apply mechanically, but review diffs for edge cases.

```bash
# Preview changes
go fix -diff ./...

# Apply all applicable modernizers
go fix ./...

# Run specific modernizers only
go fix -fix=loopvar,bnloop ./...

# Available modernizers in 1.26:
#   loopvar  : remove obsolete i := i workarounds
#   bnloop   : convert for i := 0; i < b.N; i++ to b.Loop()
#   tool     : migrate tools.go files to go.mod tool directive
#   aserror  : convert errors.As patterns to errors.AsType
#   new      : convert &T{...} to new(T{...}) where idiomatic
```
