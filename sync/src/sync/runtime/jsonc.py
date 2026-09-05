# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""JSONC parsing for sync runtime (comments and trailing commas)."""

from __future__ import annotations


def _consume_line_comment(content: str, i: int, n: int, result: list[str]) -> int:
    while i < n:
        if content[i] == "\n":
            result.append("\n")
            return i + 1
        i += 1
    return i


def _consume_block_comment(content: str, i: int, n: int, result: list[str]) -> int:
    while i < n:
        if content[i] == "\n":
            result.append("\n")
            i += 1
        elif content[i : i + 2] == "*/":
            return i + 2
        else:
            i += 1
    return i


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


def _strip_jsonc_comments(content: str) -> str:
    result: list[str] = []
    i = 0
    n = len(content)

    while i < n:
        ch = content[i]
        if ch == '"':
            i = _consume_string(content, i, n, result)
        elif content[i : i + 2] == "//":
            i = _consume_line_comment(content, i + 2, n, result)
        elif content[i : i + 2] == "/*":
            i = _consume_block_comment(content, i + 2, n, result)
        else:
            result.append(ch)
            i += 1

    return "".join(result)


def _strip_trailing_commas(content: str) -> str:
    result: list[str] = []
    i = 0
    n = len(content)

    while i < n:
        ch = content[i]
        if ch == '"':
            i = _consume_string(content, i, n, result)
        elif ch == ",":
            j = i + 1
            while j < n and content[j] in " \t\r\n":
                j += 1
            if j < n and content[j] in "}]":
                i += 1
            else:
                result.append(",")
                i += 1
        else:
            result.append(ch)
            i += 1

    return "".join(result)


def strip_jsonc(content: str) -> str:
    """Strip comments (// and /* */) and trailing commas from JSONC content."""
    cleaned = _strip_jsonc_comments(content)
    return _strip_trailing_commas(cleaned)


__all__ = [
    "strip_jsonc",
]
