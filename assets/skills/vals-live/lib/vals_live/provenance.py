# Copyright 2026 Vals-live contributors.
"""Artifact/value provenance projections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .diagnostics import redact

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .contracts import RawArtifact


def artifact_provenance(
    artifact: RawArtifact, *, parser: str = "vals.extraction", parser_version: str = "1"
) -> dict[str, Any]:
    """Project transport and parser lineage for one artifact."""
    mode = (
        "snapshot"
        if artifact.historical
        else (
            "stale-cache"
            if artifact.stale
            else ("revalidated" if artifact.cache_reused else "fresh")
        )
    )
    return redact(
        {
            "source_url": artifact.source_url,
            "discovered_from": artifact.discovered_from,
            "final_url": artifact.final_url or artifact.source_url,
            "fetched_at": artifact.fetched_at,
            "observed_at": artifact.observed_at,
            "generated_at": None,
            "etag": artifact.etag,
            "last_modified": artifact.last_modified,
            "content_type": artifact.content_type,
            "status_code": artifact.status_code,
            "sha256": artifact.sha256,
            "byte_length": len(artifact.body),
            "parser": parser,
            "parser_version": parser_version,
            "artifact_id": artifact.artifact_id,
            "raw_bytes_ref": artifact.local_path,
            "stale": bool(artifact.stale),
            "historical": bool(artifact.historical),
            "cache_reused": bool(artifact.cache_reused),
            "stale_reason": artifact.stale_reason,
            "freshness": {
                "mode": mode,
                "historical": bool(artifact.historical),
                "stale": bool(artifact.stale),
            },
        }
    )


def value_evidence(artifact: RawArtifact, **kwargs: object) -> dict[str, Any]:
    """Project field-level evidence and normalization lineage."""
    field_value = kwargs.get("field")
    field = field_value if isinstance(field_value, str) else None
    result = {
        "source_url": artifact.source_url,
        "discovered_from": artifact.discovered_from,
        "extraction_method": str(kwargs.get("extraction_method", "vals.extraction")),
        "source_path": str(kwargs.get("source_path", "")),
        "source_field": field,
        "parser": str(kwargs.get("parser", "vals.extraction")),
        "parser_version": str(kwargs.get("parser_version", "1")),
        "fetched_at": artifact.fetched_at,
        "observed_at": artifact.observed_at,
        "source_release": artifact.release,
        "raw_value": kwargs.get("raw_value"),
        "normalized_value": kwargs.get("normalized_value"),
        "unit": kwargs.get("unit"),
        "value_status": str(kwargs.get("value_status", "unknown")),
        "confidence": str(kwargs.get("confidence", "unknown")),
        "artifact_sha256": artifact.sha256,
        "artifact_id": artifact.artifact_id,
    }
    return redact(result)  # type: ignore[return-value]


def attach_provenance(row: Mapping[str, Any], artifact: RawArtifact) -> dict[str, Any]:
    """Attach artifact provenance to a normalized row."""
    result = dict(row)
    result["provenance"] = artifact_provenance(artifact)
    return result
