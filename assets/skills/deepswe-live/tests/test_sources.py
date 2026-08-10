"""Deterministic source/version/cache contract tests (no live network)."""
# ruff: noqa: CPY001, INP001, RUF043, S101

from __future__ import annotations

import hashlib
import io
import json
from typing import TYPE_CHECKING, NoReturn, Self
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
    fallback = sources.resolve_version(None)
    assert fallback["version"] == "v1.1"
    assert fallback["resolved_from"] == "default"

    monkeypatch.setenv("DEEPSWE_DEFAULT_VERSION", "v1.2")
    configured = sources.resolve_version(None)
    assert configured["version"] == "v1.2"
    assert configured["resolved_from"] == "env"
    latest = sources.resolve_version("latest")
    assert latest["version"] == "v1.2"
    assert latest["source"] == "env"


def test_latest_resolution_has_no_runtime_release_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep latest offline; releases come only from the configured fallback."""
    calls: list[object] = []

    def unexpected_network(*args: object, **kwargs: object) -> NoReturn:
        calls.append((args, kwargs))
        msg = "latest resolution must not discover releases"
        raise AssertionError(msg)

    monkeypatch.setattr(sources, "urlopen", unexpected_network)
    monkeypatch.delenv("DEEPSWE_DEFAULT_VERSION", raising=False)
    resolved = sources.resolve_version("latest")
    assert resolved["benchmark_version"] == "v1.1"
    assert calls == []


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


def test_fetch_stores_immutable_hash_refs_and_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Persist exact bytes while retaining versioned materialized paths."""
    body = json.dumps(LEADERBOARD, separators=(",", ":")).encode()
    patch_urlopen(
        monkeypatch,
        QueueOpener(
            Response(
                body,
                headers={"ETag": '"immutable"', "Last-Modified": "fixture-date"},
            )
        ),
    )
    cache_dir = tmp_path / "cache"
    result = sources.fetch_artifacts("v1.1", tmp_path / "out", cache_dir)
    metadata = artifact_meta(result, "leaderboard-live.json")
    digest = hashlib.sha256(body).hexdigest()
    assert metadata["sha256"] == digest
    assert metadata["artifact_sha256"] == digest
    assert metadata["length"] == len(body)
    assert metadata["legacy_unverified"] is False
    raw_path = cache_dir / str(metadata["raw_path"])
    sidecar_path = cache_dir / str(metadata["metadata_path"])
    manifest_path = cache_dir / str(metadata["manifest_path"])
    assert raw_path.read_bytes() == body
    assert sidecar_path.is_file()
    assert manifest_path.is_file()
    index = json.loads((cache_dir / "index.json").read_text(encoding="utf-8"))
    source_key = str(metadata["url"])
    assert index[source_key]["sha256"] == digest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["sources"][source_key]["sha256"] == digest
    assert Path(str(metadata["cache_path"])).read_bytes() == body
    assert Path(str(metadata["local_path"])).read_bytes() == body


def test_304_rejects_tampered_immutable_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A not-modified response cannot reuse tampered content-addressed bytes."""
    body = json.dumps(LEADERBOARD).encode()
    patch_urlopen(monkeypatch, QueueOpener(Response(body, headers={"ETag": '"same"'})))
    cache_dir = tmp_path / "cache"
    first = sources.fetch_artifacts("v1.1", tmp_path / "out", cache_dir)
    metadata = artifact_meta(first, "leaderboard-live.json")
    (cache_dir / str(metadata["raw_path"])).write_bytes(body + b"tampered")
    patch_urlopen(
        monkeypatch,
        QueueOpener(Response(b"", status=304, headers={"ETag": '"same"'})),
    )
    with pytest.raises(sources.SourceError) as exc_info:
        sources.fetch_artifacts("v1.1", tmp_path / "out", cache_dir)
    assert exc_info.value.code == "cache_invalid"


def test_304_rejects_missing_immutable_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A missing source index is visible instead of falling back to legacy bytes."""
    body = json.dumps(LEADERBOARD).encode()
    patch_urlopen(monkeypatch, QueueOpener(Response(body, headers={"ETag": '"same"'})))
    cache_dir = tmp_path / "cache"
    sources.fetch_artifacts("v1.1", tmp_path / "out", cache_dir)
    (cache_dir / "index.json").unlink()
    patch_urlopen(
        monkeypatch,
        QueueOpener(Response(b"", status=304, headers={"ETag": '"same"'})),
    )
    with pytest.raises(sources.SourceError, match="index"):
        sources.fetch_artifacts("v1.1", tmp_path / "out", cache_dir)


