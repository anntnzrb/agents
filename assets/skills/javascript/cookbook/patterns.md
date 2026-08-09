# Modern Syntax and Data Patterns

Read this file for modern syntax, transformation patterns, iterators, and performance-friendly defaults.

## Prefer expressive built-ins

### Destructuring, rest, and spread

```js
const user = {
  id: 1,
  profile: { name: "Ada", city: "Quito" },
  roles: ["admin", "editor"],
};

const {
  profile: { name, city },
  ...rest
} = user;

const [primaryRole, ...otherRoles] = user.roles;
const next = { ...user, active: true };
```

Use spread for shallow copies and local immutable updates. Do not pretend it is deep cloning.

### Optional chaining and nullish coalescing

```js
const city = user?.profile?.city ?? "Unknown";
const first = list?.[0];
const result = maybeFn?.();
```

Use `??` for real nullish defaults. Use `||` only when all falsy values should collapse.

## Modern array and object helpers

```js
const lastEven = numbers.findLast((n) => n % 2 === 0);
const sorted = numbers.toSorted((a, b) => a - b);
const reversed = numbers.toReversed();
const removed = numbers.toSpliced(index, 1);
const replaced = numbers.with(index, newValue);
const hasOwn = Object.hasOwn(config, "port");
```

These methods keep intent visible and reduce accidental mutation.

### `map` / `filter` / `reduce` without turning code into soup

```js
const activeNames = users
  .filter((user) => user.active)
  .map((user) => user.name);

const totalsByType = items.reduce((acc, item) => {
  acc[item.type] = (acc[item.type] ?? 0) + item.amount;
  return acc;
}, {});
```

If the chain becomes unreadable, split it into named steps. Brevity is not the goal; obviousness is.

## Immutability without self-harm

Prefer copy-on-write updates for shared state and tests.

```js
const nextUser = {
  ...user,
  profile: {
    ...user.profile,
    city: "Berlin",
  },
};
```

For deep structured cloning where supported, use `structuredClone(value)`.

Do not repeatedly spread giant objects inside hot loops. That is how clean code becomes a perf bug.

## Function patterns

### Higher-order utilities

```js
const once = (fn) => {
  let called = false;
  let value;

  return (...args) => {
    if (!called) {
      called = true;
      value = fn(...args);
    }
    return value;
  };
};

const pipe =
  (...fns) =>
  (value) =>
    fns.reduce((acc, fn) => fn(acc), value);
```

Use composition for clear transformation pipelines, not to cosplay Haskell in a CRUD app.

### Currying and partial application

Useful for reusable data transforms. Usually overkill for ad-hoc app code.

```js
const multiply = (a) => (b) => a * b;
const double = multiply(2);
```

## Iterators and generators

Use generators for lazy sequences, large data walks, or custom iteration semantics.

```js
function* range(start, end) {
  for (let value = start; value <= end; value += 1) {
    yield value;
  }
}

for (const value of range(1, 3)) {
  console.log(value);
}
```

Async generators belong in `cookbook/async.md`, but the design principle is the same: produce values incrementally instead of buffering everything first.

## Class features that matter

```js
class Cache {
  #store = new Map();

  get(key) {
    return this.#store.get(key);
  }

  set(key, value) {
    this.#store.set(key, value);
  }
}
```

Private fields are useful for encapsulation inside real classes. Do not reach for classes when a closure or module-level function set is simpler.

## Small performance helpers

### Debounce

```js
const debounce = (fn, ms) => {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
};
```

### Throttle

```js
const throttle = (fn, ms) => {
  let last = 0;
  return (...args) => {
    const now = Date.now();
    if (now - last >= ms) {
      last = now;
      fn(...args);
    }
  };
};
```

Use these for user-driven bursty events. Do not apply them blindly to hide slow logic.

## Pitfalls worth remembering

- `Array.prototype.sort()` mutates; `toSorted()` does not
- Object spread is shallow
- Repeated `await` inside loops can serialize independent work
- Repeated `JSON.parse(JSON.stringify(x))` is a correctness and performance smell
- Clever point-free chains are often harder to debug than small named functions
