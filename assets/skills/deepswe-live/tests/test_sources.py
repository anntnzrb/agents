"""Deterministic source/version/cache contract tests (no live network)."""
# ruff: noqa: CPY001, INP001, RUF043, S101

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Self
from urllib.error import HTTPError, URLError

if TYPE_CHECKING:
    from urllib.request import Request

from pathlib import Path

import _path  # noqa: F401
import pytest
from deepswe import sources

LEADERBOARD = {
    "generated_at": "2026-07-25T03:13:49Z",
    "n_tasks_in_set": 2,
    "rows": [
        {
            "model": "fixture-model",
            "harness": "fixture-harness",
            "reasoning_effort": "high",
            "config": "fixture-model-high",
            "source": "deep-swe",
            "pass_at_1": 0.5,
            "n_attempted": 2,
        }
    ],
}
TRIALS = {
    "n_trials": 2,
    "rows": [
        {
            "source": "deep-swe",
            "eval_scope": "full",
            "included_in_score": True,
            "model": "fixture-model",
            "passed": True,
        },
        {
            "source": "other-benchmark",
            "eval_scope": "smoke",
            "included_in_score": False,
            "model": "other",
            "passed": False,
        },
    ],
}


class Response:
    """Small urllib-compatible response fixture for transport tests."""

    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        final_url: str | None = None,
    ) -> None:
        """Initialize response bytes, status, headers, and optional redirect URL."""
        self.body = io.BytesIO(body)
        self.status = status
        self.code = status
        self.headers = headers or {}
        self.final_url = final_url

    def geturl(self) -> str | None:
        """Return the configured final URL."""
        return self.final_url

    def __enter__(self) -> Self:
        """Return this response for context-manager use."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Close the in-memory response body."""
        self.body.close()

    def read(self) -> bytes:
        """Read the remaining response bytes."""
        return self.body.read()

    def getcode(self) -> int:
        """Return the HTTP status code."""
        return self.status

    def getheader(self, name: str, default: str | None = None) -> str | None:
        """Return a case-insensitive header value."""
        wanted = name.lower()
        return next(
            (v for k, v in self.headers.items() if k.lower() == wanted), default
        )


class QueueOpener:
    """Queue deterministic responses for urllib transport calls."""

    def __init__(self, *responses: object) -> None:
        """Initialize the response queue and captured request list."""
        self.responses = list(responses)
        self.requests: list[Request] = []

    def __call__(self, request: Request, timeout: float = 0) -> object:
        """Return the next response while recording the request."""
        del timeout
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def patch_urlopen(monkeypatch: pytest.MonkeyPatch, opener: QueueOpener) -> None:
    """Patch the source module's stdlib transport without touching the network."""
    monkeypatch.setattr(sources, "urlopen", opener)
    monkeypatch.setattr(sources, "_utc_now", lambda: "2026-07-25T05:00:00+00:00")


def artifact_meta(result: dict[str, object], filename: str) -> dict[str, object]:
    """Return one artifact metadata mapping from a fetch result."""
    artifacts = result.get("artifacts")
    assert isinstance(artifacts, dict), result
    metadata = artifacts.get(filename)
    assert isinstance(metadata, dict), result
    return metadata


