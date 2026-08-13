# Testing

Index: use heading search; load only the task-matching section. Scope: behavior-focused tests, fewer mocks, deterministic execution; recipes cover TDD shape, table-driven tests, `require`/`assert`, snapshots, property tests, testcontainers integration, and goroutine leaks.

## Tools

- Assertions: `stretchr/testify/require`; `assert` only inside table loops
- Mocks: `go.uber.org/mock` (gomock successor)
- Goroutine leaks: `go.uber.org/goleak`
- Snapshots/golden: `hexops/autogold/v2`
- Property tests: `pgregory.net/rapid`
- Outbound HTTP mocks: `h2non/gock`; inbound HTTP server: stdlib `net/http/httptest`
- Integration containers: `testcontainers/testcontainers-go`
- TUI: `charm.land/bubbletea/v2/teatest`
- Benchmarks: stdlib `testing.B` + `perf.dev/benchstat`

## Naming and assertion shape

Test names use Given/When/Then behavior:

```go
// ──── PATTERN ────
// Test_<Subject>_<Outcome>_when_<Condition>
//   OR
// Test_<Subject>_<Action>_<ExpectedOutcome>

func Test_Email_NewEmail_lowercases_input(t *testing.T)
func Test_Email_NewEmail_rejects_input_without_at_sign(t *testing.T)
func Test_UserService_Create_persists_user_when_inputs_valid(t *testing.T)
func Test_UserService_Create_returns_validation_error_when_email_invalid(t *testing.T)
```

Names must state the asserted behavior without reading the body; a name needing a comment is misnamed. `require.*` stops immediately: use it for preconditions and primary assertions. Use `assert.*` only in table loops when all cases should report.

```go
func Test_Email_NewEmail_rejects_input_without_at_sign(t *testing.T) {
    // Given
    raw := "not-an-email"

    // When
    _, err := domain.NewEmail(raw)

    // Then
    require.Error(t, err)
    require.ErrorIs(t, err, domain.ErrInvalidEmail)
}
```

## Table-driven tests

One scenario per row, not one assertion. Lowercase sentence subtest names remain filterable through `t.Run(tt.name, ...)`; the loop body keeps Given/When/Then shape. Go 1.22+ loop capture needs no `tt := tt`; `copyloopvar` enforces this.

```go
func Test_Email_NewEmail(t *testing.T) {
    tests := []struct {
        name    string
        input   string
        want    string
        wantErr error
    }{
        {"lowercases", "ALICE@example.com", "alice@example.com", nil},
        {"trims whitespace", "  bob@example.com  ", "bob@example.com", nil},
        {"rejects missing @", "no-at-sign", "", domain.ErrInvalidEmail},
        {"rejects empty", "", "", domain.ErrInvalidEmail},
        {"rejects too long", strings.Repeat("a", 256) + "@e.com", "", domain.ErrInvalidEmail},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            // When
            got, err := domain.NewEmail(tt.input)

            // Then
            if tt.wantErr != nil {
                require.ErrorIs(t, err, tt.wantErr)
                return
            }
            require.NoError(t, err)
            assert.Equal(t, tt.want, got.String())
        })
    }
}
```

## Collaborators: mock as little as possible

Priority: (1) real implementation for domain types, pure functions, value objects; (2) an in-memory interface fake with its own behavioral-parity suite; (3) `httptest.Server` for real-wire HTTP without internet; (4) `testcontainers` for stateful Postgres, Redis, S3-compatible, or Kafka; (5) gomock ONLY for clocks, randomness, or third-party SaaS without a sandbox. Mock the narrowest seam; never mock `UserRepo` when a fake suffices.

```go
// Real interface
type UserRepo interface {
    Save(ctx context.Context, u domain.User) error
    Get(ctx context.Context, id domain.UserID) (domain.User, error)
}

// In-memory fake — production-quality, tested separately
type FakeUserRepo struct {
    mu    sync.RWMutex
    users map[domain.UserID]domain.User
}

func NewFakeUserRepo() *FakeUserRepo {
    return &FakeUserRepo{users: map[domain.UserID]domain.User{}}
}

func (r *FakeUserRepo) Save(ctx context.Context, u domain.User) error {
    r.mu.Lock(); defer r.mu.Unlock()
    r.users[u.ID] = u
    return nil
}

func (r *FakeUserRepo) Get(ctx context.Context, id domain.UserID) (domain.User, error) {
    r.mu.RLock(); defer r.mu.RUnlock()
    u, ok := r.users[id]
    if !ok { return domain.User{}, domain.ErrUserNotFound }
    return u, nil
}
```

