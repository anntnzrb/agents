# Copyright (c) 2026
"""Per-artifact and per-value provenance helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .diagnostics import redact

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .contracts import RawArtifact


def artifact_provenance(
    artifacts: Iterable[RawArtifact], *, parser: str = "livebench"
) -> list[dict[str, object]]:
    """Artifact provenance for the LiveBench adapter."""
    return [
        artifact.provenance(parser=parser, parser_version="1") for artifact in artifacts
    ]


def value_evidence(  # noqa: PLR0913
    artifact: RawArtifact,
    *,
    source_path: str,
    raw_value: object,
    normalized_value: object,
    unit: str | None,
    value_status: str,
    extraction_method: str,
    confidence: str = "high",
) -> dict[str, object]:
    """Value evidence for the LiveBench adapter."""
    return redact(
        {
            "source_url": artifact.source_url,
            "discovered_from": artifact.discovered_from,
            "extraction_method": extraction_method,
            "source_path": source_path,
            "parser": "livebench.provenance",
            "parser_version": "1",
            "fetched_at": artifact.fetched_at,
            "observed_at": artifact.observed_at,
            "source_release": artifact.release_id,
            "raw_value": raw_value,
            "normalized_value": normalized_value,
            "unit": unit,
            "value_status": value_status,
            "confidence": confidence,
            "artifact_sha256": artifact.sha256,
        }
    )


def freshness(artifacts: Iterable[RawArtifact]) -> dict[str, object]:
    """Freshness for the LiveBench adapter."""
    modes = {artifact.freshness_mode for artifact in artifacts}
    if "stale-cache" in modes:
        return {"mode": "stale-cache", "historical": False, "stale": True}
    if "snapshot" in modes:
        return {"mode": "snapshot", "historical": True, "stale": False}
    if "revalidated" in modes:
        return {"mode": "revalidated", "historical": False, "stale": False}
    return {"mode": "fresh", "historical": False, "stale": False}
