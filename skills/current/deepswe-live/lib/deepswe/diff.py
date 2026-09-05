"""Order-independent, semantics-aware comparison of DeepSWE snapshots.

This module is deliberately independent of the CLI.  It accepts decoded
snapshot mappings (or row sequences), proves release and artifact compatibility
before touching metric values, and keeps unavailable source states visible.
"""

# Copyright 2026 DeepSWE contributors.
from __future__ import annotations

import copy
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from numbers import Real
from typing import NamedTuple, cast

from .identity import canonical_identity, identity_json

_DEFAULT_METRIC = "pass_at_1"
_SEMANTIC_FIELDS: tuple[str, ...] = (
    "unit",
    "scope",
    "denominator",
    "metric_semantics_status",
)


class _Observation(NamedTuple):
    value: Real | None
    status: str
    reasons: tuple[str, ...]
    semantics: dict[str, object]
    eligible: bool


def _json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError):
        return repr(value)


def _nested_candidates(
    snapshot: Mapping[str, object],
) -> Iterable[Mapping[str, object]]:
    """Yield metadata containers without traversing row arrays."""
    yield snapshot
    for key in ("data", "metadata", "scope", "provenance", "artifact", "schema"):
        value = snapshot.get(key)
        if isinstance(value, Mapping):
            nested_mapping = cast("Mapping[str, object]", value)
            yield nested_mapping
            for nested_key in ("data", "metadata", "scope", "artifact", "schema"):
                nested = nested_mapping.get(nested_key)
                if isinstance(nested, Mapping):
                    yield cast("Mapping[str, object]", nested)


def _declared_version(snapshot: Mapping[str, object]) -> str | None:
    values: list[str] = []
    for container in _nested_candidates(snapshot):
        for key in ("benchmark_version", "version"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value)
    unique = sorted(set(values))
    if len(unique) == 1:
        return unique[0]
    # A conflicting declaration is intentionally returned as a sentinel.  It
    # cannot be mistaken for a valid version by the comparison gate.
    if len(unique) > 1:
        return "__conflicting_version__"
    return None


def _declared_schema(snapshot: Mapping[str, object]) -> str | int | float | None:
    values: list[str | int | float] = []
    for container in _nested_candidates(snapshot):
        for key in ("schema_version", "artifact_schema_version"):
            value = container.get(key)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                values.append(value)
        artifact_schema = container.get("artifact_schema")
        if isinstance(artifact_schema, Mapping):
            schema_map = cast("Mapping[str, object]", artifact_schema)
            value = schema_map.get("version")
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                values.append(value)
    unique = {_json(value): value for value in values}
    if len(unique) == 1:
        return next(iter(unique.values()))
    if len(unique) > 1:
        return "__conflicting_schema__"
    return None


def _rows(snapshot: object) -> list[Mapping[str, object]]:
    if isinstance(snapshot, Sequence) and not isinstance(
        snapshot, (str, bytes, bytearray)
    ):
        entries = cast("list[object]", cast("object", snapshot))
        return [
            cast("Mapping[str, object]", row)
            for row in entries
            if isinstance(row, Mapping)
        ]
    if not isinstance(snapshot, Mapping):
        msg = "snapshot must be a mapping or a sequence of row mappings"
        raise TypeError(msg)
    snapshot = cast("Mapping[str, object]", snapshot)
    rows_value = snapshot.get("rows")
    if isinstance(rows_value, Sequence) and not isinstance(
        rows_value, (str, bytes, bytearray)
    ):
        row_entries = cast("list[object]", cast("object", rows_value))
        return [
            cast("Mapping[str, object]", row)
            for row in row_entries
            if isinstance(row, Mapping)
        ]
    for key in ("data", "payload", "artifact", "leaderboard-live.json"):
        nested = snapshot.get(key)
        if isinstance(nested, Mapping):
            found = _rows(cast("Mapping[str, object]", nested))
            if found:
                return found
    # A lone row mapping is useful for pure-kernel callers and is harmless for
    # normal snapshots, which always have a rows member.
    if any(
        key in snapshot for key in ("model", "reasoning_effort", "harness", "config")
    ):
        return [snapshot]
    return []


def _numeric(value: object) -> Real | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        if not math.isfinite(float(value)):
            return None
    except (OverflowError, ValueError):
        return None
    return value


