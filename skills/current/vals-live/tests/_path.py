# Copyright 2026 Vals-live contributors.
import sys
from pathlib import Path
from typing import TypeIs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
FIXTURES = ROOT / "tests" / "fixtures"


def is_dict(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict)


def is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def as_dict(value: object) -> dict[str, object]:
    assert is_dict(value)
    return value


def as_list(value: object) -> list[object]:
    assert is_list(value)
    return value


def as_dict_list(value: object) -> list[dict[str, object]]:
    assert is_list(value)
    return [as_dict(item) for item in value]
