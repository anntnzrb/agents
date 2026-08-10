"""Stable, redacted diagnostics for the local DeepSWE contract layer."""

# Copyright 2026 DeepSWE contributors.
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

# Diagnostic codes are intentionally local to DeepSWE.  Command error codes
# remain the lower-case strings used by the existing CLI.
CODES = frozenset(
    {
        "CACHE_MISSING",
        "CACHE_VALIDATOR_INVALID",
        "COMPARISON_INCOMPARABLE",
        "DUPLICATE_CONFLICT",
        "DUPLICATE_IDENTITY",
        "HISTORICAL_SNAPSHOT",
        "MALFORMED_PAYLOAD",
        "MISSING_REQUIRED_INPUT",
        "MIXED_VERSION",
        "NETWORK_ERROR",
        "NUMERIC_AMBIGUITY",
        "OUT_OF_RANGE",
        "PLACEHOLDER_VALUE",
        "SCHEMA_DRIFT",
        "SOURCE_UNAVAILABLE",
        "STALE_DATA",
        "UNKNOWN_SCORE_SEMANTICS",
        "VERSION_MISMATCH",
    }
)
SEVERITIES = ("warning", "blocker", "error")

# Match credential-bearing keys, rather than arbitrary metric names.  In
# particular, ``token_count`` and the string value ``tokens`` are not secrets.
_SECRET_KEY = re.compile(
    r"^(?:authorization|proxy[-_]?authorization|cookie|set[-_]?cookie|"
    r"x[-_]?api[-_]?key|api[-_]?key|access[-_]?token|refresh[-_]?token|"
    r"auth[-_]?token|token|password|passwd|secret|client[-_]?secret|"
    r"credential|credentials)$",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?ix)(?:\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+|"
    r"\b(?:sk(?:-proj)?|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9._-]{8,}|"
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----)",
)
_SECRET_QUERY = re.compile(
    r"(?i)([?&](?:api[-_]?key|access[-_]?token|auth[-_]?token|"
    r"client[-_]?secret|token|secret|password|authorization|credential)="
    r"[^&#\s]*)"
)


def redact(value: object) -> object:
    """Recursively redact credential keys, known secret values, and query data.

    This function is intended for diagnostic and provenance projections only.
    It deliberately leaves ordinary metric strings and numeric values untouched.
    """
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            name = str(key)
            if _SECRET_KEY.fullmatch(name):
                result[name] = "<redacted>"
            else:
                result[name] = redact(item)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        if _SECRET_VALUE.search(value):
            return "<redacted>"
        return _SECRET_QUERY.sub(
            lambda match: match.group(1).split("=", 1)[0] + "=<redacted>",
            value,
        )
    return value


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One structured diagnostic with redacted, JSON-shaped details."""

    code: str
    severity: str = "warning"
    stage: str = "validate"
    message: str = ""
    source_path: str | None = None
    artifact_id: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize and validate this diagnostic."""
        code = str(self.code).strip().upper()
        if not code:
            msg = "diagnostic code must be non-empty"
            raise ValueError(msg)
        severity = str(self.severity).strip().lower()
        if severity not in SEVERITIES:
            msg = f"unsupported diagnostic severity: {self.severity}"
            raise ValueError(msg)
        stage = str(self.stage).strip().lower()
        if not stage:
            msg = "diagnostic stage must be non-empty"
            raise ValueError(msg)
        if not isinstance(self.details, Mapping):
            msg = "diagnostic details must be a mapping"
            raise TypeError(msg)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "message", str(self.message))
        if self.source_path is not None:
            object.__setattr__(self, "source_path", str(self.source_path))
        if self.artifact_id is not None:
            object.__setattr__(self, "artifact_id", str(self.artifact_id))

    def as_dict(self) -> dict[str, object]:
        """Project the diagnostic into its stable JSON shape."""
        result: dict[str, object] = {
            "code": self.code,
            "severity": self.severity,
            "stage": self.stage,
            "message": redact(self.message),
            "details": redact(dict(self.details)),
        }
        if self.source_path is not None:
            result["source_path"] = redact(self.source_path)
        if self.artifact_id is not None:
            result["artifact_id"] = redact(self.artifact_id)
        return result


