# Type Patterns



## Section index


# PEP 695 (Python 3.12+)
type JsonValue = (
    str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
)
type Headers = dict[str, str]
type Middleware = Callable[[Request], Awaitable[Response]]
```

## StrEnum / IntEnum: closed sets
Use enums for fixed known values; avoid scattered string literals.

```python
from enum import StrEnum, IntEnum, unique


@unique
class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"
    GUEST = "guest"


@unique
class HttpStatus(IntEnum):
    OK = 200
    NOT_FOUND = 404
    INTERNAL_ERROR = 500


# BAD
def check_role(role: str) -> bool: ...


# GOOD
def check_role(role: Role) -> bool: ...
```

`StrEnum` for values serialized as strings (API, DB); `IntEnum` for numeric codes; plain `Enum` for pure labels.

## Type narrowing
`isinstance`, `is None`, and `match` narrow automatically; prefer them to `cast`.

```python
def process(value: str | int | None) -> str:
    if value is None:
        return "nothing"
    # checker knows: str | int

    if isinstance(value, str):
        return value.upper()
    # checker knows: int

    return str(value * 2)
```

### TypeGuard: custom narrowing

```python
from typing import TypeGuard


def is_valid_email(value: str) -> TypeGuard[Email]:
    return "@" in value and "." in value.split("@")[1]


def send(addr: str) -> None:
    if not is_valid_email(addr):
        raise ValueError(addr)
    # checker knows: addr is Email
    deliver(addr)
```

### TypeIs (Python 3.13+): strict narrowing
Stricter than `TypeGuard`; narrows both `if` and `else` branches.

```python
from typing import TypeIs


def is_str(value: str | int) -> TypeIs[str]:
    return isinstance(value, str)


def handle(v: str | int) -> None:
    if is_str(v):
        print(v.upper())  # checker knows: str
    else:
        print(v + 1)  # checker knows: int
```

## Union syntax
Always `X | Y`; never `Union` or legacy `Optional`.

```python
# BAD: legacy typing imports
from typing import Optional, Union


def f(x: Optional[int]) -> Union[str, int]: ...


# GOOD: PEP 604 pipe syntax
def f(x: int | None) -> str | int: ...
```

## Sources

- Python docs: [typing; NewType](https://docs.python.org/3/library/typing.html#newtype)
- Python docs: [typing; Final](https://docs.python.org/3/library/typing.html#typing.Final)
- Python docs: [typing; TypeGuard](https://docs.python.org/3/library/typing.html#typing.TypeGuard)
- PEP 604: [Union syntax X | Y](https://peps.python.org/pep-0604/)
- PEP 742: [TypeIs](https://peps.python.org/pep-0742/)