def _as_reasons(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        result: list[str] = []
        for item in value:
            text = str(item)
            if text and text not in result:
                result.append(text)
        return tuple(result)
    return ()


def _metric_entry(
    row: Mapping[str, object], metric: str
) -> Mapping[str, object] | None:
    metrics = row.get("metrics")
    if isinstance(metrics, Mapping):
        metrics_map = cast("Mapping[str, object]", metrics)
        candidate = metrics_map.get(metric)
        if isinstance(candidate, Mapping):
            return cast("Mapping[str, object]", candidate)
    candidate = row.get(metric)
    if not isinstance(candidate, Mapping):
        return None
    return cast("Mapping[str, object]", candidate)


def _semantic_projection(value: Mapping[str, object] | None) -> dict[str, object]:
    if value is None:
        return {}
    result: dict[str, object] = {}
    nested = value.get("semantics")
    if isinstance(nested, Mapping):
        semantics = cast("Mapping[str, object]", nested)
        for key, item in semantics.items():
            if key in _SEMANTIC_FIELDS or key in {"family", "comparator"}:
                result[str(key)] = copy.deepcopy(item)
    nested = value.get("metric_semantics")
    if isinstance(nested, Mapping):
        metric_semantics_map = cast("Mapping[str, object]", nested)
        for key, item in metric_semantics_map.items():
            if key in _SEMANTIC_FIELDS or key in {"family", "comparator"}:
                result[str(key)] = copy.deepcopy(item)
    for key in _SEMANTIC_FIELDS:
        if key in value:
            result[key] = copy.deepcopy(value[key])
    return result


def _snapshot_metric_semantics(
    snapshot: Mapping[str, object], metric: str
) -> dict[str, object]:
    result: dict[str, object] = {}
    for container in _nested_candidates(snapshot):
        for key in ("metric_semantics", "semantics", "metrics"):
            candidate = container.get(key)
            if not isinstance(candidate, Mapping):
                continue
            candidate_map = cast("Mapping[str, object]", candidate)
            if key == "metrics":
                nested = candidate_map.get(metric)
                if not isinstance(nested, Mapping):
                    continue
                candidate_map = cast("Mapping[str, object]", nested)
            else:
                nested = candidate_map.get(metric)
                if isinstance(nested, Mapping):
                    candidate_map = cast("Mapping[str, object]", nested)
            projection = _semantic_projection(candidate_map)
            for field, value in projection.items():
                _ = result.setdefault(field, value)
    return result


def _semantic_difference(  # noqa: PLR0911
    before: Mapping[str, object], after: Mapping[str, object]
) -> str | None:
    if not before and not after:
        return None
    if set(before) != set(after):
        return "semantics_mismatch"
    for field in sorted(before):
        if _json(before[field]) != _json(after[field]):
            if field == "unit":
                return "unit_mismatch"
            if field == "scope":
                return "scope_mismatch"
            if field == "denominator":
                return "denominator_mismatch"
            return "semantics_mismatch"
    return None


def _observation(  # noqa: C901, PLR0911, PLR0912
    row: Mapping[str, object] | None, metric: str
) -> _Observation:
    if row is None:
        return _Observation(None, "missing", ("missing_row",), {}, eligible=False)

    evidence = _metric_entry(row, metric)
    if evidence is not None:
        value = evidence.get("normalized_value")
        if value is None and "value" in evidence:
            value = evidence.get("value")
        semantics = _semantic_projection(evidence)
        reasons = list(_as_reasons(evidence.get("blocked_reasons")))
        value_status = evidence.get("value_status")
        eligibility = evidence.get("comparison_eligibility")
    else:
        value = row.get(metric)
        semantics = _semantic_projection(row)
        reasons = list(_as_reasons(row.get("blocked_reasons")))
        value_status = row.get("value_status")
        eligibility = row.get("comparison_eligibility")

    numeric = _numeric(value)
    status_text = str(value_status) if isinstance(value_status, str) else ""
    if status_text in {"missing", "unparsed"}:
        status = status_text
        if status not in reasons:
            reasons.append(status)
        return _Observation(numeric, status, tuple(reasons), semantics, eligible=False)
    if value is None:
        if "missing_value" not in reasons:
            reasons.append("missing_value")
        return _Observation(None, "missing", tuple(reasons), semantics, eligible=False)
    if numeric is None:
        if "unparsed_value" not in reasons:
            reasons.append("unparsed_value")
        return _Observation(None, "unparsed", tuple(reasons), semantics, eligible=False)
    if eligibility == "blocked":
        if not reasons:
            reasons.append("comparison_blocked")
        return _Observation(
            numeric, "blocked", tuple(reasons), semantics, eligible=False
        )
    if eligibility not in (None, "eligible"):
        if not reasons:
            reasons.append(str(eligibility))
        return _Observation(
            numeric, "blocked", tuple(reasons), semantics, eligible=False
        )
    if status_text == "blocked":
        if not reasons:
            reasons.append("comparison_blocked")
        return _Observation(
            numeric, "blocked", tuple(reasons), semantics, eligible=False
        )
    return _Observation(numeric, "eligible", tuple(reasons), semantics, eligible=True)


def _raw_row_signature(row: Mapping[str, object]) -> str:
    """Canonicalize source fields while ignoring additive evidence projections."""
    source = {
        key: value for key, value in row.items() if key not in {"metrics", "raw_fields"}
    }
    return _json(source)


def _index_rows(
    rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, Mapping[str, object]], set[str], list[dict[str, object]]]:
    grouped: dict[str, list[tuple[int, Mapping[str, object], str]]] = {}
    for index, row in enumerate(rows):
        identity = identity_json(canonical_identity(row))
        grouped.setdefault(identity, []).append((index, row, _raw_row_signature(row)))
    selected: dict[str, Mapping[str, object]] = {}
    conflicts: set[str] = set()
    diagnostics: list[dict[str, object]] = []
    for identity in sorted(grouped):
        entries = grouped[identity]
        signatures = sorted({entry[2] for entry in entries})
        if len(entries) > 1:
            conflicting = len(signatures) > 1
            if conflicting:
                conflicts.add(identity)
            diagnostics.append(
                {
                    "code": "DUPLICATE_CONFLICT"
                    if conflicting
                    else "DUPLICATE_IDENTITY",
                    "severity": "error" if conflicting else "warning",
                    "stage": "comparison",
                    "message": (
                        "Conflicting rows share a configuration identity."
                        if conflicting
                        else "Identical rows share a configuration identity."
                    ),
                    "details": {
                        "identity": identity,
                        "row_indexes": sorted(entry[0] for entry in entries),
                        "signatures": signatures,
                    },
                }
            )
        # Preserve the source order for the deterministic first-row policy.
        selected[identity] = min(entries, key=lambda entry: entry[0])[1]
    return selected, conflicts, diagnostics


