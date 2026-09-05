# Copyright (c) 2026 anntnzrb
"""Immutable, source-local artifact storage for Artificial Analysis.

The store deliberately has no transport knowledge.  Callers provide exact bytes and
source metadata; this module keeps the bytes content-addressed and stores only a
credential-safe metadata projection beside them.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import NoReturn, cast

from .contracts import compact_json
from .diagnostics import redact

SHA256_HEX_LENGTH = 64


def _raise_value(message: str) -> NoReturn:
    raise ValueError(message)


def _raise_type(message: str, *, cause: BaseException | None = None) -> NoReturn:
    """Raise TypeError, chaining an optional cause."""
    if cause is None:
        raise TypeError(message)
    raise TypeError(message) from cause


def _raise_not_found(message: str) -> NoReturn:
    raise ArtifactNotFoundError(message)


def _raise_integrity(
    message: str,
    *,
    cause: BaseException | None = None,
) -> NoReturn:
    if cause is None:
        raise ArtifactIntegrityError(message)
    raise ArtifactIntegrityError(message) from cause


class ArtifactError(ValueError):
    """Base class for cache contract failures."""


class ArtifactNotFoundError(ArtifactError):
    """A requested source or artifact is not present."""


class ArtifactIntegrityError(ArtifactError):
    """An immutable artifact, sidecar, index, or manifest is invalid."""


class ArtifactStore:
    """Store immutable raw artifacts and credential-safe provenance metadata.

    ``root`` is a cache directory.  Raw bytes are written under ``artifacts``;
    source-key mappings are kept in ``index.json`` and snapshots are written to
    immutable files under ``manifests``.
    """

    _write_lock: threading.RLock = threading.RLock()

    def __init__(self, root: str | os.PathLike[str]) -> None:
        """Initialize an artifact store rooted at ``root``."""
        self.root: Path = Path(root)
        self.artifacts: Path = self.root / "artifacts"
        self.index_path: Path = self.root / "index.json"
        self.manifests: Path = self.root / "manifests"

    @staticmethod
    def hash_bytes(raw: bytes | bytearray | memoryview) -> str:
        """Return the lower-case SHA-256 digest of the exact bytes supplied."""
        return hashlib.sha256(_as_bytes(raw)).hexdigest()

    def store(
        self,
        source_key: str,
        raw: bytes | bytearray | memoryview,
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Store ``raw`` once and index it under ``source_key``.

        Raw and sidecar files are immutable.  Repeating a write for an existing
        digest returns the existing record and never rewrites its sidecar.  The
        source index itself is mutable, so a source can point to a newer digest
        while older content remains available by hash.
        """
        return self._store(source_key, raw, metadata, legacy_unverified=False)

    def promote_legacy(
        self,
        source_key: str,
        raw: bytes | bytearray | memoryview,
        metadata: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Promote caller-owned legacy bytes without deleting the legacy copy.

        Promoted records are explicitly marked ``legacy_unverified``.  Existing
        verified records are never downgraded when the same bytes are promoted
        again.
        """
        return self._store(source_key, raw, metadata, legacy_unverified=True)

    def load(
        self,
        source_key: str | None = None,
        artifact_hash: str | None = None,
    ) -> tuple[bytes, dict[str, object]]:
        """Load and verify an artifact by source key or SHA-256 hash.

        Exactly one selector is normally needed.  Supplying both is allowed only
        when the source index resolves to the requested hash.  Any missing or
        tampered immutable byte/sidecar fails closed with
        :class:`ArtifactIntegrityError`.
        """
        indexed, selected_hash = self._select_artifact(source_key, artifact_hash)
        raw = self._read_artifact(selected_hash)
        sidecar_path = self.artifacts / f"{selected_hash}.meta.json"
        sidecar = self._read_json_object(sidecar_path, "metadata sidecar")
        self._verify_record(sidecar, selected_hash, raw)
        if indexed is not None:
            self._verify_index_record(indexed, sidecar, selected_hash)
        return raw, sidecar

    def _select_artifact(
        self,
        source_key: str | None,
        artifact_hash: str | None,
    ) -> tuple[dict[str, object] | None, str]:
        if source_key is None and artifact_hash is None:
            _raise_value("source_key or artifact_hash is required")

        indexed: dict[str, object] | None = None
        selected_hash: str | None = None
        if source_key is not None:
            _require_source_key(source_key)
            index = self._read_index(required=True)
            candidate = index.get(source_key)
            if not isinstance(candidate, Mapping):
                _raise_not_found(f"source key not found: {source_key}")
            indexed = _plain_mapping(cast("Mapping[str, object]", candidate))
            selected_hash = _valid_hash(indexed.get("sha256"))
            if selected_hash is None:
                _raise_integrity(f"invalid index entry for source: {source_key}")

        if artifact_hash is not None:
            requested_hash = _valid_hash(artifact_hash)
            if requested_hash is None:
                _raise_value("artifact_hash must be a SHA-256 hex digest")
            if selected_hash is not None and requested_hash != selected_hash:
                _raise_integrity("source key does not resolve to artifact_hash")
            selected_hash = requested_hash

        if selected_hash is None:  # pragma: no cover - guarded above
            _raise_integrity("artifact selector did not resolve")
        return indexed, selected_hash

    def _read_artifact(self, digest: str) -> bytes:
        raw_path = self.artifacts / f"{digest}.raw"
        sidecar_path = self.artifacts / f"{digest}.meta.json"
        if not raw_path.is_file() or not sidecar_path.is_file():
            _raise_integrity(f"immutable artifact is incomplete: {digest}")
        try:
            return raw_path.read_bytes()
        except OSError as exc:
            _raise_integrity(f"cannot read immutable artifact: {digest}", cause=exc)

    def write_manifest(
        self,
        snapshot: object = None,
    ) -> dict[str, object]:
        """Write an immutable JSON snapshot and return its plain metadata.

        With no argument, the current source index is snapshotted.  A supplied
        mapping is useful for callers that want a deliberately scoped snapshot.
        The manifest filename is the SHA-256 of its exact canonical JSON bytes.
        """
        if snapshot is None:
            snapshot_value: object = self._read_index(required=False)
        else:
            if not isinstance(snapshot, Mapping):
                _raise_type("snapshot must be a mapping")
            snapshot_value = cast("object", snapshot)
        payload_value = _plain_json({"sources": snapshot_value})
        if not isinstance(payload_value, dict):  # pragma: no cover - defensive
            _raise_integrity("manifest projection is not an object")
        payload = compact_json(cast("object", payload_value)).encode("utf-8")
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
        metadata: object,
        *,
        legacy_unverified: bool,
    ) -> dict[str, object]:
        _require_source_key(source_key)
        if metadata is not None and not isinstance(metadata, Mapping):
            _raise_type("metadata must be a mapping")
        raw = _as_bytes(raw_value)
        digest = hashlib.sha256(raw).hexdigest()
        length = len(raw)
        if metadata is None:
            redacted_metadata = _plain_json(dict[str, object]())
        else:
            redacted_metadata = _plain_json(cast("object", metadata))
        if not isinstance(redacted_metadata, dict):  # pragma: no cover - defensive
            _raise_integrity("metadata projection is not an object")

        raw_path = self.artifacts / f"{digest}.raw"
        sidecar_path = self.artifacts / f"{digest}.meta.json"
        with self._write_lock:
            raw_exists = raw_path.exists()
            sidecar_exists = sidecar_path.exists()
            if raw_exists != sidecar_exists:
                _raise_integrity(f"immutable artifact is incomplete: {digest}")

            if raw_exists:
                if not raw_path.is_file() or not sidecar_path.is_file():
                    _raise_integrity(f"immutable artifact is not a file: {digest}")
                try:
                    existing_raw = raw_path.read_bytes()
                except OSError as exc:
                    _raise_integrity(
                        f"cannot read immutable artifact: {digest}", cause=exc
                    )
                if existing_raw != raw:
                    _raise_integrity(f"immutable artifact bytes differ: {digest}")
                existing_record = self._read_json_object(
                    sidecar_path, "metadata sidecar"
                )
                self._verify_record(existing_record, digest, raw)
                record: dict[str, object] = existing_record
            else:
                record = {
                    "source_key": source_key,
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
            # Keep the first immutable sidecar but make the source-key mapping
            # explicit for every source that points to this digest.
            index_record = dict(record)
            index_record["source_key"] = source_key
            index[source_key] = index_record
            _atomic_write(
                self.index_path,
                compact_json(index).encode("utf-8"),
                immutable=False,
            )

        return dict(record) | {"source_key": source_key}

    def _read_index(self, *, required: bool) -> dict[str, object]:
        if not self.index_path.exists():
            if required:
                _raise_not_found("source index is missing")
            return {}
        if not self.index_path.is_file():
            _raise_integrity("source index is not a file")
        return self._read_json_object(self.index_path, "source index")

    @staticmethod
    def _read_json_object(path: Path, label: str) -> dict[str, object]:
        try:
            value = cast("object", json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            _raise_integrity(f"invalid {label}: {path}", cause=exc)
        if not isinstance(value, dict):
            _raise_integrity(f"invalid {label}: {path}")
        return cast("dict[str, object]", value)

    @staticmethod
    def _verify_record(record: Mapping[str, object], digest: str, raw: bytes) -> None:
        if _valid_hash(record.get("sha256")) != digest:
            _raise_integrity(f"metadata hash mismatch: {digest}")
        length = record.get("length")
        if isinstance(length, bool) or not isinstance(length, int) or length < 0:
            _raise_integrity(f"metadata length is invalid: {digest}")
        if length != len(raw):
            _raise_integrity(f"metadata length mismatch: {digest}")
        if hashlib.sha256(raw).hexdigest() != digest:
            _raise_integrity(f"artifact hash mismatch: {digest}")
        metadata = record.get("metadata")
        if not isinstance(metadata, Mapping):
            _raise_integrity(f"metadata projection is invalid: {digest}")
        source_key = record.get("source_key")
        if not isinstance(source_key, str) or not source_key:
            _raise_integrity(f"metadata source key is invalid: {digest}")
        legacy = record.get("legacy_unverified")
        if not isinstance(legacy, bool):
            _raise_integrity(f"metadata legacy marker is invalid: {digest}")

    @staticmethod
    def _verify_index_record(
        indexed: Mapping[str, object],
        sidecar: Mapping[str, object],
        digest: str,
    ) -> None:
        # The index is a mutable lookup, but its immutable identity fields must
        # agree with the sidecar before bytes are handed to a caller.
        if _valid_hash(indexed.get("sha256")) != digest:
            _raise_integrity(f"index hash mismatch: {digest}")
        length = indexed.get("length")
        sidecar_length = sidecar.get("length")
        if length != sidecar_length:
            _raise_integrity(f"index length mismatch: {digest}")
        indexed_metadata = indexed.get("metadata")
        sidecar_metadata = sidecar.get("metadata")
        if indexed_metadata != sidecar_metadata:
            _raise_integrity(f"index metadata mismatch: {digest}")


def sha256_bytes(raw: bytes | bytearray | memoryview) -> str:
    """Compatibility helper for callers that need a deterministic digest."""
    return ArtifactStore.hash_bytes(raw)


def _as_bytes(value: bytes | bytearray | memoryview) -> bytes:
    """Return the value as immutable bytes."""
    if isinstance(value, bytes):
        return value
    return bytes(value)


def _require_source_key(source_key: object) -> None:
    """Reject empty or non-string source keys."""
    if not isinstance(source_key, str) or not source_key:
        _raise_value("source_key must be a non-empty string")


def _valid_hash(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != SHA256_HEX_LENGTH:
        return None
    lowered = value.lower()
    if any(char not in "0123456789abcdef" for char in lowered):
        return None
    return lowered


def _plain_json(value: object) -> object:
    """Redact recursively, then round-trip to ordinary JSON values."""
    projected = redact(value)
    try:
        return cast("object", json.loads(compact_json(projected)))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        _raise_type("metadata must be JSON-compatible after redaction", cause=exc)


def _plain_mapping(value: Mapping[str, object]) -> dict[str, object]:
    """Project a mapping to plain JSON-compatible values."""
    projected = _plain_json(value)
    if not isinstance(projected, dict):  # pragma: no cover - defensive
        _raise_integrity("mapping projection is not an object")
    return cast("dict[str, object]", projected)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _atomic_write(path: Path, data: bytes, *, immutable: bool) -> None:
    """Write bytes via same-directory temp + fsync + atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _ensure_immutable(path, data) if immutable else _ensure_file(path)
        if immutable:
            return

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            _ = handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # A caller cannot overwrite an immutable destination through this API.
        # The lock serializes local writers; a pre-existing target is checked
        # again immediately before replace to preserve first-writer-wins.
        if immutable and path.exists():
            _ensure_immutable(path, data)
            return
        _ = temporary.replace(path)
        temporary = None
        _fsync_directory(path.parent)
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink()


def _ensure_file(path: Path) -> None:
    if not path.is_file():
        _raise_integrity(f"target is not a file: {path}")


def _ensure_immutable(path: Path, data: bytes) -> None:
    _ensure_file(path)
    try:
        existing = path.read_bytes()
    except OSError as exc:
        _raise_integrity(f"cannot read immutable target: {path}", cause=exc)
    if existing != data:
        _raise_integrity(f"immutable target differs: {path}")


def _fsync_directory(directory: Path) -> None:
    with contextlib.suppress(OSError):
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


__all__ = [
    "ArtifactError",
    "ArtifactIntegrityError",
    "ArtifactNotFoundError",
    "ArtifactStore",
    "sha256_bytes",
]
