# Copyright (c) 2026
"""Lossless LiveBench value normalization and release-record projection."""

from __future__ import annotations

import math
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import cast

from .contracts import Diagnostic, NumericValue, RawArtifact
from .diagnostics import make_diagnostic

_SENTINELS = frozenset(
    {"", "n/a", "na", "none", "null", "—", "–", "-", "loading", "…", "..."}  # noqa: RUF001
)


def _finite_decimal(raw: str) -> Decimal | None:
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    return value


def _number(value: Decimal) -> float | int:
    as_float = float(value)
    if not math.isfinite(as_float):
        message = "non-finite numeric value"
        raise ValueError(message)
    if value == value.to_integral_value():
        return int(value)
    return as_float


def numeric_value(  # noqa: PLR0911, PLR0913
    raw: object,
    *,
    path: str,
    artifact: RawArtifact | None = None,
    unit_hint: str | None = None,
    definition: str | None = None,
    semantics: str = "known",
    placeholder_zero: bool = False,
) -> tuple[NumericValue, list[Diagnostic]]:
    """Normalize one source value while preserving raw input and source evidence."""
    evidence: dict[str, object] = {}
    if artifact is not None:
        evidence = {
            "source_url": artifact.source_url,
            "discovered_from": artifact.discovered_from,
            "extraction_method": "official_csv"
            if artifact.artifact_kind.endswith("table")
            else "official_json",
            "source_path": path,
            "parser": "livebench.normalization",
            "parser_version": "1",
            "fetched_at": artifact.fetched_at,
            "observed_at": artifact.observed_at,
            "source_release": artifact.release_id,
            "raw_value": raw,
            "artifact_sha256": artifact.sha256,
        }
    diagnostics: list[Diagnostic] = []
    if raw is None:
        return NumericValue(
            raw,
            None,
            unit_hint,
            None,
            path,
            "missing",
            semantics,
            "SOURCE_FIELD_ABSENT",
            evidence,
            "blocked",
        ), diagnostics

    text = str(raw).strip()
    lowered = text.casefold()
    if lowered in _SENTINELS or (placeholder_zero and lowered in {"0.0%", "0%"}):
        diagnostics.append(
            make_diagnostic(
                "PLACEHOLDER_VALUE",
                f"Placeholder value {text!r} is not a measurement.",
                severity="warning",
                stage="normalize",
                artifact=artifact.artifact_id if artifact else None,
                path=path,
                details={"raw_value": raw},
            )
        )
        return NumericValue(
            raw,
            None,
            unit_hint,
            None,
            path,
            "missing",
            semantics,
            "PLACEHOLDER",
            evidence,
            "blocked",
        ), diagnostics

    explicit_percent = text.endswith("%")
    numeric_text = text[:-1].strip() if explicit_percent else text
    decimal = _finite_decimal(numeric_text)
    if decimal is None:
        diagnostics.append(
            make_diagnostic(
                "MALFORMED_PAYLOAD",
                f"Numeric value {text!r} could not be parsed.",
                severity="warning",
                stage="normalize",
                artifact=artifact.artifact_id if artifact else None,
                path=path,
                details={"raw_value": raw},
            )
        )
        return NumericValue(
            raw,
            None,
            unit_hint,
            None,
            path,
            "unparsed",
            "invalid",
            None,
            evidence,
            "blocked",
        ), diagnostics

    unit = "percent" if explicit_percent else unit_hint
    normalization = "removed_percent_sign" if explicit_percent else None
    normalized = _number(decimal)
    if unit in {"ratio", "fraction"} and (decimal < 0 or decimal > 1):
        diagnostics.append(
            make_diagnostic(
                "OUT_OF_RANGE",
                "Ratio value is outside the source-declared range [0, 1].",
                severity="warning",
                stage="normalize",
                artifact=artifact.artifact_id if artifact else None,
                path=path,
                details={"raw_value": raw, "unit": unit},
            )
        )
        return NumericValue(
            raw,
            None,
            unit,
            normalization,
            path,
            "unparsed",
            "invalid",
            "OUT_OF_RANGE",
            evidence,
            "blocked",
        ), diagnostics
    if unit == "percent" and (decimal < 0 or decimal > 100):  # noqa: PLR2004
        diagnostics.append(
            make_diagnostic(
                "OUT_OF_RANGE",
                "Percent value is outside the source-declared range [0, 100].",
                severity="warning",
                stage="normalize",
                artifact=artifact.artifact_id if artifact else None,
                path=path,
                details={"raw_value": raw, "unit": unit},
            )
        )
        return NumericValue(
            raw,
            None,
            unit,
            normalization,
            path,
            "unparsed",
            "invalid",
            "OUT_OF_RANGE",
            evidence,
            "blocked",
        ), diagnostics

    # A bare number is retained but is not comparison-safe unless the source
    # has declared semantics.
    if unit is None and not definition:
        semantics = "ambiguous" if semantics == "known" else semantics
        diagnostics.append(
            make_diagnostic(
                "NUMERIC_AMBIGUITY",
                "Bare numeric value has no explicit unit or definition.",
                severity="warning",
                stage="normalize",
                artifact=artifact.artifact_id if artifact else None,
                path=path,
                details={"raw_value": raw},
            )
        )
        return NumericValue(
            raw,
            normalized,
            None,
            normalization,
            path,
            "published",
            semantics,
            None,
            evidence,
            "blocked",
        ), diagnostics

    if unit is None:
        unit = "source-defined"
    evidence["normalized_value"] = normalized
    evidence["unit"] = unit
    return NumericValue(
        raw,
        normalized,
        unit,
        normalization,
        path,
        "published",
        semantics,
        None,
        evidence,
        "eligible",
    ), diagnostics


def value_dict(value: NumericValue) -> dict[str, object]:
    """Value dict for the LiveBench adapter."""
    return value.as_dict()


def attach_artifact_evidence(
    value: dict[str, object], artifact: RawArtifact, parser: str
) -> dict[str, object]:
    """Attach artifact evidence for the LiveBench adapter."""
    result = dict(value)
    raw_evidence = result.get("source_evidence")
    evidence = (
        dict(cast("Mapping[str, object]", raw_evidence))
        if isinstance(raw_evidence, Mapping)
        else {}
    )
    evidence.update(artifact.provenance(parser=parser))
    evidence["source_path"] = result.get("source_path")
    evidence["raw_value"] = result.get("raw_value")
    evidence["normalized_value"] = result.get("normalized_value")
    result["source_evidence"] = evidence
    return result
