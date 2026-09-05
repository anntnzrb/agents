"""Expected autommit failures and process exit codes."""

from __future__ import annotations


class AutommitError(Exception):
    """An actionable failure safe to expose at the CLI boundary."""

    def __init__(self, code: str, message: str, exit_code: int = 2) -> None:
        """Store the machine-readable code, message, and exit code."""
        super().__init__(message)
        self.code: str = code
        self.message: str = message
        self.exit_code: int = exit_code


class GitError(AutommitError):
    """A Git subprocess failed."""

    def __init__(self, message: str) -> None:
        """Store a git failure message."""
        super().__init__("git_error", message, 4)


class GitMissingError(AutommitError):
    """The Git executable is unavailable."""

    def __init__(self) -> None:
        """Store the missing-git failure."""
        super().__init__("git_missing", "Git executable was not found.", 127)


class RefusalError(AutommitError):
    """Concurrent state or a safety precondition prevents mutation."""

    def __init__(self, code: str, message: str) -> None:
        """Store the refusal code and message."""
        super().__init__(code, message, 3)
