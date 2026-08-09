# Copyright (c) 2026
from __future__ import annotations

from collections.abc import Iterator

import pytest


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
    if request.node.get_closest_marker("live_smoke") is not None:
        yield
        return

    def blocked(*_args: object, **_kwargs: object) -> None:
        message = "deterministic tests must not access the network"
        raise AssertionError(message)

    monkeypatch.setattr("livebench.transport.urlopen", blocked)
    monkeypatch.setattr("urllib.request.urlopen", blocked)
    yield
