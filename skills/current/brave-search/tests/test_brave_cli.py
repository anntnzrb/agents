"""Contract tests for skills/current/brave-search/scripts/cli.py.

These tests do not hit live APIs. They load the CLI via importlib, monkeypatch
``urllib.request.urlopen`` to capture calls and return canned bodies, and then
drive ``main()`` with crafted argv to assert the documented contract:

* default count and result_filter for endpoint commands,
* compact projection of web results (drops noisy fields),
* raw passthrough is byte-for-byte,
* invalid count aborts before any network call,
* HTTP errors are surfaced as a one-line compact JSON envelope on stderr,
* missing API key is reported cleanly with a non-zero exit code.
"""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"


class FakeResponse:
    """Minimal urllib response stand-in (context-manager + .read())."""

    def __init__(
        self,
        body: bytes = b"",
        status: int = 200,
        headers: dict | None = None,
    ):
        self._body = body
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body


class CallRecorder:
    """Fake urlopen that records every call and returns/raises a fixed value."""

    def __init__(
        self,
        return_value: FakeResponse | None = None,
        side_effect: BaseException | None = None,
    ):
        self.calls: list[dict] = []
        self.return_value = return_value
        self.side_effect = side_effect

    def __call__(self, req, *args, **kwargs):
        url = getattr(req, "full_url", str(req))
        method = req.get_method() if hasattr(req, "get_method") else None
        headers = (
            {k: v for k, v in req.header_items()}
            if hasattr(req, "header_items")
            else {}
        )
        self.calls.append(
            {
                "url": url,
                "method": method,
                "headers": headers,
                "args": args,
                "kwargs": kwargs,
            },
        )
        if self.side_effect is not None:
            raise self.side_effect
        return self.return_value


