# Copyright 2026 Vals-live contributors.
"""Lossless Vals record and numeric normalization."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, cast

from .diagnostics import make
from .identity import model_id, stable_id, variant_id
from .provenance import value_evidence

if TYPE_CHECKING:
    from .contracts import ParsedDocument, RawArtifact

_SENTINELS = {
    "",
    "n/a",
    "na",
    "not available",
    "—",
    "-",
    "\N{EN DASH}",
    "loading",
    "pending",
    "null",
    "none",
}
_KNOWN_FIELDS = {
    "accuracy",
    "score",
    "quality",
    "code_quality",
    "stderr",
    "uncertainty",
    "latency",
    "latency_seconds",
    "cost",
    "cost_per_test",
    "cost_in",
    "cost_out",
    "rank",
    "model_count",
    "total_models",
    "pass_at_1",
    "pass_at_4",
    "all_pass",
    "weighted_pass",
    "temperature",
    "top_p",
    "max_output_tokens",
    "reasoning",
    "reasoning_effort",
    "verbosity",
    "compute_effort",
}
_META_FIELDS = {
    "model",
    "model_id",
    "model_name",
    "model_key",
    "slug",
    "id",
    "name",
    "provider",
    "company",
    "variant",
    "harness",
    "benchmark",
    "benchmark_name",
    "benchmark_id",
    "benchmark_slug",
    "benchmark_version",
    "family",
    "version",
    "release",
    "release_id",
    "updated",
    "updated_at",
    "url",
    "canonical_url",
    "metadata",
    "tasks",
    "metrics",
    "raw_fields",
    "source",
}


def _to_number(raw: object) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value if math.isfinite(value) else None
    if isinstance(raw, str):
        try:
            value = float(Decimal(raw.strip().replace(",", "")))
        except (InvalidOperation, ValueError, TypeError):
            return None
        return value if math.isfinite(value) else None
    return None


@dataclass(frozen=True)
class _NumericContext:
    raw: object
    unit: object
    definition: object
    source_zero: bool
    source_path: str
    field: str
    artifact: RawArtifact
    extraction_method: str
    explicit_range: tuple[float, float] | None


def _numeric_evidence(
    context: _NumericContext, result: dict[str, Any], **kwargs: object
) -> dict[str, Any]:
    normalized_value = kwargs.get("normalized_value")
    unit = kwargs.get("unit")
    value_status = str(kwargs.get("value_status", "unknown"))
    confidence = str(kwargs.get("confidence", "unknown"))
    result["source_evidence"] = value_evidence(
        context.artifact,
        extraction_method=context.extraction_method,
        source_path=context.source_path,
        raw_value=context.raw,
        normalized_value=normalized_value,
        unit=unit,
        value_status=value_status,
        confidence=confidence,
        field=context.field,
    )
    return result


def _numeric_failure(
    context: _NumericContext, **kwargs: object
) -> tuple[dict[str, Any], list[dict[str, object]]]:
    code = str(kwargs.get("code", "MALFORMED_PAYLOAD"))
    message = str(kwargs.get("message", "Numeric value could not be parsed."))
    unit = kwargs.get("unit")
    normalization_value = kwargs.get("normalization")
    normalization = (
        normalization_value if isinstance(normalization_value, str) else None
    )
    value_status = str(kwargs.get("value_status", "unparsed"))
    blocked_reason = str(kwargs.get("blocked_reason", code))
    candidates_value = kwargs.get("candidate_interpretations")
    candidate_interpretations = (
        candidates_value if isinstance(candidates_value, list) else None
    )
    details_value = kwargs.get("details")
    details = details_value if isinstance(details_value, Mapping) else None
    result: dict[str, Any] = {
        "raw_value": context.raw,
        "normalized_value": None,
        "unit": unit,
        "normalization": normalization,
        "metric_semantics_status": (
            "ambiguous" if code == "NUMERIC_AMBIGUITY" else "invalid"
        ),
        "candidate_interpretations": candidate_interpretations or [],
        "missing_reason": None,
        "source_path": context.source_path,
        "source_field": context.field,
        "value_status": value_status,
        "comparison_eligibility": "blocked",
        "blocked_reasons": [blocked_reason],
    }
    _numeric_evidence(
        context,
        result,
        normalized_value=None,
        unit=unit,
        value_status=value_status,
        confidence="low",
    )
    diagnostics = [
        make(
            code,
            message,
            stage="normalize",
            source_path=context.source_path,
            details=details or {"raw_value": context.raw, "field": context.field},
        )
    ]
    return result, diagnostics


def _numeric_placeholder(
    context: _NumericContext,
    *,
    unit: object,
    message: str,
) -> tuple[dict[str, Any], list[dict[str, object]]]:
    result: dict[str, Any] = {
        "raw_value": context.raw,
        "normalized_value": None,
        "unit": unit,
        "normalization": None,
        "metric_semantics_status": "placeholder",
        "candidate_interpretations": [],
        "missing_reason": "PLACEHOLDER",
        "source_path": context.source_path,
        "source_field": context.field,
        "value_status": "missing",
        "comparison_eligibility": "blocked",
        "blocked_reasons": ["PLACEHOLDER_VALUE"],
    }
    _numeric_evidence(
        context,
        result,
        normalized_value=None,
        unit=unit,
        value_status="missing",
        confidence="low",
    )
    diagnostics = [
        make(
            "PLACEHOLDER_VALUE",
            message,
            stage="normalize",
            source_path=context.source_path,
            details={"raw_value": context.raw},
        )
    ]
    return result, diagnostics


def _parsed_numeric(
    raw_text: object, unit: object
) -> tuple[object, str | None, str | None]:
    parsed_unit = (
        str(unit).strip().casefold() if isinstance(unit, str) and unit.strip() else None
    )
    if isinstance(raw_text, str) and raw_text.endswith("%"):
        return raw_text[:-1].strip(), "percent", "removed_percent_sign"
    return raw_text, parsed_unit, None


def _normalize_unit(
    parsed_unit: str | None,
    explicit_range: tuple[float, float] | None,
) -> tuple[str | None, tuple[float, float] | None]:
    if parsed_unit in {"percent", "%", "percentage", "percent_points"}:
        return "percent", explicit_range or (0.0, 100.0)
    if parsed_unit in {"ratio", "fraction", "proportion"}:
        return "ratio", explicit_range
    if parsed_unit in {"usd", "$", "dollar", "dollars"}:
        return "usd", explicit_range
    if parsed_unit in {
        "seconds",
        "second",
        "s",
        "ms",
        "milliseconds",
        "millisecond",
    }:
        normalized = (
            "milliseconds"
            if parsed_unit in {"ms", "milliseconds", "millisecond"}
            else "seconds"
        )
        return normalized, explicit_range
    if parsed_unit in {"count", "rank", "tokens", "token"}:
        return parsed_unit, explicit_range
    return parsed_unit, explicit_range


def _numeric_success(
    context: _NumericContext,
    number: float,
    unit: str,
    normalization: str | None,
) -> tuple[dict[str, Any], list[dict[str, object]]]:
    semantics = (
        "known"
        if isinstance(context.definition, str) and context.definition.strip()
        else (
            "unknown" if context.field.casefold() not in _KNOWN_FIELDS else "ambiguous"
        )
    )
    blocked = (
        ["UNKNOWN_SCORE_SEMANTICS" if semantics == "unknown" else "NUMERIC_AMBIGUITY"]
        if semantics != "known"
        else []
    )
    result: dict[str, Any] = {
        "raw_value": context.raw,
        "normalized_value": number,
        "unit": unit,
        "normalization": normalization,
        "metric_semantics_status": semantics,
        "candidate_interpretations": [],
        "missing_reason": None,
        "source_path": context.source_path,
        "source_field": context.field,
        "value_status": "published",
        "comparison_eligibility": "eligible" if not blocked else "blocked",
        "blocked_reasons": blocked,
    }
    _numeric_evidence(
        context,
        result,
        normalized_value=number,
        unit=unit,
        value_status="published",
        confidence="high" if semantics == "known" else "medium",
    )
    diagnostics: list[dict[str, object]] = []
    if semantics == "unknown":
        diagnostics.append(
            make(
                "UNKNOWN_SCORE_SEMANTICS",
                "A source-published metric has no recognized definition.",
                stage="normalize",
                source_path=context.source_path,
                details={"field": context.field},
            )
        )
    return result, diagnostics


def normalize_numeric(
    raw: object, **kwargs: object
) -> tuple[dict[str, Any], list[dict[str, object]]]:
    """Normalize only evidence-backed units; never coerce ambiguity or clamp values."""
    source_path_value = kwargs.get("source_path")
    field_value = kwargs.get("field")
    if not isinstance(source_path_value, str) or not isinstance(field_value, str):
        message = "normalize_numeric() requires source_path and field strings"
        raise TypeError(message)
    context = _NumericContext(
        raw=raw,
        unit=kwargs.get("unit"),
        definition=kwargs.get("definition"),
        source_zero=bool(kwargs.get("source_zero", False)),
        source_path=source_path_value,
        field=field_value,
        artifact=cast("RawArtifact", kwargs.get("artifact")),
        extraction_method=str(kwargs.get("extraction_method", "vals.extraction")),
        explicit_range=cast("tuple[float, float] | None", kwargs.get("explicit_range")),
    )
    return _normalize_numeric(context)


def _normalize_numeric(
    context: _NumericContext,
) -> tuple[dict[str, Any], list[dict[str, object]]]:
    raw_text = context.raw.strip() if isinstance(context.raw, str) else context.raw
    lowered = raw_text.casefold() if isinstance(raw_text, str) else ""
    if lowered in _SENTINELS:
        return _numeric_placeholder(
            context,
            unit=None,
            message="The source value is a placeholder or unavailable sentinel.",
        )
    if (
        isinstance(context.raw, str)
        and context.raw.strip().casefold() == "0.0%"
        and not context.source_zero
    ):
        return _numeric_placeholder(
            context,
            unit="percent",
            message="A chart or animation zero is not treated as a measurement.",
        )
    value_raw, parsed_unit, normalization = _parsed_numeric(raw_text, context.unit)
    number = _to_number(value_raw)
    if number is None:
        return _numeric_failure(
            context,
            code="MALFORMED_PAYLOAD",
            message="A numeric field was not finite or parseable.",
            unit=parsed_unit,
            normalization=None,
            value_status="unparsed",
            blocked_reason="MALFORMED_PAYLOAD",
        )
    parsed_unit, explicit_range = _normalize_unit(parsed_unit, context.explicit_range)
    if parsed_unit is None:
        return _numeric_failure(
            context,
            code="NUMERIC_AMBIGUITY",
            message="A bare number has no source-declared unit or scale.",
            unit=None,
            normalization=None,
            value_status="published",
            blocked_reason="NUMERIC_AMBIGUITY",
            candidate_interpretations=["ratio", "percent_points", "source-defined"],
        )
    if explicit_range is not None and not (
        explicit_range[0] <= number <= explicit_range[1]
    ):
        return _numeric_failure(
            context,
            code="OUT_OF_RANGE",
            message=(
                "The source-declared numeric range was violated; no clamping "
                "was applied."
            ),
            unit=parsed_unit,
            normalization=normalization,
            value_status="unparsed",
            blocked_reason="OUT_OF_RANGE",
            details={"raw_value": context.raw, "range": explicit_range},
        )
    return _numeric_success(context, number, parsed_unit, normalization)


def _unwrap_metric(value: object) -> tuple[object, dict[str, object]]:
    if isinstance(value, Mapping):
        metadata: dict[str, object] = dict(value)
        for key in ("value", "raw_value", "score", "accuracy", "value_raw"):
            if key in value:
                return value[key], metadata
    return value, {}


def _row_identity(
    row: Mapping[str, object],
) -> tuple[str | None, str | None, str | None, str | None]:
    model = next(
        (
            row.get(key)
            for key in ("model", "model_name", "model_key", "name", "slug")
            if row.get(key) is not None
        ),
        None,
    )
    benchmark = next(
        (
            row.get(key)
            for key in ("benchmark_id", "benchmark", "benchmark_name", "benchmark_slug")
            if row.get(key) is not None
        ),
        None,
    )
    provider = row.get("provider") or row.get("company")
    variant = row.get("variant")
    return (
        str(model) if model is not None else None,
        str(benchmark) if benchmark is not None else None,
        str(provider) if provider is not None else None,
        str(variant) if variant is not None else None,
    )


@dataclass(frozen=True)
class _RowContext:
    row: Mapping[str, object]
    artifact: RawArtifact
    document: ParsedDocument
    source_path: str
    benchmark_hint: Mapping[str, object] | None
    model: str
    benchmark: str | None
    provider: object
    variant: object


def _missing_row(
    row: Mapping[str, object], source_path: str
) -> tuple[dict[str, Any], list[dict[str, object]]]:
    diagnostic = make(
        "MISSING_REQUIRED_IDENTITY",
        "A model identity was not published for this row.",
        severity="error",
        stage="normalize",
        source_path=source_path,
    )
    return {
        "raw_fields": dict(row),
        "value_status": "unparsed",
        "source_evidence": [],
    }, [diagnostic]


def _initial_result(context: _RowContext) -> dict[str, Any]:
    row = context.row
    hint = context.benchmark_hint
    model_canonical, model_basis = model_id(
        context.model,
        source_id=row.get("model_id") or row.get("id"),
        url=row.get("url"),
    )
    benchmark_id, benchmark_basis = stable_id(
        "vals",
        source_id=hint.get("benchmark_id") if hint else None,
        url=hint.get("url") if hint else None,
        label=context.benchmark or "unknown",
        kind="benchmark",
    )
    return {
        "source": "vals",
        "model": context.model,
        "model_id": model_canonical,
        "model_identity_basis": model_basis,
        "provider": context.provider,
        "variant": context.variant,
        "harness": row.get("harness"),
        "model_variant_id": variant_id(
            model_canonical,
            context.provider,
            context.variant,
            row.get("harness"),
        ),
        "benchmark_id": benchmark_id,
        "benchmark_identity_basis": benchmark_basis,
        "benchmark_name": hint.get("benchmark") if hint else context.benchmark,
        "benchmark_version": row.get("benchmark_version")
        or row.get("version")
        or (hint.get("version") if hint else None),
        "benchmark_updated_at": row.get("updated")
        or (hint.get("updated") if hint else None),
        "release": row.get("release")
        or row.get("release_id")
        or context.artifact.release,
        "fallback_inclusion": row.get("fallback_inclusion")
        or row.get("fallback_state")
        or row.get("fallbacks"),
        "task_count": row.get("task_count")
        or (hint.get("total_models") if hint else None),
        "task_count_population": row.get("task_count_population")
        or ("detail_models" if hint and hint.get("total_models") is not None else None),
        "task_count_kind": (
            "published"
            if row.get("task_count") is not None
            or (hint and hint.get("total_models") is not None)
            else None
        ),
        "metrics": {},
        "raw_fields": {},
        "dependencies": [],
        "independence_class": "unknown",
        "value_status": "published",
        "source_evidence": [],
    }


def _has_metric_shape(value: Mapping[str, object]) -> bool:
    return any(
        key in value
        for key in (
            "value",
            "raw_value",
            "score",
            "accuracy",
            "quality",
            "latency",
            "cost_per_test",
        )
    )


def _metric_candidates(
    context: _RowContext,
) -> tuple[list[tuple[str, object, str]], bool]:
    row = context.row
    candidates: list[tuple[str, object, str]] = []
    known_keys = set(_META_FIELDS)
    metric_container = row.get("metrics")
    if isinstance(metric_container, Mapping):
        candidates.extend(
            (str(key), value, f"{context.source_path}.metrics.{key}")
            for key, value in metric_container.items()
        )
        known_keys.add("metrics")
    for key, value in row.items():
        if key in known_keys:
            continue
        if (
            isinstance(value, Mapping)
            and key not in {"metadata", "raw_fields"}
            and _has_metric_shape(value)
        ):
            candidates.append((str(key), value, f"{context.source_path}.{key}"))
            known_keys.add(key)
        else:
            candidates.append((str(key), value, f"{context.source_path}.{key}"))
    if not candidates and isinstance(row.get("score"), (int, float, str)):
        candidates.append(("score", row["score"], f"{context.source_path}.score"))
    source_zero = row.get("source_zero") is True or row.get("proven_zero") is True
    return candidates, source_zero


def _non_metric_field(field_name: str, value: object) -> bool:
    if isinstance(value, (Mapping, int, float)):
        return False
    if field_name in _KNOWN_FIELDS:
        return False
    if not isinstance(value, str):
        return True
    lowered = value.strip().casefold()
    return not (
        any(character.isdigit() for character in value)
        or lowered in _SENTINELS
        or lowered in {"not-a-number", "infinity", "-infinity"}
    )


def _candidate_metric(
    context: _RowContext,
    field: str,
    value: object,
    path: str,
    *,
    source_zero: bool,
) -> tuple[str, object, dict[str, Any] | None, list[dict[str, object]], bool]:
    field_name = field.rsplit(".", maxsplit=1)[-1].casefold()
    if _non_metric_field(field_name, value):
        return field, value, None, [], True
    raw_value, metadata = _unwrap_metric(value)
    unit = (
        metadata.get("unit")
        or metadata.get("scale")
        or context.row.get(f"{field}_unit")
        or context.row.get("unit")
    )
    hint = context.benchmark_hint
    definition = (
        metadata.get("definition")
        or metadata.get("description")
        or context.row.get(f"{field}_definition")
        or (
            hint.get("score_definition")
            if hint and field_name in {"score", "accuracy"}
            else None
        )
    )
    normalized, diagnostics = normalize_numeric(
        raw_value,
        unit=unit,
        definition=definition,
        source_zero=source_zero
        or metadata.get("proven_zero") is True
        or metadata.get("source_zero") is True,
        source_path=path,
        field=field_name,
        artifact=context.artifact,
        extraction_method=context.document.extraction_method,
    )
    metric = {
        "family": field_name,
        "raw_label": field,
        "definition": definition,
        "metric_semantics_status": normalized["metric_semantics_status"],
        "value": normalized,
        "comparison_eligibility": normalized["comparison_eligibility"],
        "blocked_reasons": normalized["blocked_reasons"],
    }
    keep_raw = (
        field_name not in _KNOWN_FIELDS
        or normalized["metric_semantics_status"] == "unknown"
    )
    return field, value, metric, diagnostics, keep_raw


def _finalize_row(
    result: dict[str, Any],
    row: Mapping[str, object],
    diagnostics: list[dict[str, object]],
) -> None:
    if isinstance(row.get("raw_fields"), Mapping):
        result["raw_fields"].update(dict(row["raw_fields"]))
    if any(
        item.get("value", {}).get("value_status") == "unparsed"
        for item in result["metrics"].values()
        if isinstance(item, Mapping)
    ):
        result["value_status"] = "unparsed"
    if diagnostics:
        result["warnings"] = diagnostics


def normalize_row(
    row: Mapping[str, object],
    artifact: RawArtifact,
    document: ParsedDocument,
    *,
    source_path: str = "$",
    benchmark_hint: Mapping[str, object] | None = None,
) -> tuple[dict[str, Any], list[dict[str, object]]]:
    """Normalize one source row while preserving raw evidence and diagnostics."""
    model, benchmark, provider, variant = _row_identity(row)
    if not model:
        return _missing_row(row, source_path)
    if benchmark is None and benchmark_hint:
        benchmark = (
            str(
                benchmark_hint.get("benchmark_id")
                or benchmark_hint.get("slug")
                or benchmark_hint.get("benchmark")
                or ""
            )
            or None
        )
    context = _RowContext(
        row=row,
        artifact=artifact,
        document=document,
        source_path=source_path,
        benchmark_hint=benchmark_hint,
        model=model,
        benchmark=benchmark,
        provider=provider,
        variant=variant,
    )
    result = _initial_result(context)
    candidates, source_zero = _metric_candidates(context)
    diagnostics: list[dict[str, object]] = []
    for candidate_field, candidate_value, path in candidates:
        (
            field,
            value,
            metric,
            field_diags,
            keep_raw,
        ) = _candidate_metric(
            context,
            candidate_field,
            candidate_value,
            path,
            source_zero=source_zero,
        )
        if keep_raw:
            result["raw_fields"][field] = value
        if metric is not None:
            result["metrics"][field] = metric
            result["source_evidence"].append(metric["value"]["source_evidence"])
        diagnostics.extend(field_diags)
    _finalize_row(result, row, diagnostics)
    return result, diagnostics


def _iter_direct_rows(
    root: Mapping[str, object], path: str
) -> Iterable[tuple[Mapping[str, object], str, Mapping[str, object] | None]]:
    for key in ("rows", "records", "leaderboard", "results"):
        value = root.get(key)
        if not isinstance(value, list):
            continue
        for index, item in enumerate(value):
            if isinstance(item, Mapping):
                yield item, f"{path}.{key}[{index}]", None


def _iter_task_rows(
    tasks: Mapping[str, object], path: str
) -> Iterable[tuple[Mapping[str, object], str, Mapping[str, object] | None]]:
    by_model: dict[str, dict[str, object]] = {}
    for task_name, task_rows in tasks.items():
        if not isinstance(task_rows, Mapping):
            continue
        for model_name, metric in task_rows.items():
            row = by_model.setdefault(str(model_name), {"model": model_name})
            row[str(task_name)] = metric
    for model_name, row in by_model.items():
        yield row, f"{path}.tasks[{model_name}]", None


def _iter_nested(
    root: Mapping[str, object], path: str
) -> Iterable[tuple[Mapping[str, object], str, Mapping[str, object] | None]]:
    skipped = {"rows", "records", "leaderboard", "results", "models", "tasks"}
    for key, value in root.items():
        if key in skipped or not isinstance(value, (Mapping, list)):
            continue
        yield from iter_record_candidates(value, f"{path}.{key}")


def iter_record_candidates(
    root: object, path: str = "$"
) -> Iterable[tuple[Mapping[str, object], str, Mapping[str, object] | None]]:
    """Find model rows in arbitrary JSON/decoded Astro nesting."""
    if isinstance(root, list):
        for index, item in enumerate(root):
            yield from iter_record_candidates(item, f"{path}[{index}]")
        return
    if not isinstance(root, Mapping):
        return
    row_keys = {"model", "model_name", "model_key", "model_slug"}
    if any(key in root for key in row_keys):
        yield root, path, None
    yield from _iter_direct_rows(root, path)
    tasks = root.get("tasks")
    if isinstance(tasks, Mapping):
        yield from _iter_task_rows(tasks, path)
    yield from _iter_nested(root, path)


def normalize_document_records(
    document: ParsedDocument, *, benchmark_hint: Mapping[str, object] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, object]]]:
    """Normalize every discoverable model row in a parsed document."""
    records: list[dict[str, Any]] = []
    diagnostics: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for row, path, hint in iter_record_candidates(document.root):
        if path in seen_paths:
            continue
        seen_paths.add(path)
        normalized, row_diags = normalize_row(
            row,
            document.artifact,
            document,
            source_path=path,
            benchmark_hint=benchmark_hint or hint,
        )
        if "model_id" in normalized:
            records.append(normalized)
        diagnostics.extend(row_diags)
    return records, diagnostics