def test_resolve_latest_uses_one_configured_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve latest through the configured deterministic release source."""
    monkeypatch.delenv("DEEPSWE_DEFAULT_VERSION", raising=False)
    assert sources.resolve_version(None)["version"] == "v1.1"

    monkeypatch.setenv("DEEPSWE_DEFAULT_VERSION", "v1.2")
    resolved = sources.resolve_version("latest")
    assert resolved["version"] == "v1.2"
    assert resolved["source"] == "env"


def test_resolve_explicit_semver_and_reject_major_only_or_legacy() -> None:
    """Accept semantic releases and reject legacy or major-only identifiers."""
    assert sources.resolve_version("v1.12")["version"] == "v1.12"
    assert sources.resolve_version("v1.12.1")["version"] == "v1.12.1"
    assert sources.resolve_version("v2.0")["version"] == "v2.0"
    for invalid in ("v1", "1", "latest-v1", "v0.9", ""):
        with pytest.raises(ValueError, match="version|legacy|empty"):
            sources.resolve_version(invalid)


def test_fetch_records_url_version_headers_and_writes_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fetch metadata, headers, payload bytes, and output files for one artifact."""
    body = json.dumps(LEADERBOARD).encode()
    opener = QueueOpener(
        Response(
            body,
            headers={
                "ETag": '"fixture-etag"',
                "Last-Modified": "Sat, 25 Jul 2026 03:13:49 GMT",
            },
        )
    )
    patch_urlopen(monkeypatch, opener)

    result = sources.fetch_artifacts(
        "v1.1",
        tmp_path / "out",
        tmp_path / "cache",
        include_trials=False,
        timeout=3,
        allow_stale=False,
    )
    meta = artifact_meta(result, "leaderboard-live.json")
    assert meta["benchmark_version"] == "v1.1"
    assert meta["url"].endswith("/artifacts/v1.1/leaderboard-live.json")
    assert meta["etag"] == '"fixture-etag"'
    assert meta["last_modified"] == "Sat, 25 Jul 2026 03:13:49 GMT"
    assert meta["row_count"] == 1
    assert Path(str(meta["local_path"])).read_bytes() == body
    assert meta["cache_reused"] is False


def test_response_url_path_mismatch_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reject a response redirect that does not match the requested artifact."""
    response = Response(
        json.dumps(LEADERBOARD).encode(),
        final_url="https://deepswe.datacurve.ai/downloads/leaderboard-live.json",
    )
    patch_urlopen(monkeypatch, QueueOpener(response))

    with pytest.raises(
        sources.SourceError,
        match=r"does not match requested v1\.1/leaderboard-live\.json",
    ) as exc_info:
        sources.fetch_artifacts(
            "v1.1",
            tmp_path / "out",
            tmp_path / "cache",
            include_trials=False,
            timeout=3,
            allow_stale=False,
        )

    assert exc_info.value.code == "version_mismatch"
    assert response.body.tell() == 0


def test_conditional_304_reuses_exact_cached_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reuse exact cached bytes after a conditional not-modified response."""
    body = json.dumps(LEADERBOARD, separators=(",", ":")).encode()
    opener = QueueOpener(
        Response(
            body,
            headers={"ETag": '"same"', "Last-Modified": "fixture-date"},
        ),
        Response(
            b"",
            status=304,
            headers={"ETag": '"same"', "Last-Modified": "fixture-date"},
        ),
    )
    patch_urlopen(monkeypatch, opener)
    output_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"

    first = sources.fetch_artifacts(
        "v1.1",
        output_dir,
        cache_dir,
        include_trials=False,
        timeout=3,
        allow_stale=False,
    )
    cached_bytes = Path(
        str(artifact_meta(first, "leaderboard-live.json")["local_path"])
    ).read_bytes()
    second = sources.fetch_artifacts(
        "v1.1",
        output_dir,
        cache_dir,
        include_trials=False,
        timeout=3,
        allow_stale=False,
    )
    meta = artifact_meta(second, "leaderboard-live.json")

    assert Path(str(meta["local_path"])).read_bytes() == cached_bytes
    assert meta["cache_reused"] is True
    assert opener.requests[1].get_header("If-none-match") == '"same"'
    assert opener.requests[1].get_header("If-modified-since") == "fixture-date"


def test_refresh_error_does_not_silently_return_last_good_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Raise refresh failures instead of silently returning an old cache."""
    opener = QueueOpener(
        Response(json.dumps(LEADERBOARD).encode()), URLError("offline")
    )
    patch_urlopen(monkeypatch, opener)
    output_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    sources.fetch_artifacts(
        "v1.1",
        output_dir,
        cache_dir,
        include_trials=False,
        timeout=3,
        allow_stale=False,
    )

    with pytest.raises(sources.SourceError, match="offline"):
        sources.fetch_artifacts(
            "v1.1",
            output_dir,
            cache_dir,
            include_trials=False,
            timeout=3,
            allow_stale=False,
        )


def test_allow_stale_is_explicit_and_labeled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Return stale cache data only when explicitly requested."""
    opener = QueueOpener(
        Response(json.dumps(LEADERBOARD).encode()), URLError("offline")
    )
    patch_urlopen(monkeypatch, opener)
    output_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    sources.fetch_artifacts(
        "v1.1",
        output_dir,
        cache_dir,
        include_trials=False,
        timeout=3,
        allow_stale=False,
    )
    stale = sources.fetch_artifacts(
        "v1.1",
        output_dir,
        cache_dir,
        include_trials=False,
        timeout=3,
        allow_stale=True,
    )
    assert stale.get("stale") is True or stale.get("allow_stale") is True


