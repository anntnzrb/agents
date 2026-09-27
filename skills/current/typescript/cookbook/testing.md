# Testing Cookbook

Use compile-time and runtime tests together. TypeScript proves program shape, not external data validity.

For a new application covered by `references/bun-application.md`, use `bun:test`, Bun commands, and the application's chosen schema boundary. The Vitest, `tsd`, Zod, npm, and Node examples below apply only when an existing repository already owns those tools.

---

## Compiler Gate

**Problem**: You need a cheap correctness floor.

**Solution**:

```bash
npx tsc --noEmit
```

**Tip**: Run repo `typecheck` script first if it exists.

---

## Vitest Type Assertions

**Problem**: You need to lock a public or generic API shape.

**Solution**:

```ts
import { expectTypeOf, test } from "vitest";

type AvatarProps = {
  size: "sm" | "md" | "lg";
};

test("Avatar props stay narrow", () => {
  expectTypeOf<AvatarProps["size"]>().toEqualTypeOf<"sm" | "md" | "lg">();
});
```

**Tip**: Best for helpers, hooks, library APIs, and inference-heavy utilities.

---

## Negative Type Tests with `@ts-expect-error`

**Problem**: You need to assert that bad usage stays rejected.

**Solution**:

```ts
declare function loadUser(id: string): void;

loadUser("abc");

// @ts-expect-error number should stay rejected
loadUser(123);
```

**Tip**: `@ts-expect-error` fails if the error disappears. That makes it a strong regression guard.

---

## Public API Tests with `tsd`

**Problem**: You publish a library and want declaration-level tests.

**Solution**:

```ts
import { expectType } from "tsd";
import { slugify } from ".";

expectType<string>(slugify("Hello world"));
```

Run:

```bash
npx tsd
```

**Tip**: Use `tsd` for package APIs. Use Vitest `expectTypeOf` for app code and local helpers.

---

## Boundary Validation Tests

**Problem**: JSON or request payloads still need runtime validation.

**Solution**:

```ts
import { z } from "zod";
import { expect, test } from "vitest";

const User = z.object({
  id: z.string(),
  email: z.string().email(),
});

test("rejects malformed payload", () => {
  const result = User.safeParse({ id: 1, email: "nope" });
  expect(result.success).toBe(false);
});
```

**Tip**: TypeScript types do not validate runtime input. Parse at the edge, then trust the parsed value.

---

## Resolution and Build Smoke Tests

**Problem**: Types pass, but emitted runtime or package exports still break.

**Solution**:

- run library build
- import built output from a smoke test
- check `exports`, `types`, and emitted file extensions together

Minimal smoke:

```bash
npx tsc -p tsconfig.build.json
node -e "import('./dist/index.js').then(() => console.log('ok'))"
```

**Tip**: Essential for `NodeNext`, dual packages, and published libraries.

---

## Subprocess Test Isolation and Cache Forwarding

**Problem**: Test suites isolating `HOME` or temporary directories run slowly because spawned tools re-download dependencies over the network on every test.

**Solution**:

When tests isolate filesystem writes by redirecting `HOME`, content-addressed package and toolchain caches are masked. Pass cache-bearing variables back into child process environments:

```ts
import { homedir } from "node:os";
import { join } from "node:path";

const realHome = homedir();

export const sharedToolCacheEnv = {
  BUN_INSTALL_CACHE_DIR:
    process.env["BUN_INSTALL_CACHE_DIR"] ?? join(realHome, ".bun", "install", "cache"),
  UV_CACHE_DIR:
    process.env["UV_CACHE_DIR"] ?? join(realHome, ".cache", "uv"),
  UV_PYTHON_INSTALL_DIR:
    process.env["UV_PYTHON_INSTALL_DIR"] ?? join(realHome, ".local", "share", "uv", "python"),
};
```

When tests share identical fixtures, build once per run and symlink large read-only directories (`node_modules`) instead of copying them.

**Tip**: If `real >> user` time in `time <runner> test`, the suite is waiting on blocking I/O or network fetches rather than executing test logic.

---

## Bun Test Teardown and Environment Isolation

**Problem**: Cleanup hooks fail to execute under `bun test`, or temporary environment modifications leak into concurrent tests.

**Solution**:

- `process.on("exit")` does not fire under `bun test`. Register teardown using `afterAll` or `afterEach` at module evaluation scope.
- `Bun.env` reads live `process.env` and shares state across tests. When overriding `PATH` to stub a binary in a test, capture the pristine environment at module load and restore it in teardown:

```ts
import { afterAll, it } from "bun:test";

const PRISTINE_PATH = process.env["PATH"] ?? "";

afterAll(() => {
  process.env["PATH"] = PRISTINE_PATH;
});
```

**Tip**: To isolate a suspected slow binary without code changes, prepend a failing stub script via a temporary directory in `PATH`.
