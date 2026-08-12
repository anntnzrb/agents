# Semantics and Weirdness

Read for JavaScript-native bugs: coercion, binding, closure state, execution order, prototype lookup.

## Coercion and equality

`===` default; `Object.is()` when `NaN` or signed zero matter.

```js
"5" + 3; // "53"
"5" - 3; // 2

null == undefined; // true
null === undefined; // false

Object.is(NaN, NaN); // true
Object.is(-0, 0); // false
```

Falsy: `false`, `0`, `-0`, `0n`, `""`, `null`, `undefined`, `NaN`.
Use `??` for defaults only on `null`/`undefined`.

```js
const port = config.port ?? 3000; // preserves 0
const label = userInput || "default"; // replaces "", 0, false too
```

Trusted type checks:

```js
typeof value === "string";
Array.isArray(value);
value instanceof URL;
Object.prototype.toString.call(value); // useful for edge cases
```

## Scope, closures, hoisting, TDZ

`var` function-scoped and hoisted; prefer `const`, use `let` only for real reassignment.

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

Closures capture lexical bindings, not snapshots.

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

TDZ: `let` and `const` hoisted but uninitialized.

```js
console.log(a); // undefined
var a = 1;

console.log(b); // ReferenceError
let b = 1;
```

## `this`: call site

`this` depends on how a function is called, not where defined.

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

- `obj.method()` → `this === obj`
- plain call → `undefined` in strict mode
- `fn.call(x)` / `fn.apply(x)` / `fn.bind(x)` → explicit receiver
- arrows define no own `this`; capture outer `this`

Use arrows for callbacks/lexical binding; method syntax or normal functions for a real receiver.

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

Classes are prototype-chain syntax. Property lookup climbs the chain until a match or `null`.

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

Debug separately: own/inherited properties; instance fields/prototype methods; mutation/lookup behavior.

## Weirdness checklist

Stale state: closure captured an old value; object mutated elsewhere rather than replaced; loop used `var`; method passed as callback and receiver lost.

`undefined` property: actual value is `null` or unexpected primitive; `||` used instead of `??`; method is prototype rather than instance (or vice versa); destructure ran before initialization.

Cross-file/runtime difference: strict mode/ESM changes defaults; top-level `this` differs in Node/browser; bundler/transpiler rewrites class fields/modules.

## Minimal debugging

- Log actual value and type, not merely the expected property.
- Reduce to a 10-line repro; stripped framework noise exposes JS semantics.
- Replace clever chains with named intermediates.
- Check call sites first; most `this` bugs arise where the function is passed, not defined.
