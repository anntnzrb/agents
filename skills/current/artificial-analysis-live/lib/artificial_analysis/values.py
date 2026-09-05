# Copyright (c) 2026 anntnzrb
"""Evidence records and conservative numeric parsing for Artificial Analysis."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final, cast

from .contracts import (
    ComparisonEligibility,
    MetricSemanticsStatus,
    NumericEvidence,
    SourceEvidence,
    ValueStatus,
)


class PlaceholderKind(StrEnum):
    """Recognized non-values retained as missing evidence."""

    EMPTY = "empty"
    NOT_AVAILABLE = "not_available"
    DASH = "dash"
    LOADING = "loading"
    SOURCE_MARKED_CHART_ZERO = "source_marked_chart_zero"


_PLACEHOLDER_TEXT: Final[dict[str, PlaceholderKind]] = {
    "": PlaceholderKind.EMPTY,
    "n/a": PlaceholderKind.NOT_AVAILABLE,
    "na": PlaceholderKind.NOT_AVAILABLE,
    "n.a.": PlaceholderKind.NOT_AVAILABLE,
    "none": PlaceholderKind.NOT_AVAILABLE,
    "null": PlaceholderKind.NOT_AVAILABLE,
    "not available": PlaceholderKind.NOT_AVAILABLE,
    "not applicable": PlaceholderKind.NOT_AVAILABLE,
    "-": PlaceholderKind.DASH,
    "--": PlaceholderKind.DASH,
    "\N{EN DASH}": PlaceholderKind.DASH,
    "\N{EM DASH}": PlaceholderKind.DASH,
    "\N{HORIZONTAL ELLIPSIS}": PlaceholderKind.DASH,
    "...": PlaceholderKind.DASH,
    "loading": PlaceholderKind.LOADING,
    "loading...": PlaceholderKind.LOADING,
    "pending": PlaceholderKind.LOADING,
}

_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_NUMBER_AND_UNIT_RE = re.compile(
    r"^(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
    + r")\s*(?P<unit>[A-Za-zµμ%][A-Za-z0-9µμ/_-]*)$"
)
_RANGE_RE = re.compile(
    r"^\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*(?:-|\N{EN DASH}|\N{EM DASH}|\bto\b)\s*"
    + r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*$",
)

_THOUSANDS_RE = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d*)?(?:[eE][+-]?\d+)?$")
_NONFINITE_TEXT = frozenset(
    {
        "nan",
        "+nan",
        "-nan",
        "inf",
        "+inf",
        "-inf",
        "infinity",
        "+infinity",
        "-infinity",
    }
)
_PERCENT_MAX = Decimal(100)


def _explicit_true(value: object) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "on", "true", "yes"}
    return False


def _marker_is_chart_zero(marker: object) -> bool:
    if _explicit_true(marker):
        return True
    if isinstance(marker, str):
        lowered = marker.casefold()
        if any(word in lowered for word in ("false", "never", "no")):
            return False
        return "chart" in lowered and ("zero" in lowered or "placeholder" in lowered)
    if isinstance(marker, Mapping):
        mapping = cast("Mapping[str, object]", marker)
        return any(
            str(key).casefold().replace("-", "_")
            in {
                "chart_zero",
                "source_marked_zero",
                "placeholder_zero",
                "is_placeholder",
            }
            and _explicit_true(item)
            for key, item in mapping.items()
        )
    return False


def classify_placeholder(
    raw_value: object,
    *,
    source_marker: object | None = None,
    chart_zero: bool = False,
) -> PlaceholderKind | None:
    """Classify textual placeholders and explicitly source-marked chart zeroes."""
    if chart_zero is True or _marker_is_chart_zero(source_marker):
        try:
            is_zero = (
                isinstance(raw_value, (int, float, str, Decimal))
                and float(raw_value) == 0.0
                and not isinstance(raw_value, bool)
            )
        except (OverflowError, TypeError, ValueError):
            is_zero = False
        if is_zero:
            return PlaceholderKind.SOURCE_MARKED_CHART_ZERO
    if raw_value is None:
        return PlaceholderKind.EMPTY
    if isinstance(raw_value, str):
        return _PLACEHOLDER_TEXT.get(raw_value.strip().casefold())
    return None


def _unique_reasons(reasons: Iterable[str]) -> tuple[str, ...]:
    output: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        value = str(reason)
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return tuple(output)


def _status(value: ValueStatus | str | None, default: ValueStatus) -> ValueStatus:
    return default if value is None else ValueStatus(value)


def _normalise_unit(unit: object) -> str | None:
    if unit is None:
        return None
    if not isinstance(unit, str):
        message = "unit must be a string or None"
        raise TypeError(message)
    value = unit.strip()
    if not value:
        return None
    aliases = {"percent": "%", "percentage": "%"}
    return aliases.get(value.casefold(), value)


def _parse_number_and_unit(  # noqa: C901, PLR0911, PLR0912
    raw_value: object,
    explicit_unit: str | None,
) -> tuple[Decimal | None, str | None, str | None]:
    explicit_unit = _normalise_unit(explicit_unit)
    if isinstance(raw_value, bool):
        return None, explicit_unit, "boolean_value"
    if isinstance(raw_value, int):
        return Decimal(raw_value), explicit_unit, None
    if isinstance(raw_value, float):
        if not math.isfinite(raw_value):
            return None, explicit_unit, "non_finite_value"
        return Decimal(str(raw_value)), explicit_unit, None
    if isinstance(raw_value, Decimal):
        return (
            (raw_value if raw_value.is_finite() else None),
            explicit_unit,
            (None if raw_value.is_finite() else "non_finite_value"),
        )
    if not isinstance(raw_value, str):
        return None, explicit_unit, "malformed_numeric"

    text = raw_value.strip()
    if text.casefold() in _NONFINITE_TEXT:
        return None, explicit_unit, "non_finite_value"
    if "," in text:
        if not _THOUSANDS_RE.fullmatch(text):
            return None, explicit_unit, "malformed_numeric"
        text = text.replace(",", "")
    if _RANGE_RE.fullmatch(text):
        return None, explicit_unit, "range_not_scalar"
    suffix_unit: str | None = None
    number_text = text
    if any(character.isspace() for character in text):
        return None, explicit_unit, "malformed_numeric"
    if not _NUMBER_RE.fullmatch(text):
        match = _NUMBER_AND_UNIT_RE.fullmatch(text)
        if match is None:
            return None, explicit_unit, "malformed_numeric"
        number_text = match.group("number")
        suffix_unit = _normalise_unit(match.group("unit"))
    if (
        explicit_unit
        and suffix_unit
        and explicit_unit.casefold() != suffix_unit.casefold()
    ):
        return None, explicit_unit, "unit_mismatch"
    parsed_unit = explicit_unit or suffix_unit
    try:
        value = Decimal(number_text)
    except InvalidOperation:
        return None, parsed_unit, "malformed_numeric"
    return (
        (value if value.is_finite() else None),
        parsed_unit,
        (None if value.is_finite() else "non_finite_value"),
    )


def _number_from_decimal(value: Decimal) -> int | float | None:
    """Convert a finite decimal to a JSON-safe scalar without overflow."""
    if not value.is_finite():
        return None
    if value == value.to_integral_value():
        try:
            return int(value)
        except (OverflowError, ValueError):
            return None
    try:
        converted = float(value)
    except (OverflowError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _evidence(  # noqa: PLR0913
    *,
    raw_value: object,
    normalized_value: float | None,
    unit: str | None,
    normalization: str,
    source_path: str | None,
    source_field: str | None,
    value_status: ValueStatus,
    metric_semantics_status: MetricSemanticsStatus,
    blocked_reasons: Iterable[str],
    parser: str,
    parser_version: str,
    artifact_id: str | None,
    sha256: str | None,
    formula: str | None = None,
    input_paths: Iterable[str] = (),
) -> NumericEvidence:
    reasons = list(blocked_reasons)
    if value_status is ValueStatus.MISSING:
        reasons.append("missing_value")
    elif value_status is ValueStatus.UNPARSED:
        normalized_value = None
        reasons.append("unparsed_value")
    if metric_semantics_status is MetricSemanticsStatus.UNKNOWN:
        reasons.append("semantics_unknown")
    elif metric_semantics_status is MetricSemanticsStatus.AMBIGUOUS:
        reasons.append("semantics_ambiguous")
    eligible = (
        value_status in (ValueStatus.PUBLISHED, ValueStatus.DERIVED)
        and normalized_value is not None
        and metric_semantics_status is MetricSemanticsStatus.KNOWN
        and not reasons
    )
    return NumericEvidence(
        raw_value=raw_value,
        normalized_value=normalized_value,
        unit=unit,
        normalization=normalization,
        source_path=source_path,
        source_field=source_field,
        value_status=value_status,
        metric_semantics_status=metric_semantics_status,
        comparison_eligibility=(
            ComparisonEligibility.ELIGIBLE
            if eligible
            else ComparisonEligibility.BLOCKED
        ),
        blocked_reasons=_unique_reasons(reasons),
        parser=parser,
        parser_version=parser_version,
        artifact_id=artifact_id,
        sha256=sha256,
        formula=formula,
        input_paths=tuple(input_paths),
    )


def parse_numeric(  # noqa: C901, PLR0911, PLR0913
    raw_value: object,
    *,
    unit: str | None = None,
    normalization: str | None = None,
    source_path: str | None = None,
    source_field: str | None = None,
    value_status: ValueStatus | str | None = None,
    metric_semantics_status: MetricSemanticsStatus | str = MetricSemanticsStatus.KNOWN,
    source_marker: object | None = None,
    chart_zero: bool = False,
    blocked_reasons: Iterable[str] = (),
    parser: str = "numeric",
    parser_version: str = "1",
    artifact_id: str | None = None,
    sha256: str | None = None,
    formula: str | None = None,
    input_paths: Iterable[str] = (),
) -> NumericEvidence:
    """Parse one scalar conservatively, retaining every unparsed raw value."""
    requested_status = _status(value_status, ValueStatus.PUBLISHED)

    semantic_status = MetricSemanticsStatus(metric_semantics_status)
    placeholder = classify_placeholder(
        raw_value,
        source_marker=source_marker,
        chart_zero=chart_zero,
    )
    if placeholder is not None:
        return _evidence(
            raw_value=raw_value,
            normalized_value=None,
            unit=unit,
            normalization=f"placeholder: {placeholder.value}",
            source_path=source_path,
            source_field=source_field,
            value_status=ValueStatus.MISSING,
            metric_semantics_status=semantic_status,
            blocked_reasons=blocked_reasons,
            parser=parser,
            parser_version=parser_version,
            artifact_id=artifact_id,
            sha256=sha256,
            formula=formula,
            input_paths=input_paths,
        )

    hint = normalization.casefold().strip() if normalization else ""
    explicit_unit = _normalise_unit(unit)
    decimal_value, parsed_unit, parse_error = _parse_number_and_unit(
        raw_value, explicit_unit
    )
    if parse_error is not None or decimal_value is None:
        return _evidence(
            raw_value=raw_value,
            normalized_value=None,
            unit=parsed_unit,
            normalization=(
                "range" if parse_error == "range_not_scalar" else "unparsed"
            ),
            source_path=source_path,
            source_field=source_field,
            value_status=ValueStatus.UNPARSED,
            metric_semantics_status=semantic_status,
            blocked_reasons=(*blocked_reasons, parse_error or "malformed_numeric"),
            parser=parser,
            parser_version=parser_version,
            artifact_id=artifact_id,
            sha256=sha256,
            formula=formula,
            input_paths=input_paths,
        )
    if requested_status in (ValueStatus.MISSING, ValueStatus.UNPARSED):
        return _evidence(
            raw_value=raw_value,
            normalized_value=(
                _number_from_decimal(decimal_value)
                if requested_status is ValueStatus.MISSING
                else None
            ),
            unit=parsed_unit,
            normalization=requested_status.value,
            source_path=source_path,
            source_field=source_field,
            value_status=requested_status,
            metric_semantics_status=semantic_status,
            blocked_reasons=blocked_reasons,
            parser=parser,
            parser_version=parser_version,
            artifact_id=artifact_id,
            sha256=sha256,
            formula=formula,
            input_paths=input_paths,
        )
    inferred_unit = parsed_unit
    is_percent = hint in {"percent", "percentage"} or (
        isinstance(parsed_unit, str) and parsed_unit == "%"
    )
    is_ratio = hint == "ratio" or (
        isinstance(parsed_unit, str) and parsed_unit.casefold() == "ratio"
    )
    number = _number_from_decimal(decimal_value)
    if number is None:
        return _evidence(
            raw_value=raw_value,
            normalized_value=None,
            unit=inferred_unit,
            normalization="unparsed",
            source_path=source_path,
            source_field=source_field,
            value_status=ValueStatus.UNPARSED,
            metric_semantics_status=semantic_status,
            blocked_reasons=(*blocked_reasons, "numeric_overflow"),
            parser=parser,
            parser_version=parser_version,
            artifact_id=artifact_id,
            sha256=sha256,
            formula=formula,
            input_paths=input_paths,
        )

    if is_percent:
        if decimal_value < 0 or decimal_value > _PERCENT_MAX:
            return _evidence(
                raw_value=raw_value,
                normalized_value=None,
                unit="ratio",
                normalization="percent converted to ratio",
                source_path=source_path,
                source_field=source_field,
                value_status=ValueStatus.UNPARSED,
                metric_semantics_status=semantic_status,
                blocked_reasons=(*blocked_reasons, "percent_out_of_range"),
                parser=parser,
                parser_version=parser_version,
                artifact_id=artifact_id,
                sha256=sha256,
                formula=formula,
                input_paths=input_paths,
            )
        converted = float(decimal_value / _PERCENT_MAX)
        return _evidence(
            raw_value=raw_value,
            normalized_value=converted,
            unit="ratio",
            normalization="percent converted to ratio",
            source_path=source_path,
            source_field=source_field,
            value_status=_status(value_status, ValueStatus.PUBLISHED),
            metric_semantics_status=semantic_status,
            blocked_reasons=blocked_reasons,
            parser=parser,
            parser_version=parser_version,
            artifact_id=artifact_id,
            sha256=sha256,
            formula=formula,
            input_paths=input_paths,
        )

    if is_ratio:
        if decimal_value < 0 or decimal_value > 1:
            return _evidence(
                raw_value=raw_value,
                normalized_value=None,
                unit="ratio",
                normalization="source ratio; no conversion",
                source_path=source_path,
                source_field=source_field,
                value_status=ValueStatus.UNPARSED,
                metric_semantics_status=semantic_status,
                blocked_reasons=(*blocked_reasons, "ratio_out_of_range"),
                parser=parser,
                parser_version=parser_version,
                artifact_id=artifact_id,
                sha256=sha256,
                formula=formula,
                input_paths=input_paths,
            )
        return _evidence(
            raw_value=raw_value,
            normalized_value=number,
            unit="ratio",
            normalization="source ratio; no conversion",
            source_path=source_path,
            source_field=source_field,
            value_status=_status(value_status, ValueStatus.PUBLISHED),
            metric_semantics_status=semantic_status,
            blocked_reasons=blocked_reasons,
            parser=parser,
            parser_version=parser_version,
            artifact_id=artifact_id,
            sha256=sha256,
            formula=formula,
            input_paths=input_paths,
        )

    if hint == "range":
        return _evidence(
            raw_value=raw_value,
            normalized_value=None,
            unit=inferred_unit,
            normalization="range",
            source_path=source_path,
            source_field=source_field,
            value_status=ValueStatus.UNPARSED,
            metric_semantics_status=semantic_status,
            blocked_reasons=(*blocked_reasons, "range_not_scalar"),
            parser=parser,
            parser_version=parser_version,
            artifact_id=artifact_id,
            sha256=sha256,
            formula=formula,
            input_paths=input_paths,
        )

    if inferred_unit is not None:
        stable_normalization = "source unit; no conversion"
    else:
        stable_normalization = "source numeric; no conversion"
    return _evidence(
        raw_value=raw_value,
        normalized_value=number,
        unit=inferred_unit,
        normalization=stable_normalization,
        source_path=source_path,
        source_field=source_field,
        value_status=_status(value_status, ValueStatus.PUBLISHED),
        metric_semantics_status=semantic_status,
        blocked_reasons=blocked_reasons,
        parser=parser,
        parser_version=parser_version,
        artifact_id=artifact_id,
        sha256=sha256,
        formula=formula,
        input_paths=input_paths,
    )


def evidence_blockers(evidence: NumericEvidence) -> tuple[str, ...]:
    """Return independent reasons one evidence value cannot be compared."""
    reasons = list(evidence.blocked_reasons)
    if evidence.value_status is ValueStatus.MISSING and "missing_value" not in reasons:
        reasons.append("missing_value")
    if (
        evidence.value_status is ValueStatus.UNPARSED
        and "unparsed_value" not in reasons
    ):
        reasons.append("unparsed_value")
    if evidence.normalized_value is None and "normalized_value_missing" not in reasons:
        reasons.append("normalized_value_missing")
    if (
        evidence.metric_semantics_status is MetricSemanticsStatus.UNKNOWN
        and "semantics_unknown" not in reasons
    ):
        reasons.append("semantics_unknown")
    if (
        evidence.metric_semantics_status is MetricSemanticsStatus.AMBIGUOUS
        and "semantics_ambiguous" not in reasons
    ):
        reasons.append("semantics_ambiguous")
    if evidence.comparison_eligibility is ComparisonEligibility.BLOCKED and not reasons:
        reasons.append("comparison_blocked")
    return _unique_reasons(reasons)


def comparison_blockers(
    left: NumericEvidence,
    right: NumericEvidence,
) -> tuple[str, ...]:
    """Return deterministic blockers for comparing two numeric observations."""
    reasons: list[str] = []
    for evidence in (left, right):
        reasons.extend(evidence_blockers(evidence))
    if (
        left.unit is not None
        and right.unit is not None
        and left.unit.casefold() != right.unit.casefold()
    ) or ((left.unit is None) != (right.unit is None)):
        reasons.append("unit_mismatch")
    return _unique_reasons(reasons)


__all__ = [
    "NumericEvidence",
    "PlaceholderKind",
    "SourceEvidence",
    "classify_placeholder",
    "comparison_blockers",
    "evidence_blockers",
    "parse_numeric",
]