def make(  # noqa: PLR0913
    code: str,
    message: str,
    *,
    severity: str = "warning",
    stage: str = "validate",
    source_path: str | None = None,
    artifact_id: str | None = None,
    details: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Create one redacted diagnostic dictionary."""
    return Diagnostic(
        code=code,
        severity=severity,
        stage=stage,
        message=message,
        source_path=source_path,
        artifact_id=artifact_id,
        details={} if details is None else details,
    ).as_dict()


def _normalise(item: Diagnostic | Mapping[str, object]) -> dict[str, object]:
    if isinstance(item, Diagnostic):
        return item.as_dict()
    raw = dict(item)
    code = str(raw.pop("code", "UNKNOWN")).strip().upper() or "UNKNOWN"
    severity = str(raw.pop("severity", "warning")).strip().lower() or "warning"
    stage = str(raw.pop("stage", "validate")).strip().lower() or "validate"
    message = str(raw.pop("message", ""))
    source_path_value = raw.pop("source_path", None)
    artifact_id_value = raw.pop("artifact_id", None)
    details_value = raw.pop("details", {})
    details = dict(details_value) if isinstance(details_value, Mapping) else {}
    result: dict[str, object] = {
        "code": code,
        "severity": severity,
        "stage": stage,
        "message": redact(message),
        "details": redact(details),
    }
    if source_path_value is not None:
        result["source_path"] = redact(str(source_path_value))
    if artifact_id_value is not None:
        result["artifact_id"] = redact(str(artifact_id_value))
    for key, value in raw.items():
        result[str(key)] = redact(value)
    return result


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        # A later compact JSON emission still rejects non-finite values; this
        # fallback only keeps merge ordering deterministic for diagnostics that
        # are being collected before that final boundary.
        return repr(value)


def merge_diagnostics(
    *groups: Iterable[Diagnostic | Mapping[str, object]]
    | Diagnostic
    | Mapping[str, object],
) -> list[dict[str, object]]:
    """Redact, deduplicate, and deterministically order diagnostic groups."""
    unique: dict[str, dict[str, object]] = {}
    for group in groups:
        if isinstance(group, (Diagnostic, Mapping)):
            items: Iterable[Diagnostic | Mapping[str, object]] = (group,)
        else:
            items = group
        for item in items:
            if not isinstance(item, (Diagnostic, Mapping)):
                continue
            normalized = _normalise(item)
            unique.setdefault(_canonical(normalized), normalized)

    def sort_key(item: dict[str, object]) -> tuple[str, ...]:
        return (
            str(item.get("code", "")),
            str(item.get("severity", "")),
            str(item.get("stage", "")),
            str(item.get("source_path", "")),
            str(item.get("artifact_id", "")),
            str(item.get("message", "")),
            _canonical(item.get("details", {})),
        )

    return sorted(unique.values(), key=sort_key)


def warning(  # noqa: PLR0913
    code: str,
    message: str,
    *,
    stage: str = "validate",
    source_path: str | None = None,
    artifact_id: str | None = None,
    details: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Create a warning diagnostic."""
    return make(
        code,
        message,
        severity="warning",
        stage=stage,
        source_path=source_path,
        artifact_id=artifact_id,
        details=details,
    )


def blocker(  # noqa: PLR0913
    code: str,
    message: str,
    *,
    stage: str = "validate",
    source_path: str | None = None,
    artifact_id: str | None = None,
    details: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Create a blocking diagnostic."""
    return make(
        code,
        message,
        severity="blocker",
        stage=stage,
        source_path=source_path,
        artifact_id=artifact_id,
        details=details,
    )


def error(  # noqa: PLR0913
    code: str,
    message: str,
    *,
    stage: str = "validate",
    source_path: str | None = None,
    artifact_id: str | None = None,
    details: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Create an error diagnostic."""
    return make(
        code,
        message,
        severity="error",
        stage=stage,
        source_path=source_path,
        artifact_id=artifact_id,
        details=details,
    )


__all__ = [
    "CODES",
    "SEVERITIES",
    "Diagnostic",
    "blocker",
    "error",
    "make",
    "merge_diagnostics",
    "redact",
    "warning",
]
