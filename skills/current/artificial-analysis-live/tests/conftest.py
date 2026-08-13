"""Safety fixtures for deterministic Artificial Analysis tests."""

# ruff: noqa: CPY001, INP001, SLF001
from __future__ import annotations

import os
import socket
import sys
import urllib.request
from pathlib import Path

import pytest


def _live_smoke_enabled(request: pytest.FixtureRequest) -> bool:
    path = getattr(request.node, "path", None)
    return (
        os.environ.get("RUN_LIVE_SMOKE") == "1"
        and isinstance(path, Path)
        and path.name == "test_live_smoke.py"
    )


def _deny_network(*_args: object, **_kwargs: object) -> None:
    message = (
        "network access is disabled for deterministic AA tests; "
        "set RUN_LIVE_SMOKE=1 only for tests/test_live_smoke.py"
    )
    raise AssertionError(message)


@pytest.fixture(autouse=True)
def deny_network_and_real_dotenv(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deny network and exclude the skill-root .env from normal tests."""
    if not _live_smoke_enabled(request):
        monkeypatch.setattr(urllib.request, "urlopen", _deny_network)
        monkeypatch.setattr(socket, "socket", _deny_network)

        # rsc imports urlopen as a module-local alias; patch it only when the
        # package was already imported by the test module.
        rsc_module = sys.modules.get("artificial_analysis.rsc")
        if rsc_module is not None and hasattr(rsc_module, "urlopen"):
            monkeypatch.setattr(rsc_module, "urlopen", _deny_network)

    cli_module = sys.modules.get("artificial_analysis.cli")
    if cli_module is None or not hasattr(cli_module, "_dotenv_candidates"):
        return
    skill_env = Path(__file__).resolve().parents[1] / ".env"
    original_candidates = cli_module._dotenv_candidates

    def safe_candidates(*args: object, **kwargs: object) -> list[Path]:
        return [
            Path(candidate)
            for candidate in original_candidates(*args, **kwargs)
            if Path(candidate).resolve() != skill_env.resolve()
        ]

    monkeypatch.setattr(cli_module, "_dotenv_candidates", safe_candidates)
