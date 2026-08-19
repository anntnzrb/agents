# Testing Cookbook

Recipes for writing effective tests in Go 1.26 using the standard library and common patterns.

---

## Contents

- [Table-Driven Tests](#table-driven-tests)
- [Table-Driven Tests with Errors](#table-driven-tests-with-errors)
- [Stdlib Assertions (Preferred)](#stdlib-assertions-preferred)
- [Testify Assertions (Inherited Projects)](#testify-assertions-inherited-projects)
- [Testify Require for Setup](#testify-require-for-setup)
- [Mocking with Testify](#mocking-with-testify)
- [Test Suites](#test-suites)
- [Parallel Tests](#parallel-tests)
- [Test Execution Flags](#test-execution-flags)
- [t.TempDir and t.Cleanup](#ttempdir-and-tcleanup)
- [T.ArtifactDir and -artifacts](#tartifactdir-and-artifacts)
- [Benchmarks with testing.B.Loop](#benchmarks-with-testingbloop)
- [Fuzz Testing](#fuzz-testing)
- [Test Helpers](#test-helpers)
- [HTTP Handler Testing](#http-handler-testing)

---
## Table-Driven Tests

**Problem**: How to test multiple inputs efficiently without duplicating test code?

**Solution**:

```go
func TestAdd(t *testing.T) {
    tests := []struct {
        name string
        a, b int
        want int
    }{
        {"positives", 2, 3, 5},
        {"negatives", -1, -1, -2},
        {"zero", 0, 5, 5},
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got := Add(tt.a, tt.b)
            if got != tt.want {
                t.Errorf("Add(%d, %d) = %d; want %d", tt.a, tt.b, got, tt.want)
            }
        })
    }
}
```

**Tip**: Descriptive test case names appear in test output on failure. Use subtests (`t.Run`) so you can run a single case with `go test -run TestAdd/positives`.

---

## Table-Driven Tests with Errors

**Problem**: How to test functions that return errors alongside regular values?

**Solution**:

```go
func TestParse(t *testing.T) {
    tests := []struct {
        name    string
        input   string
        want    int
        wantErr bool
    }{
        {"valid", "42", 42, false},
        {"invalid", "abc", 0, true},
        {"empty", "", 0, true},
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got, err := Parse(tt.input)
            if (err != nil) != tt.wantErr {
                t.Errorf("Parse() error = %v, wantErr %v", err, tt.wantErr)
                return
            }
            if got != tt.want {
                t.Errorf("Parse() = %v, want %v", got, tt.want)
            }
        })
    }
}
```

**Tip**: Return early after the error check to avoid nil pointer issues in the value assertion.

---

## Stdlib Assertions (Preferred)

**Problem**: How to write clean, dependency-free assertions?

**Solution**:

```go
func TestUser(t *testing.T) {
    user, err := FetchUser("alice")

    if err != nil {
        t.Fatalf("FetchUser() unexpected error: %v", err)
    }
    if user.Name != "Alice" {
        t.Errorf("Name = %q; want %q", user.Name, "Alice")
    }
    if !user.Active {
        t.Error("expected user to be active")
    }
}

// Helper pattern for repeated assertions
func equal[T comparable](t *testing.T, got, want T) {
    t.Helper()
    if got != want {
        t.Errorf("got %v; want %v", got, want)
    }
}
```

**Tip**: `if got != want` is the idiomatic Go pattern. It requires no third-party dependencies, composes naturally, and every Go developer can read it. Use `t.Fatal` to stop on unrecoverable failures, `t.Error` to report and continue.

---

## Testify Assertions (Inherited Projects)

**Problem**: How to write cleaner assertion messages when the project already depends on testify?

**Solution**:

```go
import "github.com/stretchr/testify/assert"

func TestExample(t *testing.T) {
    // Soft assertions (continues on failure)
    assert.Equal(t, expected, actual)
    assert.NotEqual(t, a, b)
    assert.Nil(t, err)
    assert.NotNil(t, result)
    assert.True(t, condition)
    assert.Empty(t, slice)
    assert.Len(t, slice, 3)
    assert.Contains(t, "hello world", "world")
    assert.ElementsMatch(t, []int{1, 2, 3}, []int{3, 2, 1})

    // Error assertions
    assert.NoError(t, err)
    assert.Error(t, err)
    assert.ErrorIs(t, err, ErrNotFound)
    assert.ErrorContains(t, err, "not found")
}
```

**Tip**: Prefer stdlib `if got != want` for new projects. Use testify only when the project already uses it; don't add testify to a project that doesn't already depend on it.

---

## Testify Require for Setup

**Problem**: How to fail fast when setup steps fail, avoiding cascading errors?

**Solution**:

```go
import (
    "github.com/stretchr/testify/assert"
    "github.com/stretchr/testify/require"
)
func TestWithSetup(t *testing.T) {
    conn, err := Connect()
    require.NoError(t, err)
    require.NotNil(t, conn)

    result := conn.Query()
    assert.Equal(t, expected, result)
}
```

**Tip**: Pattern: `require` for preconditions, `assert` for test assertions. `require` calls `t.Fatal`; the test stops immediately.

---

## Mocking with Testify

**Problem**: How to test code that depends on external services or databases?

**Solution**:

```go
import "github.com/stretchr/testify/mock"

type MockDB struct {
    mock.Mock
}

func (m *MockDB) Get(id string) (*User, error) {
    args := m.Called(id)
    if args.Get(0) == nil {
        return nil, args.Error(1)
    }
    return args.Get(0).(*User), args.Error(1)
}

func TestService(t *testing.T) {
    mockDB := new(MockDB)

    mockDB.On("Get", "123").Return(&User{Name: "John"}, nil)
    mockDB.On("Get", "999").Return(nil, ErrNotFound)

    svc := NewService(mockDB)
    user, err := svc.GetUser("123")

    assert.NoError(t, err)
    assert.Equal(t, "John", user.Name)
    mockDB.AssertExpectations(t)
}
```

**Tip**: Call `AssertExpectations(t)` at the end to verify all expected calls were made. Define interfaces, mock the interface; never mock concrete types.

---

## Test Suites

**Problem**: How to share setup/teardown logic across related tests?

**Solution**:

```go
import (
    "testing"
    "github.com/stretchr/testify/suite"
)

type ExampleSuite struct {
    suite.Suite
    db *sql.DB
}

func (s *ExampleSuite) SetupTest() {
    s.db = setupTestDB()
}

func (s *ExampleSuite) TearDownTest() {
    s.db.Close()
}

func (s *ExampleSuite) TestInsert() {
    err := Insert(s.db, "data")
    s.NoError(err)
}

func (s *ExampleSuite) TestQuery() {
    result := Query(s.db)
    s.NotEmpty(result)
}

func TestExampleSuite(t *testing.T) {
    suite.Run(t, new(ExampleSuite))
}
```

**Tip**: `SetupSuite`/`TearDownSuite` run once per suite; `SetupTest`/`TearDownTest` run per test. Each test method must start with `Test`.

---

## Parallel Tests

**Problem**: How to speed up test execution by running independent tests concurrently?

**Solution**:

```go
func TestParallel(t *testing.T) {
    tests := []struct {
        name  string
        input int
    }{
        {"case1", 1},
        {"case2", 2},
        {"case3", 3},
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            t.Parallel()
            result := Process(tt.input)
            if result == 0 {
                t.Error("expected non-zero result")
            }
        })
    }
}
```

**Tip**: Call `t.Parallel()` at the start of each subtest. Go 1.22+ loop variable semantics mean no `tt := tt` workaround is needed. Use `go test -shuffle=on` to randomize test order and catch unintended dependencies between tests.

---

## Test Execution Flags

**Problem**: How to control test execution for faster feedback or debugging?

**Solution**:

```bash
# Fail fast: stop on first test failure (Go 1.25+)
go test -failfast

# Shuffle test order to detect inter-test dependencies
go test -shuffle=on

# Run only matching tests
go test -run TestUser/valid

# Run in short mode (skip long-running tests)
go test -short

# Set a timeout for the entire test run
go test -timeout 30s
```

**Tip**: Use `-failfast` in CI to surface the first failure quickly. Use `-shuffle=on` in CI periodically to catch flaky tests. Guard long-running tests behind `if testing.Short() { t.Skip("skipping in short mode") }`.

---

## t.TempDir and t.Cleanup

**Problem**: How to manage temporary files and cleanup without leaking resources?

**Solution**:

```go
func TestProcessFile(t *testing.T) {
    dir := t.TempDir() // Auto-cleaned when the test finishes
    path := filepath.Join(dir, "input.txt")

    if err := os.WriteFile(path, []byte("hello"), 0644); err != nil {
        t.Fatal(err)
    }

    // For non-file resources, register cleanup manually
    conn, err := Connect()
    if err != nil {
        t.Fatal(err)
    }
    t.Cleanup(func() {
        conn.Close()
    })

    result := ProcessFile(path)
    if result != "HELLO" {
        t.Errorf("got %q; want %q", result, "HELLO")
    }
}
```

**Tip**: `t.TempDir()` creates a directory that is automatically removed when the test completes. `t.Cleanup` registrations run in LIFO order; the last registered cleanup runs first. Prefer `t.TempDir` over `os.MkdirTemp` + manual cleanup.

---

## T.ArtifactDir and -artifacts

**Problem**: How to persist test outputs (coverage profiles, logs, screenshots) for CI inspection?

**Solution**:

```bash
# Run tests with artifact collection
go test -artifacts=./artifacts ./...
```

```go
func TestWithArtifacts(t *testing.T) {
    dir := t.ArtifactDir() // always returns a directory in Go 1.26

    data := debugSnapshot()
    os.WriteFile(filepath.Join(dir, "snapshot.json"), data, 0644)

    // ... test assertions
}
```

**Tip**: `t.ArtifactDir()` always returns a per-test directory; no empty-string guard needed. When `-artifacts` is set with `go test`, the directory is preserved after the test; otherwise it is cleaned up automatically. Available since Go 1.26.

---

## Benchmarks with testing.B.Loop

**Problem**: How to measure function performance without the boilerplate of `for i := 0; i < b.N; i++`?

**Solution**:

```go
func BenchmarkProcess(b *testing.B) {
    data := setupData()

    for b.Loop() {
        Process(data)
    }
}

// With memory allocation reporting
func BenchmarkAlloc(b *testing.B) {
    b.ReportAllocs()
    for b.Loop() {
        _ = make([]byte, 1024)
    }
}

// Sub-benchmarks
func BenchmarkSizes(b *testing.B) {
    for _, size := range []int{10, 100, 1000} {
        b.Run(fmt.Sprintf("size-%d", size), func(b *testing.B) {
            data := make([]int, size)
            for b.Loop() {
                Process(data)
            }
        })
    }
}
```

**Tip**: `b.Loop()` (Go 1.24) replaces `for i := 0; i < b.N; i++`. The compiler unrolls the loop body for amortized zero-overhead per iteration. Run with `go test -bench=. -benchmem` to see memory allocations per operation. Call `b.ResetTimer()` after setup if you want to exclude setup time from measurements.

---

## Fuzz Testing

**Problem**: How to find edge cases and bugs by testing with random inputs?

**Solution**:

```go
func FuzzParse(f *testing.F) {
    // Seed corpus with known inputs
    f.Add("hello")
    f.Add("123")
    f.Add("")

    f.Fuzz(func(t *testing.T, input string) {
        result, err := Parse(input)
        if err != nil {
            return // Expected for some inputs
        }
        // Check invariants
        if result < 0 {
            t.Errorf("negative result for input %q", input)
        }
    })
}
```

**Tip**: Run with `go test -fuzz=FuzzParse -fuzztime=30s`. Failing inputs are saved to `testdata/fuzz/`. The fuzzer supports `string`, `[]byte`, `int`, `float64`, and `bool` as fuzzed types.

---

## Test Helpers

**Problem**: How to create reusable test utilities with proper error reporting?

**Solution**:

```go
func assertJSONEqual[T any](t *testing.T, got, want T) {
    t.Helper() // Reports the caller's line on failure

    gotJSON, err := json.Marshal(got)
    if err != nil {
        t.Fatalf("json.Marshal(got): %v", err)
    }
    wantJSON, err := json.Marshal(want)
    if err != nil {
        t.Fatalf("json.Marshal(want): %v", err)
    }
    if !bytes.Equal(gotJSON, wantJSON) {
        t.Errorf("JSON mismatch:\ngot:  %s\nwant: %s", gotJSON, wantJSON)
    }
}
```

**Tip**: Always call `t.Helper()` first in helper functions so `t.Errorf` reports the test's line, not the helper's. Use generics to avoid `any` casts when the types are known.

---

## HTTP Handler Testing

**Problem**: How to test HTTP handlers without starting a real server?

**Solution**:

```go
import (
    "net/http"
    "net/http/httptest"
)

func TestHandler(t *testing.T) {
    req := httptest.NewRequest("GET", "/users/123", nil)
    rec := httptest.NewRecorder()

    handler := NewUserHandler()
    handler.ServeHTTP(rec, req)

    if rec.Code != http.StatusOK {
        t.Errorf("status = %d; want %d", rec.Code, http.StatusOK)
    }
    if !strings.Contains(rec.Body.String(), "user") {
        t.Errorf("body does not contain 'user'")
    }
}
```

**Tip**: Use `httptest.NewServer` when testing actual HTTP client code that needs a real URL:

```go
server := httptest.NewServer(handler)
defer server.Close()
client := NewClient(server.URL) // server.URL is the test server's address
```
