"""Deterministic wire-level tests for the x-research CLI.

The provider is replaced with a small ``urllib`` response fake.  No test in
this module contacts FxTwitter or any other network service.
"""
# ruff: noqa: ANN001, ANN201, ANN202, ANN401, ARG005, CPY001, D102, D103, D105, D107, D202, INP001, PLR0913, PLR0917, PLR2004, PT018, PYI034, PYI036, S101

from __future__ import annotations

import importlib
import importlib.util
import io
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"


class FakeResponse:
    """Minimal response object consumed by ``urllib`` provider code."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status
        self.code = status
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status


class WireFake:
    """Record request URL/method/timeout and return one fixed wire result."""

    def __init__(
        self,
        body: bytes = b"{}",
        status: int = 200,
        side_effect: BaseException | None = None,
    ) -> None:
        self.body = body
        self.status = status
        self.side_effect = side_effect
        self.calls: list[dict[str, Any]] = []

    def __call__(self, request: Any, *args: Any, **kwargs: Any) -> FakeResponse:
        self.calls.append(
            {
                "url": getattr(request, "full_url", str(request)),
                "method": request.get_method()
                if hasattr(request, "get_method")
                else None,
                "timeout": kwargs.get("timeout", args[0] if args else None),
            },
        )
        if self.side_effect is not None:
            raise self.side_effect
        return FakeResponse(self.body, self.status)


def _load_cli(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def x_cli(monkeypatch: pytest.MonkeyPatch):
    """Load the entrypoint and force a deterministic HTTPS test base URL."""

    monkeypatch.setenv("X_RESEARCH_BASE_URL", "https://wire.example.test")
    cli = _load_cli(f"x_research_cli_{id(monkeypatch)}")
    provider = importlib.import_module("x_research.provider")
    # The contract intentionally exposes a module-level urlopen alias so wire
    # tests can intercept exactly what the adapter sends.
    monkeypatch.setattr(provider, "urlopen", lambda *args, **kwargs: None)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: None)
    return cli, provider


def _install_wire(
    monkeypatch: pytest.MonkeyPatch, provider: Any, **kwargs: Any
) -> WireFake:
    wire = WireFake(**kwargs)
    monkeypatch.setattr(provider, "urlopen", wire)
    monkeypatch.setattr(urllib.request, "urlopen", wire)
    return wire


def _status(
    post_id: str = "123",
    *,
    handle: str = "OpenAI",
    text: str = "A public post",
    metrics: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": post_id,
        "url": f"https://x.com/{handle}/status/{post_id}",
        "text": text,
        "created_at": "2026-08-01T12:00:00.000Z",
        "author": {
            "id": "author-1",
            "screen_name": handle,
            "name": "OpenAI",
            "url": f"https://x.com/{handle}",
            "verified": True,
        },
        "lang": "en",
    }
    if metrics:
        result.update(
            {
                "replies": 2,
                "reposts": 3,
                "likes": 5,
                "quotes": 1,
                "bookmarks": 4,
                "views": 50,
            },
        )
    return result


def _page_payload(
    posts: list[dict[str, Any]],
    *,
    bottom: str | None = "bottom-token",
    include_profile: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": 200, "results": posts}
    if bottom is not None:
        payload["cursor"] = {"top": "top-token", "bottom": bottom}
    if include_profile:
        payload["profile"] = {
            "id": "author-1",
            "screen_name": "OpenAI",
            "name": "OpenAI",
            "url": "https://x.com/OpenAI",
            "verified": True,
        }
    return payload


def _envelope(raw: str, *, stream: str = "out") -> dict[str, Any]:
    assert raw.strip(), f"expected JSON on {stream}"
    return json.loads(raw)


def _query(url: str) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(
        urllib.parse.urlsplit(url).query,
        keep_blank_values=True,
    )


def test_invalid_inputs_do_not_call_network(x_cli, monkeypatch, capsys):
    cli, provider = x_cli
    wire = _install_wire(monkeypatch, provider)

    rc = cli.main(["user-posts", "OpenAI", "--count", "0"])

    captured = capsys.readouterr()
    assert rc == 2
    error = _envelope(captured.err, stream="err")
    assert error["ok"] is False
    assert error["schema_version"] == 1
    assert error["command"] == "user-posts"
    assert error["error"]["code"]
    assert wire.calls == []


def test_fetch_rejects_non_x_status_urls_without_network(x_cli, monkeypatch, capsys):
    cli, provider = x_cli
    wire = _install_wire(monkeypatch, provider)
    rejected = [
        "https://example.test/status/123",
        "http://x.com/user/status/123",
        "https://x.com/user/status/not-numeric",
        "https://x.com/user/post/123",
        "https://x.com/user/status/123/extra",
    ]

    for target in rejected:
        rc = cli.main(["fetch", target])
        captured = capsys.readouterr()
        assert rc == 2, target
        error = _envelope(captured.err, stream="err")
        assert error["ok"] is False
        assert error["command"] == "fetch"

    assert wire.calls == []


def test_fetch_builds_exact_status_url_and_success_envelope(x_cli, monkeypatch, capsys):
    cli, provider = x_cli
    payload = {"code": 200, "message": "OK", "status": _status(metrics=True)}
    wire = _install_wire(monkeypatch, provider, body=json.dumps(payload).encode())

    rc = cli.main(["fetch", "https://x.com/OpenAI/status/123", "--lang", "en"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    envelope = _envelope(captured.out)
    assert captured.out.strip() == json.dumps(
        envelope,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert envelope["ok"] is True
    assert envelope["schema_version"] == 1
    assert envelope["command"] == "fetch"
    data = envelope["data"]
    assert data["requested_url"] == "https://x.com/OpenAI/status/123"
    assert data["provider"] == "fxtwitter"
    assert data["official"] is False
    assert data["auth_mode"] == "none"
    assert data["source_url"] == "https://wire.example.test/2/status/123?lang=en"
    assert data["endpoint"] == "/2/status/123"
    assert data["provider_status"] == 200
    assert data["post"]["id"] == "123"
    assert data["post"]["metrics"] == {
        "replies": 2,
        "reposts": 3,
        "likes": 5,
        "quotes": 1,
        "bookmarks": 4,
        "views": 50,
    }
    assert len(wire.calls) == 1
    assert wire.calls[0]["url"] == "https://wire.example.test/2/status/123?lang=en"
    assert wire.calls[0]["method"] == "GET"
    assert _query(wire.calls[0]["url"]) == {"lang": ["en"]}
    assert wire.calls[0]["timeout"] is not None


def test_missing_optional_post_values_are_omitted(x_cli, monkeypatch, capsys):
    cli, provider = x_cli
    raw = _status()
    raw.pop("lang")
    payload = {"code": 200, "status": raw}
    _install_wire(monkeypatch, provider, body=json.dumps(payload).encode())

    rc = cli.main(["fetch", "123"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    data = _envelope(captured.out)["data"]
    assert data["requested_id"] == "123"
    post = data["post"]
    assert set(post) == {"id", "url", "text", "created_at", "author"}
    assert set(post["author"]) == {"id", "handle", "name", "url", "verified"}
    for optional in ("metrics", "lang", "media", "quote_id", "reply_to_id"):
        assert optional not in post


def test_user_posts_exact_endpoint_query_and_cursor_completeness(
    x_cli,
    monkeypatch,
    capsys,
):
    cli, provider = x_cli
    payload = _page_payload([_status(metrics=True)])
    wire = _install_wire(monkeypatch, provider, body=json.dumps(payload).encode())

    rc = cli.main(
        [
            "user-posts",
            "OpenAI",
            "--count",
            "1",
            "--cursor",
            "next page",
            "--include-replies",
        ],
    )

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    data = _envelope(captured.out)["data"]
    assert data["handle"] == "OpenAI"
    assert data["profile"]["handle"] == "OpenAI"
    assert data["posts"][0]["id"] == "123"
    assert data["requested_count"] == 1
    assert data["returned_count"] == 1
    assert data["cursor"] == "bottom-token"
    assert data["has_more"] is True
    assert data["complete"] is False
    assert data["complete_reason"] == "bounded_page"
    assert len(wire.calls) == 1
    request_url = wire.calls[0]["url"]
    assert urllib.parse.urlsplit(request_url).path == "/2/profile/OpenAI/statuses"
    assert _query(request_url) == {
        "count": ["1"],
        "cursor": ["next page"],
        "groupthreads": ["0"],
        "with_replies": ["1"],
    }


def test_user_posts_default_excludes_replies(x_cli, monkeypatch, capsys):
    cli, provider = x_cli
    payload = _page_payload([_status()], bottom=None)
    payload["cursor"] = None
    wire = _install_wire(monkeypatch, provider, body=json.dumps(payload).encode())

    rc = cli.main(["user-posts", "OpenAI", "--count", "3"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    data = _envelope(captured.out)["data"]
    assert data["complete"] is True
    assert data["complete_reason"] == "provider_exhausted"
    assert "cursor" not in data
    assert "has_more" not in data
    request_url = wire.calls[0]["url"]
    assert _query(request_url) == {
        "count": ["3"],
        "groupthreads": ["0"],
    }


def test_page_output_is_capped_to_requested_count(x_cli, monkeypatch, capsys):
    cli, provider = x_cli
    payload = _page_payload(
        [_status("123"), _status("124"), _status("125")],
    )
    wire = _install_wire(monkeypatch, provider, body=json.dumps(payload).encode())

    rc = cli.main(["user-posts", "OpenAI", "--count", "2"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    data = _envelope(captured.out)["data"]
    assert [post["id"] for post in data["posts"]] == ["123", "124"]
    assert data["requested_count"] == 2
    assert data["returned_count"] == 2
    assert data["complete"] is False
    assert data["complete_reason"] == "bounded_page"
    assert len(wire.calls) == 1


def test_search_collapses_whitespace_preserves_query_and_feed(
    x_cli, monkeypatch, capsys
):
    cli, provider = x_cli
    payload = _page_payload([_status(text="policy signal")], include_profile=False)
    wire = _install_wire(monkeypatch, provider, body=json.dumps(payload).encode())

    rc = cli.main(
        [
            "search",
            "  from:OpenAI   since:2026-08-01  policy  ",
            "--count",
            "2",
            "--feed",
            "media",
            "--cursor",
            "cursor/one",
        ],
    )

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    data = _envelope(captured.out)["data"]
    assert data["query"] == "from:OpenAI since:2026-08-01 policy"
    assert data["feed"] == "media"
    assert data["posts"][0]["text"] == "policy signal"
    request_url = wire.calls[0]["url"]
    assert urllib.parse.urlsplit(request_url).path == "/2/search"
    assert _query(request_url) == {
        "q": ["from:OpenAI since:2026-08-01 policy"],
        "count": ["2"],
        "feed": ["media"],
        "cursor": ["cursor/one"],
    }


def test_conversation_accepts_root_without_code_and_preserves_cursor(
    x_cli,
    monkeypatch,
    capsys,
):
    cli, provider = x_cli
    target = _status("123", text="root")
    thread_post = _status("124", text="thread")
    reply = _status("125", text="reply")
    payload = {
        "status": target,
        "thread": [thread_post],
        "replies": [reply],
        "cursor": {"top": "top", "bottom": "conversation-next"},
    }
    wire = _install_wire(monkeypatch, provider, body=json.dumps(payload).encode())

    rc = cli.main(
        [
            "conversation",
            "123",
            "--ranking-mode",
            "recency",
            "--cursor",
            "conversation previous",
        ],
    )

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    data = _envelope(captured.out)["data"]
    assert data["requested_id"] == "123"
    assert data["ranking_mode"] == "recency"
    assert data["target"]["id"] == "123"
    assert [post["id"] for post in data["thread"]] == ["124"]
    assert [post["id"] for post in data["replies"]] == ["125"]
    assert data["returned_count"] == 3
    assert data["cursor"] == "conversation-next"
    assert data["has_more"] is True
    assert data["complete"] is False
    assert data["complete_reason"] == "bounded_page"
    request_url = wire.calls[0]["url"]
    assert urllib.parse.urlsplit(request_url).path == "/2/conversation/123"
    assert _query(request_url) == {
        "ranking_mode": ["recency"],
        "cursor": ["conversation previous"],
    }


def test_http_failure_is_compact_json_and_exit_one(x_cli, monkeypatch, capsys):
    cli, provider = x_cli
    http_error = urllib.error.HTTPError(
        "https://wire.example.test/2/status/123",
        502,
        "Bad Gateway",
        {"Content-Type": "text/html"},
        io.BytesIO(b"<html>provider failure</html>"),
    )
    wire = _install_wire(monkeypatch, provider, side_effect=http_error)

    rc = cli.main(["fetch", "123"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "<html>" not in captured.err
    error = _envelope(captured.err, stream="err")
    assert error["ok"] is False
    assert error["command"] == "fetch"
    assert error["error"]["code"] == "http_error"
    assert error["error"]["details"]["http_status"] == 502
    assert len(wire.calls) == 1


def test_non_json_provider_body_is_compact_json_error(x_cli, monkeypatch, capsys):
    cli, provider = x_cli
    wire = _install_wire(monkeypatch, provider, body=b"not-json")

    rc = cli.main(["fetch", "123"])

    captured = capsys.readouterr()
    assert rc == 1
    error = _envelope(captured.err, stream="err")
    assert error["ok"] is False
    assert error["error"]["code"] == "invalid_json"
    assert len(wire.calls) == 1


def test_malformed_status_shape_preserves_provider_status(x_cli, monkeypatch, capsys):
    cli, provider = x_cli
    payload = {"code": 200, "status": {"id": "123"}}
    wire = _install_wire(monkeypatch, provider, body=json.dumps(payload).encode())

    rc = cli.main(["fetch", "123"])

    captured = capsys.readouterr()
    assert rc == 1
    error = _envelope(captured.err, stream="err")
    assert error["ok"] is False
    assert error["error"]["code"] == "missing_field"
    assert error["error"]["details"]["provider_status"] == 200
    assert (
        error["error"]["details"]["source_url"]
        == "https://wire.example.test/2/status/123"
    )
    assert len(wire.calls) == 1


def _rich_status(
    post_id: str = "123",
    *,
    text: str = "A complete citation-safe post with a long body.",
) -> dict[str, Any]:
    """Build a normalized post fixture with optional fields to project."""

    result = _status(post_id, text=text, metrics=True)
    result.update(
        {
            "media": {
                "all": [
                    {
                        "type": "photo",
                        "url": "https://cdn.example.test/photo.jpg",
                    },
                ],
            },
            "quote_id": "quoted-1",
            "reply_to_id": "parent-1",
            "provider_unknown": "omit from summary",
        },
    )
    return result


def _assert_summary_post(
    post: dict[str, Any],
    *,
    post_id: str,
    text: str,
) -> None:
    assert post == {
        "id": post_id,
        "url": f"https://x.com/OpenAI/status/{post_id}",
        "text": text,
        "created_at": "2026-08-01T12:00:00.000Z",
        "author": {
            "id": "author-1",
            "handle": "OpenAI",
            "name": "OpenAI",
            "url": "https://x.com/OpenAI",
            "verified": True,
        },
        "lang": "en",
        "quote_id": "quoted-1",
        "reply_to_id": "parent-1",
    }


def _assert_summary_provenance(
    data: dict[str, Any],
    *,
    endpoint: str,
) -> None:
    assert data["provider"] == "fxtwitter"
    assert data["official"] is False
    assert data["auth_mode"] == "none"
    assert data["source_url"].startswith(f"https://wire.example.test{endpoint}")
    assert data["endpoint"] == endpoint
    assert isinstance(data["fetched_at"], str)
    assert data["fetched_at"]
    assert data["provider_status"] == 200


def test_fetch_summary_projects_post_and_preserves_request_provenance(
    x_cli,
    monkeypatch,
    capsys,
):
    cli, provider = x_cli
    text = "The complete text must survive projection, including citation details."
    payload = {"code": 200, "status": _rich_status(text=text)}
    wire = _install_wire(monkeypatch, provider, body=json.dumps(payload).encode())

    rc = cli.main(
        ["fetch", "https://x.com/OpenAI/status/123", "--summary"],
    )

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    envelope = _envelope(captured.out)
    data = envelope["data"]
    assert set(data) == {
        "requested_url",
        "post",
        "provider",
        "official",
        "auth_mode",
        "source_url",
        "endpoint",
        "fetched_at",
        "provider_status",
    }
    assert data["requested_url"] == "https://x.com/OpenAI/status/123"
    _assert_summary_post(data["post"], post_id="123", text=text)
    _assert_summary_provenance(data, endpoint="/2/status/123")
    assert len(wire.calls) == 1


def test_user_posts_summary_projects_posts_and_profile_with_page_metadata(
    x_cli,
    monkeypatch,
    capsys,
):
    cli, provider = x_cli
    text = "Full user timeline text remains available for citation."
    payload = _page_payload(
        [_rich_status(text=text)],
        bottom="next-user-page",
    )
    payload["profile"]["description"] = "profile field omitted by identity projection"
    wire = _install_wire(monkeypatch, provider, body=json.dumps(payload).encode())

    rc = cli.main(
        [
            "user-posts",
            "OpenAI",
            "--count",
            "1",
            "--cursor",
            "input-cursor",
            "--include-replies",
            "--summary",
        ],
    )

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    data = _envelope(captured.out)["data"]
    assert set(data) == {
        "posts",
        "requested_count",
        "returned_count",
        "profile",
        "cursor",
        "has_more",
        "complete",
        "complete_reason",
        "handle",
        "provider",
        "official",
        "auth_mode",
        "source_url",
        "endpoint",
        "fetched_at",
        "provider_status",
    }
    assert data["handle"] == "OpenAI"
    assert data["requested_count"] == 1
    assert data["returned_count"] == 1
    assert data["cursor"] == "next-user-page"
    assert data["has_more"] is True
    assert data["complete"] is False
    assert data["complete_reason"] == "bounded_page"
    _assert_summary_post(data["posts"][0], post_id="123", text=text)
    assert data["profile"] == {
        "id": "author-1",
        "handle": "OpenAI",
        "name": "OpenAI",
        "url": "https://x.com/OpenAI",
        "verified": True,
    }
    _assert_summary_provenance(
        data,
        endpoint="/2/profile/OpenAI/statuses",
    )
    assert len(wire.calls) == 1


def test_search_summary_projects_posts_and_preserves_query_page_provenance(
    x_cli,
    monkeypatch,
    capsys,
):
    cli, provider = x_cli
    text = "Search result text is retained exactly for evidence."
    payload = _page_payload(
        [_rich_status(text=text)],
        bottom="next-search-page",
        include_profile=False,
    )
    wire = _install_wire(monkeypatch, provider, body=json.dumps(payload).encode())

    rc = cli.main(
        [
            "search",
            "  OpenAI   release  ",
            "--count",
            "2",
            "--feed",
            "top",
            "--cursor",
            "search-cursor",
            "--summary",
        ],
    )

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    data = _envelope(captured.out)["data"]
    assert set(data) == {
        "posts",
        "requested_count",
        "returned_count",
        "cursor",
        "has_more",
        "complete",
        "complete_reason",
        "query",
        "feed",
        "provider",
        "official",
        "auth_mode",
        "source_url",
        "endpoint",
        "fetched_at",
        "provider_status",
    }
    assert data["query"] == "OpenAI release"
    assert data["feed"] == "top"
    assert data["requested_count"] == 2
    assert data["returned_count"] == 1
    assert data["cursor"] == "next-search-page"
    assert data["has_more"] is True
    assert data["complete"] is False
    assert data["complete_reason"] == "bounded_page"
    _assert_summary_post(data["posts"][0], post_id="123", text=text)
    _assert_summary_provenance(data, endpoint="/2/search")
    assert len(wire.calls) == 1


def test_conversation_summary_projects_every_post_bearing_value(
    x_cli,
    monkeypatch,
    capsys,
):
    cli, provider = x_cli
    target_text = "Conversation root text retained in full."
    thread_text = "Conversation thread text retained in full."
    reply_text = "Conversation reply text retained in full."
    payload = {
        "code": 200,
        "status": _rich_status(text=target_text),
        "thread": [_rich_status("124", text=thread_text)],
        "replies": [_rich_status("125", text=reply_text)],
        "cursor": {"top": "ignored-top", "bottom": "next-conversation-page"},
    }
    wire = _install_wire(monkeypatch, provider, body=json.dumps(payload).encode())

    rc = cli.main(
        [
            "conversation",
            "123",
            "--ranking-mode",
            "recency",
            "--cursor",
            "conversation-cursor",
            "--summary",
        ],
    )

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    data = _envelope(captured.out)["data"]
    assert set(data) == {
        "target",
        "thread",
        "replies",
        "cursor",
        "has_more",
        "complete",
        "complete_reason",
        "requested_id",
        "ranking_mode",
        "returned_count",
        "provider",
        "official",
        "auth_mode",
        "source_url",
        "endpoint",
        "fetched_at",
        "provider_status",
    }
    assert data["requested_id"] == "123"
    assert data["ranking_mode"] == "recency"
    assert data["returned_count"] == 3
    assert data["cursor"] == "next-conversation-page"
    assert data["has_more"] is True
    assert data["complete"] is False
    assert data["complete_reason"] == "bounded_page"
    _assert_summary_post(data["target"], post_id="123", text=target_text)
    _assert_summary_post(data["thread"][0], post_id="124", text=thread_text)
    _assert_summary_post(data["replies"][0], post_id="125", text=reply_text)
    _assert_summary_provenance(data, endpoint="/2/conversation/123")
    assert len(wire.calls) == 1


@pytest.mark.parametrize("presentation_flag", ["--summary", "--pretty"])
@pytest.mark.parametrize(
    ("base_args", "payload"),
    [
        (
            ["fetch", "123"],
            {"code": 200, "status": _rich_status()},
        ),
        (
            ["user-posts", "OpenAI", "--count", "2", "--cursor", "cursor"],
            _page_payload([_rich_status()], bottom="next-user"),
        ),
        (
            ["search", "OpenAI release", "--count", "2", "--feed", "latest"],
            _page_payload(
                [_rich_status()],
                bottom="next-search",
                include_profile=False,
            ),
        ),
        (
            ["conversation", "123", "--ranking-mode", "likes", "--cursor", "cursor"],
            {
                "code": 200,
                "status": _rich_status(),
                "thread": [],
                "replies": [],
                "cursor": {"bottom": "next-conversation"},
            },
        ),
    ],
    ids=("fetch", "user-posts", "search", "conversation"),
)
def test_presentation_flags_do_not_change_wire_request(
    x_cli,
    monkeypatch,
    capsys,
    presentation_flag,
    base_args,
    payload,
):
    cli, provider = x_cli
    wire = _install_wire(monkeypatch, provider, body=json.dumps(payload).encode())

    rc = cli.main(base_args)
    first = capsys.readouterr()
    assert rc == 0, first.err
    assert first.out
    assert first.err == ""
    assert len(wire.calls) == 1
    baseline_request = wire.calls[0]

    wire.calls.clear()
    rc = cli.main([*base_args, presentation_flag])
    flagged = capsys.readouterr()
    assert rc == 0, flagged.err
    assert flagged.out
    assert flagged.err == ""
    assert len(wire.calls) == 1
    assert wire.calls[0]["url"] == baseline_request["url"]
    assert wire.calls[0]["method"] == baseline_request["method"]


def test_pretty_fetch_output_is_valid_two_space_json(
    x_cli,
    monkeypatch,
    capsys,
):
    cli, provider = x_cli
    payload = {"code": 200, "status": _rich_status()}
    wire = _install_wire(monkeypatch, provider, body=json.dumps(payload).encode())

    rc = cli.main(["fetch", "123", "--pretty"])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert captured.err == ""
    envelope = _envelope(captured.out)
    assert captured.out == (
        json.dumps(
            envelope,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    assert captured.out.startswith('{\n  "ok": true,\n')
    assert captured.out.endswith("}\n")
    assert len(wire.calls) == 1


def test_summary_pretty_provider_error_stays_on_stderr_with_exit_one(
    x_cli,
    monkeypatch,
    capsys,
):
    cli, provider = x_cli
    http_error = urllib.error.HTTPError(
        "https://wire.example.test/2/status/123",
        503,
        "Service Unavailable",
        {"Content-Type": "text/html"},
        io.BytesIO(b"<html>provider failure</html>"),
    )
    wire = _install_wire(monkeypatch, provider, side_effect=http_error)

    rc = cli.main(["fetch", "123", "--summary", "--pretty"])

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    error = _envelope(captured.err, stream="err")
    assert error["ok"] is False
    assert error["command"] == "fetch"
    assert error["error"]["code"] == "http_error"
    assert error["error"]["details"]["http_status"] == 503
    assert captured.err == (
        json.dumps(
            error,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    assert len(wire.calls) == 1


def test_usage_error_detects_pretty_from_raw_argv(
    x_cli,
    monkeypatch,
    capsys,
):
    cli, provider = x_cli
    wire = _install_wire(monkeypatch, provider)

    rc = cli.main(
        ["fetch", "123", "--summary", "--pretty", "--unknown-option"],
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    error = _envelope(captured.err, stream="err")
    assert error["ok"] is False
    assert error["command"] == "fetch"
    assert error["error"]["code"] == "usage"
    assert captured.err == (
        json.dumps(
            error,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    assert wire.calls == []
