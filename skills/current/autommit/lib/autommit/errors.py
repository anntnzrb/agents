"""Expected autommit failures and process exit codes."""

from __future__ import annotations


class AutommitError(Exception):
    """An actionable failure safe to expose at the CLI boundary."""

    def __init__(self, code: str, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


class GitError(AutommitError):
    """A Git subprocess failed."""

    def __init__(self, message: str) -> None:
        super().__init__("git_error", message, 4)


class GitMissingError(AutommitError):
    """The Git executable is unavailable."""

    def __init__(self) -> None:
        super().__init__("git_missing", "Git executable was not found.", 127)


class RefusalError(AutommitError):
    """Concurrent state or a safety precondition prevents mutation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 3)
