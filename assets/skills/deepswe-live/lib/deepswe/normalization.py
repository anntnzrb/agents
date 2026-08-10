"""Conservative DeepSWE value and row normalization.

Normalization is additive: source rows keep every original key and value while
numeric observations are projected into ``metrics``.  Unknown fields remain in
``raw_fields`` and unknown top-level payload metadata remains in
``raw_metadata``.  No unsafe value is converted to zero.
"""

# Copyright 2026 DeepSWE contributors.
from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Final

from .provenance import value_evidence
from .semantics import MetricSemantics, metric_semantics

_NUMERIC_RE: Final[re.Pattern[str]] = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"
)
_GROUPED_NUMERIC_RE: Final[re.Pattern[str]] = re.compile(
    r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d*)?(?:[eE][+-]?\d+)?$"
)
_NUMERIC_UNIT_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"\s*(?P<unit>tokens?|token_count|usd|\$|count|ratio|fraction|%)$",
    re.IGNORECASE,
)
_SENTINELS: Final[frozenset[str]] = frozenset(
    {
        "",
        "n/a",
        "na",
        "n.a.",
        "none",
        "null",
        "not available",
        "not applicable",
        "unavailable",
        "-",
        "--",
        "–",  # noqa: RUF001
        "—",
        "…",
        "...",
        "loading",
        "loading...",
        "pending",
    }
)
_NONFINITE_TEXT: Final[frozenset[str]] = frozenset(
    {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}
)
_META_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "model",
        "reasoning_effort",
        "harness",
        "config",
        "id",
        "name",
        "model_name",
        "model_id",
        "provider",
        "company",
        "variant",
        "slug",
        "benchmark",
        "benchmark_name",
        "benchmark_id",
        "benchmark_version",
        "version",
        "release",
        "release_id",
        "source",
        "eval_scope",
        "included_in_score",
        "trial_id",
        "task_id",
        "task_count",
        "metadata",
        "scope",
        "provenance",
        "generated_at",
        "updated_at",
        "updated",
        "url",
        "raw_fields",
        "raw_metadata",
        "source_evidence",
        "derived",
        "value_status",
        "metrics",
    }
)
_METRIC_WORDS: Final[tuple[str, ...]] = (
    "metric",
    "score",
    "rate",
    "pass",
    "accuracy",
    "quality",
    "cost",
    "token",
    "step",
    "count",
    "attempt",
    "task",
    "ci_",
)


def _unique_reasons(reasons: Iterable[object]) -> list[object]:
    result: list[object] = []
    for reason in reasons:
        if reason not in result:
            result.append(reason)
    return result


def _as_number(value: Decimal) -> int | float | None:
    if not value.is_finite():
        return None
    if value == value.to_integral_value():
        try:
            return int(value)
        except (OverflowError, ValueError):
            return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _decimal_number(  # noqa: C901, PLR0911, PLR0912
    value: object,
) -> tuple[Decimal | None, str | None]:
    if isinstance(value, bool):
        return None, "BOOLEAN_VALUE"
    if isinstance(value, int):
        return Decimal(value), None
    if isinstance(value, float):
        if not math.isfinite(value):
            return None, "NON_FINITE_VALUE"
        return Decimal(str(value)), None
    if isinstance(value, Decimal):
        return (value, None) if value.is_finite() else (None, "NON_FINITE_VALUE")
    if not isinstance(value, str):
        return None, "MALFORMED_PAYLOAD"

    text = value.strip()
    folded = text.casefold()
    if folded in _NONFINITE_TEXT:
        return None, "NON_FINITE_VALUE"
    if _GROUPED_NUMERIC_RE.fullmatch(text):
        text = text.replace(",", "")
        suffix_unit: str | None = None
    elif _NUMERIC_RE.fullmatch(text):
        suffix_unit = None
    else:
        suffix_unit = None
        match = _NUMERIC_UNIT_RE.fullmatch(text)
        if match is None:
            if text.endswith("%"):
                return None, "MALFORMED_PAYLOAD"
            return None, "MALFORMED_PAYLOAD"
        text = match.group("number")
        suffix_unit = match.group("unit").casefold()
        if suffix_unit == "$":
            suffix_unit = "usd"
        elif suffix_unit == "token_count":
            suffix_unit = "tokens"
        elif suffix_unit == "fraction":
            suffix_unit = "ratio"
    try:
        decimal = Decimal(text)
    except (InvalidOperation, ValueError):
        return None, "MALFORMED_PAYLOAD"
    if not decimal.is_finite():
        return None, "NON_FINITE_VALUE"
    return decimal, suffix_unit


