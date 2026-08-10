"""Immutable, source-local storage for exact DeepSWE artifact bytes.

The cache has no transport or release-discovery behavior.  A caller supplies an
explicit source identity and the exact response bytes; this module stores those
bytes under their SHA-256 digest and keeps only a recursively redacted metadata
projection beside them.
"""

# Copyright 2026 DeepSWE contributors.
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contracts import compact_json
from .diagnostics import redact

_DIGEST_LENGTH = 64


class ArtifactError(ValueError):
    """Base class for immutable cache contract failures."""


class ArtifactNotFoundError(ArtifactError):
    """A requested source or content-addressed artifact is absent."""


class ArtifactIntegrityError(ArtifactError):
    """An immutable artifact, sidecar, index, or manifest is invalid."""


class ArtifactStore:
    """Store exact bytes and redacted DeepSWE provenance metadata.

    ``root`` is a cache directory.  Raw bytes live at
    ``artifacts/<sha256>.raw`` and their sidecar records at
    ``artifacts/<sha256>.meta.json``.  ``index.json`` maps explicit source
    identities to immutable records, while ``manifests`` contains immutable
    snapshots of that index.
    """

    _write_lock = threading.RLock()

    def __init__(self, root: str | os.PathLike[str]) -> None:
        """Initialize a cache rooted at ``root``."""
        self.root = Path(root).expanduser()
        self.artifacts = self.root / "artifacts"
        self.index_path = self.root / "index.json"
        self.manifests = self.root / "manifests"

    @staticmethod
    def hash_bytes(raw: bytes | bytearray | memoryview) -> str:
        """Return the lower-case SHA-256 digest of exact bytes."""
        return hashlib.sha256(_as_bytes(raw)).hexdigest()

    def store(
        self,
        source_key: str,
        raw: bytes | bytearray | memoryview,
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        """Store ``raw`` once and index it under an explicit source identity.

        Raw bytes and their sidecar are first-writer-wins.  The source index is
        intentionally mutable so a source can move to a newer immutable digest;
        older bytes remain available through ``load(artifact_hash=...)``.
        """
        return self._store(source_key, raw, metadata, legacy_unverified=False)

    def promote_legacy(
        self,
        source_key: str,
        raw: bytes | bytearray | memoryview,
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        """Promote caller-owned legacy bytes without deleting that copy.

        The promoted record is marked ``legacy_unverified``.  This method only
        receives bytes, so a caller's legacy file is never opened, replaced, or
        removed by the cache.
        """
        return self._store(source_key, raw, metadata, legacy_unverified=True)

    def load(  # noqa: C901, PLR0912, PLR0915
        self,
        source_key: str | None = None,
        artifact_hash: str | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        """Load and verify an artifact by source identity or SHA-256 hash.

        Missing entries and malformed immutable files raise a specific cache
        error rather than returning unvalidated bytes.  Supplying both
        selectors is allowed only when the index resolves to that hash.
        """
        if source_key is None and artifact_hash is None:
            msg = "source_key or artifact_hash is required"
            raise ValueError(msg)

        indexed: dict[str, Any] | None = None
        selected_hash: str | None = None
        safe_source_key: str | None = None
        if source_key is not None:
            _require_source_key(source_key)
            safe_source_key = _safe_source_key(source_key)
            index = self._read_index(required=True)
            candidate = index.get(safe_source_key)
            if not isinstance(candidate, Mapping):
                msg = f"source key not found: {source_key}"
                raise ArtifactNotFoundError(msg)
            indexed = _plain_mapping(candidate)
            selected_hash = _valid_hash(indexed.get("sha256"))
            if selected_hash is None:
                msg = f"invalid index entry for source: {source_key}"
                raise ArtifactIntegrityError(msg)
            indexed_source = indexed.get("source_key")
            if indexed_source != safe_source_key:
                msg = "source index identity mismatch"
                raise ArtifactIntegrityError(msg)

        if artifact_hash is not None:
            requested_hash = _valid_hash(artifact_hash)
            if requested_hash is None:
                msg = "artifact_hash must be a SHA-256 hex digest"
                raise ValueError(msg)
            if selected_hash is not None and requested_hash != selected_hash:
                msg = "source key does not resolve to artifact_hash"
                raise ArtifactIntegrityError(msg)
            selected_hash = requested_hash

        if selected_hash is None:
            msg = "cache selector did not resolve an artifact hash"
            raise ArtifactIntegrityError(msg)
        raw_path = self.artifacts / f"{selected_hash}.raw"
        sidecar_path = self.artifacts / f"{selected_hash}.meta.json"
        if not raw_path.is_file() or not sidecar_path.is_file():
            msg = f"immutable artifact is incomplete: {selected_hash}"
            raise ArtifactIntegrityError(msg)
        try:
            raw = raw_path.read_bytes()
        except OSError as exc:
            msg = f"cannot read immutable artifact: {selected_hash}"
            raise ArtifactIntegrityError(msg) from exc
        sidecar = self._read_json_object(sidecar_path, "metadata sidecar")
        self._verify_record(sidecar, selected_hash, raw)

        if indexed is not None:
            self._verify_index_record(indexed, sidecar, selected_hash)
            if (
                safe_source_key is not None
                and sidecar.get("source_key") != safe_source_key
            ):
                msg = "metadata source identity mismatch"
                raise ArtifactIntegrityError(msg)
        return raw, sidecar

    def write_manifest(
        self,
        snapshot: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        """Write an immutable JSON snapshot and return its metadata.

        With no argument, the current source index is snapshotted.  A supplied
        mapping lets callers scope a snapshot explicitly.  The manifest name is
        the SHA-256 digest of its exact canonical JSON bytes.
        """
        if snapshot is None:
            snapshot_value: object = self._read_index(required=False)
        else:
            if not isinstance(snapshot, Mapping):
                msg = "snapshot must be a mapping"
                raise TypeError(msg)
            snapshot_value = snapshot
        payload_value = _plain_json({"sources": snapshot_value})
        if not isinstance(payload_value, dict):  # pragma: no cover - defensive
            msg = "manifest projection is not an object"
            raise ArtifactIntegrityError(msg)
        payload = compact_json(payload_value).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        path = self.manifests / f"{digest}.json"
        with self._write_lock:
            _atomic_write(path, payload, immutable=True)
        return {
            "sha256": digest,
            "manifest_sha256": digest,
            "length": len(payload),
            "path": _relative(path, self.root),
            "sources": payload_value["sources"],
        }

    def _store(
        self,
        source_key: str,
        raw_value: bytes | bytearray | memoryview,
        metadata: Mapping[str, object] | None,
        *,
        legacy_unverified: bool,
    ) -> dict[str, Any]:
        _require_source_key(source_key)
        if metadata is not None and not isinstance(metadata, Mapping):
            msg = "metadata must be a mapping"
            raise TypeError(msg)
        raw = _as_bytes(raw_value)
        digest = hashlib.sha256(raw).hexdigest()
        length = len(raw)
        redacted_metadata = _plain_json({} if metadata is None else metadata)
        if not isinstance(redacted_metadata, dict):  # pragma: no cover - defensive
            msg = "metadata projection is not an object"
            raise ArtifactIntegrityError(msg)
        _verify_declared_metadata(redacted_metadata, digest, length)
        safe_source_key = _safe_source_key(source_key)

        raw_path = self.artifacts / f"{digest}.raw"
        sidecar_path = self.artifacts / f"{digest}.meta.json"
        with self._write_lock:
            raw_exists = raw_path.exists()
            sidecar_exists = sidecar_path.exists()
            if raw_exists != sidecar_exists:
                msg = f"immutable artifact is incomplete: {digest}"
                raise ArtifactIntegrityError(msg)

            if raw_exists:
                if not raw_path.is_file() or not sidecar_path.is_file():
                    msg = f"immutable artifact is not a file: {digest}"
                    raise ArtifactIntegrityError(msg)
                try:
                    existing_raw = raw_path.read_bytes()
                except OSError as exc:
                    msg = f"cannot read immutable artifact: {digest}"
                    raise ArtifactIntegrityError(msg) from exc
                if existing_raw != raw:
                    msg = f"immutable artifact bytes differ: {digest}"
                    raise ArtifactIntegrityError(msg)
                existing_record = self._read_json_object(
                    sidecar_path, "metadata sidecar"
                )
                self._verify_record(existing_record, digest, raw)
                record = existing_record
            else:
                record = {
                    "source_key": safe_source_key,
                    "sha256": digest,
                    "length": length,
                    "raw_path": _relative(raw_path, self.root),
                    "metadata_path": _relative(sidecar_path, self.root),
                    "metadata": redacted_metadata,
                    "legacy_unverified": legacy_unverified,
                }
                _atomic_write(raw_path, raw, immutable=True)
                sidecar_bytes = compact_json(record).encode("utf-8")
                _atomic_write(sidecar_path, sidecar_bytes, immutable=True)

            index = self._read_index(required=False)
            # The source index is the only mutable pointer.  Existing raw and
            # sidecar files remain untouched when this source moves to a newer
            # digest.
            index_record = dict(record)
            index_record["source_key"] = safe_source_key
            index[safe_source_key] = index_record
            _atomic_write(
                self.index_path,
                compact_json(index).encode("utf-8"),
                immutable=False,
            )

        return dict(record) | {"source_key": source_key}

    def _read_index(self, *, required: bool) -> dict[str, Any]:
        if not self.index_path.exists():
            if required:
                msg = "source index is missing"
                raise ArtifactNotFoundError(msg)
            return {}
        if not self.index_path.is_file():
            msg = "source index is not a file"
            raise ArtifactIntegrityError(msg)
        return self._read_json_object(self.index_path, "source index")

    @staticmethod
    def _read_json_object(path: Path, label: str) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            msg = f"invalid {label}: {path}"
            raise ArtifactIntegrityError(msg) from exc
        if not isinstance(value, dict):
            msg = f"invalid {label}: {path}"
            raise ArtifactIntegrityError(msg)
        return value

    @staticmethod
    def _verify_record(  # noqa: C901
        record: Mapping[str, object], digest: str, raw: bytes
    ) -> None:
        if _valid_hash(record.get("sha256")) != digest:
            msg = f"metadata hash mismatch: {digest}"
            raise ArtifactIntegrityError(msg)
        length = record.get("length")
        if isinstance(length, bool) or not isinstance(length, int) or length < 0:
            msg = f"metadata length is invalid: {digest}"
            raise ArtifactIntegrityError(msg)
        if length != len(raw):
            msg = f"metadata length mismatch: {digest}"
            raise ArtifactIntegrityError(msg)
        if hashlib.sha256(raw).hexdigest() != digest:
            msg = f"artifact hash mismatch: {digest}"
            raise ArtifactIntegrityError(msg)
        metadata = record.get("metadata")
        if not isinstance(metadata, Mapping):
            msg = f"metadata projection is invalid: {digest}"
            raise ArtifactIntegrityError(msg)
        _verify_declared_metadata(metadata, digest, len(raw))
        source_key = record.get("source_key")
        if not isinstance(source_key, str) or not source_key:
            msg = f"metadata source key is invalid: {digest}"
            raise ArtifactIntegrityError(msg)
        legacy = record.get("legacy_unverified")
        if not isinstance(legacy, bool):
            msg = f"metadata legacy marker is invalid: {digest}"
            raise ArtifactIntegrityError(msg)
        expected_raw = f"artifacts/{digest}.raw"
        expected_meta = f"artifacts/{digest}.meta.json"
        if record.get("raw_path") != expected_raw:
            msg = f"metadata raw path is invalid: {digest}"
            raise ArtifactIntegrityError(msg)
        if record.get("metadata_path") != expected_meta:
            msg = f"metadata sidecar path is invalid: {digest}"
            raise ArtifactIntegrityError(msg)
        try:
            projected = _plain_json(record)
        except (TypeError, ValueError, ArtifactError) as exc:
            msg = f"metadata projection is invalid: {digest}"
            raise ArtifactIntegrityError(msg) from exc
        if projected != dict(record):
            msg = f"metadata is not redacted: {digest}"
            raise ArtifactIntegrityError(msg)

    @staticmethod
    def _verify_index_record(
        indexed: Mapping[str, object],
        sidecar: Mapping[str, object],
        digest: str,
    ) -> None:
        if _valid_hash(indexed.get("sha256")) != digest:
            msg = f"index hash mismatch: {digest}"
            raise ArtifactIntegrityError(msg)
        length = indexed.get("length")
        sidecar_length = sidecar.get("length")
        if length != sidecar_length:
            msg = f"index length mismatch: {digest}"
            raise ArtifactIntegrityError(msg)
        indexed_metadata = indexed.get("metadata")
        sidecar_metadata = sidecar.get("metadata")
        if indexed_metadata != sidecar_metadata:
            msg = f"index metadata mismatch: {digest}"
            raise ArtifactIntegrityError(msg)
        if indexed.get("source_key") != sidecar.get("source_key"):
            msg = f"index source identity mismatch: {digest}"
            raise ArtifactIntegrityError(msg)


def sha256_bytes(raw: bytes | bytearray | memoryview) -> str:
    """Return a deterministic digest for exact bytes."""
    return ArtifactStore.hash_bytes(raw)


def _as_bytes(value: bytes | bytearray | memoryview) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    msg = "raw artifact must be bytes-like"
    raise TypeError(msg)


def _require_source_key(source_key: str) -> None:
    if not isinstance(source_key, str) or not source_key:
        msg = "source_key must be a non-empty string"
        raise ValueError(msg)


def _safe_source_key(source_key: str) -> str:
    projected = _plain_json(source_key)
    if not isinstance(projected, str):  # pragma: no cover - defensive
        msg = "source key projection is not a string"
        raise ArtifactIntegrityError(msg)
    return projected


def _valid_hash(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != _DIGEST_LENGTH:
        return None
    lowered = value.lower()
    if any(char not in "0123456789abcdef" for char in lowered):
        return None
    return lowered


def _verify_declared_metadata(
    metadata: Mapping[str, object], digest: str, length: int
) -> None:
    for key in ("sha256", "artifact_sha256"):
        if key in metadata and metadata[key] is not None:
            declared = _valid_hash(metadata[key])
            if declared != digest:
                msg = f"metadata {key} mismatch: {digest}"
                raise ArtifactIntegrityError(msg)
    for key in ("length", "byte_length", "content_length"):
        if key in metadata and metadata[key] is not None:
            value = metadata[key]
            if isinstance(value, bool) or not isinstance(value, int) or value != length:
                msg = f"metadata {key} mismatch: {digest}"
                raise ArtifactIntegrityError(msg)


def _plain_json(value: object) -> object:
    """Redact recursively and round-trip to ordinary JSON values."""
    projected = redact(value)
    try:
        return json.loads(compact_json(projected))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        msg = "metadata must be JSON-compatible after redaction"
        raise TypeError(msg) from exc


def _plain_mapping(value: Mapping[str, object]) -> dict[str, Any]:
    projected = _plain_json(value)
    if not isinstance(projected, dict):  # pragma: no cover - defensive
        msg = "mapping projection is not an object"
        raise ArtifactIntegrityError(msg)
    return projected


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _atomic_write(path: Path, data: bytes, *, immutable: bool) -> None:
    """Write via a same-directory temporary file and atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file():
            msg = f"target is not a file: {path}"
            raise ArtifactIntegrityError(msg)
        if immutable:
            try:
                existing = path.read_bytes()
            except OSError as exc:
                msg = f"cannot read immutable target: {path}"
                raise ArtifactIntegrityError(msg) from exc
            if existing != data:
                msg = f"immutable target differs: {path}"
                raise ArtifactIntegrityError(msg)
            return

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary: Path | None = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if immutable and path.exists():
            if not path.is_file() or path.read_bytes() != data:
                msg = f"immutable target differs: {path}"
                raise ArtifactIntegrityError(msg)
            return
        temporary.replace(path)
        temporary = None
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Some filesystems do not support directory fsync.  The atomic
            # replacement itself has already completed in that case.
            pass
    finally:
        if temporary is not None:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()


__all__ = [
    "ArtifactError",
    "ArtifactIntegrityError",
    "ArtifactNotFoundError",
    "ArtifactStore",
    "sha256_bytes",
]
