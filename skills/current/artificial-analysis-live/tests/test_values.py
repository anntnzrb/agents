"""Contract tests for finite JSON and numeric evidence."""

from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest

from artificial_analysis.contracts import (
    ComparisonEligibility,
    MetricSemanticsStatus,
    ValueStatus,
    compact_json,
)
from artificial_analysis.values import (
    NumericEvidence,
    PlaceholderKind,
    SourceEvidence,
    classify_placeholder,
    comparison_blockers,
    evidence_blockers,
    parse_numeric,
)


def test_compact_json_is_finite_compact_and_deterministic() -> None:
    value = {
        7: "string-key conversion",
        "decimal": Decimal("2.50"),
        "nested": (ValueStatus.PUBLISHED, frozenset({"b", "a"})),
    }

    assert compact_json(value) == (
        '{"7":"string-key conversion","decimal":2.5,"nested":["published",["a","b"]]}'
    )


@pytest.mark.parametrize(
    "non_finite",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ],
)
def test_compact_json_rejects_non_finite_numbers(non_finite: object) -> None:
    with pytest.raises(ValueError, match=r"non-finite|Out of range"):
        _ = compact_json({"value": non_finite})


def test_source_evidence_to_dict_defends_all_wire_fields() -> None:
    evidence = SourceEvidence(
        source_url="https://example.test/source",
        final_url="https://example.test/final",
        fetched_at="2026-08-09T00:00:00Z",
        observed_at="2026-08-09T00:00:01Z",
        status=ValueStatus.PUBLISHED,
        etag='"etag-1"',
        last_modified="Thu, 09 Aug 2026 00:00:00 GMT",
        sha256="abc123",
        byte_length=12,
        parser="rsc",
        parser_version="2",
        source_path="payload.rows[0]",
        raw_reference="artifact://one",
    )

    assert evidence.to_dict() == {
        "source_url": "https://example.test/source",
        "final_url": "https://example.test/final",
        "fetched_at": "2026-08-09T00:00:00Z",
        "observed_at": "2026-08-09T00:00:01Z",
        "status": "published",
        "etag": '"etag-1"',
        "last_modified": "Thu, 09 Aug 2026 00:00:00 GMT",
        "sha256": "abc123",
        "byte_length": 12,
        "parser": "rsc",
        "parser_version": "2",
        "source_path": "payload.rows[0]",
        "raw_reference": "artifact://one",
    }


def test_numeric_evidence_keeps_raw_input_and_exact_json_shape() -> None:
    evidence = parse_numeric(
        "42",
        unit="ms",
        source_path="payload.rows[0]",
        source_field="latency",
        parser="aa-numeric",
        parser_version="3",
        artifact_id="artifact-1",
        sha256="hash-1",
    )

    assert evidence.to_dict() == {
        "raw_value": "42",
        "normalized_value": 42,
        "unit": "ms",
        "normalization": "source unit; no conversion",
        "source_path": "payload.rows[0]",
        "source_field": "latency",
        "value_status": "published",
        "metric_semantics_status": "known",
        "comparison_eligibility": "eligible",
        "blocked_reasons": [],
        "parser": "aa-numeric",
        "parser_version": "3",
        "artifact_id": "artifact-1",
        "sha256": "hash-1",
    }
    assert evidence.raw_value == "42"


@pytest.mark.parametrize("raw_value", [0, "0", Decimal(0)])
def test_true_zero_is_a_real_eligible_value(raw_value: object) -> None:
    evidence = parse_numeric(raw_value)

    assert evidence.normalized_value == 0
    assert evidence.normalized_value is not None
    assert not isinstance(evidence.normalized_value, bool)
    assert evidence.value_status is ValueStatus.PUBLISHED
    assert evidence.comparison_eligibility is ComparisonEligibility.ELIGIBLE
    assert evidence.blocked_reasons == ()


