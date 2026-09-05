# Copyright (c) 2026 anntnzrb
"""Offline health reports for Artificial Analysis snapshots and caches."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path
from .diagnostics import redact, redact_query

_SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2})
_METADATA_KEYS = (
    "etag",
    "last_modified",
    "fetched_at",
    "observed_at",
    "status_code",
    "source_key",
    "source_url",
    "final_url",
    "sha256",
    "byte_length",
    "artifact_ref",
    "legacy_unverified",
)

_SENSITIVE_NAME_RE = re.compile(
    r"(?i)(?<![a-z0-9])[\w.-]*(?:api[-_ ]?key|secret|password|token)[\w.-]*",
)


def _safe_text(value: str) -> str:
    redacted = redact_query(value)
    return _SENSITIVE_NAME_RE.sub("[REDACTED]", redacted)


def _safe(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast("Mapping[str, object]", value)
        return {str(key): _safe(item) for key, item in mapping.items()}
    if isinstance(value, list):
        items = cast("list[object]", value)
        return [_safe(item) for item in items]
    if (
        isinstance(value, float)
        and not value.is_integer()
        and not abs(value) < float("inf")
    ):
        return None
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _safe_text(str(value))


def _safe_dict(value: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _safe(item) for key, item in value.items()}


def _path(path: Path | None) -> str | None:
    return _safe_text(str(path)) if path is not None else None


def _digest(path: Path) -> tuple[str | None, int | None]:
    try:
        raw = path.read_bytes()
    except (OSError, UnicodeError):
        return None, None
    return hashlib.sha256(raw).hexdigest(), len(raw)


def _diagnostic(  # noqa: PLR0913
    code: str,
    severity: str,
    stage: str,
    message: str,
    *,
    source_path: Path | None = None,
    details: object | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "code": code,
        "severity": severity,
        "stage": stage,
        "message": message,
    }
    if source_path is not None:
        result["source_path"] = _path(source_path)
    if details is not None:
        result["details"] = _safe(redact(details))
    return result


def _read_object(path: Path) -> tuple[dict[str, object] | None, str | None]:
    try:
        raw = path.read_text(encoding="utf-8")
        parsed = cast("object", json.loads(raw))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, type(exc).__name__
    if not isinstance(parsed, dict):
        return None, "not_object"
    parsed_dict = cast("dict[str, object]", parsed)
    return {str(k): v for k, v in parsed_dict.items()}, None


def _metadata(value: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key in _METADATA_KEYS:
        if key in value:
            item = value[key]
            if key in {
                "source_key",
                "source_url",
                "final_url",
                "artifact_ref",
            } and isinstance(item, str):
                item = redact_query(item)
            result[key] = _safe(item)
    nested = value.get("metadata")
    if isinstance(nested, Mapping):
        for key in _METADATA_KEYS:
            if key not in result and key in nested:
                item = nested[key]
                if key in {
                    "source_key",
                    "source_url",
                    "final_url",
                    "artifact_ref",
                } and isinstance(item, str):
                    item = redact_query(item)
                result[key] = _safe(item)
    return result


def _cache_report(  # noqa: C901, PLR0912
    cache_dir: Path | None, diagnostics: list[dict[str, object]]
) -> dict[str, object]:
    if cache_dir is None:
        return {
            "path": None,
            "present": False,
            "files": [],
            "artifacts": [],
            "validator": {"etag": None, "last_modified": None, "present": False},
        }
    report: dict[str, object] = {
        "path": _path(cache_dir),
        "present": cache_dir.is_dir(),
        "files": [],
        "artifacts": [],
    }
    if not cache_dir.is_dir():
        diagnostics.append(
            _diagnostic(
                "CACHE_MISSING",
                "warning",
                "cache",
                "Cache directory is not present.",
                source_path=cache_dir,
            ),
        )
        return report
    file_rows: list[dict[str, object]] = []
    for candidate in sorted(cache_dir.iterdir(), key=lambda item: item.name):
        if not candidate.is_file() or candidate.name == ".env":
            continue
        digest, length = _digest(candidate)
        row: dict[str, object] = {
            "name": _safe_text(candidate.name),
            "length": length,
            "sha256": digest,
        }
        if candidate.name in {"providers-cache.json", "index.json"}:
            parsed, error = _read_object(candidate)
            if error is not None:
                diagnostics.append(
                    _diagnostic(
                        "CACHE_METADATA_INVALID",
                        "warning",
                        "cache",
                        "Cache metadata is not a JSON object.",
                        source_path=candidate,
                    ),
                )
            elif parsed is not None:
                if candidate.name == "providers-cache.json":
                    row["metadata"] = _metadata(parsed)
                else:
                    entries: list[dict[str, object]] = []
                    for source_key in sorted(parsed, key=str):
                        entry_raw = parsed[source_key]
                        if isinstance(entry_raw, Mapping):
                            entry = cast("Mapping[str, object]", entry_raw)
                            raw_path = entry.get("raw_path")
                            entries.append(
                                {
                                    "source_key": _safe_text(str(source_key)),
                                    "sha256": entry.get("sha256"),
                                    "length": entry.get("length"),
                                    "raw_path": (
                                        _safe_text(str(raw_path))
                                        if raw_path is not None
                                        else None
                                    ),
                                    "legacy_unverified": (
                                        entry.get("legacy_unverified") is True
                                    ),
                                },
                            )
                    row["entries"] = _safe(entries)
        file_rows.append(row)
    report["files"] = file_rows
    metadata_rows: list[object] = [
        row.get("metadata")
        for row in file_rows
        if row.get("name") == "providers-cache.json"
    ]
    raw_cache_meta = metadata_rows[0] if metadata_rows else None
    cache_metadata: Mapping[str, object] = (
        cast("Mapping[str, object]", raw_cache_meta)
        if isinstance(raw_cache_meta, Mapping)
        else {}
    )
    etag = cache_metadata.get("etag")
    last_modified = cache_metadata.get("last_modified")
    report["validator"] = {
        "etag": etag,
        "last_modified": last_modified,
        "present": bool(etag or last_modified),
    }
    artifacts_dir = cache_dir / "artifacts"
    if artifacts_dir.is_dir():
        artifacts: list[dict[str, object]] = []
        for candidate in sorted(artifacts_dir.iterdir(), key=lambda item: item.name):
            if not candidate.is_file() or not candidate.name.endswith(
                (".raw", ".meta.json")
            ):
                continue
            digest, length = _digest(candidate)
            artifacts.append(
                {"name": _safe_text(candidate.name), "length": length, "sha256": digest}
            )
        report["artifacts"] = artifacts
        if not artifacts:
            diagnostics.append(
                _diagnostic(
                    "CACHE_ARTIFACTS_EMPTY",
                    "warning",
                    "cache",
                    "Artifact directory is present but empty.",
                    source_path=artifacts_dir,
                ),
            )
    return _safe_dict(report)


def _snapshot_report(
    snapshot_path: Path | None,
    diagnostics: list[dict[str, object]],
) -> tuple[dict[str, object], dict[str, object] | None]:
    if snapshot_path is None:
        diagnostics.append(
            _diagnostic(
                "SNAPSHOT_NOT_SELECTED",
                "warning",
                "snapshot",
                "No snapshot path was supplied.",
            )
        )
        return {"path": None, "present": False}, None
    digest, length = _digest(snapshot_path)
    report: dict[str, object] = {
        "path": _path(snapshot_path),
        "present": snapshot_path.is_file(),
        "sha256": digest,
        "length": length,
    }
    if not snapshot_path.is_file():
        diagnostics.append(
            _diagnostic(
                "SNAPSHOT_MISSING",
                "error",
                "snapshot",
                "Snapshot path is not present.",
                source_path=snapshot_path,
            ),
        )
        return report, None
    parsed, error = _read_object(snapshot_path)
    if error is not None or parsed is None:
        diagnostics.append(
            _diagnostic(
                "SNAPSHOT_INVALID",
                "error",
                "snapshot",
                "Snapshot is not a JSON object.",
                source_path=snapshot_path,
            ),
        )
        return report, None
    meta = parsed.get("meta")
    meta_mapping: Mapping[str, object] = (
        cast("Mapping[str, object]", meta) if isinstance(meta, Mapping) else {}
    )
    schema_version = meta_mapping.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        schema_version = 1
        diagnostics.append(
            _diagnostic(
                "SNAPSHOT_SCHEMA_MISSING",
                "warning",
                "schema",
                "Snapshot schema_version is missing; treating it as legacy.",
                source_path=snapshot_path,
            ),
        )
    elif schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        diagnostics.append(
            _diagnostic(
                "SNAPSHOT_SCHEMA_UNSUPPORTED",
                "error",
                "schema",
                "Snapshot schema version is unsupported.",
                source_path=snapshot_path,
                details={"schema_version": schema_version},
            ),
        )
    freshness = meta_mapping.get("freshness")
    freshness_mapping: dict[str, object] = (
        {str(k): v for k, v in cast("Mapping[object, object]", freshness).items()}
        if isinstance(freshness, Mapping)
        else {}
    )
    mode = freshness_mapping.get("mode")
    if not isinstance(mode, str) or not mode:
        mode = "snapshot"
        freshness_mapping["mode"] = mode
    _ = freshness_mapping.setdefault("historical", True)
    parser_version = meta_mapping.get("parser_version")
    if not isinstance(parser_version, str) or not parser_version:
        diagnostics.append(
            _diagnostic(
                "PARSER_VERSION_MISSING",
                "warning",
                "parser",
                "Snapshot parser version is not recorded.",
                source_path=snapshot_path,
            ),
        )
    if not freshness_mapping.get("mode"):
        diagnostics.append(
            _diagnostic(
                "FRESHNESS_UNKNOWN",
                "warning",
                "freshness",
                "Snapshot freshness mode is not recorded.",
                source_path=snapshot_path,
            ),
        )
    models_val = parsed.get("models")
    hosts_val = parsed.get("hosts")
    hosts_models_val = parsed.get("hosts_models")
    models_list = (
        cast("list[object]", models_val) if isinstance(models_val, list) else None
    )
    hosts_list = (
        cast("list[object]", hosts_val) if isinstance(hosts_val, list) else None
    )
    hosts_models_list = (
        cast("list[object]", hosts_models_val)
        if isinstance(hosts_models_val, list)
        else None
    )
    report.update(
        {
            "counts": {
                "models": len(models_list) if models_list is not None else 0,
                "hosts": len(hosts_list) if hosts_list is not None else 0,
                "hosts_models": (
                    len(hosts_models_list) if hosts_models_list is not None else 0
                ),
            },
            "meta": _metadata(meta_mapping),
        },
    )
    return _safe_dict(report), parsed


def diagnose(
    *, snapshot_path: Path | None = None, cache_dir: Path | None = None
) -> dict[str, object]:
    """Inspect local files only; this function never performs network I/O."""
    diagnostics: list[dict[str, object]] = []
    snapshot_report, snapshot = _snapshot_report(snapshot_path, diagnostics)
    cache_report = _cache_report(cache_dir, diagnostics)
    raw_meta = snapshot.get("meta") if isinstance(snapshot, Mapping) else None
    meta_mapping: Mapping[str, object] = (
        cast("Mapping[str, object]", raw_meta) if isinstance(raw_meta, Mapping) else {}
    )
    raw_schema_version = meta_mapping.get("schema_version", 1)
    schema_version = (
        raw_schema_version
        if isinstance(raw_schema_version, int)
        and not isinstance(raw_schema_version, bool)
        else 1
    )
    parser_version = meta_mapping.get("parser_version")
    raw_freshness = meta_mapping.get("freshness")
    freshness: Mapping[str, object] = (
        cast("Mapping[str, object]", raw_freshness)
        if isinstance(raw_freshness, Mapping)
        else {"mode": "snapshot", "historical": True, "stale": False}
    )
    for diagnostic_source in (
        snapshot.get("diagnostics") if isinstance(snapshot, Mapping) else None,
        meta_mapping.get("diagnostics"),
    ):
        if isinstance(diagnostic_source, list):
            source_list = cast("list[object]", diagnostic_source)
            for item in source_list:
                if isinstance(item, Mapping):
                    safe_item = _safe_dict(cast("Mapping[str, object]", item))
                    diagnostics.append(safe_item)
    report: dict[str, object] = {
        "snapshot": snapshot_report,
        "cache": cache_report,
        "schema": {
            "version": schema_version,
            "supported_versions": sorted(_SUPPORTED_SCHEMA_VERSIONS),
            "readable": (
                snapshot is not None and schema_version in _SUPPORTED_SCHEMA_VERSIONS
            ),
        },
        "parser": {
            "name": meta_mapping.get("parser"),
            "version": parser_version,
        },
        "freshness": _safe_dict(freshness),
        "artifacts": {
            "snapshot": snapshot_report.get("sha256"),
            "cache": cache_report.get("artifacts", []),
        },
        "diagnostics": sorted(
            [_safe_dict(item) for item in diagnostics],
            key=lambda item: (
                str(item.get("code", "")),
                str(item.get("stage", "")),
                str(item.get("message", "")),
            ),
        ),
    }
    diagnostic_rows = cast("list[dict[str, object]]", report["diagnostics"])
    error_count = sum(1 for item in diagnostic_rows if item.get("severity") == "error")
    warning_count = sum(
        1 for item in diagnostic_rows if item.get("severity") == "warning"
    )
    report["health"] = {
        "status": "error" if error_count else "warning" if warning_count else "ok",
        "errors": error_count,
        "warnings": warning_count,
        "checks": len(diagnostic_rows),
    }
    return _safe_dict(report)


__all__ = ["diagnose"]
