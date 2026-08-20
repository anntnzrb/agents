# Concurrency Cookbook

Go 1.26 recipes: goroutines, channels, synchronization, concurrent patterns.

## Basic Goroutines with WaitGroup

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

Go 1.22+: loop variables are per-iteration; no `item := item`. MUST call `wg.Add(1)` before `go`, never inside it.

## Goroutines with Results

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

Writes to distinct slice indices are safe without a mutex; preallocation avoids races.

## Producer-Consumer

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

Sender closes channels. Use directional channel types (`chan<-`, `<-chan`) to enforce intent at compile time.

## Fan-Out/Fan-In

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

Fan-out distributes load; fan-in merges results. Combine them for parallel pipeline stages. Close merged output only after all inputs drain.

## Select with Timeout

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

Avoid `time.After` inside loops: each call creates a timer garbage-collected only after firing. Use `time.NewTimer` and `Reset()`:

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

## Context Cancellation

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

MUST `defer cancel()` to prevent context leaks. Check `ctx.Done()` each loop iteration. Use `context.Cause(ctx)` for the cancellation reason.

## Context Timeout

```go
ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
defer cancel()

result, err := fetchData(ctx, url)
if errors.Is(err, context.DeadlineExceeded) {
    log.Println("request timed out")
}
```

Pass context as the first parameter. Stdlib and most third-party APIs accept context. Combine timeouts with cancellation for defense in depth.

## Context Values

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

Use custom key types to avoid collisions. Context values are for request-scoped metadata (trace IDs, user IDs), NEVER dependencies or business logic.

## context.WithCancelCause

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

`errors.Is` works on `context.Cause()`. Use distinct sentinel errors as causes for branching on cancellation reason. Available Go 1.20+.

## context.AfterFunc

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

`AfterFunc` runs its callback in its own goroutine when context is done. Call `stop()` to unregister it if no longer needed. Available Go 1.21+.

## errgroup for Concurrent Operations

First error returned; derived context cancelled when any goroutine returns an error.

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

`SetLimit` bounds concurrency without manual semaphores. Use `TryGo` for non-blocking submission; it returns `false` when the limit is reached.

## sourcegraph/conc Pool (Optional)

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

`conc` catches panics and re-raises them cleanly; it collects results automatically. Use it for less boilerplate than `errgroup` when the ergonomic tradeoff warrants adding this non-standard-library dependency to `go.mod`.

## Mutex for Shared State

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

Keep critical sections small. Prefer `sync/atomic` for simple integer counters; it is lock-free and faster.

## RWMutex for Read-Heavy Workloads

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

Use `RWMutex` when reads vastly outnumber writes. Multiple readers may hold `RLock` simultaneously. NEVER `Lock` while holding `RLock`: deadlock.

## sync.Once for One-Time Initialization

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

`sync.Once` is goroutine-safe; other goroutines block until its `Do` callback completes. `sync.OnceValue` and `sync.OnceValues` (Go 1.21+) return initialized values directly:

```go
var getConn = sync.OnceValue(func() *Connection {
    return connect()
})
```

## sync.Map for Concurrent Map Access

```go
var cache sync.Map

// Store
cache.Store("key", value)

// Load
if v, ok := cache.Load("key"); ok {
    // Use v.(YourType)
}

// LoadOrStore: atomic get-or-set
actual, loaded := cache.LoadOrStore("key", newValue)

// Delete
cache.Delete("key")

// Range: iterate safely
cache.Range(func(key, value any) bool {
    fmt.Println(key, value)
    return true // Continue iteration
})
```

`sync.Map` suits caches with many reads, few writes, and disjoint key sets. For general-purpose concurrent maps, use a regular `map` with `sync.RWMutex`.

## Rate Limiting

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

`Wait` blocks until allowed or context is done. `Allow` returns immediately. Use `Reserve` for custom scheduling when wait duration is needed.

## Deterministic Concurrent Testing

Use `testing/synctest` (Go 1.25+); see `cookbook/modern-1.24-1.26.md` for recipes.
