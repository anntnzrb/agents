# Concurrency

## Index

Read the section matching the task; search headings before loading unrelated detail.

Scope: goroutines, context, errgroup, channels, locks, leak prevention.

## Non-negotiables

1. `ctx context.Context` first parameter of every public function doing I/O or cancellable.
2. Every `go` has a shutdown path.
3. Run `-race` on every test; `Taskfile.yml` and CI enforce it.
4. Every package spawning goroutines uses `goleak` in `TestMain`; it catches leaks race detection cannot.

## `context.Context`

```go
// GOOD — ctx as first param, propagated through
func (s *UserService) Create(ctx context.Context, email Email) (User, error) {
    user, err := s.store.Insert(ctx, email)
    if err != nil {
        return User{}, fmt.Errorf("insert: %w", err)
    }
    if err := s.notifier.Welcome(ctx, user); err != nil {
        return User{}, fmt.Errorf("notify: %w", err)
    }
    return user, nil
}

// BAD — creates a fresh ctx, breaks request cancellation
func (s *UserService) Create(email Email) (User, error) {
    ctx := context.Background()  // ← contextcheck linter rejects this
    // ...
}
```

`contextcheck` (enabled in `golangci-strict.md`) rejects `context.Background()` when a `ctx context.Context` is available. Propagate the caller's context.

### `context.Value`

```go
// Typed key — never use a bare string
type ctxKey struct{ name string }
var requestIDKey = ctxKey{"request_id"}

func WithRequestID(ctx context.Context, id string) context.Context {
    return context.WithValue(ctx, requestIDKey, id)
}

func RequestID(ctx context.Context) string {
    v, _ := ctx.Value(requestIDKey).(string)
    return v
}
```

- Keys: unexported struct types, never strings; prevents cross-package collisions.
- `context.Value`: request-scoped metadata only — request ID, auth subject, trace span; NEVER application-scoped dependencies.
- Put loggers, DB pools, and config in the service struct, not `context.Value`.

### `WithTimeout` / `WithCancel`

Always `defer cancel()`; `fatcontext` catches misses and `lostcancel` vet catches the resulting context-goroutine leak until parent expiry.

```go
ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
defer cancel()  // ← MUST be deferred. fatcontext linter catches misses.

if err := slow(ctx); err != nil { ... }
```

## `errgroup`

Use `golang.org/x/sync/errgroup` instead of raw `go` for related goroutines.

```go
import "golang.org/x/sync/errgroup"

func FetchAll(ctx context.Context, urls []string) ([][]byte, error) {
    g, ctx := errgroup.WithContext(ctx)
    g.SetLimit(8)  // concurrency cap — leave unbounded = production outage

    results := make([][]byte, len(urls))
    for i, u := range urls {
        g.Go(func() error {
            body, err := fetch(ctx, u)
            if err != nil {
                return fmt.Errorf("fetch %s: %w", u, err)
            }
            results[i] = body
            return nil
        })
    }
    if err := g.Wait(); err != nil {
        return nil, err
    }
    return results, nil
}
```

- `WithContext(parent)` returns a child cancelled on the first non-nil error; in-flight goroutines must observe `ctx.Done()` and exit.
- Always `SetLimit(n)`; it blocks `g.Go(...)` at `n` in-flight goroutines. Unbounded fan-out can kill services.
- `g.Wait()` returns the first non-nil error and drops others. Accumulate manually when all errors are needed:

  ```go
  var mu sync.Mutex
  var errs []error
  // inside g.Go:
  //   mu.Lock(); errs = append(errs, err); mu.Unlock()
  // after Wait, errors.Join(errs...)
  ```

## Goroutine leaks — `goleak`

At the top of `*_test.go`:

```go
package store_test

import (
    "testing"
    "go.uber.org/goleak"
)

func TestMain(m *testing.M) {
    goleak.VerifyTestMain(m)
}
```

`VerifyTestMain` checks after every package test and fails with the leaking goroutine. It catches unjoined setup goroutines, DB pools, workers, and ticker loops; race detection does NOT catch leaks.

For known long-lived goroutines such as singleton workers or metrics exporters:

```go
goleak.VerifyTestMain(m,
    goleak.IgnoreTopFunction("github.com/prometheus/client_golang/prometheus.(*Registry).Push"),
)
```

## Channels

### Direction

```go
// GOOD — direction in signatures
func produce(out chan<- Item)
func consume(in <-chan Item)
func pipeline(in <-chan Item, out chan<- Item)
```

Use directional signatures; consumers cannot close the producer's channel.

### Closing

- Sender closes, always; never receiver or multiple senders.
- Multiple senders require `sync.WaitGroup` plus one closer.
- Closing a closed or `nil` channel panics; sending on a closed channel panics; receiving from a closed channel returns the zero value with `ok = false`.

Canonical fan-in:

```go
// Canonical fan-in: multiple producers, one closer
func fanIn(ctx context.Context, sources ...<-chan Item) <-chan Item {
    out := make(chan Item)
    var wg sync.WaitGroup
    wg.Add(len(sources))
    for _, src := range sources {
        go func() {
            defer wg.Done()
            for item := range src {
                select {
                case out <- item:
                case <-ctx.Done():
                    return
                }
            }
        }()
    }
    go func() { wg.Wait(); close(out) }()
    return out
}
```

