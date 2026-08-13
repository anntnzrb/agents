"""Structured errors for the raw-Git worktree controller."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(slots=True)
class DomainError(Exception):
    """An expected error that the CLI can render without a traceback."""

    code: str
    message: str
    details: Mapping[str, object] = field(default_factory=dict)
    exit_code: int = 2

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


class InputError(DomainError):
    def __init__(self, code: str, message: str, details: Mapping[str, object] | None = None) -> None:
        super().__init__(code, message, {} if details is None else details, 2)


class RefusalError(DomainError):
    def __init__(self, code: str, message: str, details: Mapping[str, object] | None = None) -> None:
        super().__init__(code, message, {} if details is None else details, 3)


class GitError(DomainError):
    def __init__(self, code: str, message: str, details: Mapping[str, object] | None = None) -> None:
        super().__init__(code, message, {} if details is None else details, 4)


class GitMissingError(DomainError):
    def __init__(self) -> None:
        super().__init__("git_missing", "Git executable was not found", {}, 127)
