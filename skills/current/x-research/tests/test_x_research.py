"""Tests for x-research, ported from test/x-research.test.ts."""

import email.message
import http.server
import io
import json
import os
import shutil
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Self, TypeIs, override

import commands
import pytest
from commands import run_command
from contracts import (
    actual_type,
    normalize_conversation_payload,
    normalize_page_payload,
    normalize_post,
    normalize_profile,
    normalize_query,
    normalize_status_payload,
    status_id_from_target,
    validate_count,
    validate_cursor,
    validate_feed,
    validate_handle,
    validate_lang,
    validate_numeric_id,
    validate_provider,
    validate_ranking_mode,
)
from models import (
    DEFAULT_BASE_URL,
    SCHEMA_VERSION,
    UNDEFINED,
    CliError,
    ContractError,
    PagePayloadData,
    ProviderError,
)
from provider import (
    FxTwitterClient,
    build_url,
    compact_text,
    encode_query,
    live_client,
    make_fx_twitter_client,
    urllib_transport,
    validate_base_url,
    validate_endpoint,
    validate_params,
    validate_timeout,
)
from summary import summary_data, summary_post

import scripts.cli as cli_mod


def _is_dict(val: object) -> TypeIs[dict[object, object]]:
    return isinstance(val, dict)


def _is_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


def _as_dict(val: object) -> dict[str, object]:
    if _is_dict(val):
        return {str(k): v for k, v in val.items()}
    raise AssertionError(f"expected dict, got {type(val)}")


def _as_list(val: object) -> list[object]:
    if _is_list(val):
        return list(val)
    raise AssertionError(f"expected list, got {type(val)}")


def _json_loads_dict(text: str) -> dict[str, object]:
    loads_fn: Callable[..., object] = json.loads
    raw = loads_fn(text)
    return _as_dict(raw)


def assert_raises[T: BaseException](exc_type: type[T], fn: Callable[[], object]) -> T:
    """Run fn, requiring it to raise exc_type; return the caught exception."""
    try:
        _ = fn()
    except exc_type as err:
        return err
    msg = f"expected {exc_type.__name__} to be raised"
    raise AssertionError(msg)


class TestValidationAndContracts:
    def test_validate_handle_accepts_valid_and_rejects_invalid(self) -> None:
        assert validate_handle("OpenAI") == "OpenAI"
        assert validate_handle("user_123") == "user_123"
        _ = assert_raises(CliError, lambda: validate_handle(""))
        _ = assert_raises(CliError, lambda: validate_handle("@OpenAI"))
        _ = assert_raises(CliError, lambda: validate_handle("invalid handle"))

    def test_validate_numeric_id_accepts_numeric_strings_only(self) -> None:
        assert validate_numeric_id("123456789") == "123456789"
        _ = assert_raises(CliError, lambda: validate_numeric_id("abc"))
        _ = assert_raises(CliError, lambda: validate_numeric_id("123a"))
        _ = assert_raises(CliError, lambda: validate_numeric_id(""))

    def test_status_id_from_target_extracts_id(self) -> None:
        assert status_id_from_target("1890000000000000000") == {
            "id": "1890000000000000000"
        }
        assert status_id_from_target(
            "https://x.com/OpenAI/status/1890000000000000000"
        ) == {
            "id": "1890000000000000000",
            "targetUrl": "https://x.com/OpenAI/status/1890000000000000000",
        }
        assert status_id_from_target("https://twitter.com/user/status/12345/") == {
            "id": "12345",
            "targetUrl": "https://twitter.com/user/status/12345/",
        }

        _ = assert_raises(
            CliError, lambda: status_id_from_target("http://x.com/user/status/123")
        )
        _ = assert_raises(
            CliError,
            lambda: status_id_from_target("https://evil.com/user/status/123"),
        )
        _ = assert_raises(
            CliError, lambda: status_id_from_target("https://x.com/user/other/123")
        )
        _ = assert_raises(
            CliError,
            lambda: status_id_from_target("https://x.com/user/status/123?query=1"),
        )
        _ = assert_raises(CliError, lambda: status_id_from_target(""))

    def test_normalize_query_collapses_whitespace_and_rejects_empty(self) -> None:
        assert normalize_query("  hello   world  ") == "hello world"
        assert normalize_query("from:OpenAI   release") == "from:OpenAI release"
        _ = assert_raises(CliError, lambda: normalize_query("   "))
        _ = assert_raises(CliError, lambda: normalize_query(123))

    def test_validate_count_restricts_to_integers_1_to_100(self) -> None:
        assert validate_count(1) == 1
        assert validate_count(20) == 20
        assert validate_count(100) == 100
        _ = assert_raises(ContractError, lambda: validate_count(0))
        _ = assert_raises(ContractError, lambda: validate_count(101))
        _ = assert_raises(ContractError, lambda: validate_count(20.5))
        _ = assert_raises(ContractError, lambda: validate_count("20"))

    def test_validate_cursor_lang_feed_ranking_mode_provider(self) -> None:
        assert validate_cursor("bottom_cursor_token") == "bottom_cursor_token"
        _ = assert_raises(CliError, lambda: validate_cursor("  "))

        assert validate_lang("en") == "en"
        _ = assert_raises(CliError, lambda: validate_lang(" "))

        assert validate_feed("latest") == "latest"
        assert validate_feed("top") == "top"
        assert validate_feed("media") == "media"
        _ = assert_raises(CliError, lambda: validate_feed("invalid"))

        assert validate_ranking_mode("likes") == "likes"
        assert validate_ranking_mode("recency") == "recency"
        _ = assert_raises(CliError, lambda: validate_ranking_mode("invalid"))

        assert validate_provider("fxtwitter") == "fxtwitter"
        _ = assert_raises(CliError, lambda: validate_provider("other"))

    def test_actual_type_returns_descriptive_types(self) -> None:
        assert actual_type(None) == "null"
        assert actual_type(UNDEFINED) == "undefined"
        assert actual_type(value=True) == "boolean"
        assert actual_type("str") == "string"
        assert actual_type(42) == "number"
        assert actual_type([]) == "array"
        assert actual_type({}) == "object"


class TestUrlAndBaseUrlValidation:
    def test_validate_base_url_requires_https_host_no_credentials_query_hash(
        self,
    ) -> None:
        assert (
            validate_base_url("https://api.fxtwitter.com")
            == "https://api.fxtwitter.com"
        )
        assert (
            validate_base_url("https://api.fxtwitter.com/")
            == "https://api.fxtwitter.com"
        )
        assert (
            validate_base_url("https://proxy.internal:8443/custom")
            == "https://proxy.internal:8443/custom"
        )

        _ = assert_raises(
            CliError, lambda: validate_base_url("http://api.fxtwitter.com")
        )
        _ = assert_raises(
            CliError, lambda: validate_base_url("https://user:pass@api.fxtwitter.com")
        )
        _ = assert_raises(
            CliError, lambda: validate_base_url("https://api.fxtwitter.com?query=1")
        )
        _ = assert_raises(
            CliError, lambda: validate_base_url("https://api.fxtwitter.com#frag")
        )
        _ = assert_raises(
            CliError, lambda: validate_base_url("   https://api.fxtwitter.com")
        )
        _ = assert_raises(CliError, lambda: validate_base_url(""))

    def test_validate_endpoint_enforces_absolute_path_no_query_hash_netref(
        self,
    ) -> None:
        assert validate_endpoint("/2/status/123") == "/2/status/123"
        _ = assert_raises(ProviderError, lambda: validate_endpoint("//2/status"))
        _ = assert_raises(ProviderError, lambda: validate_endpoint("2/status"))
        _ = assert_raises(ProviderError, lambda: validate_endpoint("/2/status?q=1"))
        _ = assert_raises(ProviderError, lambda: validate_endpoint("/2/status#frag"))

    def test_encode_query_uses_plus_for_space_and_preserves_order(self) -> None:
        params = [
            ("q", "hello world & more"),
            ("count", "20"),
            ("feed", "latest"),
        ]
        encoded = encode_query(params)
        assert encoded == "q=hello+world+%26+more&count=20&feed=latest"

    def test_build_url_constructs_complete_url(self) -> None:
        url = build_url(
            "https://api.fxtwitter.com",
            "/2/search",
            [("q", "AI agent"), ("count", "10")],
        )
        assert url == "https://api.fxtwitter.com/2/search?q=AI+agent&count=10"


