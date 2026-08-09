# Copyright (c) 2026
from __future__ import annotations

from collections.abc import Mapping
from typing import Self


class Response:
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


class QueueOpener:
    def __init__(self, *responses: Response | BaseException) -> None:
        self.responses = list(responses)
        self.requests: list[object] = []

    def __call__(self, request: object, timeout: float = 0.0) -> Response:  # noqa: ARG002
        self.requests.append(request)
        if not self.responses:
            message = "real or unexpected network request"
            raise AssertionError(message)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response
