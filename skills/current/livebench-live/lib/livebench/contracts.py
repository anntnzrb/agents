# Copyright (c) 2026
"""Stable contracts for the LiveBench source adapter and JSON wire format."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import NoReturn, cast

SCHEMA_VERSION = "1"
SOURCE = "livebench"
VALUE_STATUSES = ("published", "derived", "missing", "unparsed")


def utc_now() -> str:
    """Utc now for the LiveBench adapter."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Diagnostic:
    """Represent Diagnostic in the LiveBench adapter."""

    code: str
    severity: str
    stage: str
    message: str
    source: str | None = None
    artifact: str | None = None
    path: str | None = None
    details: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        """As dict for the LiveBench adapter."""
        value = cast("dict[str, object]", asdict(self))
        if self.source is None:
            _ = value.pop("source", None)
        if self.artifact is None:
            _ = value.pop("artifact", None)
        if self.path is None:
            _ = value.pop("path", None)
        if not self.details:
            _ = value.pop("details", None)
        return value


@dataclass(frozen=True)
class SourceTarget:
    """Represent SourceTarget in the LiveBench adapter."""

    release_id: str
    artifact_kind: str
    url: str
    discovered_from: str
    expected_content_types: tuple[str, ...] = ("*/*",)
    required: bool = True

    def as_dict(self) -> dict[str, object]:
        """As dict for the LiveBench adapter."""
        return {
            "release_id": self.release_id,
            "artifact_kind": self.artifact_kind,
            "url": self.url,
            "discovered_from": self.discovered_from,
            "expected_content_types": list(self.expected_content_types),
            "required": self.required,
        }


@dataclass
class RawArtifact:
    """Represent RawArtifact in the LiveBench adapter."""

    artifact_id: str
    source: str
    release_id: str | None
    artifact_kind: str
    source_url: str
    discovered_from: str | None
    body: bytes
    status_code: int
    content_type: str | None
    headers: dict[str, str]
    fetched_at: str
    observed_at: str
    sha256: str
    byte_length: int
    raw_bytes_ref: str | None = None
    freshness_mode: str = "fresh"
    stale: bool = False
    historical: bool = False
    cache_reused: bool = False
    generated_at: str | None = None

    def provenance(
        self, *, parser: str | None = None, parser_version: str = "1"
    ) -> dict[str, object]:
        """Provenance for the LiveBench adapter."""
        return {
            "source_url": self.source_url,
            "discovered_from": self.discovered_from,
            "fetched_at": self.fetched_at,
            "observed_at": self.observed_at,
            "generated_at": self.generated_at,
            "etag": self.headers.get("etag") or self.headers.get("ETag"),
            "last_modified": self.headers.get("last-modified")
            or self.headers.get("Last-Modified"),
            "cache_control": self.headers.get("cache-control")
            or self.headers.get("Cache-Control"),
            "age": self.headers.get("age") or self.headers.get("Age"),
            "content_type": self.content_type,
            "status_code": self.status_code,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
            "raw_bytes_ref": self.raw_bytes_ref,
            "parser": parser,
            "parser_version": parser_version,
            "stale": self.stale,
            "freshness": {
                "mode": self.freshness_mode,
                "historical": self.historical,
                "stale": self.stale,
            },
            "cache_reused": self.cache_reused,
            "release_id": self.release_id,
            "artifact_kind": self.artifact_kind,
        }


@dataclass(frozen=True)
class NumericValue:
    """Represent NumericValue in the LiveBench adapter."""

    raw_value: object
    normalized_value: float | int | None
    unit: str | None
    normalization: str | None
    source_path: str | None
    value_status: str
    metric_semantics_status: str = "known"
    missing_reason: str | None = None
    source_evidence: dict[str, object] = field(default_factory=dict)
    comparison_eligibility: str = "eligible"

    def as_dict(self) -> dict[str, object]:
        """As dict for the LiveBench adapter."""
        result = cast("dict[str, object]", asdict(self))
        if not self.source_evidence:
            _ = result.pop("source_evidence", None)
        return result


@dataclass(frozen=True)
class ResolvedRelease:
    """Represent ResolvedRelease in the LiveBench adapter."""

    requested: str
    release_id: str
    latest: bool
    date: str | None
    source_defined: bool
    authority_url: str | None
    authority_sha256: str | None
    discovered_at: str | None
    generated_at: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        """As dict for the LiveBench adapter."""
        return {
            "requested": self.requested,
            "id": self.release_id,
            "date": self.date,
            "latest": self.latest,
            "source_defined": self.source_defined,
            "authority_url": self.authority_url,
            "authority_sha256": self.authority_sha256,
            "discovered_at": self.discovered_at,
            "generated_at": self.generated_at,
            "metadata": self.metadata,
        }


class SkillError(RuntimeError):
    """Expected failure rendered as the compact JSON error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
        *,
        exit_code: int = 1,
    ) -> None:
        """Initialize this instance."""
        super().__init__(message)
        self.code: str = code
        self.message: str = message
        self.details: dict[str, object] = details or {}
        self.exit_code: int = exit_code


def raise_expected(
    code: str,
    message: str,
    details: dict[str, object] | None = None,
    *,
    exit_code: int = 1,
) -> NoReturn:
    """Raise an expected adapter error."""
    error = SkillError(code, message, details, exit_code=exit_code)
    raise error


def success(command: str, data: dict[str, object]) -> dict[str, object]:
    """Success for the LiveBench adapter."""
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "data": data,
    }


def failure(command: str, error: SkillError | Diagnostic) -> dict[str, object]:
    """Failure for the LiveBench adapter."""
    payload = {
        "code": error.code,
        "message": error.message,
        "details": error.details,
    }
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "error": payload,
    }


def compact_json(payload: dict[str, object]) -> str:
    """Serialize one finite JSON object without progress or pretty-print noise."""
    return json.dumps(
        payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def diagnostic(  # noqa: PLR0913 - parameters mirror the Diagnostic envelope fields one-to-one
    code: str,
    message: str,
    *,
    severity: str = "warning",
    stage: str = "validate",
    source: str | None = None,
    artifact: str | None = None,
    path: str | None = None,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    """Diagnostic for the LiveBench adapter."""
    return Diagnostic(
        code, severity, stage, message, source, artifact, path, details or {}
    ).as_dict()


def ensure_status(status: str) -> str:
    """Ensure status for the LiveBench adapter."""
    if status not in VALUE_STATUSES:
        message = f"unsupported value status: {status}"
        raise ValueError(message)
    return status
