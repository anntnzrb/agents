# Functional Patterns: Composition and Immutability

Reduce, partials, dispatch, pipelines, immutable data.

## Reduce for Accumulation
Combine a sequence into one value with a custom operation.

```python
from functools import reduce
from operator import add, mul

numbers = [1, 2, 3, 4, 5]
total = reduce(add, numbers)
assert total == 15

product = reduce(mul, numbers)
assert product == 120

# Custom reducer
def concat_strings(acc: str, s: str) -> str:
    return f"{acc},{s}" if acc else s

words = ["apple", "banana", "cherry"]
result = reduce(concat_strings, words, "")
assert result == "apple,banana,cherry"
```

Tip: Provide an initial `reduce()` value when possible; prefer `operator` functions (`add`, `mul`) to lambdas for better performance.

## Partial Application
Create specialized functions by fixing arguments.

```python
from functools import partial

def power(base: int, exponent: int) -> int:
    return base ** exponent

square = partial(power, exponent=2)
cube = partial(power, exponent=3)

assert square(5) == 25
assert cube(5) == 125

# With positional args
def greet(greeting: str, name: str) -> str:
    return f"{greeting}, {name}!"

say_hello = partial(greet, "Hello")
assert say_hello("Alice") == "Hello, Alice!"
```

Tip: Use `partial()` instead of wrapper functions for specialized functions; useful for callbacks and configuration.

## Memoization
Cache repeated expensive calls with identical arguments.

```python
from functools import lru_cache, cached_property

@lru_cache(maxsize=128)
def fibonacci(n: int) -> int:
    if n < 2:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

# Without cache: O(2^n), With cache: O(n)
assert fibonacci(100) == 354224848179261915075

print(fibonacci.cache_info())
fibonacci.cache_clear()  # Clear cache

# cached_property for classes
class User:
    def __init__(self, user_id: int):
        self.user_id = user_id

    @cached_property
    def full_name(self) -> str:
        return f"User-{self.user_id}"  # Computed once
```

Tip: `lru_cache` suits recursive and expensive computations; use `cached_property` for expensive instance computations needed only once.

## Function Overloading
Dispatch behavior by argument type without manual type checks.

```python
from functools import singledispatch

@singledispatch
def process(arg: object) -> str:
    return f"Default: {arg}"

@process.register(int)
def _(arg: int) -> str:
    return f"Integer: {arg * 2}"

@process.register(list)
def _(arg: list) -> str:
    return f"List with {len(arg)} items"

assert process(5) == "Integer: 10"
assert process([1, 2, 3]) == "List with 3 items"
assert process("hello") == "Default: hello"
```

Tip: `singledispatch` dispatches on the first argument's type; it supports extensible APIs without complex `if`/`isinstance` chains.

## Function Composition
Combine functions into one sequential function.

```python
from typing import Callable, TypeVar

T = TypeVar('T')
U = TypeVar('U')
V = TypeVar('V')

def compose(f: Callable[[T], U], g: Callable[[U], V]) -> Callable[[T], V]:
    def composed(x: T) -> V:
        return g(f(x))
    return composed

def add_one(x: int) -> int:
    return x + 1

def double(x: int) -> int:
    return x * 2

add_then_double = compose(add_one, double)
assert add_then_double(5) == 12  # (5 + 1) * 2
```

Tip: Composition reads right-to-left mathematically; use pipe functions or method chaining for left-to-right execution.

## Pipeline Pattern
Chain transformations left-to-right.

```python
from functools import reduce
from typing import Callable, Any

def pipe(*functions: Callable[[Any], Any]) -> Callable[[Any], Any]:
    return reduce(lambda f, g: lambda x: g(f(x)), functions, lambda x: x)

def add_one(x: int) -> int:
    return x + 1

def triple(x: int) -> int:
    return x * 3

pipeline = pipe(add_one, triple, lambda x: x - 2)
assert pipeline(5) == 16  # 5 -> 6 -> 18 -> 16
```

Tip: Pipelines clarify data transformations; each function receives the previous function's output.

## Fluent Pipeline Class
Use method chaining for readable, type-safe transformations.

```python
from typing import Generic, TypeVar, Callable

T = TypeVar('T')
U = TypeVar('U')

class Pipeline(Generic[T]):
    def __init__(self, value: T):
        self.value = value

    def then(self, func: Callable[[T], U]) -> 'Pipeline[U]':
        return Pipeline(func(self.value))

    def get(self) -> T:
        return self.value

def add_one(x: int) -> int:
    return x + 1

def triple(x: int) -> int:
    return x * 3

result = (
    Pipeline(5)
    .then(add_one)
    .then(triple)
    .then(lambda x: x - 2)
    .get()
)
assert result == 16
```

Tip: Fluent interfaces improve readability, especially in data-processing workflows.

## Frozen Dataclasses
Use immutable data structures to prevent accidental modification.

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Coordinates:
    x: float
    y: float

    def move(self, dx: float, dy: float) -> 'Coordinates':
        return Coordinates(self.x + dx, self.y + dy)

c1 = Coordinates(0, 0)
c2 = c1.move(1, 1)

assert c1.x == 0  # Original unchanged
assert c2.x == 1  # New instance
```

Tip: Frozen dataclasses are hashable and usable as dictionary keys; return new instances rather than mutating.

## NamedTuple for Immutability
Use lightweight immutable records with named fields.

```python
from typing import NamedTuple

class Point(NamedTuple):
    x: float
    y: float

p1 = Point(0, 0)
x, y = p1  # Unpack
# p1.x = 5  # TypeError - immutable
```

Tip: NamedTuples are memory-efficient and faster than dataclasses; use them for simple immutable records.

## Immutable Collections
Prevent dictionary modification or expose a read-only view; use tuples for immutable sequences.

```python
from types import MappingProxyType

config = {"api_key": "secret", "timeout": 30}
readonly_config = MappingProxyType(config)
# readonly_config["api_key"] = "new"  # TypeError

# Functional list operations with tuples
def append_immutable(lst: tuple, item) -> tuple:
    return lst + (item,)

numbers = (1, 2, 3)
new_numbers = append_immutable(numbers, 4)
assert numbers == (1, 2, 3)  # Unchanged
assert new_numbers == (1, 2, 3, 4)
```

Tip: `MappingProxyType` creates a read-only dictionary view; use tuples instead of lists for immutable sequences.

## Copy-on-Write Pattern
Update data structures without mutating the original.

```python
from copy import copy
from dataclasses import dataclass

@dataclass
class UserProfile:
    name: str
    settings: dict

    def with_setting(self, key: str, value: object) -> 'UserProfile':
        new_settings = copy(self.settings)
        new_settings[key] = value
        return UserProfile(name=self.name, settings=new_settings)

profile1 = UserProfile("Alice", {"theme": "light"})
profile2 = profile1.with_setting("theme", "dark")

assert profile1.settings["theme"] == "light"  # Unchanged
assert profile2.settings["theme"] == "dark"
```

Tip: Copy-on-write balances immutability and performance; use `copy()` for shallow copies or `deepcopy()` for nested structures.