SAMPLE_POST: dict[str, object] = {
    "id": "1001",
    "url": "https://x.com/user/status/1001",
    "text": "Sample post text",
    "created_at": "2026-08-20T12:00:00Z",
    "author": {
        "id": "auth_1",
        "screen_name": "user",
        "name": "User Name",
        "url": "https://x.com/user",
        "verified": True,
    },
    "metrics": {
        "likes": 10,
        "reposts": 5,
        "replies": 2,
    },
    "lang": "en",
    "quote": {"id": "999"},
    "replying_to": {"status": "998"},
}


class TestPayloadNormalization:
    def test_normalize_profile_extracts_identity_and_verification(self) -> None:
        prof = normalize_profile(SAMPLE_POST["author"])
        assert prof == {
            "id": "auth_1",
            "handle": "user",
            "name": "User Name",
            "url": "https://x.com/user",
            "verified": True,
        }

    def test_normalize_post_maps_metrics_quote_reply(self) -> None:
        post = normalize_post(SAMPLE_POST)
        assert post.get("id") == "1001"
        assert post.get("url") == "https://x.com/user/status/1001"
        assert post.get("text") == "Sample post text"
        assert post.get("created_at") == "2026-08-20T12:00:00Z"
        assert "author" in post
        assert post["author"].get("handle") == "user"
        assert post.get("metrics") == {"likes": 10, "reposts": 5, "replies": 2}
        assert post.get("lang") == "en"
        assert post.get("quote_id") == "999"
        assert post.get("reply_to_id") == "998"

    def test_missing_optional_post_values_are_omitted(self) -> None:
        minimal_post = {
            "id": "1002",
            "url": "https://x.com/user/status/1002",
            "text": "",
            "created_at": "2026-08-20T12:00:00Z",
            "author": {
                "id": "auth_2",
            },
        }
        post = normalize_post(minimal_post)
        assert post.get("id") == "1002"
        assert "metrics" not in post
        assert "lang" not in post
        assert "media" not in post
        assert "quote_id" not in post
        assert "reply_to_id" not in post
        assert "author" in post
        assert "handle" not in post["author"]

    def test_normalize_status_payload_handles_exact_post_root(self) -> None:
        payload = {"code": 200, "status": SAMPLE_POST}
        res = normalize_status_payload(payload)
        assert res["post"].get("id") == "1001"

    def test_normalize_page_payload_validates_count_pagination_cursor(self) -> None:
        page_with_cursor = {
            "code": 200,
            "results": [SAMPLE_POST],
            "cursor": {"bottom": "cursor_token_123"},
            "profile": SAMPLE_POST["author"],
        }
        res1 = normalize_page_payload(page_with_cursor, 20)
        assert res1.get("requested_count") == 20
        assert res1.get("returned_count") == 1
        assert res1.get("cursor") == "cursor_token_123"
        assert res1.get("has_more") is True
        assert res1.get("complete") is False
        assert res1.get("complete_reason") == "bounded_page"
        assert "profile" in res1
        assert res1["profile"].get("handle") == "user"

        page_exhausted = {
            "code": 200,
            "results": [SAMPLE_POST],
            "cursor": None,
        }
        res2 = normalize_page_payload(page_exhausted, 20)
        assert "cursor" not in res2
        assert "has_more" not in res2
        assert res2.get("complete") is True
        assert res2.get("complete_reason") == "provider_exhausted"

        page_incomplete = {
            "code": 200,
            "results": [SAMPLE_POST],
        }
        res3 = normalize_page_payload(page_incomplete, 20)
        assert res3.get("complete") is False
        assert res3.get("complete_reason") == "provider_incomplete"

    def test_page_output_is_capped_to_requested_count(self) -> None:
        posts = [
            {**SAMPLE_POST, "id": "1"},
            {**SAMPLE_POST, "id": "2"},
            {**SAMPLE_POST, "id": "3"},
        ]
        payload = {"code": 200, "results": posts}
        res = normalize_page_payload(payload, 2)
        assert res.get("requested_count") == 2
        assert res.get("returned_count") == 2
        assert "posts" in res
        assert len(res["posts"]) == 2
        assert res["posts"][0].get("id") == "1"
        assert res["posts"][1].get("id") == "2"

    def test_normalize_conversation_payload_projects_target_thread_replies(
        self,
    ) -> None:
        payload = {
            "status": SAMPLE_POST,
            "thread": [{**SAMPLE_POST, "id": "1002"}],
            "replies": [
                {**SAMPLE_POST, "id": "1003"},
                {**SAMPLE_POST, "id": "1004"},
            ],
            "cursor": {"bottom": "conv_cursor"},
        }
        res = normalize_conversation_payload(payload)
        assert "target" in res
        assert res["target"].get("id") == "1001"
        assert "thread" in res
        assert len(res["thread"]) == 1
        assert "replies" in res
        assert len(res["replies"]) == 2
        assert res.get("returned_count") == 4
        assert res.get("cursor") == "conv_cursor"
        assert res.get("has_more") is True
        assert res.get("complete") is False
        assert res.get("complete_reason") == "bounded_page"


FULL_POST: dict[str, object] = {
    "id": "2001",
    "url": "https://x.com/user/status/2001",
    "text": "Full text content",
    "created_at": "2026-08-20T12:00:00Z",
    "author": {
        "id": "auth_1",
        "handle": "user",
        "name": "User Name",
        "url": "https://x.com/user",
        "verified": True,
        "extra_junk": "remove",
    },
    "metrics": {"likes": 100},
    "media": {"photos": [{"type": "photo", "url": "https://photo.url"}]},
    "lang": "en",
    "quote_id": "2000",
    "reply_to_id": "1999",
}


class TestSummaryProjections:
    def test_summary_post_retains_citation_fields_omits_metrics_media(self) -> None:
        projected = summary_post(FULL_POST)
        assert projected["id"] == "2001"
        assert projected["url"] == "https://x.com/user/status/2001"
        assert projected["text"] == "Full text content"
        assert projected["created_at"] == "2026-08-20T12:00:00Z"
        assert projected["lang"] == "en"
        assert projected["quote_id"] == "2000"
        assert projected["reply_to_id"] == "1999"
        assert projected["author"] == {
            "id": "auth_1",
            "handle": "user",
            "name": "User Name",
            "url": "https://x.com/user",
            "verified": True,
        }
        assert "metrics" not in projected
        assert "media" not in projected

    def test_summary_data_projects_all_command_payloads(self) -> None:
        fetch_data: dict[str, object] = {
            "requested_id": "2001",
            "post": FULL_POST,
            "provider": "fxtwitter",
            "official": False,
            "auth_mode": "none",
            "source_url": "https://api.fxtwitter.com/2/status/2001",
            "endpoint": "/2/status/2001",
            "fetched_at": "2026-08-22T22:00:00Z",
            "provider_status": 200,
        }
        projected_fetch = summary_data("fetch", fetch_data)
        assert projected_fetch["requested_id"] == "2001"
        assert projected_fetch["provider"] == "fxtwitter"
        assert "post" in projected_fetch
        post_dict = _as_dict(projected_fetch["post"])
        assert "metrics" not in post_dict
        page_data: dict[str, object] = {
            "handle": "user",
            "profile": FULL_POST["author"],
            "posts": [FULL_POST],
            "requested_count": 20,
            "returned_count": 1,
            "cursor": "cur_123",
            "has_more": True,
            "complete": False,
            "complete_reason": "bounded_page",
            "provider": "fxtwitter",
            "official": False,
            "auth_mode": "none",
            "source_url": "https://api.fxtwitter.com/2/profile/user/statuses?count=20&groupthreads=0",
            "endpoint": "/2/profile/user/statuses",
            "fetched_at": "2026-08-22T22:00:00Z",
            "provider_status": 200,
        }
        projected_page = summary_data("user-posts", page_data)
        assert projected_page["handle"] == "user"
        assert projected_page["profile"] == {
            "id": "auth_1",
            "handle": "user",
            "name": "User Name",
            "url": "https://x.com/user",
            "verified": True,
        }
        posts_list = _as_list(projected_page["posts"])
        first_post = _as_dict(posts_list[0])
        assert "metrics" not in first_post


