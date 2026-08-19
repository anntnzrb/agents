# Modern Python 3.11-3.12
Concurrency, typing, stdlib upgrades.

## Exception groups (3.11+)
Raise/handle multiple exceptions at once, common in concurrent code.

```python
# Raise multiple exceptions
raise ExceptionGroup("errors", [
    ValueError("invalid value"),
    TypeError("wrong type"),
])

# Catch by type
try:
    async_operation()
except* ValueError as eg:
    print(f"Value errors: {eg.exceptions}")
except* TypeError as eg:
    print(f"Type errors: {eg.exceptions}")
```

`except*` (not `except`) handles exception groups; each handler processes all exceptions of its type.

## TaskGroup: structured concurrency (3.11+)
Multiple async tasks: all complete, or all cancel together on error. TaskGroup automatically cancels sibling tasks when one fails, preventing orphaned tasks.

```python
import asyncio

async def main():
    async with asyncio.TaskGroup() as tg:
        task1 = tg.create_task(fetch("url1"))
        task2 = tg.create_task(fetch("url2"))
    # All tasks complete or all cancelled on error
    return task1.result(), task2.result()
```

## TOML parser (3.11+)
Parse TOML without external dependencies.

```python
import tomllib

with open("pyproject.toml", "rb") as f:
    config = tomllib.load(f)

# Or from string
data = tomllib.loads('[section]\nkey = "value"')
```

Files MUST use binary mode (`"rb"`); `tomllib` is read-only; use `tomli_w` to write.

## Self type (3.11+)
`Self` makes method returns refer to the current class, not the parent; especially useful for builder methods returning `self` for chaining.

```python
from typing import Self

class Builder:
    def with_name(self, name: str) -> Self:
        self.name = name
        return self

    def clone(self) -> Self:
        return type(self)()
```

## Type-parameter syntax (3.12+)
Generic functions/classes without `TypeVar` boilerplate; bracket syntax is more concise and puts parameters in the function/class signature.

```python
# Old way
from typing import TypeVar
T = TypeVar("T")
def first(items: list[T]) -> T: ...

# New way - cleaner!
def first[T](items: list[T]) -> T:
    return items[0]

# Generic classes
class Stack[T]:
    def __init__(self) -> None:
        self._items: list[T] = []

    def push(self, item: T) -> None:
        self._items.append(item)

    def pop(self) -> T:
        return self._items.pop()

# Constrained types
def add[T: (int, float)](a: T, b: T) -> T:
    return a + b
```

## Type-alias statement (3.12+)
`type` creates aliases recognized as types rather than runtime values and supports generic parameters cleanly.

```python
# Old way
from typing import TypeAlias
Vector: TypeAlias = list[float]

# New way
type Vector = list[float]
type Point = tuple[float, float]
type Callback[T] = Callable[[T], None]
```

## F-string improvements (3.12+)
F-strings accept any quote style inside expressions without escaping and support multiline expressions, improving JSON/dict access. `f"{x:=10}"` uses a format spec, not a walrus.

```python
# Nested quotes (any quote style)
print(f"User: {user["name"]}")  # Now works!
print(f'Status: {data['status']}')

# Multiline expressions
result = f"{
    some_long_function_call(
        arg1,
        arg2
    )
}"

# Comments inside f-strings
f"{x:=10}"  # This is a format spec, not walrus!
```

## Override decorator (3.12+)
`@override` makes type checkers verify parent-method existence and signature, catching typos/mismatches early.

```python
from typing import override

class Parent:
    def greet(self) -> str:
        return "Hello"

class Child(Parent):
    @override
    def greet(self) -> str:  # Type checker verifies this exists in parent
        return "Hi"

    @override
    def great(self) -> str:  # Error: typo, no such method in parent
        return "Oops"
```

## Batched iteration (3.12+)
`batched()` processes fixed-size chunks more efficiently than manual chunking and automatically handles the final partial batch.

```python
from itertools import batched

list(batched("ABCDEFG", 3))
# [('A', 'B', 'C'), ('D', 'E', 'F'), ('G',)]

# Process in chunks
for batch in batched(large_dataset, 100):
    process_batch(batch)
```
