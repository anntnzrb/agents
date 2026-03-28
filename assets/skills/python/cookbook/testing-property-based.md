# Property-Based Testing

Use Hypothesis when the property is the point: parsers, transforms, serializers, and invariants. A few examples cannot cover the failure surface.

## Install

```bash
uv add --dev hypothesis
```

## Strategy rules

- Prefer narrow, domain-shaped strategies (`st.dates()`, `st.integers()`, bounded lists)
- Keep generated values small enough to shrink quickly
- Use `assume()` sparingly; if you need many `assume()` calls, narrow the strategy instead
- Turn the smallest counterexample into a normal regression test

## Parser round-trip

A parser should round-trip valid values cleanly.

```python
from datetime import date

from hypothesis import given, strategies as st


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


@given(st.dates())
def test_parse_date_round_trip(value: date) -> None:
    assert parse_date(value.isoformat()) == value
```

## Transform idempotence

A normalizer should be idempotent.

```python
from hypothesis import given, strategies as st


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


@given(st.text())
def test_normalize_whitespace_is_idempotent(text: str) -> None:
    normalized = normalize_whitespace(text)
    assert normalize_whitespace(normalized) == normalized
```

## Serializer round-trip

Encoding and decoding should preserve the object.

```python
import msgspec

from hypothesis import given, strategies as st


class Point(msgspec.Struct):
    x: int
    y: int


@given(st.integers(), st.integers())
def test_point_json_round_trip(x: int, y: int) -> None:
    point = Point(x, y)
    encoded = msgspec.json.encode(point)
    assert msgspec.json.decode(encoded, type=Point) == point
```

## Invariant checks

An invariant should hold for every valid input, and invalid inputs should fail fast.

```python
from dataclasses import dataclass

import pytest
from hypothesis import assume, given, strategies as st


@dataclass(frozen=True)
class Interval:
    low: int
    high: int

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError("low must be <= high")


@given(st.integers(), st.integers())
def test_interval_rejects_inverted_bounds(low: int, high: int) -> None:
    assume(low > high)
    with pytest.raises(ValueError):
        Interval(low=low, high=high)
```

## Don't use Hypothesis for

- one-off branch coverage
- trivial getters and setters
- filesystem or network glue
- logic with one or two meaningful examples