A fake's observable behavior matches the real implementation; tests against it survive production-internal changes, unlike gomock-stub tests. Gold standard: run the same suite with the fake and with testcontainers against the real implementation; investigate divergence.

```go
//go:generate mockgen -source=clock.go -destination=mocks/clock_mock.go -package=mocks

type Clock interface {
    Now() time.Time
}

// In a test:
ctrl := gomock.NewController(t)
clock := mocks.NewMockClock(ctrl)
clock.EXPECT().Now().Return(fixedTime).AnyTimes()
```

## E2E scenarios

Use one narrative and one `Test_E2E_*` per user-visible outcome. `//go:build e2e` separates slow E2E from unit tests; run `go test -tags=e2e ./...`. Use real testcontainers DB, real gin engine, and real HTTP—no mocks—to catch integration bugs. Every E2E needs a bounded `context.WithTimeout` so CI cannot hang.

```go
//go:build e2e

func Test_E2E_user_can_signup_then_login(t *testing.T) {
    // Given — full server in a goroutine
    ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
    defer cancel()

    pool := newTestDB(t)              // testcontainers Postgres
    server := startServer(t, pool)    // real gin engine on a random port
    defer server.Close()

    client := server.Client()

    // When — sign up
    resp, err := client.Post(server.URL+"/api/v1/users",
        "application/json",
        strings.NewReader(`{"email":"a@b.com","username":"alice","password":"PassWord!23"}`),
    )
    require.NoError(t, err)
    require.Equal(t, 201, resp.StatusCode)

    // When — log in
    resp, err = client.Post(server.URL+"/api/v1/auth/login",
        "application/json",
        strings.NewReader(`{"email":"a@b.com","password":"PassWord!23"}`),
    )
    require.NoError(t, err)
    require.Equal(t, 200, resp.StatusCode)

    var body struct{ Token string `json:"token"` }
    require.NoError(t, json.NewDecoder(resp.Body).Decode(&body))
    require.NotEmpty(t, body.Token)

    // Then — token works on protected endpoint
    req, _ := http.NewRequestWithContext(ctx, "GET", server.URL+"/api/v1/me", nil)
    req.Header.Set("Authorization", "Bearer "+body.Token)
    resp, err = client.Do(req)
    require.NoError(t, err)
    require.Equal(t, 200, resp.StatusCode)
}
```

## Goroutine leaks

At the top of every package spawning goroutines, use goleak; it catches a bug class the race detector cannot:

```go
package mypkg

import (
    "testing"
    "go.uber.org/goleak"
)

func TestMain(m *testing.M) {
    goleak.VerifyTestMain(m,
        goleak.IgnoreTopFunction("github.com/prometheus/client_golang/prometheus.(*Registry)..."),
    )
}
```

## Snapshots/golden: `autogold`

First run `go test -update ./...` writes `testdata/Test_RenderHelp.golden`; later runs compare and show diffs. Re-approve intentional changes with `-update`. Snapshot STRUCTURE, not BEHAVIOR: CLI `--help`, JSON response shape, generated SQL, and rendered-prompt structure (not exact wording). For actual return values, assert the actual structure with `require.Equal`.

```go
import "github.com/hexops/autogold/v2"

func Test_RenderHelp_matches_snapshot(t *testing.T) {
    // Given
    cmd := newRootCmd()

    // When
    out := captureOutput(t, func() { _ = cmd.Help() })

    // Then
    autogold.ExpectFile(t, out)
}
```

## Property tests: `rapid`

`rapid` shrinks failures to minimal counterexamples. Use it for parse/serialize/parse round-trips; algebraic properties (ordered sort, idempotent dedup, involutive JSON marshal/unmarshal); and random-input invariants (validator never panics, serializer never emits invalid UTF-8).

```go
import "pgregory.net/rapid"

func Test_Email_NewEmail_then_String_roundtrips(t *testing.T) {
    rapid.Check(t, func(t *rapid.T) {
        // Given — generate valid emails
        local  := rapid.StringMatching(`[a-z]{3,10}`).Draw(t, "local")
        domain := rapid.StringMatching(`[a-z]{3,10}\.com`).Draw(t, "domain")
        raw    := local + "@" + domain

        // When
        e, err := domain.NewEmail(raw)
        require.NoError(t, err)

        // Then — round-trip property
        e2, err := domain.NewEmail(e.String())
        require.NoError(t, err)
        require.Equal(t, e, e2)
    })
}
```

## HTTP: `httptest`

Server-side handlers use `httptest.NewRequest`/`NewRecorder`; client tests use `httptest.NewServer`, whose random-port real server exercises the upstream contract, not implementation. The fake handler is the contract.