### Selecting

```go
select {
case msg := <-incoming:
    handle(msg)
case <-ctx.Done():
    return ctx.Err()
case <-time.After(5 * time.Second):
    return ErrTimeout
}
```

- `time.After` allocates a timer each call; okay for occasional selects, NOT hot loops. Use `time.NewTimer` + `timer.Reset` for repeat selects.
- `default:` makes `select` non-blocking; use deliberately.

### Buffering

- `make(chan T)`: unbuffered synchronous handoff; sender blocks until receiver; use for coordination.
- `make(chan T, n)`: buffered asynchronous handoff up to `n`; use to decouple producer and consumer rates.

Buffered size 1 gives a non-blocking signal:

```go
ready := make(chan struct{}, 1)
// Producer
select {
case ready <- struct{}{}:  // signal once, non-blocking
default:                    // already signaled, skip
}
// Consumer
<-ready
```

## Locks

Preferred to rare:

```
Highest level (preferred)
  channels (message passing — "share memory by communicating")
  errgroup / wait group

  sync.RWMutex (many readers, occasional writer)
  sync.Mutex   (mutual exclusion)

  atomic.Int64 / atomic.Pointer  (single-word lock-free)

Lowest level (rare)
  unsafe.Pointer + barriers  (custom lock-free; needs -race AND review)
```

### `sync.Mutex`

Embed; do not expose:

```go
type Cache struct {
    mu    sync.RWMutex
    items map[string]Entry
}

func (c *Cache) Get(key string) (Entry, bool) {
    c.mu.RLock()
    defer c.mu.RUnlock()
    e, ok := c.items[key]
    return e, ok
}

func (c *Cache) Set(key string, e Entry) {
    c.mu.Lock()
    defer c.mu.Unlock()
    c.items[key] = e
}
```

- `sync.Mutex` is NOT copyable; `copylocks` vet catches `var c2 = c1` when `c1` contains one.
- `defer mu.Unlock()` immediately after `Lock()`; forgetting causes deadlocks.
- Never call user code while locked. Snapshot under lock, unlock, then invoke callbacks/listeners.

### `sync.OnceValue` / `sync.OnceFunc` (Go 1.21+)

Typed lazy initialization replaces `sync.Once` plus a global variable:

```go
var loadConfig = sync.OnceValue(func() Config {
    var cfg Config
    if err := env.Parse(&cfg); err != nil { panic(err) }
    return cfg
})

func handler() { cfg := loadConfig(); ... }
```

### Atomics

Use typed `atomic.*` APIs (Go 1.19+), never old function-style APIs:

```go
// Go 1.19+ — use the typed atomic.* family
var counter atomic.Int64
counter.Add(1)
n := counter.Load()

// NEVER — the old function-style is type-unsafe
atomic.AddInt64(&counter, 1)  // ← rejected
```

## Time

Inject a clock:

```go
type Clock interface {
    Now() time.Time
}

type realClock struct{}
func (realClock) Now() time.Time { return time.Now() }

type Service struct {
    clock Clock
}

// Tests
import "github.com/benbjohnson/clock"
fake := clock.NewMock()
fake.Set(time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC))
svc := &Service{clock: fake}
```

NEVER call `time.Now()` in domain/service code; inject it to avoid hidden dependencies, flaky tests, time-of-day-dependent retries, and untestable expirations.

`time.Sleep` in production is a code smell. Use `time.NewTicker` for periodic work with a `<-ctx.Done()` exit; `time.NewTimer` for one-shot delays; `time.After` ONLY in select statements and ONLY on non-hot paths.

## Race detector

```bash
go test -race -shuffle=on -count=1 ./...
```

- `-race` instruments accesses and catches runtime data races; ~10x slowdown, acceptable in tests, not production.
- `-shuffle=on` randomizes test order and catches ordering dependencies.
- `-count=1` defeats test caching; without it, passing may mean the test ran 3 weeks ago.
- A test failing ONLY under `-race` has a real bug; fix the race, do not disable the test.

## Common antipatterns

|Bad|Why|Good|
|---|---|---|
|`go func() { ... }()` with no `ctx` plumbing|Leaks on shutdown|`errgroup.WithContext` or pass ctx|
|Bare `time.Sleep(d)` in production|Untestable, blocks|`time.NewTimer` + select with `ctx.Done()`|
|Channel of `interface{}`|Loses type|Typed channel; use sealed interface if variants needed|
|`sync.Mutex` in a struct passed by value|Locked copies, undefined behavior|Embed in pointer-receiver type; copylocks catches it|
|Locking around an entire request handler|Serializes the whole API|Lock only the smallest critical section|
|`for { select { ... } }` without `<-ctx.Done()`|Cannot stop|Add ctx case in every long-lived select|
|`sync.WaitGroup.Add(1)` inside the goroutine|Race: Wait can return before Add|Add **before** `go`|

## Sources

- Go memory model: https://go.dev/ref/mem
- `errgroup` package: https://pkg.go.dev/golang.org/x/sync/errgroup
- `goleak`: https://github.com/uber-go/goleak
- "Go concurrency patterns" (Pike): https://go.dev/blog/pipelines
- Sync.OnceValue blog: https://go.dev/blog/synctest (1.24+ note: `testing/synctest` for time-controlled tests is now experimental)
