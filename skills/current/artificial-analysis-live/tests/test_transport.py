# Copyright (c) 2026 anntnzrb
"""Deterministic transport and cache-policy coverage for Artificial Analysis."""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING, Self, cast, final
from unittest.mock import patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from artificial_analysis import cli, rsc
from artificial_analysis.cli import (
    _evaluation_namespace,  # pyright: ignore[reportPrivateUsage]
    _evaluation_payload,  # pyright: ignore[reportPrivateUsage]
    _fetch_payload,  # pyright: ignore[reportPrivateUsage]
    _validate_304,  # pyright: ignore[reportPrivateUsage]
)


@final
class Response:
    """Minimal urllib response double used by transport tests."""

    body: bytes
    status: int
    headers: dict[str, str]
    final_url: str

    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        final_url: str = rsc.BASE_URL,
    ) -> None:
        """Initialize a response double."""
        self.body = body
        self.status = status
        self.headers = headers or {}
        self.final_url = final_url

    def read(self) -> bytes:
        """Return the response body."""
        return self.body

    def geturl(self) -> str:
        """Return the final response URL."""
        return self.final_url

    def getcode(self) -> int:
        """Return the HTTP status code."""
        return self.status

    def __enter__(self) -> Self:
        """Enter the response context manager."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Exit the response context manager."""
        return


@final
class QueueOpener:
    """Queue deterministic responses for patched urlopen calls."""

    responses: list[Response]
    requests: list[object]

    def __init__(self, *responses: Response) -> None:
        """Initialize the response queue."""
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request: object, *, timeout: float) -> Response:
        """Record a request and return the next queued response."""
        del timeout
        self.requests.append(request)
        return self.responses.pop(0)


def _request_headers(request: object) -> dict[str, str]:
    raw = cast("dict[str, str]", getattr(request, "headers", {}))
    return {str(key).lower(): str(value) for key, value in raw.items()}


def test_200_then_304_reuses_exact_bytes_and_sends_both_validators(
    tmp_path: Path,
) -> None:
    opener = QueueOpener(
        Response(
            b'0:{"rows":[]}',
            headers={
                "ETag": '"v1"',
                "Last-Modified": "Sun, 09 Aug 2026 00:00:00 GMT",
            },
        ),
        Response(
            b"",
            status=304,
            headers={"ETag": '"v1"', "Last-Modified": "Sun, 09 Aug 2026 00:00:00 GMT"},
        ),
    )
    with patch.object(rsc, "urlopen", opener):
        first = rsc.fetch_rsc()
        rsc.save_cache(
            cache_dir=tmp_path,
            fetched_at=first.fetched_at,
            status_code=first.status_code,
            etag=first.etag,
            last_modified=first.last_modified,
            body=first.body,
        )
        second = rsc.fetch_rsc(
            if_none_match=first.etag,
            if_modified_since=first.last_modified,
        )
    cached = rsc.load_cached_artifact(tmp_path)
    validated = _validate_304(
        second,
        cached,
        sent_etag=first.etag,
        sent_last_modified=first.last_modified,
    )
    assert validated.body == first.body
    assert validated.sha256 == first.sha256
    assert validated.byte_length == first.byte_length
    assert _request_headers(opener.requests[1])["if-none-match"] == '"v1"'
    assert (
        _request_headers(opener.requests[1])["if-modified-since"]
        == "Sun, 09 Aug 2026 00:00:00 GMT"
    )


def test_304_missing_and_mismatched_validator_are_structured(tmp_path: Path) -> None:
    response = rsc.FetchResult("", 304, {}, "2026-08-09T00:00:00+00:00")
    with pytest.raises(rsc.CacheError) as missing:
        _ = _validate_304(response, None, sent_etag=None, sent_last_modified=None)
    assert missing.value.code == "CACHE_MISSING"

    rsc.save_cache(
        cache_dir=tmp_path,
        fetched_at=response.fetched_at,
        status_code=200,
        etag='"known"',
        last_modified=None,
        body="payload",
    )
    cached = rsc.load_cached_artifact(tmp_path)
    mismatch = rsc.FetchResult(
        "",
        304,
        {"etag": '"other"'},
        response.fetched_at,
        etag='"other"',
    )
    with pytest.raises(rsc.CacheError) as invalid:
        _ = _validate_304(
            mismatch, cached, sent_etag='"known"', sent_last_modified=None
        )
    assert invalid.value.code == "CACHE_VALIDATOR_INVALID"