```go
func Test_GetUser_returns_user_for_existing_id(t *testing.T) {
    // Given
    svc := newSvcWithFake(t)
    r := gin.New()
    h := &Handler{Users: svc}
    h.Mount(r)

    req := httptest.NewRequest("GET", "/api/v1/users/u-1", nil)
    rec := httptest.NewRecorder()

    // When
    r.ServeHTTP(rec, req)

    // Then
    require.Equal(t, 200, rec.Code)
    var body domain.User
    require.NoError(t, json.Unmarshal(rec.Body.Bytes(), &body))
    require.Equal(t, "u-1", string(body.ID))
}
```

```go
func Test_Client_retries_on_500(t *testing.T) {
    // Given — fake upstream
    var calls int
    srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        calls++
        if calls < 3 {
            w.WriteHeader(500)
            return
        }
        w.WriteHeader(200)
        _, _ = w.Write([]byte(`{"ok":true}`))
    }))
    defer srv.Close()

    client := myclient.New(srv.URL)

    // When
    err := client.DoSomething(context.Background())

    // Then
    require.NoError(t, err)
    require.Equal(t, 3, calls)
}
```

## Determinism

- NEVER `time.Sleep` in tests; delay means inject a Clock.
- Run `go test -shuffle=on` in every CI run and `go test -count=1` to defeat cache.
- Subscribe to events, never poll: prefer channels, callbacks, and `t.Cleanup`; await with bounds.
- Use `t.Parallel()` only for tests sharing no state; large suites may speed up 4–8x.
- A 1-in-10 failure is a bug, not flake. Race detector + `-shuffle=on` + ordering hygiene catch >95% of “flake”.

## Benchmarks

Go 1.24+ `b.Loop()` replaces the indexed `b.N` loop. Always use `-count=10` for stable means; `-benchmem` reports allocations; one-run 5%-slower results are noise; 10 runs plus benchstat identifies real change.

```go
func Benchmark_NewEmail(b *testing.B) {
    for b.Loop() {  // Go 1.24+ idiom, replaces `for i := 0; i < b.N; i++`
        _, _ = domain.NewEmail("alice@example.com")
    }
}
```

```bash
go test -bench=. -count=10 -benchmem ./... | tee bench.txt
benchstat bench.txt   # statistical comparison
```

Before/after:

```bash
git stash
go test -bench=. -count=10 ./... > before.txt
git stash pop
go test -bench=. -count=10 ./... > after.txt
benchstat before.txt after.txt
```

## Coverage

```bash
go test -race -shuffle=on -coverprofile=cover.out ./...
go tool cover -html=cover.out -o cover.html
```

Aim for 80%+ on `internal/domain` and `internal/service`. Boundary code (handlers, store mappers) is covered by integration tests, so line coverage understates verification. Do not chase 100%; the last 5% usually needs fault injection. `golangci-lint` does not enforce a minimum. Coverage gates cause goal displacement; treat coverage as feedback, not a requirement.

## TUI: `teatest`

```go
import teatest "charm.land/bubbletea/v2/teatest"

func Test_Counter_increments_on_space(t *testing.T) {
    // Given
    tm := teatest.NewTestModel(t, initial(), teatest.WithInitialTermSize(80, 24))

    // When
    tm.Send(tea.KeyPressMsg{Code: ' '})

    // Then
    final := tm.FinalModel(t).(model)
    require.Equal(t, 1, final.count)
}
```

For full-view regression, snapshot rendered output with `autogold`.

## Rejected antipatterns

- Manual `if got != want { t.Errorf(...) }` → testify.
- `time.Sleep(100 * time.Millisecond)` after async work → completion signal plus bounded await.
- `t.Skip(...)` to silence failure → fix or open an issue; never silently skip.
- One mega-test asserting 12 things → split by `Then`; first failure must not hide 11.
- Snapshot-everything → snapshots for structure, assertions for values.
- Mock every collaborator → real or fake; never mock everything.
- Calling private functions from same-package `_test.go` only → test through public surface.

## Sources

- testify: https://github.com/stretchr/testify
- goleak: https://github.com/uber-go/goleak
- autogold: https://github.com/hexops/autogold
- rapid: https://pkg.go.dev/pgregory.net/rapid
- testcontainers-go: https://golang.testcontainers.org
- benchstat: https://pkg.go.dev/golang.org/x/perf/cmd/benchstat
- Go test naming conventions (Dave Cheney): https://dave.cheney.net/practical-go/presentations/qcon-china.html