SAMPLE_API_RESPONSE: dict[str, object] = {
    "code": 200,
    "status": {
        "id": "12345",
        "url": "https://x.com/user/status/12345",
        "text": "Wire test post",
        "created_at": "2026-08-22T00:00:00Z",
        "author": {
            "id": "a1",
            "screen_name": "testuser",
            "name": "Test User",
        },
    },
}


class TestCommandExecution:
    def test_run_command_fetch_exact_request_and_provenance(self) -> None:
        captured: dict[str, object] = {}

        def fake_transport(
            request: urllib.request.Request, _timeout: float
        ) -> tuple[int, str]:
            captured["url"] = request.full_url
            captured["headers"] = {k.lower(): v for k, v in request.header_items()}
            return 200, json.dumps(SAMPLE_API_RESPONSE)

        client = make_fx_twitter_client(fake_transport, DEFAULT_BASE_URL)
        result = run_command(
            {"command": "fetch", "target": "12345", "lang": "en"}, client
        )

        assert captured["url"] == "https://api.fxtwitter.com/2/status/12345?lang=en"
        headers = _as_dict(captured["headers"])
        assert headers["accept"] == "application/json"
        assert headers["user-agent"] == "x-research/1"

        assert result["requested_id"] == "12345"
        assert result["provider"] == "fxtwitter"
        assert result["official"] is False
        assert result["auth_mode"] == "none"
        assert result["provider_status"] == 200
        assert _as_dict(result["post"])["id"] == "12345"

    def test_run_command_user_posts_exact_endpoint_query_replies(self) -> None:
        captured: dict[str, object] = {}
        page_payload = {
            "code": 200,
            "results": [SAMPLE_API_RESPONSE["status"]],
            "cursor": {"bottom": "c1"},
        }

        def fake_transport(
            request: urllib.request.Request, _timeout: float
        ) -> tuple[int, str]:
            captured["url"] = request.full_url
            return 200, json.dumps(page_payload)

        client = make_fx_twitter_client(fake_transport, DEFAULT_BASE_URL)
        result = run_command(
            {
                "command": "user-posts",
                "handle": "elonmusk",
                "count": 10,
                "includeReplies": True,
                "cursor": "prev_cur",
            },
            client,
        )

        assert (
            captured["url"]
            == "https://api.fxtwitter.com/2/profile/elonmusk/statuses?count=10&groupthreads=0&cursor=prev_cur&with_replies=1"
        )
        assert result["handle"] == "elonmusk"
        assert result["requested_count"] == 10
        assert result["returned_count"] == 1
        assert result["cursor"] == "c1"

    def test_run_command_search_normalizes_whitespace_and_params(self) -> None:
        captured: dict[str, object] = {}
        search_payload = {
            "code": 200,
            "results": [SAMPLE_API_RESPONSE["status"]],
        }

        def fake_transport(
            request: urllib.request.Request, _timeout: float
        ) -> tuple[int, str]:
            captured["url"] = request.full_url
            return 200, json.dumps(search_payload)

        client = make_fx_twitter_client(fake_transport, DEFAULT_BASE_URL)
        result = run_command(
            {
                "command": "search",
                "query": "OpenAI   release   since:2026-08-01",
                "count": 15,
                "feed": "latest",
            },
            client,
        )

        assert (
            captured["url"]
            == "https://api.fxtwitter.com/2/search?q=OpenAI+release+since%3A2026-08-01&count=15&feed=latest"
        )
        assert result["query"] == "OpenAI release since:2026-08-01"
        assert result["feed"] == "latest"

    def test_run_command_conversation_ranking_mode_and_endpoint(self) -> None:
        captured: dict[str, object] = {}
        conv_payload: dict[str, object] = {
            "status": SAMPLE_API_RESPONSE["status"],
            "thread": [],
            "replies": [],
        }

        def fake_transport(
            request: urllib.request.Request, _timeout: float
        ) -> tuple[int, str]:
            captured["url"] = request.full_url
            return 200, json.dumps(conv_payload)

        client = make_fx_twitter_client(fake_transport, DEFAULT_BASE_URL)
        result = run_command(
            {"command": "conversation", "id": "998877", "rankingMode": "recency"},
            client,
        )

        assert (
            captured["url"]
            == "https://api.fxtwitter.com/2/conversation/998877?ranking_mode=recency"
        )
        assert result["requested_id"] == "998877"
        assert result["ranking_mode"] == "recency"

    def test_http_error_returns_provider_error_with_status_no_body(self) -> None:
        def fake_transport(
            _request: urllib.request.Request, _timeout: float
        ) -> tuple[int, str]:
            return 404, "Error body"

        client = make_fx_twitter_client(fake_transport, DEFAULT_BASE_URL)

        error_caught = assert_raises(
            ProviderError,
            lambda: run_command({"command": "fetch", "target": "99999"}, client),
        )
        assert error_caught.code == "http_error"
        assert error_caught.details["http_status"] == 404

    def test_malformed_json_body_returns_invalid_json_provider_error(self) -> None:
        def fake_transport(
            _request: urllib.request.Request, _timeout: float
        ) -> tuple[int, str]:
            return 200, "<html>Not JSON</html>"

        client = make_fx_twitter_client(fake_transport, DEFAULT_BASE_URL)

        error_caught = assert_raises(
            ProviderError,
            lambda: run_command({"command": "fetch", "target": "12345"}, client),
        )
        assert error_caught.code == "invalid_json"

    def test_api_error_status_code_maps_to_provider_error(self) -> None:
        error_payload = {
            "code": 404,
            "message": "Tweet not found",
        }

        def fake_transport(
            _request: urllib.request.Request, _timeout: float
        ) -> tuple[int, str]:
            return 200, json.dumps(error_payload)

        client = make_fx_twitter_client(fake_transport, DEFAULT_BASE_URL)

        error_caught = assert_raises(
            ProviderError,
            lambda: run_command({"command": "fetch", "target": "12345"}, client),
        )
        assert error_caught.code == "provider_error"
        assert error_caught.details["provider_status"] == 404

    def test_user_posts_float_count_serializes_as_integer(self) -> None:
        captured: dict[str, object] = {}

        def fake_transport(
            request: urllib.request.Request, _timeout: float
        ) -> tuple[int, str]:
            captured["url"] = request.full_url
            return 200, json.dumps({"code": 200, "results": []})

        client = make_fx_twitter_client(fake_transport, DEFAULT_BASE_URL)
        _ = run_command(
            {"command": "user-posts", "handle": "openai", "count": 10.0},
            client,
        )
        url_str = str(captured.get("url"))
        assert "count=10&" in url_str

    def test_urllib_transport_http_error_returns_status_no_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_urlopen(
            request: urllib.request.Request, timeout: float | None = None
        ) -> object:
            _ = timeout
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                email.message.Message(),
                io.BytesIO(b"err"),
            )

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        status, text = urllib_transport(
            urllib.request.Request("https://api.fxtwitter.com/2/status/1"), 5
        )
        assert status == 404
        assert text == ""

    def test_urllib_transport_network_error_maps_to_provider_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_urlopen(
            _request: urllib.request.Request, timeout: float | None = None
        ) -> object:
            _ = timeout
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        client = make_fx_twitter_client(urllib_transport, DEFAULT_BASE_URL)
        error_caught = assert_raises(
            ProviderError,
            lambda: run_command({"command": "fetch", "target": "12345"}, client),
        )
        assert error_caught.code == "network_error"
        reason_val = str(error_caught.details.get("reason"))
        assert "connection refused" in reason_val


