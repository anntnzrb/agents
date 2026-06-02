# Types Cookbook

High-signal patterns for real TypeScript work. Use these when they simplify code, not as type-gymnastics theater.

---

## Branded Domain Types

**Problem**: Primitive IDs or units get mixed up.

**Solution**:

```ts
type Brand<T, Name extends string> = T & { readonly __brand: Name };

type UserId = Brand<string, "UserId">;
type OrderId = Brand<string, "OrderId">;

function loadOrder(userId: UserId, orderId: OrderId) {
  return { userId, orderId };
}
```

**Tip**: Use brands at domain boundaries, not everywhere.

---

## `satisfies` Without Widening

**Problem**: You want shape validation without losing literal types.

**Solution**:

```ts
const routes = {
  home: "/",
  settings: "/settings",
  users: "/users",
} as const satisfies Record<string, `/${string}`>;

type RouteName = keyof typeof routes;
type RoutePath = (typeof routes)[RouteName];
```

**Tip**: Prefer `satisfies` over blunt annotations when literals matter.

---

## Discriminated Union Results

**Problem**: Exceptions or `null` make control flow muddy.

**Solution**:

```ts
type Result<T, E> = { ok: true; value: T } | { ok: false; error: E };

function parsePort(raw: string): Result<number, "invalid-port"> {
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    return { ok: false, error: "invalid-port" };
  }
  return { ok: true, value: port };
}
```

**Tip**: Discriminated unions beat `T | undefined` once callers need error detail.

---

## Template Literal Event Names

**Problem**: Stringly typed event names drift from object shape.

**Solution**:

```ts
type Watched<T> = {
  on<K extends string & keyof T>(
    event: `${K}Changed`,
    cb: (value: T[K]) => void,
  ): void;
};

type Settings = Watched<{
  theme: "light" | "dark";
  retries: number;
}>;
```

**Tip**: Great for libraries. Overkill for CRUD app internals.

---

## Safer Object Contracts

**Problem**: You need a stable object shape with extension points.

**Solution**:

```ts
interface User {
  id: string;
  email: string;
}

interface Admin extends User {
  role: "admin";
}
```

**Tip**: Prefer `interface` for extendable object contracts. Prefer `type` for unions and transforms.

---

## Deep Utility Types: Use Sparingly

**Problem**: You need a recursive helper.

**Solution**:

```ts
type DeepReadonly<T> = T extends (...args: never[]) => unknown
  ? T
  : T extends object
    ? { readonly [K in keyof T]: DeepReadonly<T[K]> }
    : T;
```

**Tip**: Recursive helpers can tank compiler performance. Reach for them only when a shallow helper is not enough.

---

## Narrowing Unknown at Boundaries

**Problem**: External data arrives as `unknown`.

**Solution**:

```ts
type User = { id: string; email: string };

function isUser(value: unknown): value is User {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    "email" in value
  );
}
```

**Tip**: Validate at the edge. Keep internals strongly typed after that point.