def _marker_is_chart_zero(marker: object) -> bool:
    if marker is True:
        return True
    if isinstance(marker, str):
        folded = marker.casefold().replace("-", "_")
        return "chart" in folded and ("zero" in folded or "placeholder" in folded)
    if isinstance(marker, Mapping):
        for key, value in marker.items():
            folded = str(key).casefold().replace("-", "_")
            if (
                folded
                in {
                    "chart_zero",
                    "source_marked_zero",
                    "placeholder_zero",
                    "is_placeholder",
                    "source_zero",
                }
                and value is True
            ):
                return True
    return False


def _source_chart_zero(
    *, raw_value: object, source_marker: object, chart_zero: bool
) -> bool:
    if not (chart_zero or _marker_is_chart_zero(source_marker)):
        return False
    if isinstance(raw_value, bool):
        return False
    if isinstance(raw_value, (int, float, Decimal)):
        try:
            return float(raw_value) == 0.0
        except (OverflowError, ValueError):
            return False
    if isinstance(raw_value, str):
        return raw_value.strip().casefold() in {"0%", "0.0%", "0.00%"}
    return False


def _semantic_metadata(spec: MetricSemantics | None) -> dict[str, object]:
    if spec is None:
        return {}
    return {
        "range": [spec.minimum, spec.maximum],
        "comparator": spec.comparator,
        "scope": spec.scope,
        "denominator": spec.denominator,
    }


def _evidence(  # noqa: PLR0913
    *,
    raw_value: object,
    normalized_value: object,
    spec: MetricSemantics | None,
    field: str | None,
    source_path: str | None,
    value_status: str,
    semantics_status: str,
    blocked_reasons: Iterable[object] = (),
    missing_reason: str | None = None,
    unit: str | None = None,
    normalization: str | None = None,
    family: str | None = None,
) -> dict[str, object]:
    selected_unit = (
        unit if unit is not None else (spec.unit if spec is not None else None)
    )
    reasons = list(blocked_reasons)
    if semantics_status == "unknown" and "UNKNOWN_SCORE_SEMANTICS" not in reasons:
        reasons.append("UNKNOWN_SCORE_SEMANTICS")
    if semantics_status == "ambiguous" and "NUMERIC_AMBIGUITY" not in reasons:
        reasons.append("NUMERIC_AMBIGUITY")
    if (
        normalized_value is None
        and value_status == "missing"
        and "SOURCE_FIELD_ABSENT" not in reasons
    ):
        reasons.append("SOURCE_FIELD_ABSENT")
    if (
        normalized_value is None
        and value_status == "unparsed"
        and "UNPARSED_VALUE" not in reasons
        and "OUT_OF_RANGE" not in reasons
    ):
        reasons.append("UNPARSED_VALUE")
    reasons = _unique_reasons(reasons)
    eligible = (
        value_status in {"published", "derived"}
        and normalized_value is not None
        and semantics_status == "known"
        and not reasons
    )
    result = value_evidence(
        raw_value=raw_value,
        normalized_value=normalized_value,
        unit=selected_unit,
        normalization=normalization,
        source_path=source_path,
        source_field=field,
        family=family or (spec.family if spec is not None else None),
        value_status=value_status,
        metric_semantics_status=semantics_status,
        comparison_eligibility="eligible" if eligible else "blocked",
        blocked_reasons=reasons,
        missing_reason=missing_reason,
    )
    result.update(_semantic_metadata(spec))
    return result


