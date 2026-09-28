"""Safety fixtures for deterministic Artificial Analysis tests."""

import os
import socket
import sys
import urllib.request
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parents[1] / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest


def _live_smoke_enabled(request: pytest.FixtureRequest) -> bool:
    return (
        os.environ.get("RUN_LIVE_SMOKE") == "1"
        and request.path.name == "test_live_smoke.py"
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

    if "artificial_analysis.cli" not in sys.modules:
        return
    from artificial_analysis import cli

    skill_env = Path(__file__).resolve().parents[1] / ".env"
    original_candidates = cli._dotenv_candidates

    def safe_candidates() -> list[Path]:
        return [
            candidate
            for candidate in original_candidates()
            if candidate.resolve() != skill_env.resolve()
        ]

    monkeypatch.setattr(cli, "_dotenv_candidates", safe_candidates)