@pytest.mark.parametrize(
    ("raw_value", "reason"),
    [
        (True, "boolean_value"),
        (False, "boolean_value"),
        (float("nan"), "non_finite_value"),
        (float("inf"), "non_finite_value"),
        (float("-inf"), "non_finite_value"),
    ],
)
def test_boolean_and_non_finite_values_are_unparsed_and_retained(
    raw_value: object, reason: str
) -> None:
    evidence = parse_numeric(raw_value)
    result = evidence.to_dict()

    assert set(result) == {
        "raw_value",
        "normalized_value",
        "unit",
        "normalization",
        "source_path",
        "source_field",
        "value_status",
        "metric_semantics_status",
        "comparison_eligibility",
        "blocked_reasons",
        "parser",
        "parser_version",
    }
    assert result["raw_value"] is raw_value
    assert result["normalized_value"] is None
    assert result["unit"] is None
    assert result["normalization"] == "unparsed"
    assert result["source_path"] is None
    assert result["source_field"] is None
    assert result["value_status"] == "unparsed"
    assert result["metric_semantics_status"] == "known"
    assert result["comparison_eligibility"] == "blocked"
    assert result["blocked_reasons"] == [reason, "unparsed_value"]
    assert result["parser"] == "numeric"
    assert result["parser_version"] == "1"


@pytest.mark.parametrize(
    ("raw_value", "kind"),
    [
        (None, PlaceholderKind.EMPTY),
        ("", PlaceholderKind.EMPTY),
        ("  N/A  ", PlaceholderKind.NOT_AVAILABLE),
        ("na", PlaceholderKind.NOT_AVAILABLE),
        ("N.A.", PlaceholderKind.NOT_AVAILABLE),
        ("none", PlaceholderKind.NOT_AVAILABLE),
        ("null", PlaceholderKind.NOT_AVAILABLE),
        ("not available", PlaceholderKind.NOT_AVAILABLE),
        ("not applicable", PlaceholderKind.NOT_AVAILABLE),
        ("-", PlaceholderKind.DASH),
        ("--", PlaceholderKind.DASH),
        ("\N{EN DASH}", PlaceholderKind.DASH),
        ("\N{EM DASH}", PlaceholderKind.DASH),
        ("\N{HORIZONTAL ELLIPSIS}", PlaceholderKind.DASH),
        ("...", PlaceholderKind.DASH),
        (" Loading... ", PlaceholderKind.LOADING),
        ("pending", PlaceholderKind.LOADING),
    ],
)
def test_placeholders_are_missing_evidence_with_exact_fields(
    raw_value: object, kind: PlaceholderKind
) -> None:
    assert classify_placeholder(raw_value) is kind
    evidence = parse_numeric(raw_value)

    assert evidence.to_dict() == {
        "raw_value": raw_value,
        "normalized_value": None,
        "unit": None,
        "normalization": f"placeholder: {kind.value}",
        "source_path": None,
        "source_field": None,
        "value_status": "missing",
        "metric_semantics_status": "known",
        "comparison_eligibility": "blocked",
        "blocked_reasons": ["missing_value"],
        "parser": "numeric",
        "parser_version": "1",
    }


@pytest.mark.parametrize(
    "marker",
    [
        True,
        "chart zero placeholder",
        {"chart_zero": True},
        {"source-marked-zero": True},
        {"is_placeholder": True},
    ],
)
def test_explicit_chart_zero_is_missing_but_literal_zero_is_not(marker: object) -> None:
    marked = parse_numeric(0, source_marker=marker)
    literal = parse_numeric(0)

    assert marked.normalized_value is None
    assert marked.normalization == "placeholder: source_marked_chart_zero"
    assert marked.value_status is ValueStatus.MISSING
    assert marked.blocked_reasons == ("missing_value",)
    assert marked.comparison_eligibility is ComparisonEligibility.BLOCKED
    assert literal.normalized_value == 0
    assert literal.comparison_eligibility is ComparisonEligibility.ELIGIBLE


def test_chart_zero_placeholder_handles_huge_numeric_input() -> None:
    huge_value = Decimal("1e1000000")

    assert classify_placeholder(huge_value, source_marker={"chart_zero": True}) is None