class TestUrlValidationParity:
    def test_validate_base_url_rejects_surrounding_whitespace(self) -> None:
        error_caught = assert_raises(
            CliError,
            lambda: validate_base_url("\thttps://api.fxtwitter.com\r\n"),
        )
        assert error_caught.code == "invalid_base_url"

    def test_validate_base_url_rejects_space_in_host(self) -> None:
        error_caught = assert_raises(
            CliError, lambda: validate_base_url("https://exa mple.com")
        )
        assert error_caught.code == "invalid_base_url"

    def test_status_id_from_target_accepts_whitespace_padded_url(self) -> None:
        parsed = status_id_from_target("  https://x.com/user/status/42\n")
        assert parsed["id"] == "42"
        assert parsed["targetUrl"] == "  https://x.com/user/status/42\n"


CLI_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestCliSubprocess:
    def test_cli_rejects_invalid_input_exit_2_json_on_stderr(self) -> None:
        proc = _run_cli("fetch", "not-a-valid-target")

        assert proc.returncode == 2
        assert proc.stdout.strip() == ""
        assert proc.stderr.strip() != ""

        err_obj = _json_loads_dict(proc.stderr)
        assert err_obj["ok"] is False
        assert err_obj["schema_version"] == SCHEMA_VERSION
        assert err_obj["command"] == "fetch"
        assert _as_dict(err_obj["error"])["code"] == "invalid_target"

    def test_cli_usage_error_pretty_emits_indented_json_exit_2(self) -> None:
        proc = _run_cli("user-posts", "@InvalidHandle!", "--pretty")

        assert proc.returncode == 2
        assert "\n  " in proc.stderr
        err_obj = _json_loads_dict(proc.stderr)
        assert err_obj["ok"] is False
        assert err_obj["command"] == "user-posts"
        assert _as_dict(err_obj["error"])["code"] == "invalid_handle"

    def test_cli_help_exits_0_with_human_readable_help(self) -> None:
        proc = _run_cli("--help")

        assert proc.returncode == 0
        assert proc.stderr.strip() == ""
        assert "fetch" in proc.stdout
        assert "user-posts" in proc.stdout
        assert "search" in proc.stdout
        assert "conversation" in proc.stdout
        _ = assert_raises(json.JSONDecodeError, lambda: _json_loads_dict(proc.stdout))


def _status_payload(post_id: str = "12345") -> dict[str, object]:
    return {
        "code": 200,
        "status": {
            "id": post_id,
            "url": f"https://x.com/user/status/{post_id}",
            "text": "post text",
            "created_at": "2026-08-22T00:00:00Z",
            "author": {"id": "a1", "screen_name": "user"},
        },
    }


def _client_for_payload(payload: object) -> FxTwitterClient:
    def fake_transport(
        _request: urllib.request.Request, _timeout: float
    ) -> tuple[int, str]:
        return 200, json.dumps(payload)

    return make_fx_twitter_client(fake_transport, DEFAULT_BASE_URL)


class TestContractsEdges:
    """Deeper normalization coverage for lib/contracts.py."""

    def test_post_media_normalization_variants(self) -> None:
        post = {
            "id": "1",
            "url": "https://x.com/u/status/1",
            "text": "t",
            "created_at": "2026-01-01T00:00:00Z",
            "author": {"id": "a1"},
            "media": {
                "photos": [
                    {
                        "type": "photo",
                        "url": "https://p/1",
                        "width": 100,
                        "altText": "alt",
                    },
                    {"type": "photo"},  # missing url -> dropped
                    "junk",
                ],
                "videos": [
                    {
                        "type": "video",
                        "url": "https://v/1",
                        "duration": 12.5,
                        "formats": [
                            {
                                "container": "mp4",
                                "url": "https://v/1.mp4",
                                "bitrate": 500,
                            },
                            {"codec": "h264"},  # no url -> dropped
                            "junk",
                        ],
                    },
                    {
                        "type": "gif",
                        "url": "https://v/2",
                        "formats": {
                            "webp": "https://v/2.webp",
                            "jpeg": "https://v/2.jpg",
                        },
                    },
                ],
                "external": {
                    "type": "player",
                    "url": "https://c/1",
                    "state": "ready",
                    "title": "Card title",
                },
            },
        }
        normalized = normalize_post(post)
        assert "media" in normalized
        media = normalized["media"]
        assert "photos" in media
        assert len(media["photos"]) == 1
        assert media["photos"][0].get("altText") == "alt"
        assert "videos" in media
        assert media["videos"][0].get("formats") == [
            {"container": "mp4", "url": "https://v/1.mp4", "bitrate": 500}
        ]
        assert media["videos"][1].get("formats") == [
            {"webp": "https://v/2.webp", "jpeg": "https://v/2.jpg"}
        ]
        assert "external" in media
        assert media["external"].get("state") == "ready"
        assert media["external"].get("title") == "Card title"

    def test_post_metrics_and_verification_edges(self) -> None:
        post = {
            "id": "1",
            "url": "https://x.com/u/status/1",
            "text": "",
            "created_at": "2026-01-01T00:00:00Z",
            "author": {"screen_name": "u", "verified": True},
            "metrics": {
                "likes": 5,
                "replies": -1,  # negative dropped
                "views": True,  # bool dropped
                "retweets": "many",  # non-number dropped
            },
            "quote": {"id": "q1"},
            "replying_to": {"status": "r1"},
            "lang": "en",
        }
        normalized = normalize_post(post)
        assert normalized.get("metrics") == {"likes": 5}
        assert "author" in normalized
        assert normalized["author"].get("verified") is True
        assert normalized.get("quote_id") == "q1"
        assert normalized.get("reply_to_id") == "r1"

    def test_post_missing_fields_raise_contract_errors(self) -> None:
        base = {
            "id": "1",
            "url": "https://x.com/u/status/1",
            "text": "t",
            "created_at": "c",
            "author": {"id": "a"},
        }
        for missing in ("id", "url", "text", "created_at", "author"):
            bad = dict(base)
            del bad[missing]
            err = assert_raises(ContractError, lambda b=bad: normalize_post(b))
            assert f"post.{missing}" in err.message

        bad_author = dict(base)
        bad_author["author"] = {"name": "no id or handle"}
        err = assert_raises(ContractError, lambda: normalize_post(bad_author))
        assert err.code == "invalid_author"

        non_obj = assert_raises(ContractError, lambda: normalize_post("x"))
        assert non_obj.code == "malformed_payload"

    def test_page_payload_cursor_states(self) -> None:
        results = [
            {
                "id": "1",
                "url": "https://x.com/u/status/1",
                "text": "t",
                "created_at": "c",
                "author": {"id": "a"},
            }
        ]

        def page(cursor_marker: object) -> PagePayloadData:
            payload: dict[str, object] = {"results": results}
            if cursor_marker != "absent":
                payload["cursor"] = cursor_marker
            return normalize_page_payload(payload, 10)

        assert page("absent").get("complete_reason") == "provider_incomplete"
        exhausted = page(None)
        assert exhausted.get("complete") is True
        assert exhausted.get("complete_reason") == "provider_exhausted"
        assert page({}).get("complete_reason") == "provider_incomplete"
        assert page({"bottom": None}).get("complete_reason") == "provider_exhausted"
        assert page({"bottom": ""}).get("complete_reason") == "provider_incomplete"
        usable = page({"bottom": "next"})
        assert usable.get("cursor") == "next"
        assert usable.get("has_more") is True
        assert usable.get("complete_reason") == "bounded_page"

    def test_page_results_array_validation_and_index_enrichment(self) -> None:
        err = assert_raises(
            ContractError,
            lambda: normalize_page_payload({"results": "nope"}, 10),
        )
        assert err.code == "invalid_results"

        err = assert_raises(
            ContractError,
            lambda: normalize_page_payload({"results": [{"id": "1"}]}, 10),
        )
        assert err.details.get("index") == 0

        err = assert_raises(ContractError, lambda: normalize_page_payload({}, 10))
        assert err.code == "missing_field"

    def test_conversation_missing_sections(self) -> None:
        valid_status = _as_dict(SAMPLE_API_RESPONSE["status"])
        for missing in ("status", "thread", "replies"):
            payload: dict[str, object] = {
                "status": valid_status,
                "thread": [],
                "replies": [],
            }
            del payload[missing]
            err = assert_raises(
                ContractError,
                lambda p=payload: normalize_conversation_payload(p),
            )
            assert err.code == "missing_field"
            assert missing in err.message

        err = assert_raises(
            ContractError,
            lambda: normalize_conversation_payload(
                {"status": valid_status, "thread": "no", "replies": []}
            ),
        )
        assert err.code == "invalid_results"

    def test_status_payload_validation(self) -> None:
        err = assert_raises(ContractError, lambda: normalize_status_payload({}))
        assert err.code == "missing_field"
        err = assert_raises(
            ContractError, lambda: normalize_status_payload({"status": "x"})
        )
        assert err.code == "invalid_status"

    def test_status_id_from_target_url_rejections(self) -> None:
        for bad in (
            "http://x.com/u/status/1",
            "https://example.com/u/status/1",
            "https://x.com/u/profile/1",
            "https://x.com/u/status/1?x=1",
            "https://x.com/u/status/1#frag",
            "https://u:p@x.com/u/status/1",
            "https://x.com:8443/u/status/1",
            "abc",
            "",
            "   ",
        ):
            err = assert_raises(CliError, lambda b=bad: status_id_from_target(b))
            assert err.code == "invalid_target"

        ok = status_id_from_target("https://x.com/u/status/1/")
        assert ok["id"] == "1"
        assert ok["targetUrl"] == "https://x.com/u/status/1/"

        default_port = status_id_from_target("https://x.com:443/u/status/9")
        assert default_port["id"] == "9"

    def test_validate_cursor_feed_lang_and_count(self) -> None:
        assert validate_cursor("abc") == "abc"
        err = assert_raises(CliError, lambda: validate_cursor(""))
        assert err.code == "usage"
        err = assert_raises(CliError, lambda: validate_cursor(" " * 300))
        assert err.code == "usage"

        assert validate_feed("top") == "top"
        err = assert_raises(CliError, lambda: validate_feed("bogus"))
        assert err.code == "usage"

        assert validate_lang("en") == "en"
        err = assert_raises(CliError, lambda: validate_lang(""))
        assert err.code == "usage"
        assert validate_lang("not a lang!") == "not a lang!"

        for bad in (0, 101, -1, "10", True, None, 1.5):
            err = assert_raises(ContractError, lambda b=bad: validate_count(b))
            assert err.code == "invalid_count"

    def test_summary_data_skips_non_post_values(self) -> None:
        data: dict[str, object] = {
            "post": "scalar",
            "posts": ["x", {"id": "1"}],
            "profile": "no",
        }
        summary = summary_data("fetch", data)
        assert "post" not in summary
        assert summary["posts"] == [{"id": "1"}]
        assert "profile" not in summary


