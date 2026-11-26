"""Subprocess tests for scripts/cli.py; network edges use a loopback fixture."""

import importlib.util
import json
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Protocol,
    TypeIs,
    override,
    runtime_checkable,
)

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType

_json_loads: Callable[[str | bytes | bytearray], object] = json.loads

CLI = Path(__file__).parent.parent / "scripts" / "cli.py"


@runtime_checkable
class _YtCli(Protocol):
    def normalize_video_id(self, raw: str) -> str | None: ...


def _is_mapping(val: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(val, Mapping)


def _is_object_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


def _load_cli() -> ModuleType:
    spec = importlib.util.spec_from_file_location("yt_cli_under_test", CLI)
    assert spec is not None, f"cannot load {CLI}"
    assert spec.loader is not None, f"cannot load {CLI}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def yt_cli() -> _YtCli:
    module = _load_cli()
    if not isinstance(module, _YtCli):
        raise TypeError(f"{module} does not implement _YtCli")
    return module


def api_env(server: str) -> dict[str, str]:
    """Environment overlay pointing the CLI at the loopback fixture."""
    return {
        "YT_CLIENT_ID": "c",
        "YT_CLIENT_SECRET": "s",
        "YT_REFRESH_TOKEN": "r",
        "YT_TEST_TOKEN_URL": server + "/token",
        "YT_TEST_API_BASE": server,
    }


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


_PLAYLIST: dict[str, object] = {
    "id": "pl-1",
    "snippet": {"title": "Testlist"},
    "status": {"privacyStatus": "private"},
}

_SECOND_PLAYLIST: dict[str, object] = {
    "id": "pl-2",
    "snippet": {"title": "Testlist archive"},
    "status": {"privacyStatus": "private"},
}

_PLAYLIST_ITEMS: list[dict[str, object]] = [
    {
        "id": "item-1",
        "snippet": {
            "position": 0,
            "title": "First video",
            "resourceId": {"kind": "youtube#video", "videoId": "vid00000001"},
        },
    },
    {
        "id": "item-2",
        "snippet": {
            "position": 1,
            "title": "Second video",
            "resourceId": {"kind": "youtube#video", "videoId": "vid00000002"},
        },
    },
]

_VIDEO: dict[str, object] = {
    "id": "vid00000001",
    "snippet": {
        "title": "First video",
        "channelTitle": "TestChannel",
        "publishedAt": "2024-01-02T03:04:05Z",
    },
    "contentDetails": {"duration": "PT1M2S"},
}


class _Fixture(BaseHTTPRequestHandler):
    """Loopback stand-in for the token and API endpoints."""

    playlists: ClassVar[list[dict[str, object]]] = [dict(_PLAYLIST)]

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

    def do_DELETE(self) -> None:
        self._json({})

    def do_GET(self) -> None:
        if "channels" in self.path:
            self._json({"items": [{"snippet": {"title": "TestChannel"}}]})
        elif "playlistItems" in self.path:
            self._json({"items": list(_PLAYLIST_ITEMS)})
        elif "playlists" in self.path:
            self._json({"items": [dict(item) for item in self.playlists]})
        elif "videos" in self.path:
            self._json({"items": [dict(_VIDEO)]})
        else:
            self._json({"items": []})


class _AmbiguousFixture(_Fixture):
    playlists: ClassVar[list[dict[str, object]]] = [
        dict(_PLAYLIST),
        dict(_SECOND_PLAYLIST),
    ]


@pytest.fixture
def server() -> Iterator[str]:
    """Serve the fixture on a loopback port for one test."""
    httpd = HTTPServer(("127.0.0.1", 0), _Fixture)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def ambiguous_server() -> Iterator[str]:
    """Serve two playlists sharing the same title prefix."""
    httpd = HTTPServer(("127.0.0.1", 0), _AmbiguousFixture)
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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("  dQw4w9WgXcQ  ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PLabc123",
            "dQw4w9WgXcQ",
        ),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?si=sharetoken", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch", None),
        ("https://www.youtube.com/watch?v=short", None),
        ("https://vimeo.com/dQw4w9WgXcQ", None),
        ("not a video at all", None),
        ("dQw4w9WgXc", None),
        ("", None),
    ],
)
def test_normalize_video_id(yt_cli: _YtCli, raw: str, expected: str | None) -> None:
    assert yt_cli.normalize_video_id(raw) == expected


def test_playlists_items_returns_fixture_entries(server: str) -> None:
    proc = run_cli("playlists", "items", "Testlist", env=api_env(server))
    assert proc.returncode == 0
    raw = _json_loads(proc.stdout)
    assert _is_mapping(raw)
    assert raw["ok"] is True
    items = raw["items"]
    assert _is_object_list(items)
    assert len(items) == 2
    first = items[0]
    assert _is_mapping(first)
    assert first["position"] == 0
    assert first["id"] == "vid00000001"
    assert first["title"] == "First video"
    playlist = raw["playlist"]
    assert _is_mapping(playlist)
    assert playlist["id"] == "pl-1"


