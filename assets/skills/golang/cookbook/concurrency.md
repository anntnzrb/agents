# Concurrency Cookbook

Recipes for goroutines, channels, synchronization, and concurrent patterns in Go 1.26.

---

## Contents

- [Basic Goroutines with WaitGroup](#basic-goroutines-with-waitgroup)
- [Goroutines with Results](#goroutines-with-results)
- [Producer-Consumer Pattern](#producer-consumer-pattern)
- [Fan-Out/Fan-In](#fan-outfan-in)
- [Select with Timeout](#select-with-timeout)
- [Context Cancellation](#context-cancellation)
- [Context Timeout](#context-timeout)
- [Context Values](#context-values)
- [context.WithCancelCause](#contextwithcancelcause)
- [context.AfterFunc](#contextafterfunc)
- [errgroup for Concurrent Operations](#errgroup-for-concurrent-operations)
- [sourcegraph/conc Pool (Optional)](#sourcegraphconc-pool-optional)
- [Mutex for Shared State](#mutex-for-shared-state)
- [RWMutex for Read-Heavy Workloads](#rwmutex-for-read-heavy-workloads)
- [sync.Once for One-Time Initialization](#synconce-for-one-time-initialization)
- [sync.Map for Concurrent Map Access](#syncmap-for-concurrent-map-access)
- [Rate Limiting](#rate-limiting)
- [Deterministic Concurrent Testing with synctest](#deterministic-concurrent-testing-with-synctest)

---
## Basic Goroutines with WaitGroup

**Problem**: How to run multiple tasks concurrently and wait for all to complete?

**Solution**:

```go
import "sync"

func processAll(items []Item) {
    var wg sync.WaitGroup

    for _, item := range items {
        wg.Add(1)
        go func() {
            defer wg.Done()
            process(item)
        }()
    }

    wg.Wait()
}
```

**Tip**: Go 1.22+ loop variables are per-iteration — no more `item := item` needed. Always call `wg.Add(1)` before starting the goroutine, not inside it.

---

## Goroutines with Results

**Problem**: How to collect results from multiple concurrent goroutines?

**Solution**:

```go
func processAllWithResults(items []Item) []Result {
    results := make([]Result, len(items))
    var wg sync.WaitGroup

    for i, item := range items {
        wg.Add(1)
        go func() {
            defer wg.Done()
            results[i] = process(item)
        }()
    }

    wg.Wait()
    return results
}
```

**Tip**: Writing to different slice indices is safe without a mutex. The pre-allocated slice avoids races.

---

## Producer-Consumer Pattern

**Problem**: How to decouple data production from consumption using channels?

**Solution**:

```go
func producer(ch chan<- int) {
    for i := 0; i < 10; i++ {
        ch <- i
    }
    close(ch)
}

func consumer(ch <-chan int) {
    for v := range ch {
        fmt.Println(v)
    }
}

func main() {
    ch := make(chan int, 10) // Buffered channel
    go producer(ch)
    consumer(ch)
}
```

**Tip**: Always close channels from the sender side. Use directional channel types (`chan<-`, `<-chan`) to enforce intent at compile time.

---

## Fan-Out/Fan-In

**Problem**: How to distribute work across multiple workers and merge their results?

**Solution**:

```go
func fanOut(input <-chan int, workers int) []<-chan int {
    outputs := make([]<-chan int, workers)
    for i := 0; i < workers; i++ {
        outputs[i] = worker(input)
    }
    return outputs
}

func fanIn(channels ...<-chan int) <-chan int {
    var wg sync.WaitGroup
    out := make(chan int)

    for _, ch := range channels {
        wg.Add(1)
        go func() {
            defer wg.Done()
            for v := range ch {
                out <- v
            }
        }()
    }

    go func() {
        wg.Wait()
        close(out)
    }()

    return out
}
```

**Tip**: Fan-out distributes load; fan-in merges results. Combine for parallel pipeline stages. Close the merged output only after all inputs drain.

---

## Select with Timeout

**Problem**: How to avoid blocking forever when waiting for channel operations?

**Solution**:

```go
func doWithTimeout(ch <-chan Result, timeout time.Duration) (Result, error) {
    select {
    case result, ok := <-ch:
        if !ok {
            return Result{}, fmt.Errorf("channel closed")
        }
        return result, nil
    case <-time.After(timeout):
        return Result{}, errors.New("timeout")
    }
}
```

**Tip**: Avoid `time.After` inside loops — each call creates a new timer that is garbage-collected only after firing. Use `time.NewTimer` and `Reset()` for loops:

```go
t := time.NewTimer(timeout)
defer t.Stop()
for {
    t.Reset(timeout)
    select {
    case v := <-ch:
        // process v
    case <-t.C:
        return errors.New("timeout")
    }
}
```

---

## Context Cancellation

**Problem**: How to gracefully stop long-running goroutines?

**Solution**:

```go
func longRunningTask(ctx context.Context) error {
    for {
        select {
        case <-ctx.Done():
            return context.Cause(ctx)
        default:
            if done := doPartialWork(); done {
                return nil
            }
        }
    }
}

// Usage
ctx, cancel := context.WithCancel(context.Background())
defer cancel()

go func() {
    time.Sleep(5 * time.Second)
    cancel()
}()

err := longRunningTask(ctx)
```

**Tip**: Always `defer cancel()` to prevent context leaks. Check `ctx.Done()` in every loop iteration. Use `context.Cause(ctx)` to retrieve the cancellation reason.

---

## Context Timeout

**Problem**: How to automatically cancel operations that take too long?

**Solution**:

```go
ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
defer cancel()

result, err := fetchData(ctx, url)
if errors.Is(err, context.DeadlineExceeded) {
    log.Println("request timed out")
}
```

**Tip**: Pass context as the first parameter. The stdlib and most third-party APIs accept context. Combine timeouts with cancellation for defense in depth.

---

## Context Values

**Problem**: How to pass request-scoped data through function calls without changing signatures?

**Solution**:

```go
type ctxKey string

const userIDKey ctxKey = "userID"

func WithUserID(ctx context.Context, id string) context.Context {
    return context.WithValue(ctx, userIDKey, id)
}

func UserIDFrom(ctx context.Context) (string, bool) {
    id, ok := ctx.Value(userIDKey).(string)
    return id, ok
}
```

**Tip**: Use custom types for keys to avoid collisions. Only use for request-scoped metadata (trace IDs, user IDs), never for dependencies or business logic.

---

## context.WithCancelCause

**Problem**: How to propagate a cancellation reason so callers can distinguish failures?

**Solution**:

```go
ctx, cancel := context.WithCancelCause(context.Background())

go func() {
    time.Sleep(5 * time.Second)
    if err := healthCheck(); err != nil {
        cancel(fmt.Errorf("health check failed: %w", err))
    }
}()

if err := worker(ctx); err != nil {
    cause := context.Cause(ctx)
    log.Println("cancelled because:", cause)
}
```

**Tip**: `errors.Is` works on `context.Cause()` too. Use distinct sentinel errors as causes to let callers branch on cancellation reason. Available since Go 1.20.

---

## context.AfterFunc

**Problem**: How to schedule cleanup or notification when a context is done — without a dedicated goroutine?

**Solution**:

```go
ctx, cancel := context.WithCancel(context.Background())
defer cancel()

stop := context.AfterFunc(ctx, func() {
    conn.Close()
    log.Println("connection closed due to context cancellation")
})
defer stop() // Unregister if context is not done yet

// ... use ctx normally
```

**Tip**: `AfterFunc` runs the callback in its own goroutine when the context is done. Call `stop()` to unregister the callback if it is no longer needed. Available since Go 1.21.

---

## errgroup for Concurrent Operations

**Problem**: How to run concurrent operations and return on first error?

**Solution**:

```go
import "golang.org/x/sync/errgroup"

func fetchAll(urls []string) ([]Response, error) {
    g, ctx := errgroup.WithContext(context.Background())
    g.SetLimit(10) // Max concurrent goroutines

    responses := make([]Response, len(urls))

    for i, url := range urls {
        g.Go(func() error {
            resp, err := fetch(ctx, url)
            if err != nil {
                return err
            }
            responses[i] = resp
            return nil
        })
    }

    if err := g.Wait(); err != nil {
        return nil, err
    }
    return responses, nil
}
```

**Tip**: The context from `errgroup.WithContext` is cancelled when any goroutine returns an error. `SetLimit` bounds concurrency without manual semaphores. Use `TryGo` instead of `Go` for non-blocking submission — it returns `false` if the limit is reached.

---

## sourcegraph/conc Pool (Optional)

**Problem**: How to manage goroutine pools with panic recovery and result collection?

**Solution**:

```go
import "github.com/sourcegraph/conc/pool"

// Pool with results
func processWithResults(items []Item) []Result {
    p := pool.NewWithResults[Result]().WithMaxGoroutines(10)
    for _, item := range items {
        p.Go(func() Result { return process(item) })
    }
    return p.Wait()
}

// Pool with errors
func processWithErrors(items []Item) error {
    p := pool.New().WithErrors().WithMaxGoroutines(10)
    for _, item := range items {
        p.Go(func() error { return process(item) })
    }
    return p.Wait()
}
```

**Tip**: `conc` catches panics and re-raises them cleanly. Results are collected automatically. Use when you want less boilerplate than `errgroup`. Not a standard library — add to `go.mod` only if the ergonomic tradeoff is worth it.

---

## Mutex for Shared State

**Problem**: How to safely access shared data from multiple goroutines?

**Solution**:

```go
type Counter struct {
    mu    sync.Mutex
    value int
}

func (c *Counter) Inc() {
    c.mu.Lock()
    defer c.mu.Unlock()
    c.value++
}

func (c *Counter) Value() int {
    c.mu.Lock()
    defer c.mu.Unlock()
    return c.value
}
```

**Tip**: Keep the critical section small. For simple integer counters, prefer `sync/atomic` — it is lock-free and faster.

---

## RWMutex for Read-Heavy Workloads

**Problem**: How to allow concurrent reads while ensuring exclusive writes?

**Solution**:

```go
type Cache struct {
    mu   sync.RWMutex
    data map[string]string
}

func (c *Cache) Get(key string) (string, bool) {
    c.mu.RLock()
    defer c.mu.RUnlock()
    v, ok := c.data[key]
    return v, ok
}

func (c *Cache) Set(key, value string) {
    c.mu.Lock()
    defer c.mu.Unlock()
    c.data[key] = value
}
```

**Tip**: Use `RWMutex` when reads vastly outnumber writes. Multiple readers can hold `RLock` simultaneously. Never `Lock` while holding `RLock` — that deadlocks.

---

## sync.Once for One-Time Initialization

**Problem**: How to ensure initialization code runs exactly once, even with concurrent callers?

**Solution**:

```go
type Client struct {
    initOnce sync.Once
    conn     *Connection
}

func (c *Client) getConn() *Connection {
    c.initOnce.Do(func() {
        c.conn = connect()
    })
    return c.conn
}
```

**Tip**: `sync.Once` is goroutine-safe. Other goroutines block until the `Do` callback completes. For values that need to be returned, wrap in a struct like above — `sync.OnceValue` and `sync.OnceValues` (Go 1.21+) return the value directly instead:

```go
var getConn = sync.OnceValue(func() *Connection {
    return connect()
})
```

---

## sync.Map for Concurrent Map Access

**Problem**: How to use a map safely from multiple goroutines without manual locking?

**Solution**:

```go
var cache sync.Map

// Store
cache.Store("key", value)

// Load
if v, ok := cache.Load("key"); ok {
    // Use v.(YourType)
}

// LoadOrStore — atomic get-or-set
actual, loaded := cache.LoadOrStore("key", newValue)

// Delete
cache.Delete("key")

// Range — iterate safely
cache.Range(func(key, value any) bool {
    fmt.Println(key, value)
    return true // Continue iteration
})
```

**Tip**: `sync.Map` is optimized for caches with many reads, few writes, and disjoint key sets. For general-purpose concurrent maps, use a regular `map` with `sync.RWMutex`.

---

## Rate Limiting

**Problem**: How to limit the rate of operations (e.g., API calls)?

**Solution**:

```go
import "golang.org/x/time/rate"

// Allow 10 requests per second, burst of 20
limiter := rate.NewLimiter(10, 20)

func handleRequest(ctx context.Context) error {
    if err := limiter.Wait(ctx); err != nil {
        return err // Context cancelled
    }
    return processRequest()
}

// Non-blocking check
if limiter.Allow() {
    processRequest()
} else {
    return errors.New("rate limited")
}
```

**Tip**: `Wait` blocks until allowed or the context is done. `Allow` returns immediately. Use `Reserve` for custom scheduling when you need to know how long to wait.

For deterministic concurrent testing, use `testing/synctest` (Go 1.25+). See `cookbook/modern-1.24-1.26.md` for recipes.