class TestProviderEdges:
    """Deeper coverage for lib/provider.py validation and status mapping."""

    def test_compact_text_truncates_and_flattens(self) -> None:

        assert compact_text(None) == ""
        assert compact_text(UNDEFINED) == ""
        assert compact_text("a\rb\nc") == "a b c"
        long_text = "x" * 200
        assert len(compact_text(long_text)) == 160
        assert compact_text(long_text).endswith("…")

    def test_validate_base_url_malformed_port(self) -> None:
        err = assert_raises(CliError, lambda: validate_base_url("https://x.com:abc"))
        assert err.code == "invalid_base_url"
        assert "malformed" in err.message

    def test_validate_base_url_unicode_and_control_chars(self) -> None:
        err = assert_raises(
            CliError, lambda: validate_base_url("https://x.com/\x01path")
        )
        assert err.code == "invalid_base_url"

    def test_validate_timeout_bounds(self) -> None:

        assert validate_timeout(5) == 5
        for bad in (0, -1, 61, True, "5", float("nan"), float("inf")):
            err = assert_raises(ProviderError, lambda b=bad: validate_timeout(b))
            assert err.code == "invalid_timeout"

    def test_validate_endpoint_rejections(self) -> None:
        for bad in ("", "nopath", "//net/path", "/x?q=1", "/x#f", "/x\x01"):
            err = assert_raises(ProviderError, lambda b=bad: validate_endpoint(b))
            assert err.code == "invalid_endpoint"

    def test_validate_params_rejections(self) -> None:

        assert validate_params(None) == []
        for bad in ("str", [("a",)], [("a", "b", "c")], [(1, "x")], [("a", 2)]):
            err = assert_raises(
                ProviderError,
                lambda b=bad: validate_params(b),
            )
            assert err.code == "invalid_endpoint"

    def test_request_json_provider_status_variants(self) -> None:
        # payload without "code" -> provider_status falls back to http_status
        result = _client_for_payload({"status": {}}).request_json("/2/x")
        assert result["provider_status"] is None

        # malformed code field
        err = assert_raises(
            ProviderError,
            lambda: _client_for_payload({"code": "200"}).request_json("/2/x"),
        )
        assert err.code == "invalid_provider_status"

        err = assert_raises(
            ProviderError,
            lambda: _client_for_payload({"code": 200.5}).request_json("/2/x"),
        )
        assert err.code == "invalid_provider_status"

        # non-dict payload
        err = assert_raises(
            ProviderError,
            lambda: _client_for_payload([1, 2]).request_json("/2/x"),
        )
        assert err.code == "invalid_payload"

    def test_request_json_invalid_endpoint_propagates(self) -> None:
        client = _client_for_payload({})
        err = assert_raises(ProviderError, lambda: client.request_json("no-slash"))
        assert err.code == "invalid_endpoint"

    def test_urllib_transport_success_decodes_body(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Resp:
            def read(self) -> bytes:
                return b'{"ok":true}'

            def getcode(self) -> int:
                return 200

            def __enter__(self) -> Self:
                return self

            def __exit__(self, *args: object) -> bool:
                return False

        def fake_open(
            _request: urllib.request.Request, timeout: float | None = None
        ) -> _Resp:
            _ = timeout
            return _Resp()

        monkeypatch.setattr(urllib.request, "urlopen", fake_open)
        status, text = urllib_transport(
            urllib.request.Request("https://api.fxtwitter.com/x"), 5
        )
        assert status == 200
        assert text == '{"ok":true}'

    def test_live_client_honors_base_url_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:

        monkeypatch.delenv("X_RESEARCH_BASE_URL", raising=False)
        client = live_client()
        assert callable(client.request_json)

        monkeypatch.setenv("X_RESEARCH_BASE_URL", "not a url at all!")
        err = assert_raises(CliError, live_client)
        assert err.code == "invalid_base_url"


class TestCommandBranches:
    """Deeper coverage for lib/commands.py branches."""

    def test_fetch_url_target_sets_requested_url(self) -> None:
        client = _client_for_payload(_status_payload("77"))
        data = run_command(
            {
                "command": "fetch",
                "target": "https://x.com/user/status/77",
            },
            client,
        )
        assert data["requested_url"] == "https://x.com/user/status/77"
        assert "requested_id" not in data
        assert _as_dict(data["post"])["id"] == "77"

    def test_fetch_rejects_bad_provider_and_lang(self) -> None:
        client = _client_for_payload(_status_payload())
        err = assert_raises(
            CliError,
            lambda: run_command(
                {"command": "fetch", "target": "1", "provider": "bogus"},
                client,
            ),
        )
        assert err.code == "usage"

        err = assert_raises(
            CliError,
            lambda: run_command(
                {"command": "fetch", "target": "1", "lang": "   "},
                client,
            ),
        )
        assert err.code == "usage"

    def test_contract_error_enriched_with_provenance(self) -> None:
        client = _client_for_payload({"code": 200})  # missing status field
        err = assert_raises(
            ContractError,
            lambda: run_command({"command": "fetch", "target": "1"}, client),
        )
        assert err.code == "missing_field"
        assert str(err.details["source_url"]).startswith("https://api.fxtwitter.com")
        assert err.details["endpoint"] == "/2/status/1"
        assert err.details["http_status"] == 200
        assert err.details["provider_status"] == 200

    def test_non_contract_normalize_failure_maps_invalid_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(_payload: object) -> object:
            raise TypeError("boom")

        monkeypatch.setattr(commands, "normalize_status_payload", explode)
        client = _client_for_payload(_status_payload())
        err = assert_raises(
            ContractError,
            lambda: run_command({"command": "fetch", "target": "1"}, client),
        )
        assert err.code == "invalid_provider_payload"

    def test_unknown_command_raises_usage(self) -> None:
        err = assert_raises(
            CliError,
            lambda: run_command({"command": "bogus"}, _client_for_payload({})),
        )
        assert err.code == "usage"

    def test_search_and_conversation_cursor_params(self) -> None:
        captured: dict[str, object] = {}

        def fake_transport(
            request: urllib.request.Request, _timeout: float
        ) -> tuple[int, str]:
            captured["url"] = request.full_url
            if "search" in request.full_url:
                return 200, json.dumps({"code": 200, "results": []})
            return 200, json.dumps(
                {"status": _status_payload("9")["status"], "thread": [], "replies": []}
            )

        client = make_fx_twitter_client(fake_transport, DEFAULT_BASE_URL)
        _ = run_command({"command": "search", "query": "q", "cursor": "cur1"}, client)
        assert "cursor=cur1" in str(captured["url"])

        _ = run_command(
            {
                "command": "conversation",
                "id": "9",
                "rankingMode": "likes",
                "cursor": "cur2",
            },
            client,
        )
        assert "cursor=cur2" in str(captured["url"])
        assert "ranking_mode=likes" in str(captured["url"])

    def test_conversation_invalid_ranking(self) -> None:
        err = assert_raises(
            CliError,
            lambda: run_command(
                {
                    "command": "conversation",
                    "id": "9",
                    "rankingMode": "bogus",
                },
                _client_for_payload({}),
            ),
        )
        assert err.code == "usage"


class TestCliInProcess:
    """Drive run_cli in-process with a stubbed live client."""

    def _patch_client(self, monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
        monkeypatch.setattr(
            cli_mod, "live_client", lambda: _client_for_payload(payload)
        )

    def test_fetch_success_envelope_stdout(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._patch_client(monkeypatch, _status_payload("5"))
        rc = cli_mod.run_cli(["fetch", "5"])
        assert rc == 0
        out = _json_loads_dict(capsys.readouterr().out)
        assert out["ok"] is True
        assert out["command"] == "fetch"
        data = _as_dict(out["data"])
        post = _as_dict(data["post"])
        assert post["id"] == "5"
        assert capsys.readouterr().err == ""

    def test_fetch_summary_and_pretty(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = _status_payload("5")
        status_dict = _as_dict(payload["status"])
        status_dict["metrics"] = {"likes": 10}
        status_dict["media"] = {"photos": [{"type": "photo", "url": "u"}]}
        payload["status"] = status_dict
        self._patch_client(monkeypatch, payload)
        rc = cli_mod.run_cli(["fetch", "5", "--summary", "--pretty"])
        assert rc == 0
        out_text = capsys.readouterr().out
        assert "\n  " in out_text
        envelope = _json_loads_dict(out_text)
        data = _as_dict(envelope["data"])
        post = _as_dict(data["post"])
        assert "metrics" not in post
        assert "media" not in post
        assert post["id"] == "5"

    def test_user_posts_and_conversation_success(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def fake_transport(
            request: urllib.request.Request, _timeout: float
        ) -> tuple[int, str]:
            if "/2/profile/" in request.full_url:
                return 200, json.dumps(
                    {"code": 200, "results": [SAMPLE_API_RESPONSE["status"]]}
                )
            return 200, json.dumps(
                {
                    "status": SAMPLE_API_RESPONSE["status"],
                    "thread": [],
                    "replies": [],
                }
            )

        monkeypatch.setattr(
            cli_mod,
            "live_client",
            lambda: make_fx_twitter_client(fake_transport, DEFAULT_BASE_URL),
        )
        assert cli_mod.run_cli(["user-posts", "openai", "--count", "5"]) == 0
        out = _json_loads_dict(capsys.readouterr().out)
        assert _as_dict(out["data"])["requested_count"] == 5

        assert cli_mod.run_cli(["conversation", "9"]) == 0
        out = _json_loads_dict(capsys.readouterr().out)
        assert _as_dict(out["data"])["returned_count"] == 1

    def test_search_success(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._patch_client(monkeypatch, {"code": 200, "results": []})
        assert cli_mod.run_cli(["search", "hello", "--feed", "top"]) == 0
        out = _json_loads_dict(capsys.readouterr().out)
        assert _as_dict(out["data"])["feed"] == "top"

    def test_usage_and_contract_and_provider_errors(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._patch_client(monkeypatch, _status_payload())

        assert cli_mod.run_cli(["fetch", "not-a-target"]) == 2
        err = _json_loads_dict(capsys.readouterr().err)
        assert _as_dict(err["error"])["code"] == "invalid_target"

        assert cli_mod.run_cli(["user-posts", "bad handle"]) == 2
        err = _json_loads_dict(capsys.readouterr().err)
        assert _as_dict(err["error"])["code"] == "invalid_handle"

        self._patch_client(monkeypatch, {"code": 200})
        assert cli_mod.run_cli(["fetch", "5"]) == 1
        err = _json_loads_dict(capsys.readouterr().err)
        assert _as_dict(err["error"])["code"] == "missing_field"

        def http_error_transport(
            _request: urllib.request.Request, _timeout: float
        ) -> tuple[int, str]:
            return 500, "server error"

        monkeypatch.setattr(
            cli_mod,
            "live_client",
            lambda: make_fx_twitter_client(http_error_transport, DEFAULT_BASE_URL),
        )
        assert cli_mod.run_cli(["fetch", "5"]) == 1
        err = _json_loads_dict(capsys.readouterr().err)
        assert _as_dict(err["error"])["code"] == "http_error"

    def test_internal_error_exit_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def explode() -> object:
            raise RuntimeError("client exploded")

        monkeypatch.setattr(cli_mod, "live_client", explode)
        assert cli_mod.run_cli(["fetch", "5"]) == 1
        err = _json_loads_dict(capsys.readouterr().err)
        assert _as_dict(err["error"])["code"] == "internal_error"

    def test_version_and_missing_command(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli_mod.run_cli(["--version"]) == 0
        assert "1.0.0" in capsys.readouterr().out

        assert cli_mod.run_cli([]) == 2
        err = _json_loads_dict(capsys.readouterr().err)
        assert _as_dict(err["error"])["code"] == "usage"
        assert err["command"] == "unknown"

        assert cli_mod.run_cli(["search", "q", "--feed", "bogus"]) == 2

    def test_sanitize_drops_undefined_and_nulls_arrays(self) -> None:
        sanitized = cli_mod._sanitize(
            {"a": UNDEFINED, "b": [1, UNDEFINED, {"c": UNDEFINED}], "d": "x"}
        )
        assert sanitized == {"b": [1, None, {}], "d": "x"}

    def test_get_command_hint(self) -> None:

        assert cli_mod.get_command_hint(["fetch", "x"]) == "fetch"
        assert cli_mod.get_command_hint(["nope"]) == "unknown"
        assert cli_mod.get_command_hint(["--pretty", "search", "q"]) == "search"


class TestEndToEnd:
    """Full e2e: cli.py subprocess -> real HTTPS transport -> local TLS server.

    Trust is injected via a sitecustomize.py on PYTHONPATH that loads the
    test CA into every default SSL context (equivalent to installing a test
    CA in the system trust store). Everything else is a real TLS handshake.
    """

    @staticmethod
    def _make_certs(tmp_path: Path) -> tuple[Path, Path, Path] | None:
        """Generate a local CA + localhost server cert via openssl."""
        if shutil.which("openssl") is None:
            return None
        ca_key = tmp_path / "ca.key"
        ca_crt = tmp_path / "ca.crt"
        srv_key = tmp_path / "srv.key"
        srv_csr = tmp_path / "srv.csr"
        srv_crt = tmp_path / "srv.crt"
        ext = tmp_path / "srv.ext"
        ext_lines = (
            "subjectAltName=DNS:localhost",
            "basicConstraints=CA:FALSE",
            "keyUsage=digitalSignature,keyEncipherment",
            "extendedKeyUsage=serverAuth",
            "",
        )
        _ = ext.write_text("\n".join(ext_lines), encoding="utf-8")
        cmds = [
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(ca_key),
                "-out",
                str(ca_crt),
                "-days",
                "1",
                "-nodes",
                "-subj",
                "/CN=TestCA",
                "-addext",
                "basicConstraints=critical,CA:TRUE",
                "-addext",
                "keyUsage=critical,keyCertSign,cRLSign",
            ],
            [
                "openssl",
                "req",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(srv_key),
                "-out",
                str(srv_csr),
                "-nodes",
                "-subj",
                "/CN=localhost",
            ],
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                str(srv_csr),
                "-CA",
                str(ca_crt),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(srv_crt),
                "-days",
                "1",
                "-extfile",
                str(ext),
            ],
        ]
        try:
            for cmd in cmds:
                _ = subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        except subprocess.CalledProcessError, FileNotFoundError:
            return None
        return ca_crt, srv_crt, srv_key

    @staticmethod
    def _trust_site_dir(tmp_path: Path, ca_crt: Path) -> Path:
        site_dir = tmp_path / "trustsite"
        site_dir.mkdir(exist_ok=True)
        _ = (site_dir / "sitecustomize.py").write_text(
            "\n".join(
                (
                    "import ssl",
                    f"_CA = {str(ca_crt)!r}",
                    "_orig = ssl.create_default_context",
                    "def _patched(*a, **k):",
                    "    ctx = _orig(*a, **k)",
                    "    ctx.load_verify_locations(_CA)",
                    "    return ctx",
                    "ssl.create_default_context = _patched",
                    "ssl._create_default_https_context = _patched",
                    "",
                )
            ),
            encoding="utf-8",
        )
        return site_dir

    def _run_e2e(
        self,
        tmp_path: Path,
        handler_cls: type[http.server.BaseHTTPRequestHandler],
        args: list[str],
    ) -> subprocess.CompletedProcess[str]:
        certs = self._make_certs(tmp_path)
        if certs is None:
            pytest.skip("openssl unavailable or cert generation failed")
        assert certs is not None
        ca_crt, srv_crt, srv_key = certs
        site_dir = self._trust_site_dir(tmp_path, ca_crt)

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(srv_crt), str(srv_key))
        server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            env = {
                **os.environ,
                "X_RESEARCH_BASE_URL": f"https://localhost:{server.server_port}",
                "PYTHONPATH": str(site_dir),
            }
            return subprocess.run(
                [sys.executable, str(CLI_PATH), *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
                env=env,
            )
        finally:
            server.shutdown()
            thread.join(timeout=5)

    def test_cli_e2e_fetch_over_local_https(self, tmp_path: Path) -> None:
        status_payload = _status_payload("555")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/2/status/555":
                    body = json.dumps(status_payload).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    _ = self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()

            @override
            def log_message(self, format: str, *args: object) -> None:
                pass

        proc = self._run_e2e(tmp_path, Handler, ["fetch", "555"])
        assert proc.returncode == 0, proc.stderr
        envelope = _json_loads_dict(proc.stdout)
        assert envelope["ok"] is True
        data = _as_dict(envelope["data"])
        post = _as_dict(data["post"])
        assert post["id"] == "555"
        assert data["provider_status"] == 200
        assert str(data["source_url"]).startswith("https://localhost:")

    def test_cli_e2e_fetch_http_error_from_local_https(self, tmp_path: Path) -> None:
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()

            @override
            def log_message(self, format: str, *args: object) -> None:
                pass

        proc = self._run_e2e(tmp_path, Handler, ["fetch", "555"])
        assert proc.returncode == 1
        err_env = _json_loads_dict(proc.stderr)
        assert err_env["ok"] is False
        err_obj = _as_dict(err_env["error"])
        assert err_obj["code"] == "http_error"
        assert _as_dict(err_obj["details"])["http_status"] == 500


class TestResidualBranches:
    """Surgical coverage for remaining defensive/optional branches."""

    def test_actual_type_fallback_for_exotic_values(self) -> None:
        assert actual_type((1, 2)) == "tuple"
        assert actual_type(object()) == "object"
        assert actual_type(3.5) == "number"

    def test_status_id_from_target_urlsplit_value_error(self) -> None:
        # port property raising ValueError inside urlsplit result
        err = assert_raises(
            CliError,
            lambda: status_id_from_target("https://x.com:notaport/u/status/1"),
        )
        assert err.code == "invalid_target"

    def test_required_string_invalid_field_branches(self) -> None:
        post = _as_dict(SAMPLE_API_RESPONSE["status"])
        post["id"] = 123  # non-string
        err = assert_raises(ContractError, lambda: normalize_post(post))
        assert err.code == "invalid_field"

        post2 = _as_dict(SAMPLE_API_RESPONSE["status"])
        post2["url"] = ""  # empty non-allowed
        err = assert_raises(ContractError, lambda: normalize_post(post2))
        assert err.code == "invalid_field"

    def test_optional_string_and_verification_dict(self) -> None:
        post = _as_dict(SAMPLE_API_RESPONSE["status"])
        post["lang"] = 5  # optional non-string -> dropped
        post["author"] = {"id": "a", "verification": {"verified": False}}
        normalized = normalize_post(post)
        assert "lang" not in normalized
        assert "author" in normalized
        assert normalized["author"].get("verified") is False

        post2 = _as_dict(SAMPLE_API_RESPONSE["status"])
        post2["author"] = {"id": "a", "verification": {"verified": "yes"}}
        normalized2 = normalize_post(post2)
        assert "author" in normalized2
        assert "verified" not in normalized2["author"]

    def test_page_results_tuple_actual_type(self) -> None:
        err = assert_raises(
            ContractError,
            lambda: normalize_page_payload({"results": (1, 2)}, 10),
        )
        assert err.code == "invalid_results"
        assert err.details["actual_type"] == "tuple"

    def test_conversation_replies_index_enrichment(self) -> None:
        payload = {
            "status": _as_dict(SAMPLE_API_RESPONSE["status"]),
            "thread": [],
            "replies": [
                {
                    "id": "ok",
                    "url": "u",
                    "text": "t",
                    "created_at": "c",
                    "author": {"id": "a"},
                },
                {"bad": True},
            ],
        }
        err = assert_raises(
            ContractError, lambda: normalize_conversation_payload(payload)
        )
        assert err.details.get("index") == 1

    def test_page_index_in_details_when_absent(self) -> None:
        payload = {"results": [{"id": 42}]}
        err = assert_raises(ContractError, lambda: normalize_page_payload(payload, 10))
        assert err.details["index"] == 0

    def test_conversation_page_cursor_bounded(self) -> None:
        payload = {
            "status": _as_dict(SAMPLE_API_RESPONSE["status"]),
            "thread": [_as_dict(SAMPLE_API_RESPONSE["status"])],
            "replies": [],
            "cursor": {"bottom": "next-page"},
        }
        conv = normalize_conversation_payload(payload)
        assert conv.get("has_more") is True

    def test_user_posts_default_count_and_fetch_provider_params(self) -> None:
        captured: list[str] = []

        def fake_transport(
            request: urllib.request.Request, _timeout: float
        ) -> tuple[int, str]:
            captured.append(request.full_url)
            if "/2/status/" in request.full_url:
                return 200, json.dumps(_status_payload("1"))
            return 200, json.dumps({"code": 200, "results": []})

        client = make_fx_twitter_client(fake_transport, DEFAULT_BASE_URL)
        # user-posts without count -> default 20
        data = run_command(
            {"command": "user-posts", "handle": "openai"},
            client,
        )
        assert data["requested_count"] == 20
        assert "count=20" in captured[-1]
        assert "groupthreads=0" in captured[-1]

        # fetch validates provider and forwards lang
        _ = run_command(
            {"command": "fetch", "target": "1", "provider": "fxtwitter", "lang": "en"},
            client,
        )
        assert "lang=en" in captured[-1]

    def test_conversation_default_ranking_param(self) -> None:
        urls: list[str] = []

        def fake_transport(
            request: urllib.request.Request, _timeout: float
        ) -> tuple[int, str]:
            urls.append(request.full_url)
            return 200, json.dumps(
                {
                    "status": _as_dict(SAMPLE_API_RESPONSE["status"]),
                    "thread": [],
                    "replies": [],
                }
            )

        client = make_fx_twitter_client(fake_transport, DEFAULT_BASE_URL)
        _ = run_command({"command": "conversation", "id": "9"}, client)
        assert "ranking_mode=likes" in urls[-1]  # default

    def test_normalize_exception_maps_invalid_payload_userposts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_page(_payload: object, _count: object) -> object:
            raise ValueError("x")

        monkeypatch.setattr(
            commands,
            "normalize_page_payload",
            fail_page,
        )
        client = _client_for_payload({"code": 200})
        err = assert_raises(
            ContractError,
            lambda: run_command({"command": "user-posts", "handle": "openai"}, client),
        )
        assert err.code == "invalid_provider_payload"

    def test_normalize_exception_maps_invalid_payload_search(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_page(_payload: object, _count: object) -> object:
            raise ValueError("x")

        monkeypatch.setattr(
            commands,
            "normalize_page_payload",
            fail_page,
        )
        client = _client_for_payload({"code": 200})
        err = assert_raises(
            ContractError,
            lambda: run_command({"command": "search", "query": "q"}, client),
        )
        assert err.code == "invalid_provider_payload"

    def test_normalize_exception_maps_invalid_payload_conversation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_conv(_payload: object) -> object:
            raise ValueError("x")

        monkeypatch.setattr(
            commands,
            "normalize_conversation_payload",
            fail_conv,
        )
        client = _client_for_payload({"code": 200})
        err = assert_raises(
            ContractError,
            lambda: run_command({"command": "conversation", "id": "9"}, client),
        )
        assert err.code == "invalid_provider_payload"

    def test_transport_raising_provider_error_propagates(self) -> None:
        def transport_raises(
            _request: urllib.request.Request, _timeout: float
        ) -> tuple[int, str]:
            raise ProviderError(code="custom", message="boom", details={})

        client = make_fx_twitter_client(transport_raises, DEFAULT_BASE_URL)
        err = assert_raises(ProviderError, lambda: client.request_json("/2/x"))
        assert err.code == "custom"

    def test_validate_endpoint_urlsplit_value_error(self) -> None:
        # malformed endpoint that trips urlsplit's ValueError
        for bad in ("http://[::1", "/\ud800x"):
            with pytest.raises(ProviderError) as exc_info:
                _ = validate_endpoint(bad)
            assert exc_info.value.code == "invalid_endpoint"

    def test_decode_payload_invalid_json(self) -> None:
        def fake_transport(
            _request: urllib.request.Request, _timeout: float
        ) -> tuple[int, str]:
            return 200, "this is not json{"

        client = make_fx_twitter_client(fake_transport, DEFAULT_BASE_URL)
        err = assert_raises(ProviderError, lambda: client.request_json("/2/x"))
        assert err.code == "invalid_json"

    def test_cli_emit_failure_and_write_envelope_pretty(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli_mod.emit_failure(
            "fetch",
            CliError(code="usage", message="bad", details={}),
            pretty=True,
        )
        err_text = capsys.readouterr().err
        assert "\n  " in err_text
        parsed = _json_loads_dict(err_text)
        assert _as_dict(parsed["error"])["code"] == "usage"

        cli_mod.emit_success("fetch", {"post": {"id": "1"}}, pretty=False)
        out = _json_loads_dict(capsys.readouterr().out)
        assert out["ok"] is True

    def test_cli_main_delegates_to_run_cli(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, object] = {}

        def fake_run_cli(args: object) -> int:
            seen["a"] = args
            return 7

        monkeypatch.setattr(cli_mod, "run_cli", fake_run_cli)
        assert cli_mod.main(["fetch", "1"]) == 7
        assert seen["a"] == ["fetch", "1"]


class TestFinalEdges:
    """Last-mile coverage."""

    def test_is_help_returns_zero_on_parse_failures(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # help flag present + parse failure -> 0
        assert cli_mod.run_cli(["--help", "bogus"]) == 0
        _ = capsys.readouterr()
        # subcommand help -> 0
        assert cli_mod.run_cli(["fetch", "--help"]) == 0
        _ = capsys.readouterr()

    def test_contract_errors_enriched_for_page_commands(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def contract_boom(_payload: object, _count: object) -> object:
            raise ContractError(code="invalid_results", message="bad", details={})

        monkeypatch.setattr(commands, "normalize_page_payload", contract_boom)
        client = _client_for_payload({"code": 200})
        for ci in (
            {"command": "user-posts", "handle": "openai"},
            {"command": "search", "query": "q"},
        ):
            err = assert_raises(ContractError, lambda c=ci: run_command(c, client))
            assert err.code == "invalid_results"
            assert "source_url" in err.details

    def test_contract_error_enriched_for_conversation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def conv_boom(_payload: object) -> object:
            raise ContractError(code="missing_field", message="x", details={})

        monkeypatch.setattr(
            commands,
            "normalize_conversation_payload",
            conv_boom,
        )
        client = _client_for_payload({"code": 200})
        err = assert_raises(
            ContractError,
            lambda: run_command({"command": "conversation", "id": "9"}, client),
        )
        assert "source_url" in err.details

    def test_post_optional_lang_and_media_object_none(self) -> None:
        post = _as_dict(SAMPLE_API_RESPONSE["status"])
        post["lang"] = "en"
        # external lacks type/url -> dropped; whole media object omitted
        post["media"] = {"external": {"state": "x"}}
        normalized = normalize_post(post)
        assert normalized.get("lang") == "en"
        assert "media" not in normalized

    def test_conversation_status_non_dict(self) -> None:
        err = assert_raises(
            ContractError,
            lambda: normalize_conversation_payload(
                {"status": "nope", "thread": [], "replies": []}
            ),
        )
        assert err.code == "invalid_status"
