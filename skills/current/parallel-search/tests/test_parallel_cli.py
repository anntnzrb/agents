"""Contract tests for skills/current/parallel-search/scripts/cli.py.

These tests do not hit live APIs. They load the CLI via importlib, monkeypatch
``urllib.request.urlopen`` to capture calls and return canned bodies, and then
drive ``main()`` with crafted argv to assert the documented contract:

* default parameters for search and extract,
* compact projection of search results,
* raw passthrough is byte-for-byte,
* invalid arguments abort before any network call,
* HTTP errors are surfaced as a one-line compact JSON envelope on stderr,
* missing API key is reported cleanly with a non-zero exit code.
"""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
import urllib.request
from http.client import HTTPMessage
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, Self, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import ModuleType

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"


class _ParallelCli(Protocol):
    def main(self, argv: list[str]) -> int: ...


class FakeResponse:
    """Minimal urllib response stand-in (context-manager + .read())."""

    def __init__(
        self,
        body: bytes = b"",
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._body: bytes = body
        self.status: int = status
        self.headers: dict[str, str] = headers or {}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class CallRecorder:
    """Fake urlopen that records every call and returns/raises a fixed value."""

    def __init__(
        self,
        return_value: FakeResponse | None = None,
        side_effect: BaseException | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.return_value: FakeResponse | None = return_value
        self.side_effect: BaseException | None = side_effect

    def __call__(
        self, req: urllib.request.Request, *args: object, **kwargs: object
    ) -> FakeResponse | None:
        url = req.full_url
        method = req.get_method()
        headers = dict(req.header_items())
        data = req.data
        self.calls.append(
            {
                "url": url,
                "method": method,
                "headers": headers,
                "data": data,
                "args": args,
                "kwargs": kwargs,
            },
        )
        if self.side_effect is not None:
            raise self.side_effect
        return self.return_value


def _load_cli(module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec is not None, f"cannot load {SCRIPT_PATH}"
    assert spec.loader is not None, f"cannot load {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def parallel_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _ParallelCli:
    """Load the CLI with env loading neutralized so tests are deterministic."""
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    monkeypatch.setenv("PARALLEL_ENV_FILE", str(tmp_path / "no_such_file.env"))
    monkeypatch.delenv("SKILLS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    cli = _load_cli("parallel_cli_under_test")
    return cast("_ParallelCli", cast("object", cli))


def _stub_response(payload: object) -> FakeResponse:
    return FakeResponse(body=json.dumps(payload).encode())


def _err_field(envelope: Mapping[str, object], name: str) -> object:
    error = envelope.get("error")
    if isinstance(error, dict) and name in error:
        return cast("object", error[name])
    return envelope.get(f"error.{name}")


def test_search_sends_post_request_and_compacts(
    parallel_cli: _ParallelCli,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PARALLEL_API_KEY", "TEST_KEY")
    payload = {
        "results": [
            {
                "title": "Parallel AI",
                "url": "https://parallel.ai",
                "publish_date": "2026-01-01",
                "excerpts": ["Search engine for AI agents."],
                "ignored_noise": 12345,
            },
        ],
    }
    recorder = CallRecorder(return_value=_stub_response(payload))
    monkeypatch.setattr(urllib.request, "urlopen", recorder)

    rc = parallel_cli.main(["search", "parallel search", "mode=turbo", "max_results=3"])
    captured = capsys.readouterr()

    assert rc == 0, f"unexpected stderr: {captured.err!r}"
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["url"] == "https://api.parallel.ai/v1/search"
    assert call["method"] == "POST"
    assert call["data"] is not None
    req_body = json.loads(cast("bytes", call["data"]).decode("utf-8"))
    assert req_body["search_queries"] == ["parallel search"]
    assert req_body["mode"] == "turbo"
    assert req_body["advanced_settings"]["max_results"] == 3

    parsed = cast("dict[str, object]", json.loads(captured.out))
    assert parsed["type"] == "search"
    assert parsed["query"] == "parallel search"
    results = cast("list[dict[str, object]]", parsed["results"])
    assert len(results) == 1
    assert results[0]["title"] == "Parallel AI"
    assert results[0]["url"] == "https://parallel.ai"
    assert "ignored_noise" not in results[0]


def test_extract_sends_post_request(
    parallel_cli: _ParallelCli,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PARALLEL_API_KEY", "TEST_KEY")
    payload = {
        "results": [
            {
                "url": "https://example.com",
                "title": "Example Domain",
                "full_content": "# Example\nContent here",
                "excerpts": ["Content here"],
            },
        ],
    }
    recorder = CallRecorder(return_value=_stub_response(payload))
    monkeypatch.setattr(urllib.request, "urlopen", recorder)

    rc = parallel_cli.main(["extract", "https://example.com", "full_content=1"])
    captured = capsys.readouterr()

    assert rc == 0, f"unexpected stderr: {captured.err!r}"
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["url"] == "https://api.parallel.ai/v1/extract"
    req_body = json.loads(cast("bytes", call["data"]).decode("utf-8"))
    assert req_body["urls"] == ["https://example.com"]
    assert (
        req_body["advanced_settings"]["full_content"]["max_chars_per_result"] == 50000
    )

    parsed = cast("dict[str, object]", json.loads(captured.out))
    assert parsed["type"] == "extract"
    results = cast("list[dict[str, object]]", parsed["results"])
    assert len(results) == 1
    assert results[0]["full_content"] == "# Example\nContent here"


def test_task_create_sends_processor_and_input(
    parallel_cli: _ParallelCli,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PARALLEL_API_KEY", "TEST_KEY")
    payload = {"run_id": "trun_123", "status": "queued"}
    recorder = CallRecorder(return_value=_stub_response(payload))
    monkeypatch.setattr(urllib.request, "urlopen", recorder)

    rc = parallel_cli.main(["task-create", "Research AI agents", "processor=pro"])
    captured = capsys.readouterr()

    assert rc == 0, f"unexpected stderr: {captured.err!r}"
    call = recorder.calls[0]
    assert call["url"] == "https://api.parallel.ai/v1/tasks/runs"
    req_body = json.loads(cast("bytes", call["data"]).decode("utf-8"))
    assert req_body["input"] == "Research AI agents"
    assert req_body["processor"] == "pro"


def test_http_html_error_emits_compact_json(
    parallel_cli: _ParallelCli,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PARALLEL_API_KEY", "TEST_KEY")
    html_body = (
        b"<!DOCTYPE html><html><head><title>401 Unauthorized</title></head>"
        b"<body><h1>Invalid API Key</h1></body></html>"
    )
    response_headers = HTTPMessage()
    response_headers["Content-Type"] = "text/html"
    http_err = urllib.error.HTTPError(
        url="https://api.parallel.ai/v1/search",
        code=401,
        msg="Unauthorized",
        hdrs=response_headers,
        fp=io.BytesIO(html_body),
    )
    recorder = CallRecorder(side_effect=http_err)
    monkeypatch.setattr(urllib.request, "urlopen", recorder)

    rc = parallel_cli.main(["search", "test"])
    captured = capsys.readouterr()

    assert rc != 0
    assert "<html" not in captured.err.lower()
    err_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert len(err_lines) == 1
    envelope = cast("dict[str, object]", json.loads(err_lines[0]))
    assert _err_field(envelope, "provider") == "parallel"
    assert _err_field(envelope, "status") == 401


def test_missing_api_key_returns_nonzero(
    parallel_cli: _ParallelCli,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = parallel_cli.main(["search", "test"])
    captured = capsys.readouterr()
    assert rc != 0
    assert "PARALLEL_API_KEY required" in captured.err
