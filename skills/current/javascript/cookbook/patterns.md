# Modern Syntax and Data Patterns

Modern syntax, transformation patterns, iterators, and performance defaults.

## Built-ins

### Destructuring, rest, spread

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

Spread: shallow copies and local immutable updates; not deep cloning.

### Optional chaining, nullish coalescing

```js
const city = user?.profile?.city ?? "Unknown";
const first = list?.[0];
const result = maybeFn?.();
```

`??`: nullish defaults. `||`: only when every falsy value should collapse.

## Array/object helpers

```js
const lastEven = numbers.findLast((n) => n % 2 === 0);
const sorted = numbers.toSorted((a, b) => a - b);
const reversed = numbers.toReversed();
const removed = numbers.toSpliced(index, 1);
const replaced = numbers.with(index, newValue);
const hasOwn = Object.hasOwn(config, "port");
```

These preserve intent and reduce accidental mutation.

### `map` / `filter` / `reduce`

```js
const activeNames = users
  .filter((user) => user.active)
  .map((user) => user.name);

const totalsByType = items.reduce((acc, item) => {
  acc[item.type] = (acc[item.type] ?? 0) + item.amount;
  return acc;
}, {});
```

Split unreadable chains into named steps; obviousness > brevity.

## Immutability

Prefer copy-on-write for shared state and tests.

```js
const nextUser = {
  ...user,
  profile: {
    ...user.profile,
    city: "Berlin",
  },
};
```

Use `structuredClone(value)` for deep structured cloning where supported. NEVER repeatedly spread giant objects in hot loops; that creates performance bugs.

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

Use composition for clear transformation pipelines, not Haskell-style cleverness in CRUD apps.

### Currying and partial application

Useful for reusable data transforms; usually overkill for ad-hoc app code.

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

Async generators belong in `cookbook/async.md`; principle unchanged: produce incrementally, not by buffering everything first.

## Classes

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

Private fields: encapsulation inside real classes. Prefer a closure or module-level function set when simpler.

## Performance helpers

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

Use for user-driven bursty events; NEVER apply blindly to hide slow logic.

## Pitfalls

- `Array.prototype.sort()` mutates; `toSorted()` does not
- Object spread is shallow
- Repeated `await` inside loops can serialize independent work
- Repeated `JSON.parse(JSON.stringify(x))` is a correctness and performance smell
- Clever point-free chains are often harder to debug than small named functions
