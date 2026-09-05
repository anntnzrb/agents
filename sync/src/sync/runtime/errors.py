# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Sync runtime error helpers and console reporting primitives."""

from __future__ import annotations

import errno
import sys
from typing import Never, NoReturn

__all__ = [
    "assert_never",
    "err",
    "is_errno",
    "panic_message",
    "warn",
]

_OS_ERROR_CODE_MAP: dict[type[OSError], tuple[str, ...]] = {
    FileNotFoundError: ("ENOENT",),
    FileExistsError: ("EEXIST",),
    PermissionError: ("EACCES", "EPERM"),
    IsADirectoryError: ("EISDIR",),
    NotADirectoryError: ("ENOTDIR",),
    ProcessLookupError: ("ESRCH",),
    BlockingIOError: ("EAGAIN", "EWOULDBLOCK"),
    InterruptedError: ("EINTR",),
    ConnectionRefusedError: ("ECONNREFUSED",),
    ConnectionResetError: ("ECONNRESET",),
    TimeoutError: ("ETIMEDOUT",),
}


def panic_message(payload: object) -> str:
    """Extract a human-readable panic message from an arbitrary payload or error."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, BaseException):
        message = str(payload)
        return message or payload.__class__.__name__
    return "panic"


def err(message: str) -> None:
    """Write an error message to stderr with 'sync: ' prefix."""
    sys.stderr.write(f"sync: {message}\n")
    sys.stderr.flush()


def warn(message: str) -> None:
    """Write a warning message to stderr with 'sync: warning: ' prefix."""
    sys.stderr.write(f"sync: warning: {message}\n")
    sys.stderr.flush()


def is_errno(error: object, code: str) -> bool:
    """Check if an error matches a specific errno code name (e.g. 'ENOENT')."""
    if isinstance(error, OSError):
        target_errno = getattr(errno, code, None)
        if target_errno is not None and error.errno == target_errno:
            return True
        for err_type, codes in _OS_ERROR_CODE_MAP.items():
            if isinstance(error, err_type) and code in codes:
                return True
    return getattr(error, "code", None) == code


def assert_never(value: Never) -> NoReturn:
    """Assert that a code branch is unreachable at runtime."""
    message = f"unhandled variant: {value!r}"
    raise AssertionError(message)
