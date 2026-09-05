# Copyright 2026 Vals-live contributors.
# ruff: noqa: INP001
"""Deterministic HTTP response and request fakes for vals-live tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from urllib.request import Request


@dataclass
class Response:
    """Represent one deterministic HTTP response."""

    body: bytes = b""
    status: int = 200
    headers: dict[str, str] | None = None
    final_url: str = ""

    def __post_init__(self) -> None:
        """Normalize headers for case-insensitive lookup."""
        self.headers = dict(self.headers or {})

    def __enter__(self) -> Self:
        """Enter the deterministic response context."""
        return self

    def __exit__(self, *args: object) -> None:
        """Exit the deterministic response context."""
        return

    def read(self) -> bytes:
        """Return the queued response body."""
        return self.body

    def getcode(self) -> int:
        """Return the queued HTTP status."""
        return self.status

    def geturl(self) -> str:
        """Return the queued final URL."""
        return self.final_url

    def getheader(self, name: str, default: str | None = None) -> str | None:
        """Return a header using HTTP case-insensitive matching."""
        for key, value in (self.headers or {}).items():
            if key.lower() == name.lower():
                return value
        return default


class QueueOpener:
    """Queue deterministic responses without network access."""

    responses: list[Response | BaseException]
    requests: list[Request]

    def __init__(self, *responses: Response | BaseException) -> None:
        """Initialize the response queue and request capture."""
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request: Request, *, timeout: float = 30.0) -> Response:
        """Record a request and return or raise its next queued result."""
        del timeout
        self.requests.append(request)
        if not self.responses:
            msg = "unexpected live request"
            raise AssertionError(msg)
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result
