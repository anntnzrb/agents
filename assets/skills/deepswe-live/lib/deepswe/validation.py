"""Strict, source-local validation and metrics-only diagnostics for DeepSWE.

The validator sits at the JSON artifact boundary.  It deliberately validates only
identity and shape that the DeepSWE source contract owns; all unrecognised fields
remain in the returned payload and are never interpreted as task or trial data.
"""

# Copyright 2026 DeepSWE contributors.
from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
from typing import Final

from .diagnostics import merge_diagnostics, redact, warning
from .provenance import artifact_evidence

BENCHMARK: Final[str] = "DeepSWE"
LEADERBOARD_ARTIFACT: Final[str] = "leaderboard-live.json"
TRIALS_ARTIFACT: Final[str] = "trials.json"
ARTIFACT_NAMES: Final[tuple[str, str]] = (LEADERBOARD_ARTIFACT, TRIALS_ARTIFACT)
LEGACY_ARTIFACT_SCHEMA: Final[int] = 1
SUPPORTED_ARTIFACT_SCHEMAS: Final[frozenset[int]] = frozenset({LEGACY_ARTIFACT_SCHEMA})

# Artifact versions are deliberately kept in lockstep with the source resolver,
# while this module remains importable without importing sources.py.
_VERSION_RE = re.compile(
    r"^v(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)"
    r"(?:\.(?P<patch>0|[1-9][0-9]*))?"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_MAJOR_ONLY_RE = re.compile(r"^v?[0-9]+$")
_VERSION_COMPONENT_RE = re.compile(
    r"^v[0-9]+(?:\.[0-9]+)+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)

# Keys used by known published payloads.  Unknown keys are retained; this set is
# only used to produce a deterministic schema-drift summary.
_KNOWN_TOP_LEVEL: Final[frozenset[str]] = frozenset(
    {
        "artifact",
        "benchmark",
        "benchmark_version",
        "count",
        "generated_at",
        "metadata",
        "n_rows",
        "n_tasks_in_set",
        "n_trials",
        "payload_schema",
        "row_count",
        "schema",
        "schema_version",
        "scope",
        "stats",
        "version",
        "artifact_schema",
        "artifact_schema_version",
    }
)
_KNOWN_ROW_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "config",
        "ci_half",
        "ci_hi",
        "ci_lo",
        "derived",
        "eval_scope",
        "harness",
        "id",
        "included_in_score",
        "mean_agent_steps",
        "mean_cost_usd",
        "mean_output_tokens",
        "metrics",
        "model",
        "model_name",
        "n_attempted",
        "n_tasks_attempted",
        "name",
        "pass_at_1",
        "pass_rate",
        "passed",
        "raw_fields",
        "reasoning_effort",
        "result",
        "source",
        "task",
        "task_id",
        "trajectory",
        "trial_id",
    }
)
_COUNT_KEYS: Final[tuple[str, ...]] = (
    "count",
    "row_count",
    "n_rows",
    "n_trials",
)
_SCHEMA_KEYS: Final[tuple[str, ...]] = (
    "artifact_schema",
    "artifact_schema_version",
    "payload_schema",
    "schema",
    "schema_version",
)


