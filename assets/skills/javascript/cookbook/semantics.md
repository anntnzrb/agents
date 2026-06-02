# Semantics and Weirdness

Read this file when the bug smells like JavaScript itself: coercion, binding, closure state, execution order, or prototype lookup.

## Coercion and equality

Use `===` by default. Reach for `Object.is()` when `NaN` or signed zero actually matter.

```js
"5" + 3; // "53"
"5" - 3; // 2

null == undefined; // true
null === undefined; // false

Object.is(NaN, NaN); // true
Object.is(-0, 0); // false
```

### Truthy / falsy traps

Falsy values:

- `false`
- `0`
- `-0`
- `0n`
- `""`
- `null`
- `undefined`
- `NaN`

Prefer `??` when you only want a default for `null` / `undefined`.

```js
const port = config.port ?? 3000; // preserves 0
const label = userInput || "default"; // replaces "", 0, false too
```

### Type checks worth trusting

```js
typeof value === "string";
Array.isArray(value);
value instanceof URL;
Object.prototype.toString.call(value); // useful for edge cases
```

## Scope, closures, hoisting, TDZ

`var` is function-scoped and hoisted in ways that cause ghost bugs. Prefer `const`; use `let` only when reassignment is real.

```js
for (var i = 0; i < 3; i++) {
  setTimeout(() => console.log(i), 0);
}
// 3, 3, 3

for (let i = 0; i < 3; i++) {
  setTimeout(() => console.log(i), 0);
}
// 0, 1, 2
```

Closures capture bindings from lexical scope, not snapshot copies of your intent.

```js
function createCounter() {
  let count = 0;
  return {
    inc() {
      count += 1;
      return count;
    },
    get() {
      return count;
    },
  };
}
```

Temporal Dead Zone: `let` and `const` are hoisted, but not initialized.

```js
console.log(a); // undefined
var a = 1;

console.log(b); // ReferenceError
let b = 1;
```

## `this` is a call-site problem

The value of `this` depends on **how** a function is called, not where it was defined.

```js
const user = {
  name: "Ada",
  greet() {
    return this.name;
  },
};

user.greet(); // "Ada"

const loose = user.greet;
loose(); // undefined in strict mode
```

### Quick rules

- `obj.method()` -> `this === obj`
- plain function call -> `undefined` in strict mode
- `fn.call(x)` / `fn.apply(x)` / `fn.bind(x)` -> explicit receiver
- arrow functions do **not** define their own `this`; they capture outer `this`

Use arrow functions for callbacks and lexical binding. Use method syntax or normal functions when you need a real receiver.

```js
class Timer {
  count = 0;

  start() {
    setInterval(() => {
      this.count += 1;
    }, 1000);
  }
}
```

## Prototypes and classes

Classes are syntax over the prototype chain. Property lookup climbs that chain until it finds a match or hits `null`.

```js
const animal = {
  speak() {
    return "noise";
  },
};

const dog = Object.create(animal);
dog.bark = () => "woof";

dog.speak(); // "noise"
```

```js
class Animal {
  speak() {
    return "noise";
  }
}

class Dog extends Animal {
  bark() {
    return "woof";
  }
}
```

When debugging, separate:

- own properties vs inherited properties
- instance fields vs prototype methods
- data mutation vs lookup behavior

## Common weirdness checklist

### If state looks stale

- Did a closure capture an old value?
- Did you mutate an object elsewhere instead of replacing it?
- Did a loop use `var` instead of `let`?
- Did you pass a method as a callback and lose the receiver?

### If a property is `undefined`

- Is the value actually `null` or an unexpected primitive?
- Are you using `||` where `??` was intended?
- Is the method on the prototype instead of the instance, or vice versa?
- Did a destructure run before initialization?

### If behavior differs between files or runtimes

- Is strict mode / ESM changing defaults?
- Is `this` in top-level code different between Node and the browser?
- Is a bundler or transpiler rewriting class fields / modules?

## Minimal debugging moves

- Log the **actual value and type**, not just the property you hoped existed.
- Reduce the bug to a 10-line repro. JS semantics become obvious fast when stripped of framework noise.
- Replace clever chains with named intermediate values while debugging.
- Check call sites first. Most `this` bugs are introduced where the function is passed, not where it is defined.