def test_304_rejects_missing_validator_after_legacy_promotion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Promotion does not make a validator-less legacy cache conditional-safe."""
    body = json.dumps(LEADERBOARD).encode()
    cache_dir = tmp_path / "cache"
    legacy_path = cache_dir / "v1.1" / "leaderboard-live.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(body)
    legacy_metadata = {
        "benchmark": "DeepSWE",
        "benchmark_version": "v1.1",
        "artifact": "leaderboard-live.json",
        "url": "https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json",
    }
    legacy_path.with_name(legacy_path.name + ".meta.json").write_text(
        json.dumps(legacy_metadata), encoding="utf-8"
    )
    patch_urlopen(monkeypatch, QueueOpener(Response(b"", status=304, headers={})))
    with pytest.raises(sources.SourceError, match="validator"):
        sources.fetch_artifacts("v1.1", tmp_path / "out", cache_dir)


def test_valid_legacy_cache_is_promoted_without_deleting_materialized_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Legacy version/artifact files survive immutable promotion."""
    body = json.dumps(LEADERBOARD).encode()
    cache_dir = tmp_path / "cache"
    legacy_path = cache_dir / "v1.1" / "leaderboard-live.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(body)
    legacy_metadata = {
        "benchmark": "DeepSWE",
        "benchmark_version": "v1.1",
        "artifact": "leaderboard-live.json",
        "url": "https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json",
        "etag": '"legacy"',
    }
    legacy_meta_path = legacy_path.with_name(legacy_path.name + ".meta.json")
    legacy_meta_path.write_text(json.dumps(legacy_metadata), encoding="utf-8")
    patch_urlopen(
        monkeypatch,
        QueueOpener(Response(b"", status=304, headers={"ETag": '"legacy"'})),
    )
    result = sources.fetch_artifacts("v1.1", tmp_path / "out", cache_dir)
    metadata = artifact_meta(result, "leaderboard-live.json")
    assert metadata["legacy_unverified"] is True
    assert legacy_path.read_bytes() == body
    assert json.loads(legacy_meta_path.read_text(encoding="utf-8")) == legacy_metadata
    assert (cache_dir / "index.json").is_file()
    assert list((cache_dir / "manifests").glob("*.json"))


def test_immutable_metadata_is_redacted_in_sidecar_index_and_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Credentials in a source identity never reach immutable projections."""
    monkeypatch.setattr(
        sources,
        "ARTIFACT_BASE_URL",
        "https://deepswe.datacurve.ai/artifacts?access_token=source-secret",
    )
    body = json.dumps(LEADERBOARD).encode()
    patch_urlopen(monkeypatch, QueueOpener(Response(body)))
    cache_dir = tmp_path / "cache"
    result = sources.fetch_artifacts("v1.1", tmp_path / "out", cache_dir)
    metadata = artifact_meta(result, "leaderboard-live.json")
    persisted = [
        (cache_dir / str(metadata["metadata_path"])).read_text(encoding="utf-8"),
        (cache_dir / "index.json").read_text(encoding="utf-8"),
        (cache_dir / str(metadata["manifest_path"])).read_text(encoding="utf-8"),
    ]
    assert all("source-secret" not in text for text in persisted)


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


def test_strict_payload_validation_preserves_unknown_fields_and_rejects_future_schema(
    tmp_path: Path,
) -> None:
    """Validate shape/identity while retaining source-owned extension fields."""
    path = tmp_path / "v1.1" / "leaderboard-live.json"
    path.parent.mkdir()
    payload = {
        "benchmark": "DeepSWE",
        "benchmark_version": "v1.1",
        "artifact": "leaderboard-live.json",
        "rows": [{"model": "fixture", "x_extension": {"keep": True}}],
        "top_extension": ["keep"],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert sources.load_artifact(path) == payload

    future = dict(payload)
    future["schema_version"] = 2
    path.write_text(json.dumps(future), encoding="utf-8")
    with pytest.raises(sources.SourceError) as exc_info:
        sources.load_artifact(path)
    assert exc_info.value.code == "unsupported_schema"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "JSON object"),
        ({"rows": [{"ok": True}], "count": 2}, "count"),
        ({"rows": [{"ok": True}], "benchmark": "Other"}, "benchmark"),
        ({"rows": [{"ok": True}], "artifact": "trials.json"}, "artifact"),
        ({"rows": [{"ok": True}], "benchmark_version": "v1.2"}, "version"),
    ],
)
def test_strict_payload_validation_reports_one_structural_error(
    tmp_path: Path, payload: object, message: str
) -> None:
    """Malformed identity/shape payloads produce one stable source failure."""
    path = tmp_path / "v1.1" / "leaderboard-live.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(sources.SourceError, match=message):
        sources.load_artifact(path)


if __name__ == "__main__":
    pytest.main([__file__])
