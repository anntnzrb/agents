"""Structured errors for the raw-Git worktree controller."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(slots=True)
class DomainError(Exception):
    """An expected error that the CLI can render without a traceback."""

    code: str
    message: str
    details: Mapping[str, object] = field(default_factory=dict[str, object])
    exit_code: int = 2

    def __post_init__(self) -> None:
        """Initialize the base exception."""
        Exception.__init__(self, self.message)

    def as_dict(self) -> dict[str, object]:
        """Serialize to a plain dict."""
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


class InputError(DomainError):
    """An input validation error."""

    def __init__(
        self, code: str, message: str, details: Mapping[str, object] | None = None
    ) -> None:
        """Initialize with a code, message, and details."""
        super().__init__(code, message, {} if details is None else details, 2)


class RefusalError(DomainError):
    """An operation refusal with an exit code."""

    def __init__(
        self, code: str, message: str, details: Mapping[str, object] | None = None
    ) -> None:
        """Initialize with a code, message, and details."""
        super().__init__(code, message, {} if details is None else details, 3)


class GitError(DomainError):
    """A git subprocess failure."""

    def __init__(
        self, code: str, message: str, details: Mapping[str, object] | None = None
    ) -> None:
        """Initialize with a code, message, and details."""
        super().__init__(code, message, {} if details is None else details, 4)


class GitMissingError(DomainError):
    """A missing git executable."""

    def __init__(self) -> None:
        """Initialize the missing-git error."""
        super().__init__("git_missing", "Git executable was not found", {}, 127)
