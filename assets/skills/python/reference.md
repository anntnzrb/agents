# Python Quick Reference

Keep this file for fast decisions while coding. Load cookbooks for tutorials and deep patterns.

## Typed JSON and Boundary Schemas

For JSON/API/RPC/CLI/env payloads, keep known shapes in the type system while they are still dict-shaped.

| Shape               | Prefer                     | Example                          |
| ------------------- | -------------------------- | -------------------------------- | ------------------------ |
| fixed object keys   | `TypedDict`                | API request/response payloads    |
| optional keys       | `NotRequired` / `Required` | sparse updates                   |
| fixed string values | `Literal`                  | `status: Literal["ok", "error"]` |
| small variant set   | discriminated union        | `Created                         | Updated`with a`kind` tag |

```python
from typing import Literal, NotRequired, TypedDict

class UserCreated(TypedDict):
    kind: Literal["user.created"]
    user_id: str
    email: str

class UserUpdated(TypedDict):
    kind: Literal["user.updated"]
    user_id: str
    email: NotRequired[str]

Event = UserCreated | UserUpdated
```

Boundary rule:

1. Decode or receive untrusted data at the edge.
2. Validate/narrow once with typed code, Pydantic `TypeAdapter`, or msgspec.
3. Convert inward to `TypedDict`s or domain objects.
4. Keep `dict[str, Any]` and validator objects out of core logic unless the project intentionally uses them as domain models.

### Pydantic standalone validation

```python
from typing import Literal, TypedDict
from pydantic import ConfigDict, TypeAdapter

class CreateUser(TypedDict):
    action: Literal["create_user"]
    email: str

adapter = TypeAdapter(CreateUser, config=ConfigDict(strict=True))
payload = adapter.validate_python(raw_payload)
```

### msgspec closed payload

```python
from typing import Literal
import msgspec

class CreateUser(msgspec.Struct, forbid_unknown_fields=True):
    action: Literal["create_user"]
    email: str

payload = msgspec.json.decode(raw_bytes, type=CreateUser)
```

## Type System Defaults

- Public functions and methods should have explicit parameter and return types.
- For inputs, prefer abstract/read-only protocols when mutation is not required: `Iterable[T]`, `Sequence[T]`, `Mapping[K, V]`.
- For concrete implementation returns, prefer concrete types: `list[T]`, `dict[K, V]`, domain objects.
- Use `object` instead of `Any` when accepting any value but treating it generically.
- Prefer `T | None`, `A | B`, `Protocol`, `typing.Self`, and `@override` when supported by the project target.
- Avoid `cast(...)`, `# type: ignore`, and `pyright: ignore`; improve the model first.

## Error Handling and Result Types

Catch specific exceptions at the layer that can act. At process/task/API boundaries, log and deliberately map or re-raise. Preserve exception context; do not hide bad input with broad fallbacks.

```python
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

@dataclass(frozen=True, slots=True)
class Ok(Generic[T]):
    value: T

@dataclass(frozen=True, slots=True)
class Err:
    code: str
    message: str

Result = Ok[T] | Err

def parse_count(value: object) -> Result[int]:
    if isinstance(value, int):
        return Ok(value)
    return Err("invalid_count", "count must be an integer")
```

## Anti-Patterns

| Avoid                                                      | Do Instead                                                                          |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------- | -------------------------------------------- | ----------------------------- |
| Mutable default args `def f(items=[])`                     | `def f(items: Sequence[T]                                                           | None = None)`or`field(default_factory=list)` |
| `dict[str, Any]` for known payloads                        | `TypedDict` / `Literal` / discriminated unions                                      |
| `Any` for "accepts anything"                               | `object` plus narrowing                                                             |
| Concrete mutable input types (`list[T]`) when only reading | `Sequence[T]`, `Iterable[T]`, `Mapping[K, V]`                                       |
| Abstract return types from concrete implementations        | Concrete `list[T]`, `dict[K, V]`, domain objects                                    |
| `Optional[T]` / `Union[A, B]` on modern targets            | `T                                                                                  | None`/`A                                     | B` when runtime target allows |
| `requests.get` in async code                               | `httpx.AsyncClient` or `await asyncio.to_thread(...)` for unavoidable blocking work |
| Bare `asyncio.create_task()`                               | `TaskGroup` or tracked/cancelled task lifecycle                                     |
| Classes for data bags                                      | `@dataclass(frozen=True, slots=True)` or `TypedDict`                                |
| Inheritance hierarchies for behavior seams                 | Protocols + composition                                                             |
| Mutating function arguments                                | Return new values / copy-on-write                                                   |
| `try/except Exception` around core logic                   | Specific exceptions; boundary-level catch/log/map only                              |
| Blind `dataclasses.asdict()` in hot paths                  | Explicit shallow projection or serializer                                           |
| `os.path` string manipulation                              | `pathlib.Path`                                                                      |
| Naive UTC `utcnow()`                                       | timezone-aware `datetime.now(UTC)`                                                  |

## Pitfalls and Fixes

| Pitfall                            | Fix                                                               |
| ---------------------------------- | ----------------------------------------------------------------- |
| Raw `response.json()` moves inward | Validate/narrow at the API adapter immediately                    |
| Pydantic/msgspec everywhere        | Validate once at the edge; convert inward                         |
| Pydantic coercion hides bad input  | Use strict mode where coercion is unsafe                          |
| msgspec accepts unexpected keys    | Use `forbid_unknown_fields=True` for closed payloads              |
| mypy/Pyright narrowing pain        | Use `isinstance`, `match`, Protocols, or discriminated unions     |
| Shared mutable state               | Prefer immutable data or copy-on-write                            |
| Over-clever comprehensions         | Extract a named pure function                                     |
| Async client leaks                 | Use `async with` or explicit application lifecycle                |
| Slow tests from real I/O           | Use fixtures, `tmp_path`, local fakes, and boundary seams         |
| Hypothesis noise                   | Reserve for invariants/round-trips; keep strategies domain-shaped |
| Ruff/formatter churn               | Use `ruff format` as the only formatter                           |

## Project Structure

Prefer `src/` layout unless the repository has an established convention.

```text
my-project/
├── src/my_project/
│   ├── __init__.py
│   ├── main.py          # Entry point / CLI shell
│   ├── config.py        # Env/config parsing boundary
│   ├── domain/          # Typed values, entities, invariants
│   ├── services/        # Pure business logic / use cases
│   └── adapters/        # DB/API/filesystem/process boundaries
├── tests/
│   ├── unit/
│   └── integration/
├── pyproject.toml
└── uv.lock
```

## Quick Data Structure Reminders

| Need                            | Use                                       |
| ------------------------------- | ----------------------------------------- |
| Ordered mutable sequence        | `list`                                    |
| Fixed immutable record/sequence | `tuple` / `NamedTuple` / frozen dataclass |
| Fast lookup by key              | `dict`                                    |
| Membership/deduplication        | `set` / `frozenset`                       |
| FIFO queue                      | `collections.deque`                       |
| Priority queue                  | `heapq`                                   |
| Counting                        | `collections.Counter`                     |
| Grouping defaults               | `collections.defaultdict`                 |
