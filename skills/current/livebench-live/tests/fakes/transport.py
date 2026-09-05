# Copyright (c) 2026
from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Mapping


@final
class Response:
    body: bytes
    status: int
    headers: dict[str, str]
    final_url: str | None

    def __init__(
        self,
        body: bytes | str = b"",
        *,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
        final_url: str | None = None,
    ) -> None:
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.status = status
        self.headers = dict(headers or {})
        self.final_url = final_url

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self.final_url or "fixture://response"


@final
class QueueOpener:
    responses: list[Response | BaseException]
    requests: list[object]

    def __init__(self, *responses: Response | BaseException) -> None:
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request: object, timeout: float = 0.0) -> Response:
        self.requests.append(request)
        if not self.responses:
            message = "real or unexpected network request"
            raise AssertionError(message)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response