def parse_numeric(  # noqa: C901, PLR0911, PLR0912, PLR0913, PLR0915
    raw_value: object,
    *,
    metric: str | None = None,
    field: str | None = None,
    unit: str | None = None,
    source_path: str | None = None,
    source_field: str | None = None,
    source_marker: object = None,
    chart_zero: bool = False,
    value_status: str = "published",
    blocked_reasons: Iterable[object] = (),
    normalization: str | None = None,
) -> dict[str, object]:
    """Parse one DeepSWE scalar without coercion or clamping.

    Known fields use the source-local registry to resolve bare numbers.  A
    percent suffix is converted to a ratio only for ratio fields.  Unknown
    fields are retained with their numeric observation but remain blocked from
    strict comparisons because their scale and meaning are not published.
    """
    selected_field = source_field or field or metric
    spec = metric_semantics(metric or field or "")
    path = source_path or (f"$.{selected_field}" if selected_field else None)
    marker = source_marker
    if isinstance(source_marker, Mapping):
        marker = dict(source_marker)
    selected_unit = unit or (spec.unit if spec is not None else None)

    if raw_value is None:
        return _evidence(
            raw_value=None,
            normalized_value=None,
            spec=spec,
            field=selected_field,
            source_path=path,
            value_status="missing",
            semantics_status="placeholder",
            blocked_reasons=(*blocked_reasons, "SOURCE_FIELD_ABSENT"),
            missing_reason="SOURCE_FIELD_ABSENT",
            unit=selected_unit,
            normalization="missing",
        )

    if isinstance(raw_value, str) and raw_value.strip().casefold() in _SENTINELS:
        return _evidence(
            raw_value=raw_value,
            normalized_value=None,
            spec=spec,
            field=selected_field,
            source_path=path,
            value_status="missing",
            semantics_status="placeholder",
            blocked_reasons=(*blocked_reasons, "PLACEHOLDER_VALUE"),
            missing_reason="PLACEHOLDER_VALUE",
            unit=selected_unit,
            normalization="placeholder",
        )

    if (
        _source_chart_zero(
            raw_value=raw_value, source_marker=marker, chart_zero=chart_zero
        )
        and isinstance(raw_value, str)
        and raw_value.strip().endswith("%")
    ):
        return _evidence(
            raw_value=raw_value,
            normalized_value=None,
            spec=spec,
            field=selected_field,
            source_path=path,
            value_status="missing",
            semantics_status="placeholder",
            blocked_reasons=(*blocked_reasons, "PLACEHOLDER_VALUE"),
            missing_reason="PLACEHOLDER_VALUE",
            unit="ratio" if spec is not None and spec.unit == "ratio" else "percent",
            normalization="placeholder: source_marked_chart_zero",
        )

    decimal, parsed_unit_or_error = _decimal_number(raw_value)
    # ``_decimal_number`` returns the suffix unit for successful strings and
    # the parse error for failures.  Do not mistake ``%`` for a diagnostic.
    suffix_unit = parsed_unit_or_error if decimal is not None else None
    parse_error = parsed_unit_or_error if decimal is None else None
    if parse_error is not None or decimal is None:
        status = "unparsed"
        semantics_status = "invalid"
        return _evidence(
            raw_value=raw_value,
            normalized_value=None,
            spec=spec,
            field=selected_field,
            source_path=path,
            value_status=status,
            semantics_status=semantics_status,
            blocked_reasons=(*blocked_reasons, parse_error or "MALFORMED_PAYLOAD"),
            unit=selected_unit,
            normalization=normalization or "unparsed",
        )

    # Recover a suffix unit without reparsing the scalar.  This is intentionally
    # restricted to the small set accepted by ``_NUMERIC_UNIT_RE``.
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if text.endswith("%"):
            suffix_unit = "%"
        else:
            unit_match = _NUMERIC_UNIT_RE.fullmatch(text)
            if unit_match is not None:
                suffix_unit = unit_match.group("unit").casefold()
                if suffix_unit == "$":
                    suffix_unit = "usd"
                elif suffix_unit == "token_count":
                    suffix_unit = "tokens"
                elif suffix_unit == "fraction":
                    suffix_unit = "ratio"

    expected_unit = spec.unit if spec is not None else unit
    if suffix_unit is not None and suffix_unit != "%":
        if expected_unit is not None and suffix_unit != expected_unit:
            return _evidence(
                raw_value=raw_value,
                normalized_value=None,
                spec=spec,
                field=selected_field,
                source_path=path,
                value_status="unparsed",
                semantics_status="invalid",
                blocked_reasons=(*blocked_reasons, "UNIT_MISMATCH"),
                unit=expected_unit,
                normalization=normalization or "unit mismatch",
            )
        expected_unit = suffix_unit
    if suffix_unit == "%":
        # A percent sign is lexical unit syntax, not a diagnostic.  Convert it
        # before applying the metric's canonical range so a known ratio sees
        # 50% as .5 and 101% as the out-of-range ratio 1.01.
        if spec is not None and spec.unit != "ratio":
            return _evidence(
                raw_value=raw_value,
                normalized_value=None,
                spec=spec,
                field=selected_field,
                source_path=path,
                value_status="unparsed",
                semantics_status="invalid",
                blocked_reasons=(*blocked_reasons, "UNIT_MISMATCH"),
                unit=spec.unit,
                normalization=normalization or "unit mismatch",
            )
        if spec is None and unit not in {None, "ratio", "percent"}:
            return _evidence(
                raw_value=raw_value,
                normalized_value=None,
                spec=spec,
                field=selected_field,
                source_path=path,
                value_status="unparsed",
                semantics_status="invalid",
                blocked_reasons=(*blocked_reasons, "UNIT_MISMATCH"),
                unit=unit,
                normalization=normalization or "unit mismatch",
            )
        if expected_unit == "ratio":
            decimal /= Decimal(100)
            normalization = normalization or "percent converted to ratio"
        else:
            expected_unit = "percent"
            normalization = normalization or "source percent; no conversion"
    if expected_unit is None:
        semantics_status = "unknown" if spec is None else "ambiguous"
        reasons = (
            ("UNKNOWN_SCORE_SEMANTICS", "NUMERIC_AMBIGUITY")
            if spec is None
            else ("NUMERIC_AMBIGUITY",)
        )
        number = _as_number(decimal)
        return _evidence(
            raw_value=raw_value,
            normalized_value=number,
            spec=spec,
            field=selected_field,
            source_path=path,
            value_status=value_status,
            semantics_status=semantics_status,
            blocked_reasons=(*blocked_reasons, *reasons),
            unit=None,
            normalization=normalization or "ambiguous scale",
        )

    number = _as_number(decimal)
    if number is None:
        return _evidence(
            raw_value=raw_value,
            normalized_value=None,
            spec=spec,
            field=selected_field,
            source_path=path,
            value_status="unparsed",
            semantics_status="invalid",
            blocked_reasons=(*blocked_reasons, "NON_FINITE_VALUE"),
            unit=expected_unit,
            normalization=normalization or "unparsed",
        )

    minimum = (
        spec.minimum
        if spec is not None
        else (
            0
            if expected_unit in {"ratio", "percent", "count", "tokens", "usd"}
            else None
        )
    )
    maximum = (
        spec.maximum
        if spec is not None
        else (
            100
            if expected_unit == "percent"
            else (1 if expected_unit == "ratio" else None)
        )
    )
    if (minimum is not None and decimal < Decimal(str(minimum))) or (
        maximum is not None and decimal > Decimal(str(maximum))
    ):
        return _evidence(
            raw_value=raw_value,
            normalized_value=None,
            spec=spec,
            field=selected_field,
            source_path=path,
            value_status="unparsed",
            semantics_status="invalid",
            blocked_reasons=(*blocked_reasons, "OUT_OF_RANGE"),
            unit=expected_unit,
            normalization=normalization or "out of range; no clamping",
        )

    known = spec is not None
    stable_normalization = normalization or (
        "source ratio; no conversion"
        if expected_unit == "ratio"
        else "source unit; no conversion"
    )
    return _evidence(
        raw_value=raw_value,
        normalized_value=number,
        spec=spec,
        field=selected_field,
        source_path=path,
        value_status=value_status,
        semantics_status="known" if known else "unknown",
        blocked_reasons=blocked_reasons,
        unit=expected_unit,
        normalization=stable_normalization,
    )


