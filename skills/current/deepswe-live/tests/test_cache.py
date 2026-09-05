"""Immutable DeepSWE cache and provenance contract tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from deepswe import cache

SOURCE_KEY = "https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json"
BODY = b'{"benchmark":"DeepSWE","rows":[{"model":"fixture"}]}'
METADATA = {
    "benchmark": "DeepSWE",
    "release": "v1.1",
    "artifact": "leaderboard-live.json",
    "url": SOURCE_KEY,
    "etag": '"fixture-etag"',
    "last_modified": "Sat, 25 Jul 2026 03:13:49 GMT",
}


def test_store_writes_exact_content_addressed_bytes_and_provenance(
    tmp_path: Path,
) -> None:
    store = cache.ArtifactStore(tmp_path)

    record = store.store(SOURCE_KEY, BODY, METADATA)
    digest = hashlib.sha256(BODY).hexdigest()
    raw_path = tmp_path / "artifacts" / f"{digest}.raw"
    sidecar_path = tmp_path / "artifacts" / f"{digest}.meta.json"

    assert raw_path.read_bytes() == BODY
    assert record["sha256"] == digest
    assert record["length"] == len(BODY)
    assert raw_path.exists()
    assert sidecar_path.exists()

    sidecar = cast(
        "dict[str, object]", json.loads(sidecar_path.read_text(encoding="utf-8"))
    )
    assert sidecar["sha256"] == digest
    assert sidecar["length"] == len(BODY)
    sidecar_meta = cast("dict[str, object]", sidecar["metadata"])
    assert sidecar_meta["release"] == "v1.1"
    assert sidecar_meta["artifact"] == "leaderboard-live.json"
    assert sidecar_meta["etag"] == '"fixture-etag"'

    index = cast(
        "dict[str, dict[str, object]]",
        json.loads((tmp_path / "index.json").read_text(encoding="utf-8")),
    )
    assert index[SOURCE_KEY]["sha256"] == digest
    assert index[SOURCE_KEY]["metadata"] == sidecar["metadata"]

    loaded_body, loaded = store.load(source_key=SOURCE_KEY)
    assert loaded_body == BODY
    assert loaded == sidecar
    by_hash_body, by_hash = store.load(artifact_hash=digest)
    assert by_hash_body == BODY
    assert by_hash == sidecar


def test_metadata_urls_and_nested_credentials_are_redacted_everywhere(
    tmp_path: Path,
) -> None:
    source_key = "https://example.test/data.json?access_token=source-secret&keep=value"
    metadata = {
        "url": "https://example.test/data.json?api_key=url-secret&keep=value",
        "headers": {
            "Authorization": "Bearer header-secret",
            "Cookie": "session=cookie-secret",
        },
        "nested": [{"token": "nested-secret"}],
        "release": "v1.1",
        "artifact": "leaderboard-live.json",
    }
    store = cache.ArtifactStore(tmp_path)
    record = store.store(source_key, BODY, metadata)
    digest = record["sha256"]
    assert isinstance(digest, str)

    sidecar_path = tmp_path / "artifacts" / f"{digest}.meta.json"
    sidecar_text = sidecar_path.read_text(encoding="utf-8")
    index_text = (tmp_path / "index.json").read_text(encoding="utf-8")
    manifest = store.write_manifest()
    manifest_path_val = cast("str", manifest["path"])
    manifest_text = (tmp_path / manifest_path_val).read_text(encoding="utf-8")

    for persisted in (sidecar_text, index_text, manifest_text):
        assert "source-secret" not in persisted
        assert "url-secret" not in persisted
        assert "header-secret" not in persisted
        assert "cookie-secret" not in persisted
        assert "nested-secret" not in persisted
    sidecar = cast("dict[str, object]", json.loads(sidecar_text))
    assert sidecar["source_key"] == (
        "https://example.test/data.json?access_token=<redacted>&keep=value"
    )
    sidecar_meta = cast("dict[str, object]", sidecar["metadata"])
    assert (
        sidecar_meta["url"]
        == "https://example.test/data.json?api_key=<redacted>&keep=value"
    )
    sidecar_headers = cast("dict[str, object]", sidecar_meta["headers"])
    assert sidecar_headers["Authorization"] == "<redacted>"
    sidecar_nested = cast("list[dict[str, object]]", sidecar_meta["nested"])
    assert sidecar_nested[0]["token"] == "<redacted>"  # noqa: S105


def test_atomic_failure_leaves_no_partial_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_replace(_source: object, _destination: object) -> None:
        msg = "simulated atomic replace failure"
        raise OSError(msg)

    monkeypatch.setattr(Path, "replace", fail_replace)
    store = cache.ArtifactStore(tmp_path)
    digest = hashlib.sha256(BODY).hexdigest()

    with pytest.raises(OSError, match="simulated atomic replace failure"):
        _ = store.store(SOURCE_KEY, BODY, METADATA)

    assert not (tmp_path / "artifacts" / f"{digest}.raw").exists()
    assert not (tmp_path / "artifacts" / f"{digest}.meta.json").exists()
    assert not list((tmp_path / "artifacts").glob("*.tmp"))


def test_tampered_or_missing_immutable_files_fail_closed(tmp_path: Path) -> None:
    store = cache.ArtifactStore(tmp_path)
    record = store.store(SOURCE_KEY, BODY, METADATA)
    digest = record["sha256"]
    assert isinstance(digest, str)
    raw_path = tmp_path / "artifacts" / f"{digest}.raw"
    sidecar_path = tmp_path / "artifacts" / f"{digest}.meta.json"

    _ = raw_path.write_bytes(BODY + b"tampered")
    with pytest.raises(cache.ArtifactIntegrityError):
        _ = store.load(artifact_hash=digest)

    _ = raw_path.write_bytes(BODY)
    sidecar_path.unlink()
    with pytest.raises(cache.ArtifactIntegrityError):
        _ = store.load(artifact_hash=digest)


def test_raw_and_sidecar_are_immutable_but_source_index_can_move(
    tmp_path: Path,
) -> None:
    store = cache.ArtifactStore(tmp_path)
    first = store.store(SOURCE_KEY, BODY, METADATA)
    digest = first["sha256"]
    assert isinstance(digest, str)
    sidecar_path = tmp_path / "artifacts" / f"{digest}.meta.json"
    original_sidecar = sidecar_path.read_bytes()

    _ = store.store(SOURCE_KEY, BODY, {**METADATA, "etag": "changed"})
    assert sidecar_path.read_bytes() == original_sidecar

    newer_body = BODY + b"\n"
    newer = store.store(SOURCE_KEY, newer_body, METADATA)
    assert newer["sha256"] != digest
    assert (tmp_path / "artifacts" / f"{digest}.raw").read_bytes() == BODY
    loaded, _ = store.load(source_key=SOURCE_KEY)
    assert loaded == newer_body
    old_loaded, _ = store.load(artifact_hash=digest)
    assert old_loaded == BODY


def test_legacy_promotion_preserves_caller_file_and_marks_record(
    tmp_path: Path,
) -> None:
    legacy_path = tmp_path / "legacy" / "v1.1" / "leaderboard-live.json"
    legacy_path.parent.mkdir(parents=True)
    _ = legacy_path.write_bytes(BODY)

    store = cache.ArtifactStore(tmp_path / "new-cache")
    record = store.promote_legacy(
        SOURCE_KEY,
        legacy_path.read_bytes(),
        {**METADATA, "legacy_path": str(legacy_path)},
    )

    assert legacy_path.read_bytes() == BODY
    assert record["legacy_unverified"] is True
    loaded, metadata = store.load(source_key=SOURCE_KEY)
    assert loaded == BODY
    assert metadata["legacy_unverified"] is True
    metadata_inner = cast("dict[str, object]", metadata["metadata"])
    assert metadata_inner["legacy_path"] == str(legacy_path)


def test_manifest_is_content_addressed_and_immutable(tmp_path: Path) -> None:
    store = cache.ArtifactStore(tmp_path)
    _ = store.store(SOURCE_KEY, BODY, METADATA)

    first = store.write_manifest()
    second = store.write_manifest()
    assert first == second
    manifest_path_val = cast("str", first["path"])
    manifest_path = tmp_path / manifest_path_val
    manifest_bytes = manifest_path.read_bytes()
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    assert first["sha256"] == digest
    assert first["manifest_sha256"] == digest
    assert first["length"] == len(manifest_bytes)
    payload = cast(
        "dict[str, dict[str, dict[str, object]]]", json.loads(manifest_bytes)
    )
    assert payload["sources"][SOURCE_KEY]["sha256"] == hashlib.sha256(BODY).hexdigest()
