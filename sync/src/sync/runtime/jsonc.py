# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""JSONC parsing for sync runtime (comments and trailing commas)."""

from __future__ import annotations

from typing import TypeGuard


def is_obj_dict(val: object) -> TypeGuard[dict[str, object]]:
    """Narrow an unknown JSON value to a string-keyed object."""
    return isinstance(val, dict)


def is_obj_list(val: object) -> TypeGuard[list[object]]:
    """Narrow an unknown JSON value to an array."""
    return isinstance(val, list)


def _consume_string(content: str, i: int, n: int, result: list[str]) -> int:
    result.append('"')
    i += 1
    while i < n:
        ch = content[i]
        result.append(ch)
        if ch == "\\":
            i += 1
            if i < n:
                result.append(content[i])
                i += 1
            continue
        if ch == '"':
            return i + 1
        i += 1
    return i


def _skip_comment(content: str, i: int, n: int) -> tuple[int, int]:
    """Skip a // or /* comment at i; return (end index, newlines seen)."""
    newlines = 0
    if content[i + 1] == "/":
        i += 2
        while i < n and content[i] != "\n":
            i += 1
        return i, newlines
    i += 2
    while i < n:
        if content[i] == "\n":
            newlines += 1
            i += 1
        elif content[i : i + 2] == "*/":
            return i + 2, newlines
        else:
            i += 1
    return i, newlines


def strip_jsonc(content: str) -> str:
    """Strip comments (// and /* */) and trailing commas from JSONC content."""
    result: list[str] = []
    i = 0
    n = len(content)
    while i < n:
        ch = content[i]
        if ch == '"':
            i = _consume_string(content, i, n, result)
        elif content[i : i + 2] in ("//", "/*"):
            i, newlines = _skip_comment(content, i, n)
            result.append("\n" * newlines)
        elif ch == ",":
            j = i + 1
            while True:
                while j < n and content[j] in " \t\r\n":
                    j += 1
                if content[j : j + 2] in ("//", "/*"):
                    j, _ = _skip_comment(content, j, n)
                else:
                    break
            if j < n and content[j] in "}]":
                i += 1
            else:
                result.append(",")
                i += 1
        else:
            result.append(ch)
            i += 1
    return "".join(result)


__all__ = [
    "is_obj_dict",
    "is_obj_list",
    "strip_jsonc",
]
