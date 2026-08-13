# Types Cookbook

High-signal patterns for real TypeScript work. Use these when they simplify code, not as type-gymnastics theater.

---

## Branded Domain Types

**Problem**: Primitive IDs or units get mixed up.

**Solution**:

```ts
declare const brand: unique symbol;

type Brand<T, Name extends string> = T & {
  readonly [brand]: Name;
};

type UserId = Brand<string, "UserId">;
type OrderId = Brand<string, "OrderId">;

function loadOrder(userId: UserId, orderId: OrderId) {
  return { userId, orderId };
}
```

**Tip**: Use brands at domain boundaries, not everywhere.

---

## Readonly Contracts Where Mutation Is Not Part of the API

**Problem**: Consumers should observe a value, not mutate the owner's state.

**Solution**:

```ts
type User = {
  readonly id: UserId;
  readonly email: string;
};

function listUsers(): readonly User[] {
  return [];
}
```

**Tip**: Use `readonly` for new public or boundary contracts when it reflects ownership. Do not tighten existing mutable APIs without a migration plan.

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

## Constructive Modeling: Shape Out the Illegal Value

**Problem**: A validity constraint lives in callers' heads, enforced by checks scattered at use sites.

**Solution**: Choose the shape that cannot build the illegal value:

```ts
// Non-empty list: a head plus a rest, not a list plus a length check.
type NonEmpty<T> = [T, ...T[]];

// Even-length pairs: pairs of pairs, not a length check.
type Pairs<T> = [T, T][];

// A valid range: start plus duration, not two timestamps you must keep ordered.
interface TimeRange {
  start: Date;
  duration: number;
}
```

**Tip**: Strengthen only where partiality actually appears. If every operation on the plain shape is total, keep the plain shape. A `!`, cast, or "should never happen" throw marks the place a type is too weak; push that check up into the type, then stop.

---

## Schema-Derived Types

**Problem**: Hand-rolled types duplicate a shape an authoritative schema already owns.

**Solution**: Derive instead of redeclaring:

```ts
type ApiUser = typeof api.types.user; // from a server's schema module or a generated type
type Update = Omit<ApiUser, "id" | "createdAt">;
type HandlerArgs = Parameters<typeof handler>[0];
type Unwrapped<T> = Awaited<T>;
```

**Tip**: Reach for `Pick`/`Omit`/`Parameters`/`ReturnType`/`Awaited`/`typeof` before declaring a new interface. Manual duplication drifts.

---

## Exhaustive Tagged-State Handling

**Problem**: A new state can be added without updating every consumer.

**Solution**:

```ts
function assertNever(value: never): never {
  throw new Error(`Unexpected state: ${JSON.stringify(value)}`);
}

function describe(result: Result<number, "invalid-port">): string {
  switch (result.ok) {
    case true:
      return String(result.value);
    case false:
      return result.error;
    default:
      return assertNever(result);
  }
}
```

**Tip**: Apply this to closed domain unions you control. It is not a reason to invent a union around every boolean.

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
