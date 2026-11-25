"""Subprocess tests for scripts/cli.py; network edges use a loopback fixture."""

import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, TypeIs, override

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

_json_loads: Callable[[str | bytes | bytearray], object] = json.loads

CLI = Path(__file__).parent.parent / "scripts" / "cli.py"


def _is_mapping(val: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(val, Mapping)


def run_cli(
    *argv: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the CLI as a subprocess with an overlaid environment."""
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, str(CLI), *argv],
        capture_output=True,
        text=True,
        env=full_env,
        timeout=60,
        check=False,
    )


class _Fixture(BaseHTTPRequestHandler):
    """Loopback stand-in for the token and API endpoints."""

    @override
    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        _ = self.wfile.write(body)

    def do_POST(self) -> None:
        if "token" in self.path:
            self._json({"access_token": "fake-access", "refresh_token": "fake-refresh"})
        else:
            self._json({"id": "pl-new"})

    def do_GET(self) -> None:
        if "channels" in self.path:
            self._json({"items": [{"snippet": {"title": "TestChannel"}}]})
        else:
            self._json({"items": []})


@pytest.fixture
def server() -> Iterator[str]:
    """Serve the fixture on a loopback port for one test."""
    httpd = HTTPServer(("127.0.0.1", 0), _Fixture)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    thread.join(timeout=5)


def test_no_credentials_is_clean_json_error(tmp_path: Path) -> None:
    env = {
        "YT_CLIENT_ID": "",
        "YT_CLIENT_SECRET": "",
        "YT_REFRESH_TOKEN": "",
        "XDG_CONFIG_HOME": str(tmp_path),
    }
    proc = run_cli("auth", "status", env=env)
    assert proc.returncode == 1
    raw = _json_loads(proc.stdout)
    assert _is_mapping(raw)
    assert raw["ok"] is False
    error = raw["error"]
    assert _is_mapping(error)
    assert error["code"] == "NO_CREDENTIALS"


def test_bootstrap_step_one_prints_url() -> None:
    proc = run_cli(
        "auth",
        "bootstrap",
        env={"YT_CLIENT_ID": "cid", "YT_CLIENT_SECRET": "sec"},
    )
    raw = _json_loads(proc.stdout)
    assert _is_mapping(raw)
    assert raw["ok"] is True
    url = raw["url"]
    assert isinstance(url, str)
    assert "accounts.google.com" in url
    assert "access_type=offline" in url


def test_credentials_from_xdg_file(tmp_path: Path, server: str) -> None:
    cfg_dir = tmp_path / "yt"
    cfg_dir.mkdir()
    _ = (cfg_dir / "oauth.json").write_text(
        json.dumps({"client_id": "c", "client_secret": "s", "refresh_token": "r"}),
        encoding="utf-8",
    )
    env = {
        "YT_CLIENT_ID": "",
        "YT_CLIENT_SECRET": "",
        "YT_REFRESH_TOKEN": "",
        "XDG_CONFIG_HOME": str(tmp_path),
        "YT_TEST_TOKEN_URL": server + "/token",
        "YT_TEST_API_BASE": server,
    }
    proc = run_cli("auth", "status", env=env)
    raw = _json_loads(proc.stdout)
    assert _is_mapping(raw)
    assert raw["ok"] is True
    assert raw["channel"] == "TestChannel"


def test_help_runs() -> None:
    proc = run_cli("--help")
    assert proc.returncode == 0