@pytest.mark.parametrize(
    ("raw_value", "normalization", "reason"),
    [
        ("abc", None, "malformed_numeric"),
        ("12 milliseconds", None, "malformed_numeric"),
        ({"value": 1}, None, "malformed_numeric"),
        ("1-2", None, "range_not_scalar"),
        ("1 to 2", None, "range_not_scalar"),
        ("3", "range", "range_not_scalar"),
    ],
)
def test_malformed_and_range_values_remain_unparsed(
    raw_value: object, normalization: str | None, reason: str
) -> None:
    evidence = parse_numeric(raw_value, normalization=normalization)

    assert (
        evidence.raw_value is raw_value
        if isinstance(raw_value, dict)
        else evidence.raw_value == raw_value
    )
    assert evidence.normalized_value is None
    assert evidence.value_status is ValueStatus.UNPARSED
    assert evidence.metric_semantics_status is MetricSemanticsStatus.KNOWN
    assert evidence.comparison_eligibility is ComparisonEligibility.BLOCKED
    assert evidence.blocked_reasons == (reason, "unparsed_value")
    assert (
        evidence.normalization == "range"
        if reason == "range_not_scalar"
        else evidence.normalization == "unparsed"
    )


@pytest.mark.parametrize(
    ("raw_value", "normalization", "unit", "reason"),
    [
        ("101%", None, None, "percent_out_of_range"),
        ("-1", "percent", None, "percent_out_of_range"),
        ("1.1", "ratio", None, "ratio_out_of_range"),
        ("-0.1ratio", None, None, "ratio_out_of_range"),
    ],
)
def test_percent_and_ratio_out_of_range_values_are_blocked(
    raw_value: object,
    normalization: str | None,
    unit: str | None,
    reason: str,
) -> None:
    evidence = parse_numeric(raw_value, normalization=normalization, unit=unit)

    assert evidence.raw_value == raw_value
    assert evidence.normalized_value is None
    assert evidence.value_status is ValueStatus.UNPARSED
    assert evidence.comparison_eligibility is ComparisonEligibility.BLOCKED
    assert evidence.blocked_reasons == (reason, "unparsed_value")
    assert evidence.unit == "ratio"
    assert evidence.normalization in {
        "percent converted to ratio",
        "source ratio; no conversion",
    }


def test_unit_mismatch_is_retained_as_an_unparsed_raw_value() -> None:
    evidence = parse_numeric("5ms", unit="s")

    assert evidence.to_dict() == {
        "raw_value": "5ms",
        "normalized_value": None,
        "unit": "s",
        "normalization": "unparsed",
        "source_path": None,
        "source_field": None,
        "value_status": "unparsed",
        "metric_semantics_status": "known",
        "comparison_eligibility": "blocked",
        "blocked_reasons": ["unit_mismatch", "unparsed_value"],
        "parser": "numeric",
        "parser_version": "1",
    }


@pytest.mark.parametrize(
    (
        "raw_value",
        "normalization",
        "unit",
        "expected_value",
        "expected_unit",
        "expected_text",
    ),
    [
        ("25", "percent", None, 0.25, "ratio", "percent converted to ratio"),
        ("25%", None, None, 0.25, "ratio", "percent converted to ratio"),
        (100, "percentage", None, 1.0, "ratio", "percent converted to ratio"),
        ("0.25", "ratio", None, 0.25, "ratio", "source ratio; no conversion"),
        ("0.25ratio", None, None, 0.25, "ratio", "source ratio; no conversion"),
        (1, None, "ratio", 1, "ratio", "source ratio; no conversion"),
    ],
)
def test_explicit_percent_and_ratio_normalization(  # noqa: PLR0917
    raw_value: object,
    normalization: str | None,
    unit: str | None,
    expected_value: float,
    expected_unit: str,
    expected_text: str,
) -> None:
    evidence = parse_numeric(raw_value, normalization=normalization, unit=unit)

    assert evidence.normalized_value == expected_value
    assert evidence.unit == expected_unit
    assert evidence.normalization == expected_text
    assert evidence.value_status is ValueStatus.PUBLISHED
    assert evidence.metric_semantics_status is MetricSemanticsStatus.KNOWN
    assert evidence.comparison_eligibility is ComparisonEligibility.ELIGIBLE
    assert evidence.blocked_reasons == ()
    assert evidence.raw_value == raw_value