def normalize_metric(  # noqa: PLR0913
    field: str,
    raw_value: object,
    *,
    source_path: str | None = None,
    source_marker: object = None,
    chart_zero: bool = False,
    unit: str | None = None,
    value_status: str = "published",
) -> dict[str, object]:
    """Normalize one named DeepSWE metric into value evidence."""
    value = raw_value
    if isinstance(raw_value, Mapping):
        for key in ("value", "raw_value", "score", "value_raw"):
            if key in raw_value:
                value = raw_value[key]
                break
        if unit is None:
            candidate_unit = raw_value.get("unit") or raw_value.get("scale")
            if isinstance(candidate_unit, str):
                unit = candidate_unit.strip().casefold()
        source_marker = raw_value.get(
            "source_marker", raw_value.get("metadata", source_marker)
        )
        chart_zero = chart_zero or raw_value.get("chart_zero") is True
    return parse_numeric(
        value,
        metric=field,
        unit=unit,
        source_path=source_path or f"$.{field}",
        source_field=field,
        source_marker=source_marker,
        chart_zero=chart_zero,
        value_status=value_status,
    )


def normalize_numeric(raw_value: object, **kwargs: object) -> dict[str, object]:
    """Keyword-friendly alias for :func:`parse_numeric`."""
    allowed = {
        "metric",
        "field",
        "unit",
        "source_path",
        "source_field",
        "source_marker",
        "chart_zero",
        "value_status",
        "blocked_reasons",
        "normalization",
    }
    options = {key: value for key, value in kwargs.items() if key in allowed}
    return parse_numeric(raw_value, **options)  # type: ignore[arg-type]


