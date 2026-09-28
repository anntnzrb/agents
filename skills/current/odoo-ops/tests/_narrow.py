"""Narrowing helpers and widened JSON decoding for tests."""

import json
from collections.abc import Callable
from typing import TypeIs


def parse_json(s: str | bytes) -> object:
    fn: Callable[..., object] = json.loads
    return fn(s)


def parse_json_dict(s: str | bytes) -> dict[str, object]:
    data = parse_json(s)
    if is_obj_dict(data):
        return data
    raise AssertionError(f"Expected dict from JSON, got {type(data)}")


def is_obj_dict(val: object) -> TypeIs[dict[str, object]]:
    return isinstance(val, dict)


def is_obj_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


def is_obj_tuple(val: object) -> TypeIs[tuple[object, ...]]:
    return isinstance(val, tuple)


def is_obj_seq(val: object) -> TypeIs[list[object] | tuple[object, ...]]:
    return isinstance(val, (list, tuple))


def to_str_list(val: object) -> list[str]:
    if is_obj_list(val):
        return [str(x) for x in val]
    return []


def mock_call_args(call: object) -> tuple[object, ...]:
    args: object = getattr(call, "args", call)
    if is_obj_tuple(args):
        return args
    return ()


def mock_call_kwargs(call: object) -> dict[str, object]:
    kw: object = getattr(call, "kwargs", None)
    if is_obj_dict(kw):
        return kw
    return {}
