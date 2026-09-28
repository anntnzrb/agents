# Copyright (c) 2026
"""Stable contracts for the LiveBench source adapter and JSON wire format."""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import NoReturn, TypeIs

SCHEMA_VERSION = "1"
SOURCE = "livebench"
VALUE_STATUSES = ("published", "derived", "missing", "unparsed")


def utc_now() -> str:
    """Utc now for the LiveBench adapter."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
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
        value: dict[str, object] = {
            "code": self.code,
            "severity": self.severity,
            "stage": self.stage,
            "message": self.message,
        }
        if self.source is not None:
            value["source"] = self.source
        if self.artifact is not None:
            value["artifact"] = self.artifact
        if self.path is not None:
            value["path"] = self.path
        if self.details:
            value["details"] = dict(self.details)
        return value


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
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
        result: dict[str, object] = {
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "unit": self.unit,
            "normalization": self.normalization,
            "source_path": self.source_path,
            "value_status": self.value_status,
            "metric_semantics_status": self.metric_semantics_status,
            "missing_reason": self.missing_reason,
            "comparison_eligibility": self.comparison_eligibility,
        }
        if self.source_evidence:
            result["source_evidence"] = dict(self.source_evidence)
        return result


@dataclass(frozen=True, slots=True)
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


_json_loads: Callable[[str | bytes | bytearray], object] = json.loads


def load_json(source: str | bytes | bytearray) -> object:
    """Decode JSON source into an untyped object."""
    return _json_loads(source)


def is_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    """Return True when value is a mapping with string keys."""
    return isinstance(value, Mapping)


def is_dict(value: object) -> TypeIs[dict[str, object]]:
    """Return True when value is a dict with string keys."""
    return isinstance(value, dict)


def is_list(value: object) -> TypeIs[list[object]]:
    """Return True when value is a list."""
    return isinstance(value, list)


def is_tuple(value: object) -> TypeIs[tuple[object, ...]]:
    """Return True when value is a tuple."""
    return isinstance(value, tuple)


def is_sequence(value: object) -> TypeIs[Sequence[object]]:
    """Return True when value is a non-string, non-bytes sequence."""
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def as_int(value: object, default: int = 0) -> int:
    """Convert a JSON-decoded scalar to int or return default."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, (float, str)):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def as_dict(value: object) -> dict[str, object]:
    """Return value as a string-keyed dict or raise TypeError."""
    if is_dict(value):
        return value
    if is_mapping(value):
        return dict(value)
    msg = f"expected mapping, got {type(value).__name__}"
    raise TypeError(msg)


def as_list(value: object) -> list[object]:
    """Return value as a list or raise TypeError."""
    if is_list(value):
        return value
    msg = f"expected list, got {type(value).__name__}"
    raise TypeError(msg)


def as_dict_list(value: object) -> list[dict[str, object]]:
    """Return value as a list of string-keyed dicts or raise TypeError."""
    return [as_dict(item) for item in as_list(value)]