def test_http_error_304_reuses_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reuse cache data when urllib raises a 304 HTTPError."""
    body = json.dumps(LEADERBOARD).encode()
    not_modified = HTTPError(
        "https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json",
        304,
        "Not Modified",
        {"ETag": '"same"'},
        io.BytesIO(),
    )
    patch_urlopen(
        monkeypatch,
        QueueOpener(Response(body, headers={"ETag": '"same"'}), not_modified),
    )
    output_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    sources.fetch_artifacts(
        "v1.1",
        output_dir,
        cache_dir,
        include_trials=False,
        timeout=3,
        allow_stale=False,
    )
    second = sources.fetch_artifacts(
        "v1.1",
        output_dir,
        cache_dir,
        include_trials=False,
        timeout=3,
        allow_stale=False,
    )
    assert artifact_meta(second, "leaderboard-live.json")["cache_reused"] is True


def test_http_error_304_wrong_final_url_rejects_cached_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reject cached data when a 304 response redirects incorrectly."""
    body = json.dumps(LEADERBOARD).encode()
    not_modified = HTTPError(
        "https://deepswe.datacurve.ai/downloads/leaderboard-live.json",
        304,
        "Not Modified",
        {"ETag": '"same"'},
        io.BytesIO(),
    )
    patch_urlopen(
        monkeypatch,
        QueueOpener(Response(body, headers={"ETag": '"same"'}), not_modified),
    )
    output_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    sources.fetch_artifacts(
        "v1.1",
        output_dir,
        cache_dir,
        include_trials=False,
        timeout=3,
        allow_stale=False,
    )

    with pytest.raises(sources.SourceError) as exc_info:
        sources.fetch_artifacts(
            "v1.1",
            output_dir,
            cache_dir,
            include_trials=False,
            timeout=3,
            allow_stale=True,
        )

    assert exc_info.value.code == "version_mismatch"


def test_trials_are_opt_in_and_malformed_payloads_are_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fetch optional trials and reject malformed local artifacts."""
    opener = QueueOpener(
        Response(json.dumps(LEADERBOARD).encode()),
        Response(json.dumps(TRIALS).encode()),
    )
    patch_urlopen(monkeypatch, opener)
    result = sources.fetch_artifacts(
        "v1.1",
        tmp_path / "out",
        tmp_path / "cache",
        include_trials=True,
        timeout=3,
        allow_stale=False,
    )
    assert "trials.json" in result["artifacts"]

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not-json", encoding="utf-8")
    with pytest.raises(sources.SourceError, match="malformed JSON"):
        sources.load_artifact(malformed)

    wrong_shape = tmp_path / "wrong-shape.json"
    wrong_shape.write_text(json.dumps({"rows": {"not": "a-list"}}), encoding="utf-8")
    with pytest.raises(sources.SourceError, match="rows array"):
        sources.load_artifact(wrong_shape)


def test_http_304_without_cache_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reject a 304 response when no valid cache entry exists."""
    patch_urlopen(monkeypatch, QueueOpener(Response(b"", status=304)))
    with pytest.raises(sources.SourceError, match="304"):
        sources.fetch_artifacts(
            "v1.1",
            tmp_path / "out",
            tmp_path / "cache",
            include_trials=False,
            timeout=3,
            allow_stale=False,
        )


def test_payload_version_mismatch_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reject payloads whose declared release differs from the request."""
    mismatched = {**LEADERBOARD, "benchmark_version": "v1.2"}
    patch_urlopen(
        monkeypatch,
        QueueOpener(Response(json.dumps(mismatched).encode())),
    )
    with pytest.raises(sources.SourceError, match=r"expected v1\.1"):
        sources.fetch_artifacts(
            "v1.1",
            tmp_path / "out",
            tmp_path / "cache",
            include_trials=False,
            timeout=3,
            allow_stale=False,
        )


if __name__ == "__main__":
    pytest.main([__file__])
