# Copyright (c) 2026
"""Immutable, content-addressed artifact cache with validator sidecars."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .contracts import RawArtifact, SourceTarget, utc_now
from .diagnostics import redact

CACHE_VERSION = "1"


def default_cache_dir() -> Path:
    """Default cache dir for the LiveBench adapter."""
    configured = os.environ.get("LIVEBENCH_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = (
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("USERPROFILE")
            or str(Path.home())
        )
        return Path(base) / "livebench-live"
    if os.name == "posix" and os.uname().sysname == "Darwin":
        return Path.home() / "Library" / "Caches" / "livebench-live"
    base = os.environ.get("XDG_CACHE_HOME")
    return (
        Path(base).expanduser() if base else Path.home() / ".cache"
    ) / "livebench-live"


def target_key(target: SourceTarget) -> str:
    """Target key for the LiveBench adapter."""
    material = f"{target.release_id}\0{target.artifact_kind}\0{target.url}".encode()
    return hashlib.sha256(material).hexdigest()


def sha256_bytes(body: bytes) -> str:
    """Sha256 bytes for the LiveBench adapter."""
    return hashlib.sha256(body).hexdigest()


class CacheStore:
    """Raw bytes are immutable; index metadata may only point at a new artifact."""

    def __init__(self, root: Path | None = None) -> None:
        """Initialize this instance."""
        self.root = (root or default_cache_dir()).expanduser()

    def _target_dir(self, target: SourceTarget) -> Path:
        return (
            self.root
            / "livebench"
            / "releases"
            / target.release_id
            / target.artifact_kind
        )

    def _index_path(self, target: SourceTarget) -> Path:
        return self._target_dir(target) / f"{target_key(target)}.index.json"

    def load(self, target: SourceTarget) -> tuple[bytes, dict[str, object]] | None:  # noqa: PLR0911
        """Load for the LiveBench adapter."""
        index_path = self._index_path(target)
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(index, dict):
            return None
        body_path = Path(str(index.get("raw_bytes_ref", "")))
        meta_path = Path(str(index.get("metadata_path", "")))
        if not body_path.is_absolute():
            body_path = self.root / body_path
        if not meta_path.is_absolute():
            meta_path = self.root / meta_path
        try:
            body = body_path.read_bytes()
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(metadata, dict):
            return None
        if (
            metadata.get("source_url") != target.url
            or metadata.get("release_id") != target.release_id
        ):
            return None
        expected_hash = str(metadata.get("sha256", ""))
        if not expected_hash or sha256_bytes(body) != expected_hash:
            return None
        return body, metadata

    def save(
        self, target: SourceTarget, body: bytes, metadata: dict[str, object]
    ) -> dict[str, object]:
        """Save for the LiveBench adapter."""
        digest = sha256_bytes(body)
        target_dir = self._target_dir(target)
        artifacts_dir = target_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        body_path = artifacts_dir / f"{target.artifact_kind}-{digest}.bin"
        meta_path = artifacts_dir / f"{target.artifact_kind}-{digest}.meta.json"
        if not body_path.exists():
            _atomic_write_bytes(body_path, body)
        safe_meta = dict(redact(metadata))
        safe_meta.update(
            {
                "sha256": digest,
                "byte_length": len(body),
                "cache_version": CACHE_VERSION,
                "raw_bytes_ref": str(body_path),
                "metadata_path": str(meta_path),
            }
        )
        _atomic_write_text(
            meta_path, json.dumps(safe_meta, separators=(",", ":"), ensure_ascii=False)
        )
        index = {
            "source_url": target.url,
            "release_id": target.release_id,
            "artifact_kind": target.artifact_kind,
            "sha256": digest,
            "raw_bytes_ref": str(body_path),
            "metadata_path": str(meta_path),
            "updated_at": utc_now(),
        }
        _atomic_write_text(
            self._index_path(target),
            json.dumps(index, separators=(",", ":"), ensure_ascii=False),
        )
        return safe_meta

    def artifact(
        self,
        target: SourceTarget,
        *,
        body: bytes | None = None,
        metadata: dict[str, object] | None = None,
    ) -> RawArtifact | None:
        """Artifact for the LiveBench adapter."""
        loaded = (
            (body, metadata)
            if body is not None and metadata is not None
            else self.load(target)
        )
        if loaded is None:
            return None
        raw_body, meta = loaded
        digest = sha256_bytes(raw_body)
        return RawArtifact(
            artifact_id=f"livebench:{target.release_id}:{target.artifact_kind}:sha256:{digest}",
            source="livebench",
            release_id=target.release_id,
            artifact_kind=target.artifact_kind,
            source_url=target.url,
            discovered_from=target.discovered_from,
            body=raw_body,
            status_code=int(meta.get("status_code", 200)),
            content_type=str(meta.get("content_type"))
            if meta.get("content_type")
            else None,
            headers={str(k): str(v) for k, v in dict(meta.get("headers", {})).items()}
            if isinstance(meta.get("headers"), dict)
            else {},
            fetched_at=str(meta.get("fetched_at", utc_now())),
            observed_at=str(meta.get("observed_at", meta.get("fetched_at", utc_now()))),
            sha256=digest,
            byte_length=len(raw_body),
            raw_bytes_ref=str(meta.get("raw_bytes_ref"))
            if meta.get("raw_bytes_ref")
            else None,
            freshness_mode=str(meta.get("freshness_mode", "fresh")),
            stale=bool(meta.get("stale", False)),
            historical=bool(meta.get("historical", False)),
            cache_reused=bool(meta.get("cache_reused", False)),
            generated_at=str(meta.get("generated_at"))
            if meta.get("generated_at")
            else None,
        )


def _atomic_write_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        temp = Path(handle.name)
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def _atomic_write_text(path: Path, body: str) -> None:
    _atomic_write_bytes(path, body.encode("utf-8"))