def _blocked(
    config: str,
    before: _Observation | None,
    after: _Observation | None,
    *,
    reason: str,
) -> dict[str, object]:
    reasons: list[str] = []
    if before is not None:
        reasons.extend(before.reasons)
    if after is not None:
        reasons.extend(after.reasons)
    if reason not in reasons:
        reasons.insert(0, reason)
    deduped: list[str] = []
    for item in reasons:
        if item not in deduped:
            deduped.append(item)
    statuses = [item.status for item in (before, after) if item is not None]
    status = (
        "blocked"
        if "blocked" in statuses
        else "unparsed"
        if "unparsed" in statuses
        else "missing"
    )
    return {
        "config": config,
        "status": status,
        "reason": deduped[0],
        "reasons": deduped,
        "before": before.value if before is not None else None,
        "after": after.value if after is not None else None,
    }


def _global_block(
    reason: str,
    code: str,
    message: str,
) -> dict[str, object]:
    return {
        "changes": [],
        "blocked": [
            {
                "config": None,
                "status": "blocked",
                "reason": reason,
                "reasons": [reason],
                "before": None,
                "after": None,
            }
        ],
        "diagnostics": [
            {
                "code": code,
                "severity": "blocker",
                "stage": "comparison",
                "message": message,
                "details": {"reason": reason},
            }
        ],
    }