def _load_cli(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {SCRIPT_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def brave_cli(monkeypatch, tmp_path):
    """Load the CLI with env loading neutralized so tests are deterministic.

    The real skill ships a ``.env`` file with a real key. We must not depend
    on it, so we wipe the env, point ``BRAVE_SEARCH_ENV_FILE`` at a path
    that does not exist, change into an empty tmp dir, and finally stub
    ``load_env`` to a no-op. Tests that need a key set ``BRAVE_API_KEY``
    themselves.
    """
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.setenv("BRAVE_SEARCH_ENV_FILE", str(tmp_path / "no_such_file.env"))
    monkeypatch.delenv("SKILLS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    cli = _load_cli("brave_cli_under_test")
    monkeypatch.setattr(cli, "load_env", lambda: None)
    return cli


def _request_qs(call: dict) -> dict[str, list[str]]:
    return parse_qs(urlparse(call["url"]).query)


def _stub_response(payload: dict) -> FakeResponse:
    return FakeResponse(body=json.dumps(payload).encode())


def _err_field(envelope: dict, name: str):
    """Pull ``error.<name>`` from an envelope that uses either flat dotted keys
    (``{"error.provider": ...}``) or a nested ``{"error": {"provider": ...}}``.
    """
    if (
        "error" in envelope
        and isinstance(envelope["error"], dict)
        and name in envelope["error"]
    ):
        return envelope["error"][name]
    return envelope.get(f"error.{name}")


# ---------------------------------------------------------------------------
# 1. web applies default count=5 and result_filter=web
# ---------------------------------------------------------------------------


def test_web_applies_default_count_and_result_filter(brave_cli, monkeypatch, capsys):
    monkeypatch.setenv("BRAVE_API_KEY", "TEST_KEY")
    recorder = CallRecorder(return_value=_stub_response({"results": []}))
    monkeypatch.setattr(urllib.request, "urlopen", recorder)

    rc = brave_cli.main(["web", "rust async"])
    captured = capsys.readouterr()

    assert rc == 0, f"unexpected stderr: {captured.err!r}"
    assert len(recorder.calls) == 1, "expected exactly one urlopen call"

    qs = _request_qs(recorder.calls[0])
    # parse_qs returns list-of-one for any present value.
    assert qs.get("count") == ["5"], f"count default missing; got qs={qs}"
    assert qs.get("result_filter") == ["web"], (
        f"result_filter default missing; got qs={qs}"
    )
    assert qs.get("q") == ["rust async"], f"q missing or wrong; got qs={qs}"


# ---------------------------------------------------------------------------
# 2. compact web projection drops noisy fields, keeps title/url/description
# ---------------------------------------------------------------------------


def test_compact_web_projection_drops_noisy_fields(brave_cli, monkeypatch, capsys):
    monkeypatch.setenv("BRAVE_API_KEY", "TEST_KEY")
    payload = {
        "query": "rust",
        "results": [
            {
                "title": "Rust homepage",
                "url": "https://www.rust-lang.org/",
                "description": "A language empowering everyone to build reliable software.",
                # fields the contract says to drop
                "videos": {"title": "video spam"},
                "mixed": {"type": "mixed", "value": "noise"},
                "meta_url": {"scheme": "https", "netloc": "example.com"},
                "profile": {"name": "spammy"},
                "thumbnail": {"src": "https://cdn.example.com/thumb.jpg"},
            },
        ],
    }
    recorder = CallRecorder(return_value=_stub_response(payload))
    monkeypatch.setattr(urllib.request, "urlopen", recorder)

    rc = brave_cli.main(["web", "rust"])
    captured = capsys.readouterr()

    assert rc == 0, f"unexpected stderr: {captured.err!r}"
    assert captured.err == "", f"expected no stderr; got {captured.err!r}"

    parsed = json.loads(captured.out)
    # The CLI may emit a list, or a dict with a "results" key. Accept either,
    # but it must have a single first row.
    if isinstance(parsed, list):
        rows = parsed
    else:
        rows = parsed.get("results")
    assert rows, f"expected non-empty results in stdout; got: {captured.out!r}"
    first = rows[0]

    for kept in ("title", "url", "description"):
        assert kept in first, f"{kept!r} must be kept; got keys: {sorted(first)}"
    for dropped in ("videos", "mixed", "meta_url", "profile", "thumbnail"):
        assert dropped not in first, (
            f"{dropped!r} must be dropped; got keys: {sorted(first)}"
        )


# ---------------------------------------------------------------------------
# 3. raw streams upstream bytes unchanged
# ---------------------------------------------------------------------------


def test_raw_streams_upstream_bytes_unchanged(brave_cli, monkeypatch, capsys):
    monkeypatch.setenv("BRAVE_API_KEY", "TEST_KEY")
    body = '{"raw":true,"bytes":"unicode ✓ é 漢字"}'.encode()
    recorder = CallRecorder(return_value=FakeResponse(body=body))
    monkeypatch.setattr(urllib.request, "urlopen", recorder)

    rc = brave_cli.main(["raw", "/web/search"])
    captured = capsys.readouterr()

    assert rc == 0, f"unexpected stderr: {captured.err!r}"
    # Stdout must match byte-for-byte (after UTF-8 decode by capsys).
    assert captured.out.encode("utf-8") == body, (
        f"raw passthrough diverged; expected {body!r}, got {captured.out!r}"
    )
    # raw must not silently add the compact-projection defaults.
    qs = _request_qs(recorder.calls[0])
    assert "count" not in qs, f"raw must not inject count default; got qs={qs}"
    assert "result_filter" not in qs, f"raw must not inject result_filter; got qs={qs}"


# ---------------------------------------------------------------------------
# 4. count=50 returns rc=2 before any network call
# ---------------------------------------------------------------------------


def test_count_50_returns_rc2_no_network(brave_cli, monkeypatch, capsys):
    monkeypatch.setenv("BRAVE_API_KEY", "TEST_KEY")
    recorder = CallRecorder(return_value=_stub_response({"results": []}))
    monkeypatch.setattr(urllib.request, "urlopen", recorder)

    rc = brave_cli.main(["web", "rust", "count=50"])
    captured = capsys.readouterr()

    assert rc == 2, f"expected rc=2 for invalid count; got {rc}"
    assert recorder.calls == [], (
        f"urlopen must not be called when count is invalid; calls={recorder.calls}"
    )
    assert captured.err.strip(), "expected a concise stderr explanation"


# ---------------------------------------------------------------------------
# 5. HTTP HTML error emits compact JSON envelope, not raw HTML
# ---------------------------------------------------------------------------


def test_http_html_error_emits_compact_json(brave_cli, monkeypatch, capsys):
    monkeypatch.setenv("BRAVE_API_KEY", "TEST_KEY")
    html_body = (
        b"<!DOCTYPE html><html><head><title>502 Bad Gateway</title></head>"
        b"<body><h1>502 Bad Gateway</h1><p>cloudflare-nginx</p></body></html>"
    )
    http_err = urllib.error.HTTPError(
        url="https://api.search.brave.com/res/v1/web/search?q=rust",
        code=502,
        msg="Bad Gateway",
        hdrs={"Content-Type": "text/html"},
        fp=io.BytesIO(html_body),
    )
    recorder = CallRecorder(side_effect=http_err)
    monkeypatch.setattr(urllib.request, "urlopen", recorder)

    rc = brave_cli.main(["web", "rust"])
    captured = capsys.readouterr()

    assert rc != 0, "expected non-zero exit on HTTP error"
    # No raw HTML on stderr.
    assert "<html" not in captured.err.lower(), (
        f"raw HTML leaked to stderr: {captured.err!r}"
    )
    # Exactly one line, parseable as compact JSON.
    err_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert len(err_lines) == 1, f"expected single-line stderr; got: {err_lines!r}"
    envelope = json.loads(err_lines[0])
    assert _err_field(envelope, "provider") == "brave-search", (
        f"bad provider: {envelope}"
    )
    assert _err_field(envelope, "status") == 502, f"bad status: {envelope}"
    assert isinstance(_err_field(envelope, "message"), str) and _err_field(
        envelope,
        "message",
    ), f"bad message: {envelope}"
    assert _err_field(envelope, "body_bytes") == len(html_body), (
        f"bad body_bytes: {envelope}"
    )
    assert isinstance(_err_field(envelope, "body_preview"), str), (
        f"bad body_preview: {envelope}"
    )
    assert isinstance(_err_field(envelope, "body_truncated"), bool), (
        f"bad body_truncated: {envelope}"
    )


# ---------------------------------------------------------------------------
# 6. summarizer-key without an API key returns non-zero with a clear message
# ---------------------------------------------------------------------------


def test_summarizer_key_without_api_key_returns_nonzero(brave_cli, monkeypatch, capsys):
    # env is wiped by the fixture; load_env is stubbed to a no-op so the
    # real on-disk .env file cannot resurrect the key.
    sentinel = CallRecorder(return_value=_stub_response({"summarizer": {"key": "X"}}))
    monkeypatch.setattr(urllib.request, "urlopen", sentinel)

    rc = brave_cli.main(["summarizer-key", "anything"])
    captured = capsys.readouterr()

    assert rc != 0, f"expected non-zero rc; got {rc}"
    assert sentinel.calls == [], "urlopen must not run when the key is missing"
    err_lower = captured.err.lower()
    assert "key" in err_lower, f"stderr should mention the key: {captured.err!r}"
