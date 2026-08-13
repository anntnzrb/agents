# Copyright 2026 Vals-live contributors.
# ruff: noqa: INP001
"""Keep deterministic vals-live tests offline by default."""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from collections.abc import Iterator

import _path  # noqa: F401
import pytest
from vals_live import cache


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Register the explicit opt-in live smoke marker."""
    config.addinivalue_line(
        "markers",
        "live_smoke: opt-in smoke against the current official Vals source",
    )


@pytest.fixture(autouse=True)
def deny_network(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Reject transport access in every test except marked live smoke."""
    if request.node.get_closest_marker("live_smoke") is not None:
        yield
        return

    def blocked(_request: object, **_kwargs: object) -> NoReturn:
        message = "deterministic tests must not access the network"
        raise AssertionError(message)

    monkeypatch.setattr(cache, "urlopen", blocked)
    yield
