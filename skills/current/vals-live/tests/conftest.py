# Copyright 2026 Vals-live contributors.
"""Keep deterministic vals-live tests offline by default."""

from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

import pytest

import _path
from vals_live import cache

_ = _path.ROOT


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
    getter: Callable[..., object] = getattr
    node = getter(request, "node", None)
    get_marker = getter(node, "get_closest_marker", None)
    if callable(get_marker) and get_marker("live_smoke") is not None:
        yield
        return

    def blocked(_request: object, **_kwargs: object) -> NoReturn:
        message = "deterministic tests must not access the network"
        raise AssertionError(message)

    monkeypatch.setattr(cache, "urlopen", blocked)
    yield
