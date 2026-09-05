# Copyright (c) 2026 anntnzrb
"""Stable diagnostics and credential-safe projections for Artificial Analysis."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import cast

from .contracts import (
    DIAGNOSTIC_CODES,
    DIAGNOSTIC_SEVERITIES,
    REDACTED,
    Diagnostic,
    compact_json,
    redact,
    redact_query,
)

# Public aliases keep the catalog discoverable without coupling callers to the
# contracts implementation details.
CODES = DIAGNOSTIC_CODES
SEVERITIES = DIAGNOSTIC_SEVERITIES


def _as_diagnostic(value: Diagnostic | Mapping[object, object]) -> Diagnostic:
    if isinstance(value, Diagnostic):
        return value
    # Accepting a plain mapping keeps merge useful at a JSON boundary while
    # retaining one canonical Diagnostic shape.
    return Diagnostic(
        code=str(value.get("code", "")),
        severity=str(value.get("severity", "")),
        stage=str(value.get("stage", "")),
        message=str(value.get("message", "")),
        source_path=(
            str(value["source_path"]) if value.get("source_path") is not None else None
        ),
        artifact_id=(
            str(value["artifact_id"]) if value.get("artifact_id") is not None else None
        ),
        details=value.get("details"),
    )


def merge_diagnostics(
    *groups: Iterable[Diagnostic | Mapping[object, object]]
    | Diagnostic
    | Mapping[object, object],
) -> list[Diagnostic]:
    """Merge diagnostics in first-seen order, dropping exact duplicates."""
    merged: list[Diagnostic] = []
    seen: set[str] = set()
    for group in groups:
        if isinstance(group, (Diagnostic, Mapping)):
            items = cast("Iterable[Diagnostic | Mapping[object, object]]", (group,))
        else:
            items = group
        for item in items:
            diagnostic = _as_diagnostic(item)
            key = compact_json(diagnostic.to_dict())
            if key in seen:
                continue
            seen.add(key)
            merged.append(diagnostic)
    return merged


__all__ = ["REDACTED", "Diagnostic", "merge_diagnostics", "redact", "redact_query"]