def compare_snapshots(  # noqa: C901
    before: Mapping[str, object] | Sequence[Mapping[str, object]],
    after: Mapping[str, object] | Sequence[Mapping[str, object]],
    metric: object = _DEFAULT_METRIC,
) -> dict[str, object]:
    """Compare two same-release snapshots without imputing unavailable values.

    Benchmark version is checked first.  Schema and metric semantic metadata are
    checked next, before rows or values are interpreted.  Eligible pairs retain
    the historical ``config``/``before``/``after``/``delta`` fields and gain a
    status; unavailable observations are emitted in ``blocked`` with their
    source status and reasons.
    """
    if not isinstance(metric, str) or not metric.strip():
        msg = "metric must be a non-empty string"
        raise ValueError(msg)
    metric = metric.strip()
    before_snapshot = before if isinstance(before, Mapping) else None
    after_snapshot = after if isinstance(after, Mapping) else None
    if before_snapshot is None or after_snapshot is None:
        # Row sequences have no release/schema declarations.  Refuse to infer
        # them rather than silently comparing unversioned data.
        return _global_block(
            "missing_version",
            "MISSING_VERSION",
            "both snapshots must declare benchmark_version",
        )

    before_version = _declared_version(before_snapshot)
    after_version = _declared_version(after_snapshot)
    if (
        before_version is None
        or after_version is None
        or before_version == "__conflicting_version__"
        or after_version == "__conflicting_version__"
    ):
        return _global_block(
            "missing_version",
            "MISSING_VERSION",
            "both snapshots must declare one benchmark_version",
        )
    if before_version != after_version:
        return _global_block(
            "mixed_version",
            "MIXED_VERSION",
            (
                "snapshots use different benchmark versions: "
                f"{before_version!r} and {after_version!r}"
            ),
        )

    before_schema = _declared_schema(before_snapshot)
    after_schema = _declared_schema(after_snapshot)
    if (
        before_schema == "__conflicting_schema__"
        or after_schema == "__conflicting_schema__"
        or (before_schema is None) != (after_schema is None)
        or (
            before_schema is not None
            and after_schema is not None
            and _json(before_schema) != _json(after_schema)
        )
    ):
        return _global_block(
            "schema_mismatch",
            "SCHEMA_DRIFT",
            "snapshots do not declare compatible artifact schemas",
        )

    semantic_reason = _semantic_difference(
        _snapshot_metric_semantics(before_snapshot, metric),
        _snapshot_metric_semantics(after_snapshot, metric),
    )
    if semantic_reason is not None:
        return _global_block(
            semantic_reason,
            "COMPARISON_INCOMPARABLE",
            "snapshots do not declare compatible metric semantics",
        )

    before_rows = _rows(before_snapshot)
    after_rows = _rows(after_snapshot)
    before_map, before_conflicts, before_diagnostics = _index_rows(before_rows)
    after_map, after_conflicts, after_diagnostics = _index_rows(after_rows)
    diagnostics = before_diagnostics + after_diagnostics
    changes: list[dict[str, object]] = []
    blocked: list[dict[str, object]] = []
    identities = sorted(set(before_map) | set(after_map))
    for config in identities:
        before_row = before_map.get(config)
        after_row = after_map.get(config)
        if config in before_conflicts or config in after_conflicts:
            blocked.append(
                _blocked(
                    config,
                    _observation(before_row, metric)
                    if before_row is not None
                    else None,
                    _observation(after_row, metric) if after_row is not None else None,
                    reason="duplicate_conflict",
                )
            )
            continue
        before_value = _observation(before_row, metric)
        after_value = _observation(after_row, metric)
        if not before_value.eligible or not after_value.eligible:
            reason = (
                before_value.reasons[0]
                if not before_value.eligible and before_value.reasons
                else after_value.reasons[0]
                if after_value.reasons
                else "comparison_incomparable"
            )
            blocked.append(_blocked(config, before_value, after_value, reason=reason))
            continue
        row_semantic_reason = _semantic_difference(
            before_value.semantics,
            after_value.semantics,
        )
        if row_semantic_reason is not None:
            blocked.append(
                _blocked(config, before_value, after_value, reason=row_semantic_reason)
            )
            diagnostics.append(
                {
                    "code": "COMPARISON_INCOMPARABLE",
                    "severity": "blocker",
                    "stage": "comparison",
                    "message": "Metric semantics differ for one configuration.",
                    "details": {"config": config, "reason": row_semantic_reason},
                }
            )
            continue
        if before_value.value is None or after_value.value is None:
            blocked.append(
                _blocked(
                    config,
                    before_value,
                    after_value,
                    reason="comparison_incomparable",
                )
            )
            continue
        changes.append(
            {
                "config": config,
                "before": before_value.value,
                "after": after_value.value,
                "delta": after_value.value - before_value.value,
                "status": "eligible",
            }
        )

    changes.sort(key=lambda item: str(item["config"]))
    blocked.sort(key=lambda item: (str(item.get("config")), str(item.get("reason"))))
    diagnostics.sort(key=_json)
    return {
        "changes": changes,
        "blocked": blocked,
        "diagnostics": diagnostics,
    }


__all__ = ["compare_snapshots"]