class PayloadValidationError(ValueError):
    """A stable, expected failure while validating one JSON artifact."""

    def __init__(  # noqa: D107
        self,
        message: str,
        *,
        code: str = "invalid_artifact_shape",
        path: str | Path | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = None if path is None else str(path)
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class PayloadFacts:
    """Validated identity and shape facts without copying unknown values."""

    payload: dict[str, object]
    schema_version: int
    benchmark: str
    benchmark_version: str | None
    artifact: str | None
    row_count: int
    top_level_fields: tuple[str, ...]
    row_fields: tuple[str, ...]
    unknown_top_level_fields: tuple[str, ...]
    unknown_row_fields: tuple[str, ...]
    path_version: str | None


def _label(path: str | Path | None) -> str:
    return str(path) if path is not None else "<artifact>"


def _fail(
    message: str,
    *,
    code: str = "invalid_artifact_shape",
    path: str | Path | None = None,
    field: str | None = None,
    value: object = None,
) -> None:
    details: dict[str, object] = {}
    if field is not None:
        details["field"] = field
    # Do not include raw values in diagnostics: values can contain credentials or
    # trial/task bodies.  Callers can still use the stable field and code.
    if value is not None and isinstance(value, (str, int, float, bool)):
        details["observed_type"] = type(value).__name__
    raise PayloadValidationError(message, code=code, path=path, details=details)


def _version(value: object, *, path: str | Path | None, field: str) -> str:
    if not isinstance(value, str):
        _fail(
            f"artifact {_label(path)} {field} must be a string",
            field=field,
            value=value,
            path=path,
        )
    candidate = value.strip()
    match = _VERSION_RE.fullmatch(candidate)
    if match is None:
        _fail(
            f"artifact {_label(path)} has invalid {field}",
            code="version_mismatch",
            field=field,
            path=path,
        )
    major = int(match.group("major"))
    minor = int(match.group("minor"))
    if major < 1 or (major == 1 and minor < 1):
        _fail(
            f"artifact {_label(path)} has unsupported {field}",
            code="version_mismatch",
            field=field,
            path=path,
        )
    return candidate


def _path_version(path: str | Path | None) -> str | None:
    if path is None:
        return None
    components = [part for part in re.split(r"[/\\]+", str(path)) if part]
    found: list[str] = []
    for index, component in enumerate(components):
        is_parent = index == len(components) - 2
        if is_parent and component.casefold() == "latest":
            _fail(
                f"artifact path {_label(path)} must use a concrete benchmark version",
                code="version_mismatch",
                path=path,
            )
        if is_parent and _MAJOR_ONLY_RE.fullmatch(component):
            _fail(
                f"artifact path {_label(path)} contains unsupported major-only version",
                code="version_mismatch",
                path=path,
            )
        if _VERSION_COMPONENT_RE.fullmatch(component):
            found.append(_version(component, path=path, field="path version"))
    if not found:
        return None
    if len(set(found)) != 1:
        _fail(
            f"artifact path {_label(path)} contains mixed benchmark versions",
            code="version_mismatch",
            path=path,
        )
    return found[0]


def _declared_version(
    payload: Mapping[str, object], *, path: str | Path | None
) -> str | None:
    found: list[tuple[str, str]] = []
    for field in ("benchmark_version", "version"):
        if field not in payload:
            continue
        found.append((field, _version(payload[field], path=path, field=field)))
    if not found:
        return None
    values = {value for _, value in found}
    if len(values) != 1:
        _fail(
            f"artifact {_label(path)} declares conflicting benchmark versions",
            code="version_mismatch",
            path=path,
        )
    return found[0][1]


def _schema_number(key: str, value: object, *, path: str | Path | None) -> int:
    candidate = value
    if isinstance(candidate, Mapping):
        candidate = candidate.get("version", candidate.get("schema_version"))
    if isinstance(candidate, bool):
        candidate = None
    if isinstance(candidate, int):
        number = candidate
    elif isinstance(candidate, str):
        text = candidate.strip().casefold()
        if text in {"1", "v1", "legacy-1", "legacy_v1"}:
            number = 1
        else:
            try:
                number = int(text)
            except ValueError:
                number = -1
    else:
        number = -1
    if number not in SUPPORTED_ARTIFACT_SCHEMAS:
        _fail(
            f"artifact {_label(path)} declares unsupported {key}",
            code="unsupported_schema",
            field=key,
            path=path,
        )
    return number


def _schema_version(payload: Mapping[str, object], *, path: str | Path | None) -> int:
    declarations = [
        (key, _schema_number(key, payload[key], path=path))
        for key in _SCHEMA_KEYS
        if key in payload
    ]
    if not declarations:
        # Legacy is selected only after root/rows/count checks have succeeded in
        # inspect_payload below.
        return LEGACY_ARTIFACT_SCHEMA
    values = {value for _, value in declarations}
    if len(values) != 1:
        _fail(
            f"artifact {_label(path)} declares conflicting artifact schemas",
            code="unsupported_schema",
            path=path,
        )
    return declarations[0][1]


def _validate_shape(  # noqa: C901
    payload: object, *, path: str | Path | None
) -> tuple[dict[str, object], list[Mapping[str, object]]]:
    if not isinstance(payload, Mapping):
        _fail(
            f"artifact {_label(path)} must contain a JSON object",
            code="invalid_artifact_shape",
            path=path,
        )
    root: dict[str, object] = dict(payload)
    if "rows" not in root or not isinstance(root["rows"], list):
        _fail(
            f"artifact {_label(path)} must contain a rows array",
            code="invalid_artifact_shape",
            path=path,
            field="rows",
        )
    rows_value = root["rows"]
    rows: list[Mapping[str, object]] = []
    for index, row in enumerate(rows_value):
        if not isinstance(row, Mapping):
            _fail(
                f"artifact {_label(path)} rows must be JSON objects",
                code="invalid_artifact_shape",
                path=path,
                field=f"rows[{index}]",
                value=row,
            )
        rows.append(row)
    for key in _COUNT_KEYS:
        if key not in root:
            continue
        declared = root[key]
        if isinstance(declared, bool) or not isinstance(declared, int):
            _fail(
                f"artifact {_label(path)} {key} must be an integer",
                code="invalid_artifact_shape",
                path=path,
                field=key,
                value=declared,
            )
        if declared != len(rows):
            _fail(
                f"artifact {_label(path)} {key} does not match rows length",
                code="invalid_artifact_shape",
                path=path,
                field=key,
            )
    scope = root.get("scope")
    if scope is not None and not isinstance(scope, str):
        _fail(
            f"artifact {_label(path)} scope must be a string",
            field="scope",
            path=path,
            value=scope,
        )
    generated_at = root.get("generated_at")
    if generated_at is not None and not isinstance(generated_at, str):
        _fail(
            f"artifact {_label(path)} generated_at must be a string",
            field="generated_at",
            path=path,
            value=generated_at,
        )
    return root, rows


def inspect_payload(  # noqa: C901
    payload: object,
    *,
    artifact_name: str | None = None,
    expected_version: str | None = None,
    path: str | Path | None = None,
) -> PayloadFacts:
    """Validate one payload and return identity/shape facts.

    Validation order intentionally checks the JSON object, rows array, row object
    entries, and count agreement before interpreting an optional artifact schema.
    This prevents a future schema declaration from making malformed legacy shape
    appear valid.
    """
    root, rows = _validate_shape(payload, path=path)

    if "benchmark" in root:
        benchmark = root["benchmark"]
        if not isinstance(benchmark, str):
            _fail(
                f"artifact {_label(path)} benchmark must be a string",
                path=path,
                field="benchmark",
                value=benchmark,
            )
        if benchmark != BENCHMARK:
            _fail(
                (
                    f"artifact {_label(path)} declares benchmark "
                    f"{benchmark!r}, expected {BENCHMARK!r}"
                ),
                code="benchmark_mismatch",
                path=path,
                field="benchmark",
            )
    else:
        benchmark = BENCHMARK

    path_version = _path_version(path)
    declared_version = _declared_version(root, path=path)
    resolved_expected = (
        _version(expected_version, path=path, field="expected version")
        if expected_version is not None
        else None
    )
    observed = declared_version or path_version
    for left, right, label in (
        (declared_version, path_version, "payload/path"),
        (declared_version, resolved_expected, "payload/request"),
        (path_version, resolved_expected, "path/request"),
    ):
        if left is not None and right is not None and left != right:
            _fail(
                f"artifact {_label(path)} {label} version {left!r} "
                f"does not match expected {right}",
                code="version_mismatch",
                path=path,
            )

    declared_artifact: str | None = None
    if "artifact" in root:
        value = root["artifact"]
        if not isinstance(value, str) or not value.strip():
            _fail(
                f"artifact {_label(path)} artifact must be a non-empty string",
                path=path,
                field="artifact",
                value=value,
            )
        declared_artifact = value
        if declared_artifact not in ARTIFACT_NAMES:
            _fail(
                (
                    f"artifact {_label(path)} declares unsupported artifact "
                    f"{declared_artifact!r}"
                ),
                code="artifact_mismatch",
                path=path,
                field="artifact",
            )
        if artifact_name is not None and declared_artifact != artifact_name:
            _fail(
                (
                    f"artifact {_label(path)} declares artifact "
                    f"{declared_artifact!r}, expected {artifact_name!r}"
                ),
                code="artifact_mismatch",
                path=path,
                field="artifact",
            )
    elif artifact_name is not None and artifact_name not in ARTIFACT_NAMES:
        _fail(
            f"unsupported DeepSWE artifact {artifact_name!r}",
            code="artifact_mismatch",
            path=path,
            field="artifact",
        )

    schema_version = _schema_version(root, path=path)
    top_fields = tuple(sorted(str(key) for key in root))
    row_fields = tuple(sorted({str(key) for row in rows for key in row}))
    unknown_top = tuple(sorted(set(top_fields) - _KNOWN_TOP_LEVEL))
    unknown_rows = tuple(sorted(set(row_fields) - _KNOWN_ROW_FIELDS))
    return PayloadFacts(
        payload=root,
        schema_version=schema_version,
        benchmark=BENCHMARK,
        benchmark_version=observed,
        artifact=declared_artifact or artifact_name,
        row_count=len(rows),
        top_level_fields=top_fields,
        row_fields=row_fields,
        unknown_top_level_fields=unknown_top,
        unknown_row_fields=unknown_rows,
        path_version=path_version,
    )


def validate_payload(
    payload: object,
    *,
    artifact_name: str | None = None,
    expected_version: str | None = None,
    path: str | Path | None = None,
) -> dict[str, object]:
    """Validate and return a copy of one payload, retaining every input field."""
    return inspect_payload(
        payload,
        artifact_name=artifact_name,
        expected_version=expected_version,
        path=path,
    ).payload


# Explicit aliases make the source-local boundary convenient to callers without
# requiring them to know which noun the caller uses for a JSON artifact.
validate_artifact = validate_payload
validate = validate_payload


def _metric_summary(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, int | float]]:
    values: dict[str, list[int | float]] = {}
    for row in rows:
        for key, raw in row.items():
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            if not math.isfinite(float(raw)):
                continue
            values.setdefault(str(key), []).append(raw)
    return {
        key: {
            "count": len(items),
            "min": min(items),
            "max": max(items),
        }
        for key, items in sorted(values.items())
    }


