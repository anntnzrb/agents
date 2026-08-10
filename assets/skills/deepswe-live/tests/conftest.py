"""Pytest policy: deterministic DeepSWE tests must not use the network."""
# ruff: noqa: CPY001, INP001

from __future__ import annotations

import os
import socket
import urllib.request
from typing import NoReturn

import _path  # noqa: F401
import pytest
from deepswe import sources


def _live_smoke_allowed(request: pytest.FixtureRequest) -> bool:
    """Allow network only for the explicit opt-in smoke module."""
    module = getattr(request.node, "module", None)
    name = getattr(module, "__name__", "")
    return name.endswith("test_live_smoke") and os.environ.get("RUN_LIVE_SMOKE") == "1"


@pytest.fixture(autouse=True)
def deny_network(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail immediately on URL or socket access outside the live smoke test."""
    if _live_smoke_allowed(request):
        return

    def denied(*_args: object, **_kwargs: object) -> NoReturn:
        message = (
            "network access is disabled for offline DeepSWE tests; "
            "use RUN_LIVE_SMOKE=1 for the dedicated smoke test"
        )
        raise AssertionError(message)

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(sources, "urlopen", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(urllib.request, "urlopen", denied)
