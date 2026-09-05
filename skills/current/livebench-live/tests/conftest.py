# Copyright (c) 2026
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
LIB_DIR = SKILL_DIR / "lib"
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live_smoke: opt-in smoke against the current official LiveBench source",
    )


@pytest.fixture(autouse=True)
def deny_network(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Reject accidental network access in every deterministic test."""
    node = cast("pytest.Item", request.node)
    if node.get_closest_marker("live_smoke") is not None:
        yield
        return

    def blocked(*_args: object, **_kwargs: object) -> None:
        message = "deterministic tests must not access the network"
        raise AssertionError(message)

    monkeypatch.setattr("livebench.transport.urlopen", blocked)
    monkeypatch.setattr("urllib.request.urlopen", blocked)
    yield
