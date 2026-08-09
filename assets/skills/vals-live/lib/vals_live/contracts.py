# Copyright 2026 Vals-live contributors.
"""Stable wire and internal record contracts for vals-live."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

SCHEMA_VERSION = "1"
VALUE_STATUSES = ("published", "derived", "missing", "unparsed")


def compact(value: object) -> str:
    """Serialize one finite, compact JSON value."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def success(command: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """Build a successful stable command envelope."""
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "data": dict(data),
    }


def failure(
    command: str, code: str, message: str, details: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Build a failed stable command envelope."""
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "error": {"code": code, "message": message, "details": dict(details or {})},
    }


@dataclass
class Diagnostic:
    """Represent one structured source diagnostic."""

    code: str
    severity: str = "warning"
    stage: str = "validate"
    message: str = ""
    source_path: str | None = None
    artifact_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serialize this diagnostic for the public contract."""
        value = {
            "code": self.code,
            "severity": self.severity,
            "stage": self.stage,
            "message": self.message,
            "details": dict(self.details),
        }
        if self.source_path is not None:
            value["source_path"] = self.source_path
        if self.artifact_id is not None:
            value["artifact_id"] = self.artifact_id
        return value


@dataclass
class RawArtifact:
    """Retain immutable source bytes and their transport metadata."""

    source_url: str
    discovered_from: str
    body: bytes
    status_code: int = 200
    content_type: str | None = None
    final_url: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    fetched_at: str | None = None
    observed_at: str | None = None
    release: str | None = None
    stale: bool = False
    stale_reason: dict[str, object] | None = None
    cache_reused: bool = False
    historical: bool = False
    sha256: str | None = None
    local_path: str | None = None

    @property
    def artifact_id(self) -> str:
        """Return the content-addressed artifact identity."""
        digest = self.sha256 or ""
        return f"vals:{self.release or 'snapshot'}:sha256:{digest}"


@dataclass
class ParsedDocument:
    """Represent one parsed source document and extraction lineage."""

    root: Any
    document_kind: str
    extraction_method: str
    source_paths: list[dict[str, Any]]
    artifact: RawArtifact
    parser: str = "vals.extraction"
    parser_version: str = "1"
    unknown_fields: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Catalog:
    """Hold discovered benchmark and model catalog populations."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    active_selector_entries: list[dict[str, Any]] = field(default_factory=list)
    all_detail_anchors: list[dict[str, Any]] = field(default_factory=list)
    version_selector_entries: list[dict[str, Any]] = field(default_factory=list)
    models: list[dict[str, Any]] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class RequestContext:
    """Describe one command's source and selector context."""

    command: str
    snapshot: str | None = None
    allow_stale: bool = False
    cache_dir: str | None = None
    release: str | None = None
    selectors: dict[str, Any] = field(default_factory=dict)


def diagnostic_list(
    items: list[Diagnostic] | list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Convert diagnostics to JSON-compatible dictionaries."""
    return [
        item.as_dict() if isinstance(item, Diagnostic) else dict(item) for item in items
    ]


def scope(
    *,
    source: str = "vals",
    benchmark: str | None = None,
    benchmark_version: str | None = None,
    release: str | None = None,
    model_variant: str | None = None,
    **extra: object,
) -> dict[str, Any]:
    """Build the nearest-scope metadata projection."""
    result: dict[str, Any] = {
        "source": source,
        "benchmark": benchmark,
        "benchmark_version": benchmark_version,
        "release": release,
        "model_variant": model_variant,
        "score_definition": extra.pop("score_definition", None),
        "task_count": extra.pop("task_count", None),
        "task_count_population": extra.pop("task_count_population", None),
        "task_count_kind": extra.pop("task_count_kind", None),
        "harness": extra.pop("harness", None),
        "filters_applied": extra.pop("filters_applied", {}),
    }
    result.update(extra)
    return result