@pytest.mark.parametrize(
    "normalized_value",
    [True, False],
)
def test_numeric_evidence_rejects_boolean_normalized_values(
    normalized_value: bool,
) -> None:
    with pytest.raises(TypeError, match="must not be bool"):
        _ = NumericEvidence(
            raw_value=normalized_value,
            normalized_value=cast("int | float | None", normalized_value),
        )


@pytest.mark.parametrize(
    "normalized_value", [float("nan"), float("inf"), float("-inf")]
)
def test_numeric_evidence_rejects_non_finite_normalized_values(
    normalized_value: float,
) -> None:
    with pytest.raises(ValueError, match="must be finite"):
        _ = NumericEvidence(
            raw_value=normalized_value, normalized_value=normalized_value
        )


@pytest.mark.parametrize("value_status", [ValueStatus.MISSING, ValueStatus.UNPARSED])
def test_numeric_evidence_clears_normalized_values_for_non_normalized_statuses(
    value_status: ValueStatus,
) -> None:
    evidence = NumericEvidence(
        raw_value="not-a-number",
        normalized_value=42,
        value_status=value_status,
    )

    assert evidence.value_status is value_status
    assert evidence.normalized_value is None


@pytest.mark.parametrize(
    (
        "value_status",
        "metric_semantics_status",
        "blocked_reasons",
        "expected_reasons",
    ),
    [
        (
            ValueStatus.MISSING,
            MetricSemanticsStatus.KNOWN,
            (),
            ("missing_value",),
        ),
        (
            None,
            MetricSemanticsStatus.UNKNOWN,
            (),
            ("semantics_unknown",),
        ),
        (
            None,
            MetricSemanticsStatus.AMBIGUOUS,
            (),
            ("semantics_ambiguous",),
        ),
        (
            None,
            MetricSemanticsStatus.KNOWN,
            ("source_untrusted", "source_untrusted"),
            ("source_untrusted",),
        ),
    ],
)
def test_status_semantics_and_custom_blockers_are_independent(
    value_status: ValueStatus | None,
    metric_semantics_status: MetricSemanticsStatus,
    blocked_reasons: tuple[str, ...],
    expected_reasons: tuple[str, ...],
) -> None:
    evidence = parse_numeric(
        5,
        value_status=value_status,
        metric_semantics_status=metric_semantics_status,
        blocked_reasons=blocked_reasons,
    )

    expected_normalized = None if value_status is ValueStatus.MISSING else 5
    assert evidence.normalized_value == expected_normalized
    assert evidence.raw_value == 5
    assert evidence.comparison_eligibility is ComparisonEligibility.BLOCKED
    assert evidence.blocked_reasons == expected_reasons
    expected_blockers = (
        (*expected_reasons, "normalized_value_missing")
        if expected_normalized is None
        else expected_reasons
    )
    assert evidence_blockers(evidence) == expected_blockers


def test_explicit_blocked_eligibility_has_a_blocker_even_without_other_reasons() -> (
    None
):
    evidence = NumericEvidence(
        raw_value=7,
        normalized_value=7,
        value_status=ValueStatus.PUBLISHED,
        metric_semantics_status=MetricSemanticsStatus.KNOWN,
        comparison_eligibility=ComparisonEligibility.BLOCKED,
    )

    assert evidence.to_dict() == {
        "raw_value": 7,
        "normalized_value": 7,
        "unit": None,
        "normalization": None,
        "source_path": None,
        "source_field": None,
        "value_status": "published",
        "metric_semantics_status": "known",
        "comparison_eligibility": "blocked",
        "blocked_reasons": [],
        "parser": "numeric",
        "parser_version": "1",
    }
    assert evidence_blockers(evidence) == ("comparison_blocked",)


def test_comparison_blockers_keep_independent_reasons_and_stable_order() -> None:
    left = parse_numeric(None)
    right = parse_numeric(
        1,
        unit="ms",
        metric_semantics_status=MetricSemanticsStatus.UNKNOWN,
    )

    assert comparison_blockers(left, right) == (
        "missing_value",
        "normalized_value_missing",
        "semantics_unknown",
        "unit_mismatch",
    )
