# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Safety contract for the eval review server."""

from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

SKILL: Path = Path(__file__).resolve().parents[1]
VIEWER_DIR: Path = SKILL / "eval-viewer"
MODULE: dict[str, object] = {}
exec(  # noqa: S102 - test loads the script module into a controlled namespace
    compile(
        (VIEWER_DIR / "generate_review.py").read_text(encoding="utf-8"),
        str(VIEWER_DIR / "generate_review.py"),
        "exec",
    ),
    MODULE,
)
SERVER_CONFIG = cast("Callable[..., object]", MODULE["ServerConfig"])
SERVE = cast("Callable[[object], None]", MODULE["_serve"])


def test_occupied_port_falls_back_without_killing_its_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An occupied viewer port is never freed by terminating a foreign process."""
    bound_ports: list[int] = []
    opened_urls: list[str] = []

    class FakeServer:
        def __init__(
            self,
            address: tuple[str, int],
            handler: object,
        ) -> None:
            del handler
            port = address[1]
            bound_ports.append(port)
            if len(bound_ports) == 1:
                raise OSError("port already in use")
            self.server_address: tuple[str, int] = (address[0], 45678)
            self.closed: bool = False

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            self.closed = True

    monkeypatch.setitem(MODULE, "HTTPServer", FakeServer)
    webbrowser_module = MODULE["webbrowser"]

    def fake_open(url: str) -> bool:
        opened_urls.append(url)
        return True

    monkeypatch.setattr(webbrowser_module, "open", fake_open)

    config = SERVER_CONFIG(
        workspace=tmp_path,
        skill_name="fixture",
        feedback_path=tmp_path / "feedback.json",
        previous={},
        previous_workspace=None,
        benchmark_path=None,
        port=3117,
    )
    SERVE(config)

    assert bound_ports == [3117, 0]
    assert opened_urls == ["http://localhost:45678"]