def diagnose_payload(
    payload: object,
    *,
    artifact_name: str | None = None,
    expected_version: str | None = None,
    path: str | Path | None = None,
    metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return deterministic diagnostics/evidence without exposing row bodies."""
    facts = inspect_payload(
        payload,
        artifact_name=artifact_name,
        expected_version=expected_version,
        path=path,
    )
    rows_value = facts.payload.get("rows")
    rows = rows_value if isinstance(rows_value, list) else []
    row_mappings = [row for row in rows if isinstance(row, Mapping)]
    diagnostics: list[Mapping[str, object]] = []
    if facts.unknown_top_level_fields or facts.unknown_row_fields:
        diagnostics.append(
            warning(
                "SCHEMA_DRIFT",
                (
                    "payload contains unknown fields; values were preserved but "
                    "not interpreted"
                ),
                stage="validate",
                source_path=_label(path),
                artifact_id=facts.artifact,
                details={
                    "unknown_top_level_fields": list(facts.unknown_top_level_fields),
                    "unknown_row_fields": list(facts.unknown_row_fields),
                },
            )
        )

    evidence: dict[str, object] = {
        "artifact": facts.artifact,
        "benchmark": facts.benchmark,
        "benchmark_version": facts.benchmark_version,
        "schema_version": facts.schema_version,
        "row_count": facts.row_count,
        "top_level_fields": list(facts.top_level_fields),
        "row_fields": list(facts.row_fields),
        "unknown_top_level_fields": list(facts.unknown_top_level_fields),
        "unknown_row_fields": list(facts.unknown_row_fields),
        "metrics": _metric_summary(row_mappings),
    }
    if metadata is not None:
        evidence["source"] = artifact_evidence(
            metadata,
            metadata=metadata,
            benchmark_version=facts.benchmark_version,
            source_path=_label(path) if path is not None else None,
        )

    result: dict[str, object] = {
        "summary": {
            "artifact": facts.artifact,
            "benchmark": facts.benchmark,
            "benchmark_version": facts.benchmark_version,
            "schema_version": facts.schema_version,
            "row_count": facts.row_count,
            "fields": list(facts.row_fields),
            "metrics": _metric_summary(row_mappings),
        },
        "diagnostics": merge_diagnostics(diagnostics),
        "evidence": evidence,
    }
    redacted = redact(result)
    return dict(redacted) if isinstance(redacted, Mapping) else result


__all__ = [
    "ARTIFACT_NAMES",
    "BENCHMARK",
    "LEADERBOARD_ARTIFACT",
    "LEGACY_ARTIFACT_SCHEMA",
    "SUPPORTED_ARTIFACT_SCHEMAS",
    "TRIALS_ARTIFACT",
    "PayloadFacts",
    "PayloadValidationError",
    "diagnose_payload",
    "inspect_payload",
    "validate",
    "validate_artifact",
    "validate_payload",
]
