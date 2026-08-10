"""Contract tests for the AA-local immutable artifact store."""

# ruff: noqa: CPY001, INP001, D103, S101

import hashlib
import json
from pathlib import Path

import _path  # noqa: F401
import pytest
from artificial_analysis import provenance
from artificial_analysis.diagnostics import REDACTED
from artificial_analysis.provenance import (
    ArtifactIntegrityError,
    ArtifactStore,
)


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "cache")


def test_hash_path_and_exact_bytes_are_deterministic(store: ArtifactStore) -> None:
    raw = b"rsc\x00payload\xff"
    digest = hashlib.sha256(raw).hexdigest()

    record = store.store("coding", raw, {"url": "https://example.test/data"})

    assert store.hash_bytes(raw) == digest
    assert record["sha256"] == digest
    assert record["length"] == len(raw)
    assert (store.root / "artifacts" / f"{digest}.raw").read_bytes() == raw
    loaded_raw, _ = store.load(source_key="coding")
    assert loaded_raw == raw


def test_sidecar_index_and_immutable_manifest_are_written(store: ArtifactStore) -> None:
    record = store.store("models", b"snapshot", {"scope": "public"})
    digest = str(record["sha256"])
    sidecar_path = store.root / "artifacts" / f"{digest}.meta.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    index = json.loads(store.index_path.read_text(encoding="utf-8"))

    assert sidecar == record
    assert index["models"]["sha256"] == digest
    manifest = store.write_manifest()
    manifest_path = store.root / "manifests" / f"{manifest['sha256']}.json"
    manifest_bytes = manifest_path.read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == manifest["sha256"]
    assert json.loads(manifest_bytes)["sources"]["models"]["sha256"] == digest
    assert store.write_manifest() == manifest


def test_atomic_writes_use_replace_and_leave_no_temp_files(
    store: ArtifactStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replaced: list[Path] = []
    original_replace = provenance.os.replace

    def track_replace(
        source: str | bytes | Path, destination: str | bytes | Path
    ) -> None:
        replaced.append(Path(destination))
        original_replace(source, destination)

    monkeypatch.setattr(provenance.os, "replace", track_replace)
    store.store("atomic", b"payload", {"kind": "test"})

    assert {path.name for path in replaced} >= {
        "index.json",
        f"{store.hash_bytes(b'payload')}.raw",
        f"{store.hash_bytes(b'payload')}.meta.json",
    }
    assert not list(store.root.rglob("*.tmp"))


def test_redaction_is_recursive_and_does_not_persist_credentials(
    store: ArtifactStore,
) -> None:
    record = store.store(
        "safe",
        b"bytes",
        {
            "api_key": "top-secret",
            "nested": [
                {"Authorization": "Bearer nested-secret"},
                {"url": "https://example.test/?token=url-secret&keep=1"},
            ],
            "output_tokens": 12,
        },
    )
    sidecar_text = (
        store.root / "artifacts" / f"{record['sha256']}.meta.json"
    ).read_text(encoding="utf-8")
    sidecar = json.loads(sidecar_text)

    assert "top-secret" not in sidecar_text
    assert "nested-secret" not in sidecar_text
    assert "url-secret" not in sidecar_text
    assert sidecar["metadata"] == {
        "api_key": REDACTED,
        "nested": [
            {"Authorization": REDACTED},
            {"url": "https://example.test/?token=[REDACTED]&keep=1"},
        ],
        "output_tokens": 12,
    }


def test_tampered_or_missing_immutable_files_fail_closed(store: ArtifactStore) -> None:
    record = store.store("tamper", b"untouched", {})
    digest = str(record["sha256"])
    raw_path = store.root / "artifacts" / f"{digest}.raw"
    sidecar_path = store.root / "artifacts" / f"{digest}.meta.json"

    raw_path.write_bytes(b"changed")
    with pytest.raises(ArtifactIntegrityError):
        store.load(artifact_hash=digest)

    raw_path.write_bytes(b"untouched")
    sidecar_path.unlink()
    with pytest.raises(ArtifactIntegrityError):
        store.load(artifact_hash=digest)


def test_immutable_artifact_does_not_overwrite_first_sidecar(
    store: ArtifactStore,
) -> None:
    first = store.store("immutable", b"same", {"version": 1})
    sidecar_path = store.root / "artifacts" / f"{first['sha256']}.meta.json"
    first_sidecar = sidecar_path.read_bytes()

    second = store.store("immutable", b"same", {"version": 2})

    assert second["metadata"] == {"version": 1}
    assert sidecar_path.read_bytes() == first_sidecar


def test_legacy_promotion_keeps_caller_files_and_marks_record(
    store: ArtifactStore,
    tmp_path: Path,
) -> None:
    legacy_raw = tmp_path / "legacy-response.bin"
    legacy_meta = tmp_path / "legacy-response.json"
    legacy_raw.write_bytes(b"legacy bytes")
    legacy_meta.write_text('{"source": "legacy"}', encoding="utf-8")

    record = store.promote_legacy(
        "legacy",
        legacy_raw.read_bytes(),
        {"source": "legacy", "api_key": "not-persisted"},
    )

    assert record["legacy_unverified"] is True
    assert legacy_raw.read_bytes() == b"legacy bytes"
    assert legacy_meta.read_text(encoding="utf-8") == '{"source": "legacy"}'
    loaded_raw, loaded_record = store.load(source_key="legacy")
    assert loaded_raw == b"legacy bytes"
    assert loaded_record["legacy_unverified"] is True
    assert loaded_record["metadata"]["api_key"] == REDACTED