def test_playlists_items_resolves_title_prefix(server: str) -> None:
    proc = run_cli("playlists", "items", "Test", env=api_env(server))
    raw = _json_loads(proc.stdout)
    assert _is_mapping(raw)
    assert raw["ok"] is True


def test_playlists_exact_title_wins_over_longer_prefix_match(
    ambiguous_server: str,
) -> None:
    proc = run_cli("playlists", "items", "Testlist", env=api_env(ambiguous_server))
    raw = _json_loads(proc.stdout)
    assert _is_mapping(raw)
    assert raw["ok"] is True
    playlist = raw["playlist"]
    assert _is_mapping(playlist)
    assert playlist["id"] == "pl-1"


def test_playlists_add_ambiguous_title_prefix_fails_closed(
    ambiguous_server: str,
) -> None:
    proc = run_cli(
        "playlists",
        "add",
        "Test",
        "vid00000009",
        env=api_env(ambiguous_server),
    )
    assert proc.returncode == 1
    assert not proc.stderr
    raw = _json_loads(proc.stdout)
    assert _is_mapping(raw)
    assert raw["ok"] is False
    error = raw["error"]
    assert _is_mapping(error)
    assert error["code"] == "AMBIGUOUS_PLAYLIST"
    details = error["details"]
    assert _is_mapping(details)
    matches = details["matches"]
    assert _is_object_list(matches)
    assert len(matches) == 2


def test_playlists_apply_malformed_manifest_is_structured_error(
    tmp_path: Path, server: str
) -> None:
    manifest = tmp_path / "bad.tsv"
    _ = manifest.write_text(
        "Testlist\tvid00000001\nmissing-video-column\n", encoding="utf-8"
    )
    proc = run_cli("playlists", "apply", str(manifest), env=api_env(server))
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    raw = _json_loads(proc.stdout)
    assert _is_mapping(raw)
    assert raw["ok"] is False
    error = raw["error"]
    assert _is_mapping(error)
    assert error["code"] == "BAD_MANIFEST"
    details = error["details"]
    assert _is_mapping(details)
    assert details["line"] == 2


def test_playlists_add_skips_present_videos(server: str) -> None:
    proc = run_cli(
        "playlists",
        "add",
        "Testlist",
        "vid00000001",
        "https://youtu.be/vid00000009",
        "https://www.youtube.com/shorts/vid00000002",
        env=api_env(server),
    )
    assert proc.returncode == 0
    raw = _json_loads(proc.stdout)
    assert _is_mapping(raw)
    assert raw["ok"] is True
    assert raw["added"] == ["vid00000009"]
    assert raw["skipped"] == ["vid00000001", "vid00000002"]


def test_playlists_remove_maps_video_to_item(server: str) -> None:
    proc = run_cli(
        "playlists",
        "remove",
        "Testlist",
        "vid00000001",
        "vid00000009",
        env=api_env(server),
    )
    assert proc.returncode == 0
    raw = _json_loads(proc.stdout)
    assert _is_mapping(raw)
    assert raw["ok"] is True
    assert raw["removed"] == ["vid00000001"]
    assert raw["not_found"] == ["vid00000009"]


def test_videos_info_projects_fields(server: str) -> None:
    proc = run_cli(
        "videos",
        "info",
        "vid00000001",
        "https://www.youtube.com/watch?v=vid00000002",
        env=api_env(server),
    )
    assert proc.returncode == 0
    raw = _json_loads(proc.stdout)
    assert _is_mapping(raw)
    assert raw["ok"] is True
    videos = raw["videos"]
    assert _is_object_list(videos)
    first = videos[0]
    assert _is_mapping(first)
    assert first["id"] == "vid00000001"
    assert first["title"] == "First video"
    assert first["channel"] == "TestChannel"
    assert first["duration"] == "PT1M2S"
    assert first["publishedAt"] == "2024-01-02T03:04:05Z"


def test_invalid_video_input_fails_before_network(server: str) -> None:
    proc = run_cli("videos", "info", "not a video at all", env=api_env(server))
    assert proc.returncode == 1
    raw = _json_loads(proc.stdout)
    assert _is_mapping(raw)
    assert raw["ok"] is False
    error = raw["error"]
    assert _is_mapping(error)
    assert error["code"] == "INVALID_VIDEO"


def test_search_returns_results(server: str) -> None:
    proc = run_cli("search", "test query", "--limit", "3", env=api_env(server))
    assert proc.returncode == 0
    raw = _json_loads(proc.stdout)
    assert _is_mapping(raw)
    assert raw["ok"] is True
    results = raw["results"]
    assert _is_object_list(results)