def test_tampered_artifact_fails_closed(tmp_path: Path) -> None:
    rsc.save_cache(
        cache_dir=tmp_path,
        fetched_at="2026-08-09T00:00:00+00:00",
        status_code=200,
        etag='"known"',
        body="payload",
    )
    index = cast(
        "dict[str, dict[str, str]]",
        json.loads((tmp_path / "index.json").read_text(encoding="utf-8")),
    )
    digest = str(index[rsc.BASE_URL]["sha256"])
    _ = (tmp_path / "artifacts" / f"{digest}.raw").write_bytes(b"tampered")
    assert rsc.load_cached_artifact(tmp_path) is None


def test_legacy_promotion_is_non_destructive_and_marked(tmp_path: Path) -> None:
    body = b"legacy payload"
    _ = (tmp_path / rsc.CACHE_BODY_FILE).write_bytes(body)
    metadata = {
        "etag": '"legacy"',
        "status_code": 200,
        "body_file": rsc.CACHE_BODY_FILE,
    }
    _ = (tmp_path / rsc.CACHE_META_FILE).write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    before_body = (tmp_path / rsc.CACHE_BODY_FILE).read_bytes()
    before_meta = (tmp_path / rsc.CACHE_META_FILE).read_bytes()
    loaded = rsc.load_cached_artifact(tmp_path)
    assert loaded is not None
    assert loaded[0] == body
    assert loaded[1]["legacy_unverified"] is True
    assert (tmp_path / rsc.CACHE_BODY_FILE).read_bytes() == before_body
    assert (tmp_path / rsc.CACHE_META_FILE).read_bytes() == before_meta


def _fetch_args(tmp_path: Path, *, allow_stale: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        cache_dir=tmp_path / "cache",
        timeout_seconds=1.0,
        min_endpoints=0,
        min_providers=0,
        stale_policy="allow-last-good" if allow_stale else "error",
        allow_stale=allow_stale,
        strict=False,
        output_json=tmp_path / "snapshot.json",
        output_endpoints=tmp_path / "endpoints.txt",
        output_url=tmp_path / "url.txt",
    )


def test_refresh_outage_is_error_by_default(tmp_path: Path) -> None:
    args = _fetch_args(tmp_path)
    with (
        patch.object(cli, "_required_api_key", return_value="secret"),
        patch.object(cli, "fetch_rsc", side_effect=OSError("offline")),
        pytest.raises(OSError, match="offline"),
    ):
        _ = _fetch_payload(args)


def test_explicit_stale_marks_fallback_without_writing_cache(tmp_path: Path) -> None:
    args = _fetch_args(tmp_path, allow_stale=True)
    cache_dir = cast("Path", args.cache_dir)
    cache_dir.mkdir()
    _ = (cache_dir / rsc.CACHE_LAST_GOOD_FILE).write_text(
        json.dumps(
            {
                "meta": {"fetched_at": "2026-08-09T00:00:00+00:00"},
                "hosts_models": [{"slug": "host_model-1"}],
            },
        ),
        encoding="utf-8",
    )
    with (
        patch.object(cli, "_required_api_key", return_value="secret"),
        patch.object(cli, "fetch_rsc", side_effect=OSError("offline")),
    ):
        payload = _fetch_payload(args)
    freshness = cast("dict[str, object]", payload["freshness"])
    assert freshness["mode"] == "stale-last-good"
    fallback = cast("dict[str, object]", payload["fallback"])
    assert fallback["used"] is True
    assert not (cache_dir / rsc.CACHE_META_FILE).exists()


def test_evaluation_public_urls_require_https() -> None:
    args = _evaluation_namespace(
        {"url": "http://example.test/evaluation"},
    )
    with pytest.raises(cli.CliUsageError, match="HTTPS"):
        _ = _evaluation_payload(args)


def test_metadata_redaction_and_atomic_outputs(tmp_path: Path) -> None:
    rsc.save_cache(
        cache_dir=tmp_path,
        fetched_at="2026-08-09T00:00:00+00:00",
        status_code=200,
        etag='"e"',
        body="payload",
        headers={"authorization": "Bearer secret", "x-api-key": "secret"},
    )
    assert "secret" not in (tmp_path / "index.json").read_text(encoding="utf-8")
    rsc.write_outputs(
        output_json=tmp_path / "out.json",
        output_endpoints=tmp_path / "endpoints.txt",
        output_url=tmp_path / "url.txt",
        payload={"meta": {}},
        slugs=["provider_model-1"],
        full_url="https://artificialanalysis.ai/?models=&endpoints=provider_model-1",
    )
    assert (tmp_path / "out.json").exists()
    assert not list(tmp_path.glob("*.tmp"))
