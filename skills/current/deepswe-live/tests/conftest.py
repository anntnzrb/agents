"""Pytest policy: deterministic DeepSWE tests must not use the network."""

from __future__ import annotations

import os
import socket
import sys
import urllib.request
from pathlib import Path
from typing import NoReturn, cast

import pytest

_SKILL_DIR = Path(__file__).resolve().parents[1]
_LIB_DIR = _SKILL_DIR / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from deepswe import sources


def _live_smoke_allowed(request: pytest.FixtureRequest) -> bool:
    """Allow network only for the explicit opt-in smoke module."""
    node: object = cast("object", request.node)
    module: object = getattr(node, "module", None)
    name: object = getattr(module, "__name__", "")
    return (
        isinstance(name, str)
        and name.endswith("test_live_smoke")
        and os.environ.get("RUN_LIVE_SMOKE") == "1"
    )


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