def _looks_like_metric(field: str, value: object) -> bool:
    folded = field.casefold()
    if any(word in folded for word in _METRIC_WORDS):
        return True
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return True
    if value is None and field.endswith(("_value", "_metric")):
        return True
    if isinstance(value, str):
        text = value.strip().casefold()
        return (
            text in _SENTINELS
            or text in _NONFINITE_TEXT
            or bool(_NUMERIC_RE.fullmatch(text))
            or bool(_GROUPED_NUMERIC_RE.fullmatch(text))
            or bool(_NUMERIC_UNIT_RE.fullmatch(text))
            or text.endswith("%")
        )
    return isinstance(value, Mapping) and any(
        key in value for key in ("value", "raw_value", "score", "value_raw")
    )


def _evidence_like(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and "normalized_value" in value
        and "raw_value" in value
    )


def normalize_row(
    row: Mapping[str, object],
    *,
    source_path: str = "$",
) -> dict[str, object]:
    """Copy one row and attach metric evidence and unknown raw fields."""
    result: dict[str, object] = dict(row)
    metrics: dict[str, object] = {}
    existing_metrics = row.get("metrics")
    if isinstance(existing_metrics, Mapping):
        for key, value in existing_metrics.items():
            name = str(key)
            if _evidence_like(value):
                metrics[name] = dict(value)
            else:
                metrics[name] = normalize_metric(
                    name,
                    value,
                    source_path=f"{source_path}.metrics.{name}",
                )
    existing_raw = row.get("raw_fields")
    raw_fields: dict[str, object] = (
        dict(existing_raw) if isinstance(existing_raw, Mapping) else {}
    )
    known_names = set(SEMANTIC_FIELDS)
    for key, value in row.items():
        name = str(key)
        if name in {"metrics", "raw_fields"} or name.casefold() in _META_FIELDS:
            continue
        path = f"{source_path}.{name}"
        if name in known_names:
            metrics[name] = normalize_metric(name, value, source_path=path)
            continue
        if _looks_like_metric(name, value):
            metrics[name] = normalize_metric(name, value, source_path=path)
            raw_fields[name] = value
        else:
            raw_fields[name] = value
    if metrics:
        result["metrics"] = metrics
    if raw_fields:
        result["raw_fields"] = raw_fields
    return result


