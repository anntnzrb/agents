"""Contract tests for assets/skills/reddit/scripts/cli.py.

These tests do not hit live APIs. They load the CLI via importlib, monkeypatch
``urllib.request.urlopen`` to capture calls and return canned JSON, and then
drive ``main()`` with crafted argv to assert the documented contract:

* ``explain`` normalizes terms (trim/collapse/hyphen-to-space) and refuses empty input;
* ``post-url``, ``search``, and ``user-analysis`` validate their arguments and
  abort with rc=2 before any network call when given bad input;
* HTTP 403 block pages become a compact JSON error envelope on stderr with
  ``kind="network_security_block"``;
* ``browse`` returns a compact listing that keeps useful fields and drops
  noisy ones.
"""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
import urllib.request
from pathlib import Path

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
def reddit_cli(monkeypatch, tmp_path):
    """Load the CLI with env loading neutralized so tests are deterministic."""
    monkeypatch.delenv("REDDIT_USER_AGENT", raising=False)
    monkeypatch.delenv("REDDIT_BASE_URL", raising=False)
    monkeypatch.setenv("REDDIT_ENV_FILE", str(tmp_path / "no_such_file.env"))
    monkeypatch.delenv("SKILLS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    cli = _load_cli("reddit_cli_under_test")
    monkeypatch.setattr(cli, "load_env", lambda: None)
    return cli


def _no_network_urlopen(monkeypatch) -> CallRecorder:
    """Install a urlopen stub that should never be called for validation failures."""
    recorder = CallRecorder(return_value=FakeResponse(body=b"{}"))
    monkeypatch.setattr(urllib.request, "urlopen", recorder)
    return recorder


# ---------------------------------------------------------------------------
# 1. explain " cake-day " normalizes to "cake day"
# ---------------------------------------------------------------------------


def test_explain_normalizes_whitespace_and_hyphens(reddit_cli, capsys):
    rc = reddit_cli.main(["explain", " cake-day "])
    captured = capsys.readouterr()

    assert rc == 0, f"unexpected stderr: {captured.err!r}"
    parsed = json.loads(captured.out)
    assert parsed["term"] == "cake day", f"term not normalized; got {parsed!r}"
    # The definition should be the real one, not the "Unknown term" fallback.
    assert "anniversary" in parsed["definition"].lower(), (
        f"expected the cake-day definition; got {parsed!r}"
    )


# ---------------------------------------------------------------------------
# 2. explain with empty term returns rc=2, no traceback
# ---------------------------------------------------------------------------


def test_explain_empty_term_returns_rc2(reddit_cli, capsys, monkeypatch):
    recorder = _no_network_urlopen(monkeypatch)
    rc = reddit_cli.main(["explain", ""])
    captured = capsys.readouterr()

    assert rc == 2, f"expected rc=2 for empty term; got {rc}"
    assert "Traceback" not in captured.err, (
        f"empty term must not raise; got stderr: {captured.err!r}"
    )
    assert captured.err.strip(), "expected a concise stderr explanation"
    assert recorder.calls == [], "urlopen must not be called for empty term"


# ---------------------------------------------------------------------------
# 3. post-url not-a-url returns rc=2, no traceback, no network
# ---------------------------------------------------------------------------


def test_post_url_not_a_url_returns_rc2(reddit_cli, capsys, monkeypatch):
    recorder = _no_network_urlopen(monkeypatch)
    rc = reddit_cli.main(["post-url", "not-a-url"])
    captured = capsys.readouterr()

    assert rc == 2, f"expected rc=2 for non-URL input; got {rc}"
    assert "Traceback" not in captured.err, (
        f"bad URL must not raise; got stderr: {captured.err!r}"
    )
    assert captured.err.strip(), "expected a concise stderr explanation"
    assert recorder.calls == [], "urlopen must not be called for non-URL input"


# ---------------------------------------------------------------------------
# 4. search subreddits=not-json returns rc=2 without network
# ---------------------------------------------------------------------------


def test_search_invalid_subreddits_returns_rc2(reddit_cli, capsys, monkeypatch):
    recorder = _no_network_urlopen(monkeypatch)
    rc = reddit_cli.main(["search", "h1b", "subreddits=not-json"])
    captured = capsys.readouterr()

    assert rc == 2, f"expected rc=2 for malformed subreddits; got {rc}"
    assert "Traceback" not in captured.err, (
        f"malformed subreddits must not raise; got stderr: {captured.err!r}"
    )
    assert captured.err.strip(), "expected a concise stderr explanation"
    assert recorder.calls == [], "urlopen must not be called for malformed subreddits"


# ---------------------------------------------------------------------------
# 5. user-analysis time_range=invalid returns rc=2 without network
# ---------------------------------------------------------------------------


def test_user_analysis_invalid_time_range_returns_rc2(reddit_cli, capsys, monkeypatch):
    recorder = _no_network_urlopen(monkeypatch)
    rc = reddit_cli.main(["user-analysis", "spez", "time_range=invalid"])
    captured = capsys.readouterr()

    assert rc == 2, f"expected rc=2 for invalid time_range; got {rc}"
    assert "Traceback" not in captured.err, (
        f"invalid time_range must not raise; got stderr: {captured.err!r}"
    )
    assert captured.err.strip(), "expected a concise stderr explanation"
    assert recorder.calls == [], "urlopen must not be called for invalid time_range"


# ---------------------------------------------------------------------------
# 6. HTTP 403 block page emits compact JSON, not raw HTML
# ---------------------------------------------------------------------------


def test_http_403_block_emits_compact_json(reddit_cli, capsys, monkeypatch):
    html_body = (
        b"<!DOCTYPE html><html><head><title>Blocked</title></head>"
        b"<body><h1>Blocked by network security</h1>"
        b"<p>Please slow down and try again later.</p></body></html>"
    )
    http_err = urllib.error.HTTPError(
        url="https://www.reddit.com/r/all/hot.json?limit=10",
        code=403,
        msg="Forbidden",
        hdrs={"Content-Type": "text/html"},
        fp=io.BytesIO(html_body),
    )
    recorder = CallRecorder(side_effect=http_err)
    monkeypatch.setattr(urllib.request, "urlopen", recorder)

    rc = reddit_cli.main(["browse", "all"])
    captured = capsys.readouterr()

    assert rc != 0, "expected non-zero exit on HTTP 403"
    # No raw HTML on stderr.
    assert "<html" not in captured.err.lower(), (
        f"raw HTML leaked to stderr: {captured.err!r}"
    )
    err_lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert err_lines, "expected a non-empty stderr envelope"
    envelope = json.loads(err_lines[-1])
    err = envelope.get("error", envelope)
    assert err.get("kind") == "network_security_block", f"bad kind: {err}"
    assert err.get("provider") == "reddit", f"bad provider: {err}"
    assert err.get("status") == 403, f"bad status: {err}"
    assert err.get("body_bytes") == len(html_body), f"bad body_bytes: {err}"
    assert isinstance(err.get("body_preview"), str), f"bad body_preview: {err}"
    assert isinstance(err.get("body_truncated"), bool), f"bad body_truncated: {err}"


# ---------------------------------------------------------------------------
# 7. compact listing projection keeps useful post fields
# ---------------------------------------------------------------------------


def test_compact_listing_keeps_useful_fields(reddit_cli, capsys, monkeypatch):
    payload = {
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        # useful fields the contract says to keep
                        "id": "abc123",
                        "title": "Test post",
                        "subreddit": "python",
                        "author": "somebody",
                        "score": 42,
                        "num_comments": 7,
                        "url": "https://example.com/post",
                        "permalink": "/r/python/comments/abc123/test/",
                        "created_utc": 1_700_000_000.0,
                        "over_18": False,
                        "is_self": True,
                        # noisy fields the contract says to drop
                        "selftext": "lots of text " * 200,
                        "selftext_html": "<div>html version of selftext</div>",
                        "thumbnail": "self",
                        "thumbnail_height": 70,
                        "thumbnail_width": 70,
                        "preview": {"images": [{"source": {"url": "preview"}}]},
                        "media": {"reddit_video": {"fallback_url": "video"}},
                        "media_embed": {},
                        "secure_media": {},
                        "secure_media_embed": {},
                        "gallery_data": {"items": []},
                        "crosspost_parent_list": ["noise"],
                        "all_awardings": [{"name": "Silver"}],
                        "link_flair_richtext": [{"a": "/r/python", "e": "r/python"}],
                        "author_flair_text": "mod",
                        "treatment_tags": ["spam"],
                        "top_awarded_type": None,
                        "pwls": 0,
                        "link_flair_background_color": "#000000",
                        "link_flair_text_color": "dark",
                        "url_overridden_by_dest": "https://example.com/post",
                    },
                },
            ],
        },
    }
    recorder = CallRecorder(
        return_value=FakeResponse(body=json.dumps(payload).encode()),
    )
    monkeypatch.setattr(urllib.request, "urlopen", recorder)

    rc = reddit_cli.main(["browse", "python"])
    captured = capsys.readouterr()

    assert rc == 0, f"unexpected stderr: {captured.err!r}"
    parsed = json.loads(captured.out)
    if isinstance(parsed, list):
        rows = parsed
    else:
        # CLI may wrap in {"posts": [...]} / {"results": [...]} / {"data": {...}}.
        for key in ("posts", "results", "data", "children"):
            if key in parsed:
                inner = parsed[key]
                if isinstance(inner, list):
                    rows = inner
                    break
                if isinstance(inner, dict) and "children" in inner:
                    rows = inner["children"]
                    break
        else:
            pytest.fail(f"could not locate listing rows in stdout: {parsed!r}")
    assert rows, f"expected non-empty listing; got: {parsed!r}"
    first = rows[0]
    if "data" in first and isinstance(first["data"], dict):
        first = first["data"]

    for kept in ("id", "title", "subreddit", "url"):
        assert kept in first, f"{kept!r} must be kept; got keys: {sorted(first)}"
    for dropped in (
        "selftext_html",
        "preview",
        "media",
        "media_embed",
        "secure_media",
        "secure_media_embed",
        "gallery_data",
        "crosspost_parent_list",
        "all_awardings",
        "link_flair_richtext",
        "thumbnail_height",
        "thumbnail_width",
        "treatment_tags",
        "link_flair_background_color",
        "link_flair_text_color",
        "url_overridden_by_dest",
    ):
        assert dropped not in first, (
            f"{dropped!r} must be dropped; got keys: {sorted(first)}"
        )
