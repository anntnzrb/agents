"""Shared payload types and error classes for omp-search."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class SearchSource(TypedDict):
    """One deduplicated source entry in the JSON envelope."""

    title: str
    domain: str
    age: str | None


class SearchError(TypedDict):
    """Machine-readable error detail in a failure payload."""

    code: str
    message: str


class SearchSuccessPayload(TypedDict):
    """JSON envelope emitted when the search succeeds."""

    ok: Literal[True]
    query: str
    provider: str
    providers: list[str]
    providers_count: int
    answer: str
    sources: list[SearchSource]
    sources_count: int
    truncated: bool
    compact: bool
    parsed: bool
    exit_code: Literal[0]
    raw: NotRequired[str]


class SearchFailurePayload(TypedDict):
    """JSON envelope emitted when the search fails."""

    ok: Literal[False]
    query: str
    provider: str
    providers: NotRequired[list[str]]
    providers_count: NotRequired[int]
    answer: Literal[""]
    sources: list[SearchSource]
    sources_count: NotRequired[int]
    truncated: Literal[False]
    compact: bool
    parsed: bool
    exit_code: int
    error: SearchError
    raw: NotRequired[str]
    diagnostics: NotRequired[str]


type SearchResult = SearchSuccessPayload | SearchFailurePayload


class CliOptions(TypedDict, total=False):
    """Parsed command-line options for the search command."""

    query_words: list[str]
    provider: str
    providers: list[str]
    single: bool
    recency: Literal["day", "week", "month", "year"]
    limit: int
    full: bool
    include_raw: bool
    timeout: float
    omp_bin: str


class OmpBinaryNotFoundError(Exception):
    """Raised when the omp executable cannot be resolved."""

    def __init__(self, message: str) -> None:
        """Store the human-readable failure message."""
        super().__init__(message)
        self.message = message


class OmpExecutionError(Exception):
    """Raised when an omp child process exits with a nonzero code."""

    def __init__(self, exit_code: int, stdout: str, stderr: str, message: str) -> None:
        """Store the child exit code, captured streams, and message."""
        super().__init__(message)
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.message = message


class OmpTimeoutError(Exception):
    """Raised when an omp child process exceeds the outer timeout."""

    def __init__(
        self, timeout_seconds: float, message: str, partial_stdout: str
    ) -> None:
        """Store the timeout budget, message, and partial stdout."""
        super().__init__(message)
        self.timeout_seconds = timeout_seconds
        self.message = message
        self.partial_stdout = partial_stdout