# Kept as a tuple to make the candidate set explicit and avoid importing the
# registry's mutable mapping into row code.
SEMANTIC_FIELDS: Final[tuple[str, ...]] = tuple(
    name
    for name in (
        metric_semantics(name).field
        for name in (
            "pass_rate",
            "pass_at_1",
            "pass_at_4",
            "n_passed",
            "n_attempted",
            "n_tasks_attempted",
            "n_tasks_passed_any",
            "ci_passed",
            "ci_attempted",
            "ci_lo",
            "ci_hi",
            "ci_half",
            "mean_output_tokens",
            "mean_cost_usd",
            "mean_agent_steps",
        )
    )
    if name is not None
)


def normalize_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    source_path: str = "$.rows",
) -> list[dict[str, object]]:
    """Normalize a sequence of source rows with stable evidence paths."""
    return [
        normalize_row(row, source_path=f"{source_path}[{index}]")
        for index, row in enumerate(rows)
        if isinstance(row, Mapping)
    ]


def _top_level_known(key: str) -> bool:
    return key in {
        "rows",
        "leaderboard",
        "models",
        "results",
        "records",
        "trials",
        "data",
        "payload",
        "content",
        "json",
        "scope",
        "provenance",
        "generated_at",
        "benchmark",
        "benchmark_version",
        "version",
        "release",
        "metadata",
        "stats",
        "artifacts",
        "raw_metadata",
    }


def normalize_payload(  # noqa: C901
    payload: Mapping[str, object] | Sequence[Mapping[str, object]] | None,
    *,
    source_path: str = "$",
) -> object:
    """Normalize rows in a payload while preserving unknown metadata."""
    if isinstance(payload, Sequence) and not isinstance(
        payload, (str, bytes, bytearray)
    ):
        return normalize_rows(payload, source_path=f"{source_path}.rows")
    if not isinstance(payload, Mapping):
        return payload
    if any(key in payload for key in ("model", "config", "pass_at_1", "trial_id")):
        return normalize_row(payload, source_path=source_path)
    result: dict[str, object] = dict(payload)
    raw_metadata: dict[str, object] = (
        dict(payload.get("raw_metadata"))
        if isinstance(payload.get("raw_metadata"), Mapping)
        else {}
    )
    for key, value in payload.items():
        name = str(key)
        if name == "raw_metadata" or _top_level_known(name):
            if name in {
                "rows",
                "leaderboard",
                "models",
                "results",
                "records",
                "trials",
            }:
                if isinstance(value, Sequence) and not isinstance(
                    value, (str, bytes, bytearray)
                ):
                    result[name] = normalize_rows(
                        value,
                        source_path=f"{source_path}.{name}",
                    )
                elif isinstance(value, Mapping):
                    nested = normalize_payload(
                        value, source_path=f"{source_path}.{name}"
                    )
                    result[name] = nested
            elif name in {"data", "payload", "content", "json"} and isinstance(
                value, Mapping
            ):
                result[name] = normalize_payload(
                    value, source_path=f"{source_path}.{name}"
                )
            continue
        raw_metadata[name] = value
    if raw_metadata:
        result["raw_metadata"] = raw_metadata
    return result


__all__ = [
    "SEMANTIC_FIELDS",
    "normalize_metric",
    "normalize_numeric",
    "normalize_payload",
    "normalize_row",
    "normalize_rows",
    "parse_numeric",
]
