"""Command-line interface for published DeepSWE benchmark artifacts."""
# ruff: noqa: CPY001

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import quote as url_quote

from .analysis import build_report, filter_trials, rank_rows
from .contracts import (
    COMPARISON_SEMANTIC_FIELDS,
    DIAGNOSTIC_FIELDS,
    EVIDENCE_FIELDS,
    SEMANTIC_STATUSES,
    VALUE_STATUSES,
)
from .contracts import SCHEMA_VERSION as CONTRACT_SCHEMA_VERSION
from .diagnostics import merge_diagnostics, redact
from .diff import compare_snapshots
from .identity import canonical_identity, classify_duplicates, identity_json
from .normalization import normalize_payload, normalize_rows
from .overlap import dependency_summary
from .sources import DEFAULT_VERSION as SOURCE_DEFAULT_VERSION
from .sources import fetch_artifacts, load_artifact, resolve_version
from .validation import diagnose_payload

EXPECTED_SNAPSHOT_COUNT = 2

SCHEMA_VERSION = CONTRACT_SCHEMA_VERSION
IDENTITY_COMPONENT_COUNT = 4
LEGACY_IDENTITY_COMPONENT_COUNT = 3
DEFAULT_VERSION = SOURCE_DEFAULT_VERSION
BENCHMARK = "DeepSWE"
ARTIFACT_BASE = "https://deepswe.datacurve.ai/artifacts"


class CliError(RuntimeError):
    """An expected command failure rendered in the JSON error envelope."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize an error with its stable code and rendered message."""
        super().__init__(message)
        self.code = code
        self.message = message


class CliUsageError(CliError):
    """A malformed command line (exit status 2)."""

    def __init__(self, message: str) -> None:
        """Initialize a usage error with the standard usage code."""
        super().__init__("usage", message)


class _ArgumentParser(argparse.ArgumentParser):
    """Argparse parser that lets ``main`` emit the normal error envelope."""

    def error(self, message: str) -> None:
        raise CliUsageError(message)


_SEMVER_RE = re.compile(
    r"^v?(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)"
    r"(?:\.(?P<patch>0|[1-9][0-9]*))?(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_VERSION_IN_PATH_RE = re.compile(r"(?:^|[/\\])(v[0-9]+(?:\.[0-9]+)+)(?:[/\\]|$)")


def _version_arg(raw: str) -> str:
    value = raw.strip()
    if not value:
        message = "version must be latest or a semantic version such as v1.1"
        raise argparse.ArgumentTypeError(message)
    if value.lower() == "latest":
        return "latest"
    if value.lower() in {"v1", "1"} or re.fullmatch(r"v?[0-9]+", value):
        message = (
            "major-only versions are not supported; use latest or a semantic "
            "version such as v1.1"
        )
        raise argparse.ArgumentTypeError(message)
    match = _SEMVER_RE.fullmatch(value)
    if match is None:
        message = "version must be latest or a semantic version such as v1.1"
        raise argparse.ArgumentTypeError(message)
    # Artifact paths are versioned with the v-prefixed spelling.
    return value if value.startswith("v") else f"v{value}"


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        message = "must be a positive integer"
        raise argparse.ArgumentTypeError(message) from exc
    if value <= 0:
        message = "must be a positive integer"
        raise argparse.ArgumentTypeError(message)
    return value


def _nonnegative_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        message = "must be a non-negative integer"
        raise argparse.ArgumentTypeError(message) from exc
    if value < 0:
        message = "must be a non-negative integer"
        raise argparse.ArgumentTypeError(message)
    return value


def _positive_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        message = "must be a positive number"
        raise argparse.ArgumentTypeError(message) from exc
    if not math.isfinite(value) or value <= 0:
        message = "must be a positive number"
        raise argparse.ArgumentTypeError(message)
    return value


def _threshold(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        message = "must be a number between 0 and 1"
        raise argparse.ArgumentTypeError(message) from exc
    if not math.isfinite(value) or value < 0 or value > 1:
        message = "must be a number between 0 and 1"
        raise argparse.ArgumentTypeError(message)
    return value


def _default_cache_dir() -> Path:
    configured = os.environ.get("DEEPSWE_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    return (Path(xdg).expanduser() if xdg else Path.home() / ".cache") / "deepswe"


def _default_output_dir() -> Path:
    configured = os.environ.get("DEEPSWE_OUTPUT_DIR")
    if configured:
        return Path(configured).expanduser()
    return _default_cache_dir() / "artifacts"


def _add_version_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--version",
        type=_version_arg,
        default=argparse.SUPPRESS,
        help="benchmark release (latest or semantic version such as v1.1)",
    )


def _add_fetch_options(
    parser: argparse.ArgumentParser, *, snapshot: bool = False
) -> None:
    _add_version_option(parser)
    if snapshot:
        parser.add_argument(
            "--snapshot",
            type=Path,
            help="read this local JSON artifact instead of fetching",
        )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="directory for fetched artifacts",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="conditional-request cache directory",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=30.0,
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="permit an explicitly stale cached artifact after a fetch failure",
    )


def _add_quality_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--min-pass-at-1",
        type=_threshold,
        default=None,
        help="exclude rows below this pass@1 threshold",
    )
    parser.add_argument(
        "--min-attempted",
        type=_nonnegative_int,
        default=None,
        help="exclude rows with fewer attempted samples",
    )
    parser.add_argument(
        "--min-tasks",
        type=_nonnegative_int,
        default=None,
        help="exclude rows with fewer attempted tasks",
    )
    parser.add_argument("--limit", type=_nonnegative_int, default=10)


def _add_strict_semantics_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--strict-semantics",
        action="store_true",
        help="block values without known source semantics from comparisons",
    )


def _add_strict_duplicates_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--strict-rank",
        "--strict-duplicates",
        dest="strict_duplicates",
        action="store_true",
        help="block conflicting duplicate identities while ranking",
    )


def _add_strict_compare_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--strict-compare",
        "--strict",
        dest="strict_compare",
        action="store_true",
        help="block incompatible schemas, semantics, and duplicate identities",
    )


def _add_trial_filter_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", default="deep-swe")
    parser.add_argument("--eval-scope", default="full")
    included = parser.add_mutually_exclusive_group()
    included.add_argument(
        "--included-only",
        dest="included_only",
        action="store_true",
        default=True,
        help="retain only trials included in the published score (default)",
    )
    included.add_argument(
        "--all",
        "--include-excluded",
        dest="included_only",
        action="store_false",
        help="include excluded trials",
    )
    parser.add_argument("--limit", type=_nonnegative_int, default=None)


def build_parser() -> argparse.ArgumentParser:
    """Build the public DeepSWE command grammar."""
    parser = _ArgumentParser(
        prog="deepswe-live",
        description="Read published DeepSWE benchmark metrics and derived comparisons.",
    )
    # Keeping --version before the subcommand useful is harmless, while every
    # subcommand also accepts it after the command (the documented spelling).
    _add_version_option(parser)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    fetch = commands.add_parser("fetch", help="fetch the published leaderboard")
    _add_fetch_options(fetch)
    fetch.add_argument(
        "--trials",
        action="store_true",
        help="also fetch the optional raw trials artifact",
    )

    report = commands.add_parser("report", help="build the primary decision report")
    _add_fetch_options(report, snapshot=True)
    _add_quality_options(report)
    _add_strict_semantics_option(report)

    report.add_argument(
        "--pareto-axis",
        action="append",
        default=None,
        metavar="METRIC:ORDER",
        help="add a Pareto axis; ORDER is min/asc or max/desc (repeatable)",
    )
    report.add_argument(
        "--efficiency",
        action="append",
        default=None,
        metavar="NAME=NUMERATOR/DENOMINATOR",
        help="derive an explicit ratio under each row (repeatable)",
    )
    rank = commands.add_parser("rank", help="rank published leaderboard rows")
    _add_fetch_options(rank, snapshot=True)
    rank.add_argument(
        "metric_pos", nargs="?", help="metric to rank (default: pass_at_1)"
    )
    rank.add_argument("--metric", dest="metric_opt", help="metric to rank")
    rank.add_argument(
        "--order",
        choices=(
            "asc",
            "desc",
            "ascending",
            "descending",
            "min",
            "max",
            "minimize",
            "maximize",
        ),
        default="desc",
    )
    _add_quality_options(rank)
    _add_strict_semantics_option(rank)
    _add_strict_duplicates_option(rank)
    trials = commands.add_parser("trials", help="filter raw trial records")
    _add_fetch_options(trials, snapshot=True)
    _add_trial_filter_options(trials)

    stats = commands.add_parser("stats", help="summarize a published artifact")
    _add_fetch_options(stats, snapshot=True)
    stats.add_argument(
        "--trials",
        action="store_true",
        help="summarize raw trials instead of the leaderboard",
    )
    _add_strict_semantics_option(stats)
    _add_trial_filter_options(stats)

    diagnose = commands.add_parser(
        "diagnose",
        help="inspect artifact shape and provenance without exposing rows",
    )
    _add_fetch_options(diagnose, snapshot=True)
    diagnose.add_argument(
        "--trials",
        action="store_true",
        help="inspect the optional raw trials artifact explicitly",
    )

    schema = commands.add_parser("schema", help="describe the CLI response schema")
    _add_version_option(schema)

    compare = commands.add_parser("compare", help="compare two same-version snapshots")
    compare.add_argument("left_pos", nargs="?", help="older/left snapshot path")
    compare.add_argument("right_pos", nargs="?", help="newer/right snapshot path")
    compare.add_argument(
        "--left", "--before", dest="left_opt", help="older/left snapshot path"
    )
    compare.add_argument(
        "--right", "--after", dest="right_opt", help="newer/right snapshot path"
    )
    compare.add_argument(
        "--snapshot",
        dest="snapshots",
        action="append",
        type=Path,
        help="left then right snapshot (may be supplied twice)",
    )
    _add_version_option(compare)
    compare.add_argument("--metric", default="pass_at_1")
    compare.add_argument("--limit", type=_nonnegative_int, default=10)
    _add_strict_semantics_option(compare)
    _add_strict_compare_option(compare)

    return parser


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _safe_error_message(value: object) -> str:
    redacted = redact(str(value))
    text = redacted if isinstance(redacted, str) else str(redacted)
    return text[:512]


def _emit(value: Mapping[str, Any], *, stdout: TextIO) -> None:
    print(_compact_json(value), file=stdout)


def _success(command: str, data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "data": dict(data),
    }


def _error(command: str, code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "error": {"code": code, "message": _safe_error_message(message)},
    }


def _as_mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _unwrap(value: object) -> object:
    if (
        isinstance(value, Mapping)
        and value.get("ok") is True
        and isinstance(value.get("data"), Mapping)
    ):
        return value["data"]
    return value


def _first(mapping: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _version_from(value: object, fallback: str | None = None) -> str | None:
    if isinstance(value, Mapping):
        candidate = _first(value, "benchmark_version", "version", "release")
        if isinstance(candidate, Mapping):
            candidate = _first(candidate, "benchmark_version", "version", "name")
        if candidate is not None:
            value = candidate
        else:
            for key in ("scope", "metadata", "provenance"):
                found = _version_from(value.get(key), None)
                if found:
                    return found
            value = None
    if isinstance(value, str):
        try:
            return _version_arg(value)
        except argparse.ArgumentTypeError:
            return value
    return fallback


def _resolve(raw: str | None) -> tuple[str, Mapping[str, Any]]:
    requested = raw or "latest"
    # Validate before calling the source module, so a forbidden legacy path
    # cannot be constructed even if a source implementation is permissive.
    requested = _version_arg(requested)
    try:
        resolved = resolve_version(requested)
    except CliError:
        raise
    except Exception as exc:
        code = "version"
        raise CliError(code, str(exc)) from exc
    if isinstance(resolved, Mapping):
        version = _version_from(resolved)
        if version is None:
            version = DEFAULT_VERSION if requested == "latest" else requested
        return version, resolved
    version = _version_from(
        resolved, DEFAULT_VERSION if requested == "latest" else requested
    )
    if version is None:
        code = "version"
        message = "source did not resolve a benchmark version"
        raise CliError(code, message)
    return version, {"benchmark_version": version, "requested": requested}


def _uri_for(path: Path) -> str:
    try:
        absolute = path.expanduser().resolve()
    except OSError:
        absolute = path.expanduser()
    return "file://" + url_quote(str(absolute))


def _artifact_url(version: str | None, artifact: str) -> str:
    if not version:
        return f"{ARTIFACT_BASE}/unknown/{artifact}"
    return f"{ARTIFACT_BASE}/{version}/{artifact}"


def _provenance(  # noqa: C901, PLR0912
    *,
    source: object = None,
    payload: object = None,
    version: str | None = None,
    artifact: str = "leaderboard-live.json",
    snapshot: Path | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    candidates: list[Mapping[str, Any]] = []
    for value in (source, payload):
        mapping = _as_mapping(value)
        if mapping is None:
            continue
        # Keep the wrapper before its nested metadata so artifact-specific
        # candidates are considered first when the list is traversed below.
        candidates.append(mapping)
        for key in ("provenance", "sources", "metadata", "meta"):
            nested = _as_mapping(mapping.get(key))
            if nested is None:
                continue
            # fetch_artifacts keeps provenance keyed by artifact filename.
            specific = _as_mapping(nested.get(artifact))
            candidates.append(specific if specific is not None else nested)
        artifacts = _as_mapping(mapping.get("artifacts"))
        if artifacts is not None:
            specific_artifact = _as_mapping(artifacts.get(artifact))
            if specific_artifact is not None:
                candidates.append(specific_artifact)
    # Candidates are ordered from least-specific wrappers to artifact-specific
    # metadata; iterate in reverse while filling only missing values.
    metadata_keys = {
        "url",
        "URL",
        "fetched_at",
        "generated_at",
        "generatedAt",
        "etag",
        "ETag",
        "last_modified",
        "Last-Modified",
        "http_status",
        "status",
        "artifact",
        "local_path",
        "cache_path",
        "cache_reused",
        "stale",
        "freshness",
        "snapshot",
        "snapshot_path",
        "sha256",
        "artifact_sha256",
        "length",
        "raw_path",
        "metadata_path",
        "artifact_ref",
        "manifest_sha256",
        "manifest_path",
        "manifest_ref",
        "legacy_unverified",
    }
    for candidate in reversed(candidates):
        for key, value in candidate.items():
            if key in metadata_keys and value is not None and key not in result:
                result[key] = value

    if snapshot is not None:
        result.setdefault("url", _uri_for(snapshot))
        result.setdefault("snapshot", True)
        result.setdefault("snapshot_path", str(snapshot.expanduser()))
        try:
            result.setdefault(
                "fetched_at",
                datetime.fromtimestamp(
                    snapshot.stat().st_mtime, timezone.utc
                ).isoformat(),
            )
        except OSError:
            result.setdefault("fetched_at", _now())
        result.setdefault("freshness", "snapshot")
    else:
        result.setdefault("url", _artifact_url(version, artifact))
        result.setdefault("fetched_at", _now())

    aliases = {
        "URL": "url",
        "ETag": "etag",
        "Last-Modified": "last_modified",
        "generated_at": "generatedAt",
    }
    for canonical, alternate in aliases.items():
        if canonical not in result and alternate in result:
            result[canonical] = result[alternate]
        if alternate not in result and canonical in result:
            result[alternate] = result[canonical]
    return result


def _scope(
    *,
    version: str | None,
    filters: Mapping[str, Any],
    value_status: str,
) -> dict[str, Any]:
    if value_status not in {"published", "published_raw", "derived"}:
        value_status = "derived"
    scope = {
        "benchmark": BENCHMARK,
        "benchmark_version": version or DEFAULT_VERSION,
        "filters_applied": dict(filters),
        "value_status": value_status,
    }
    scope.update(dependency_summary())
    return scope


def _with_scope(  # noqa: PLR0913
    value: object,
    *,
    command: str,
    version: str | None,
    filters: Mapping[str, Any],
    value_status: str,
    source: object = None,
    payload: object = None,
    artifact: str = "leaderboard-live.json",
    snapshot: Path | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    del command
    mapping = dict(value) if isinstance(value, Mapping) else {"result": value}
    existing_scope = _as_mapping(mapping.get("scope")) or {}
    merged_filters = dict(existing_scope.get("filters_applied", {}))
    merged_filters.update(filters)
    actual_version = (
        _version_from(existing_scope, version) or version or DEFAULT_VERSION
    )
    if actual_version == "latest":
        actual_version = version if version and version != "latest" else DEFAULT_VERSION
    mapping["scope"] = _scope(
        version=actual_version,
        filters=merged_filters,
        value_status=value_status,
    )
    if provenance is None:
        provenance = _provenance(
            source=source,
            payload=payload,
            version=actual_version,
            artifact=artifact,
            snapshot=snapshot,
        )
    dependency = dependency_summary()
    mapping.setdefault("dependencies", dependency["dependencies"])
    mapping.setdefault("independence_class", dependency["independence_class"])
    mapping["provenance"] = dict(provenance)
    return mapping


def _value_payload(value: object, *, artifact: str) -> object:
    value = _unwrap(value)
    if isinstance(value, (str, Path)):
        path = Path(value).expanduser()
        if path.exists():
            try:
                return _unwrap(load_artifact(path))
            except Exception as exc:
                code = "malformed"
                message = f"could not load {artifact}: {exc}"
                raise CliError(code, message) from exc
        return value
    mapping = _as_mapping(value)
    if mapping is not None:
        for key in ("payload", "data", "content", "json"):
            nested = mapping.get(key)
            if isinstance(nested, (Mapping, list)):
                return _unwrap(nested)
        path = _first(mapping, "path", "local_path", "file")
        if isinstance(path, (str, Path)):
            candidate = Path(path).expanduser()
            if candidate.exists():
                try:
                    return _unwrap(load_artifact(candidate))
                except Exception as exc:
                    code = "malformed"
                    message = f"could not load {artifact}: {exc}"
                    raise CliError(code, message) from exc
    return value


def _select_artifact(
    source: object, *, artifact: str, version: str | None = None
) -> object:
    del version
    if not isinstance(source, Mapping):
        return source
    stem = artifact.removesuffix(".json")
    aliases = (
        artifact,
        stem,
        stem.replace("-live", ""),
        "leaderboard" if "leaderboard" in stem else "trials",
    )
    artifacts = _as_mapping(source.get("artifacts"))
    if artifacts is not None:
        for key in aliases:
            if key in artifacts:
                return _value_payload(artifacts[key], artifact=artifact)
    for key in aliases:
        if key in source:
            value = source[key]
            # A metadata mapping is not an artifact payload; resolve its path
            # or payload before falling through to the wrapper.
            selected = _value_payload(value, artifact=artifact)
            if selected is not value or isinstance(selected, (list, Path)):
                return selected
            if isinstance(selected, Mapping) and selected is not source:
                return selected
    path = _first(
        source,
        f"{stem}_path",
        f"{stem.replace('-', '_')}_path",
        "leaderboard_path" if "leaderboard" in stem else "trials_path",
    )
    if path is not None:
        return _value_payload(path, artifact=artifact)
    # A direct artifact object commonly has rows/data at its top level.
    return source


def _rows(
    value: object, *, trials: bool = False, normalize: bool | None = None
) -> list[dict[str, Any]]:
    should_normalize = not trials if normalize is None else normalize
    value = _unwrap(value)
    if isinstance(value, list):
        rows = [dict(row) for row in value if isinstance(row, Mapping)]
        return normalize_rows(rows, source_path="$.rows") if should_normalize else rows
    mapping = _as_mapping(value)
    if mapping is None:
        return []
    preferred = (
        ("trials", "rows", "data", "records", "results")
        if trials
        else ("rows", "leaderboard", "models", "results", "data")
    )
    for key in preferred:
        candidate = mapping.get(key)
        if isinstance(candidate, list):
            rows = [dict(row) for row in candidate if isinstance(row, Mapping)]
            return (
                normalize_rows(rows, source_path=f"$.{key}")
                if should_normalize
                else rows
            )
        if isinstance(candidate, Mapping):
            nested = _rows(candidate, trials=trials, normalize=should_normalize)
            if nested:
                return nested
    if any(key in mapping for key in ("model", "config", "pass_at_1", "trial_id")):
        rows = [dict(mapping)]
        return normalize_rows(rows, source_path="$") if should_normalize else rows
    return []


def _context_payload(payload: object, *, artifact: str) -> object:
    """Normalize leaderboard payloads while preserving raw trial payloads."""
    if artifact == "trials.json":
        return payload
    return normalize_payload(payload)


def _fetch_context(
    args: argparse.Namespace, *, artifact: str, include_trials: bool
) -> dict[str, Any]:
    version, resolved = _resolve(getattr(args, "version", "latest"))
    output_dir = getattr(args, "output_dir", None) or _default_output_dir()
    cache_dir = getattr(args, "cache_dir", None) or _default_cache_dir()
    try:
        source = fetch_artifacts(
            version,
            output_dir=output_dir,
            cache_dir=cache_dir,
            include_trials=include_trials,
            timeout=getattr(args, "timeout", 30.0),
            allow_stale=bool(getattr(args, "allow_stale", False)),
        )
    except CliError:
        raise
    except Exception as exc:
        raise CliError(_exception_code(exc), str(exc)) from exc
    if not isinstance(source, Mapping):
        code = "schema"
        message = "source returned an invalid artifact envelope"
        raise CliError(code, message)
    payload = _select_artifact(source, artifact=artifact, version=version)
    return {
        "source": source,
        "payload": _context_payload(payload, artifact=artifact),
        "version": _version_from(source, version) or version,
        "resolved": resolved,
        "artifact": artifact,
        "snapshot": None,
    }


def _snapshot_context(args: argparse.Namespace, *, artifact: str) -> dict[str, Any]:
    path_value = getattr(args, "snapshot", None)
    if path_value is None:
        message = f"{args.command} requires --snapshot when loading a local artifact"
        raise CliUsageError(message)
    path = Path(path_value).expanduser()
    try:
        raw = load_artifact(path)
    except CliError:
        raise
    except Exception as exc:
        code = _exception_code(exc)
        message = f"could not load snapshot {path}: {exc}"
        raise CliError(code, message) from exc
    payload = _unwrap(raw)
    version = _version_from(payload) or _version_from(raw)
    if version is None:
        path_match = _VERSION_IN_PATH_RE.search(str(path))
        version = path_match.group(1) if path_match else None
    requested = getattr(args, "version", "latest")
    if version is None:
        code = "version"
        message = (
            "snapshot must declare benchmark_version in payload metadata or "
            "include a concrete version component in its path"
        )
        raise CliError(code, message)
    if requested and requested != "latest":
        expected, _ = _resolve(requested)
        if version != expected:
            code = "mixed_version"
            message = (
                f"snapshot benchmark version {version!r} does not match "
                f"requested {expected!r}"
            )
            raise CliError(code, message)
        version = expected
    selected = _select_artifact(payload, artifact=artifact, version=version)
    return {
        "source": raw,
        "payload": _context_payload(selected, artifact=artifact),
        "version": version,
        "resolved": {"benchmark_version": version, "snapshot": True},
        "artifact": artifact,
        "snapshot": path,
    }


def _context(
    args: argparse.Namespace, *, artifact: str, include_trials: bool
) -> dict[str, Any]:
    if getattr(args, "snapshot", None) is not None:
        return _snapshot_context(args, artifact=artifact)
    return _fetch_context(args, artifact=artifact, include_trials=include_trials)


def _quality_filters(args: argparse.Namespace) -> dict[str, Any]:
    filters: dict[str, Any] = {"quality_exclusion": "none"}
    for name, key in (
        ("min_pass_at_1", "min_pass_at_1"),
        ("min_attempted", "min_attempted"),
        ("min_tasks", "min_tasks"),
    ):
        value = getattr(args, name, None)
        if value is not None:
            filters[key] = value
    if len(filters) > 1:
        filters["quality_exclusion"] = "explicit_thresholds"
    pareto_axes = getattr(args, "pareto_axis", None)
    efficiencies = getattr(args, "efficiency", None)
    if pareto_axes is not None:
        filters["pareto_axes"] = pareto_axes
    if efficiencies is not None:
        filters["efficiency"] = efficiencies
    if getattr(args, "strict_semantics", False):
        filters["strict_semantics"] = True
    if getattr(args, "strict_duplicates", False):
        filters["strict_duplicates"] = True
    if pareto_axes is not None or efficiencies is not None:
        filters["analysis_options"] = "explicit"
    return filters


def _analysis_result(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {"result": value}


def _handle_fetch(args: argparse.Namespace) -> dict[str, Any]:
    context = _fetch_context(
        args,
        artifact="trials.json" if args.trials else "leaderboard-live.json",
        include_trials=args.trials,
    )
    source = context["source"]
    data = _fetch_output(source)
    artifact = context["artifact"]
    filters: dict[str, Any]
    status: str
    if args.trials:
        filters = {
            "artifact": "trials.json",
            "source": "deep-swe",
            "eval_scope": "full",
            "included_in_score": True,
            "raw_scope": "broader_than_full_deepswe",
        }
        status = "published_raw"
    else:
        filters = {"artifact": "leaderboard-live.json"}
        status = "published"
    return _with_scope(
        data,
        command="fetch",
        version=context["version"],
        filters=filters,
        value_status=status,
        source=source,
        payload=context["payload"],
        artifact=artifact,
    )


def _handle_report(args: argparse.Namespace) -> dict[str, Any]:
    context = _context(args, artifact="leaderboard-live.json", include_trials=False)
    try:
        result = build_report(
            context["payload"],
            min_pass_at_1=args.min_pass_at_1,
            min_attempted=args.min_attempted,
            min_tasks=args.min_tasks,
            limit=args.limit,
            pareto_axes=args.pareto_axis,
            efficiency_specs=args.efficiency,
            strict_semantics=getattr(args, "strict_semantics", False),
        )
    except Exception as exc:
        raise CliError(_exception_code(exc), str(exc)) from exc
    filters = {"artifact": "leaderboard-live.json", **_quality_filters(args)}
    return _with_scope(
        _analysis_result(result),
        command="report",
        version=context["version"],
        filters=filters,
        value_status="derived",
        source=context["source"],
        payload=context["payload"],
        artifact=context["artifact"],
        snapshot=context["snapshot"],
    )


def _fetch_output(source: object) -> dict[str, Any]:
    """Project fetch metadata without dumping the optional raw trial payload."""
    if not isinstance(source, Mapping):
        return {"artifacts": source}
    data = dict(source)
    artifacts = data.get("artifacts")
    if isinstance(artifacts, Mapping):
        projected: dict[str, Any] = {}
        for name, value in artifacts.items():
            if isinstance(value, Mapping):
                projected[name] = {
                    key: item
                    for key, item in value.items()
                    if key
                    not in {"data", "payload", "raw", "body", "raw_body", "raw_bytes"}
                }
            else:
                projected[name] = value
        data["artifacts"] = projected
    for key in ("payloads", "leaderboard", "trials"):
        data.pop(key, None)
    known = {
        "artifacts",
        "provenance",
        "scope",
        "benchmark",
        "benchmark_version",
        "version",
        "generated_at",
        "fetched_at",
        "metadata",
    }
    unknown = {
        str(key): value
        for key, value in data.items()
        if str(key) not in known and key != "raw_metadata"
    }
    if unknown:
        existing = data.get("raw_metadata")
        merged = dict(existing) if isinstance(existing, Mapping) else {}
        merged.update(unknown)
        data["raw_metadata"] = merged
        for key in unknown:
            data.pop(key, None)
    return data


def _handle_rank(args: argparse.Namespace) -> dict[str, Any]:
    context = _context(args, artifact="leaderboard-live.json", include_trials=False)
    metric = args.metric_opt or args.metric_pos or "pass_at_1"
    rows = _rows(context["payload"])
    try:
        result = rank_rows(
            rows,
            metric,
            args.order,
            min_pass_at_1=args.min_pass_at_1,
            min_attempted=args.min_attempted,
            min_tasks=args.min_tasks,
            limit=args.limit,
            strict_semantics=getattr(args, "strict_semantics", False),
            strict_duplicates=getattr(args, "strict_duplicates", False),
        )
    except Exception as exc:
        raise CliError(_exception_code(exc), str(exc)) from exc
    filters = {
        "artifact": "leaderboard-live.json",
        "metric": metric,
        "order": args.order,
        **_quality_filters(args),
    }
    return _with_scope(
        _analysis_result(result),
        command="rank",
        version=context["version"],
        filters=filters,
        value_status="derived",
        source=context["source"],
        payload=context["payload"],
        artifact=context["artifact"],
        snapshot=context["snapshot"],
    )


def _handle_trials(args: argparse.Namespace) -> dict[str, Any]:
    context = _context(args, artifact="trials.json", include_trials=True)
    rows = _rows(context["payload"], trials=True)
    try:
        result = filter_trials(
            rows,
            source=args.source,
            eval_scope=args.eval_scope,
            included_only=args.included_only,
            limit=args.limit,
        )
    except Exception as exc:
        raise CliError(_exception_code(exc), str(exc)) from exc
    filters = {
        "artifact": "trials.json",
        "source": args.source,
        "eval_scope": args.eval_scope,
        "included_in_score": args.included_only,
    }
    return _with_scope(
        _analysis_result(result),
        command="trials",
        version=context["version"],
        filters=filters,
        value_status="published_raw",
        source=context["source"],
        payload=context["payload"],
        artifact=context["artifact"],
        snapshot=context["snapshot"],
    )


def _numeric(value: object) -> float | int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        return None
    return value


def _stats_for_rows(
    rows: Sequence[Mapping[str, Any]], *, strict_semantics: bool = False
) -> dict[str, Any]:
    fields = sorted({str(key) for row in rows for key in row})
    missing = {
        field: sum(1 for row in rows if row.get(field) is None) for field in fields
    }
    ranges: dict[str, dict[str, float | int]] = {}
    blocked: dict[str, list[str]] = {}
    for field in fields:
        values: list[float | int] = []
        for row in rows:
            if strict_semantics:
                metrics = row.get("metrics")
                evidence = metrics.get(field) if isinstance(metrics, Mapping) else None
                if isinstance(evidence, Mapping):
                    value = evidence.get("normalized_value")
                    if evidence.get("comparison_eligibility") != "eligible":
                        reasons = evidence.get("blocked_reasons")
                        if isinstance(reasons, Sequence) and not isinstance(
                            reasons, (str, bytes, bytearray)
                        ):
                            blocked.setdefault(field, []).extend(
                                str(reason) for reason in reasons
                            )
                        continue
                    numeric = _numeric(value)
                else:
                    numeric = None
            else:
                numeric = _numeric(row.get(field))
            if numeric is not None:
                values.append(numeric)
        if values:
            ranges[field] = {"min": min(values), "max": max(values)}
    result: dict[str, Any] = {
        "row_count": len(rows),
        "fields": fields,
        "missing": missing,
        "numeric_ranges": ranges,
    }
    if strict_semantics:
        result["strict_semantics"] = True
        result["blocked"] = {
            field: sorted(set(reasons)) for field, reasons in blocked.items()
        }
    return result


def _handle_stats(args: argparse.Namespace) -> dict[str, Any]:
    artifact = "trials.json" if args.trials else "leaderboard-live.json"
    context = _context(args, artifact=artifact, include_trials=args.trials)
    payload = context["payload"]
    if (
        isinstance(payload, Mapping)
        and isinstance(payload.get("stats"), Mapping)
        and not args.trials
        and not getattr(args, "strict_semantics", False)
    ):
        result = dict(payload["stats"])
        status = "published"
    elif args.trials:
        rows = _rows(
            payload,
            trials=True,
            normalize=bool(getattr(args, "strict_semantics", False)),
        )
        try:
            filtered = filter_trials(
                rows,
                source=args.source,
                eval_scope=args.eval_scope,
                included_only=args.included_only,
                limit=args.limit,
            )
        except Exception as exc:
            raise CliError(_exception_code(exc), str(exc)) from exc
        selected = _rows(filtered, trials=True, normalize=False)
        result = _stats_for_rows(
            selected, strict_semantics=getattr(args, "strict_semantics", False)
        )
        if isinstance(filtered, Mapping):
            result["input_count"] = filtered.get("input_count", len(rows))
            result["matched_count"] = filtered.get("matched_count", len(selected))
        status = "published_raw"
    else:
        rows = _rows(payload)
        result = _stats_for_rows(
            rows, strict_semantics=getattr(args, "strict_semantics", False)
        )
        status = "derived"
    filters = {
        "artifact": artifact,
        "source": args.source if args.trials else "published leaderboard",
        "eval_scope": args.eval_scope if args.trials else None,
        "included_in_score": args.included_only if args.trials else None,
    }
    if getattr(args, "strict_semantics", False):
        filters["strict_semantics"] = True
    filters = {key: value for key, value in filters.items() if value is not None}
    return _with_scope(
        result,
        command="stats",
        version=context["version"],
        filters=filters,
        value_status=status,
        source=context["source"],
        payload=payload,
        artifact=artifact,
        snapshot=context["snapshot"],
    )


def _diagnose_metadata(
    context: Mapping[str, Any], *, artifact: str
) -> tuple[Mapping[str, object] | None, Path | None]:
    source = context.get("source")
    if isinstance(source, Mapping):
        artifacts = source.get("artifacts")
        if isinstance(artifacts, Mapping):
            candidate = artifacts.get(artifact)
            if isinstance(candidate, Mapping):
                local_path = candidate.get("local_path")
                path = (
                    Path(local_path).expanduser()
                    if isinstance(local_path, str)
                    else None
                )
                return candidate, path
        return source, None
    return None, None


def _diagnose_duplicates(
    payload: object, *, trials: bool = False
) -> tuple[dict[str, list[dict[str, object]]], list[dict[str, object]]]:
    """Project duplicate facts without returning raw row or task fields."""
    rows = _rows(payload, trials=trials, normalize=False)
    report = classify_duplicates(rows)
    projected: dict[str, list[dict[str, object]]] = {
        "identical": [],
        "conflicting": [],
    }
    diagnostics: list[dict[str, object]] = []
    for bucket, bucket_groups in projected.items():
        groups = report.get(bucket, bucket_groups)
        if not isinstance(groups, Sequence):
            continue
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            indexes = group.get("row_indexes")
            row_indexes = (
                sorted(int(index) for index in indexes)
                if isinstance(indexes, Sequence)
                and not isinstance(indexes, (str, bytes, bytearray))
                else []
            )
            identity = group.get("identity")
            safe_identity = identity if isinstance(identity, str) else "<anonymous>"
            if safe_identity.startswith('["published_id","row",'):
                safe_identity = "<anonymous>"
            bucket_groups.append(
                {
                    "identity": safe_identity,
                    "row_indexes": row_indexes,
                    "count": len(row_indexes),
                }
            )
            diagnostics.append(
                {
                    "code": (
                        "DUPLICATE_CONFLICT"
                        if bucket == "conflicting"
                        else "DUPLICATE_IDENTITY"
                    ),
                    "severity": "error" if bucket == "conflicting" else "warning",
                    "stage": "diagnose",
                    "message": (
                        "Conflicting rows share a configuration identity."
                        if bucket == "conflicting"
                        else "Identical rows share a configuration identity."
                    ),
                    "details": {
                        "identity": safe_identity,
                        "row_indexes": row_indexes,
                        "count": len(row_indexes),
                    },
                }
            )
    return projected, merge_diagnostics(diagnostics)


def _handle_diagnose(args: argparse.Namespace) -> dict[str, Any]:
    artifact = "trials.json" if args.trials else "leaderboard-live.json"
    context = _context(args, artifact=artifact, include_trials=args.trials)
    metadata, materialized_path = _diagnose_metadata(context, artifact=artifact)
    snapshot = context.get("snapshot")
    source_path = snapshot if isinstance(snapshot, Path) else materialized_path
    version = context.get("version")
    expected_version = version if isinstance(version, str) else None
    try:
        result = diagnose_payload(
            context["payload"],
            artifact_name=artifact,
            expected_version=expected_version,
            path=source_path,
            metadata=metadata,
        )
    except Exception as exc:
        raise CliError(_exception_code(exc), str(exc)) from exc
    duplicate_report, duplicate_diagnostics = _diagnose_duplicates(
        context["payload"], trials=bool(args.trials)
    )
    result["duplicate_report"] = duplicate_report
    if duplicate_diagnostics:
        result["diagnostics"] = merge_diagnostics(
            result.get("diagnostics", []), duplicate_diagnostics
        )
    filters: dict[str, Any] = {
        "artifact": artifact,
        "operation": "diagnose",
        "trials_explicit": bool(args.trials),
    }
    return _with_scope(
        result,
        command="diagnose",
        version=context["version"],
        filters=filters,
        value_status="published_raw" if args.trials else "published",
        source=context["source"],
        payload=context["payload"],
        artifact=artifact,
        snapshot=context["snapshot"],
    )


def _schema_data(version: str) -> dict[str, Any]:
    return {
        "commands": [
            "fetch",
            "report",
            "rank",
            "trials",
            "stats",
            "schema",
            "compare",
            "diagnose",
        ],
        "schema_version": SCHEMA_VERSION,
        "artifact_schema": {
            "supported": [1],
            "legacy_when_absent": 1,
            "required": ["rows"],
            "optional_counts": ["count", "row_count", "n_rows", "n_trials"],
            "unknown_fields": "preserved",
        },
        "envelope": {
            "success": {
                "ok": True,
                "schema_version": 1,
                "command": "string",
                "data": "object",
            },
            "error": {
                "ok": False,
                "schema_version": 1,
                "command": "string",
                "error": {"code": "string", "message": "string"},
            },
        },
        "scope": {
            "required": [
                "benchmark",
                "benchmark_version",
                "filters_applied",
                "value_status",
            ],
            "value_status": ["published", "published_raw", "derived"],
            "dependencies": "array; [] when no explicit claims are published",
            "independence_class": "unknown when no explicit claims are published",
        },
        "diagnostics": {
            "field": "diagnostics",
            "fields": list(DIAGNOSTIC_FIELDS),
            "ordering": "code,severity,stage,path,details",
            "redaction": "credentials and secret query parameters are redacted",
        },
        "evidence": {
            "value_status": list(VALUE_STATUSES),
            "metric_semantics_status": list(SEMANTIC_STATUSES),
            "comparison_eligibility": ["eligible", "blocked"],
            "fields": list(EVIDENCE_FIELDS),
        },
        "comparison": {
            "strict_semantics": "--strict-semantics",
            "strict_compare": "--strict-compare",
            "strict_rank": "--strict-rank",
            "strict_duplicates": "--strict-duplicates",
            "same_benchmark_version": True,
            "identity": "JSON tuple [model, reasoning_effort, harness, config]",
            "duplicate_policy": {
                "identical": "warning; deterministic first",
                "conflicting": "warning by default; blocked in strict mode",
            },
            "semantic_fields": list(COMPARISON_SEMANTIC_FIELDS),
            "legacy_keys": ["config", "before", "after", "delta"],
        },
        "overlap": {
            "dependencies": [],
            "independence_class": "unknown",
            "collision_policy": "exact canonical component and release only",
        },
        "provenance": {
            "required": ["url", "fetched_at"],
            "optional": ["generated_at", "etag", "last_modified"],
        },
        "artifact_base": ARTIFACT_BASE,
        "benchmark_version": version,
        "report_options": {
            "pareto_axis": "repeatable METRIC:ORDER; omitted uses default axes",
            "efficiency": "repeatable NAME=NUMERATOR/DENOMINATOR; derived only",
        },
    }


def _handle_schema(args: argparse.Namespace) -> dict[str, Any]:
    version, _ = _resolve(getattr(args, "version", "latest"))
    data = {"schema": _schema_data(version)}
    return _with_scope(
        data,
        command="schema",
        version=version,
        filters={"artifact": "leaderboard-live.json", "operation": "schema"},
        value_status="derived",
        provenance=_provenance(version=version, artifact="leaderboard-live.json"),
    )


def _compare_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    values: list[str | Path] = []
    if args.snapshots:
        values.extend(args.snapshots)
    if args.left_opt:
        values.append(args.left_opt)
    if args.right_opt:
        values.append(args.right_opt)
    if args.left_pos:
        values.append(args.left_pos)
    if args.right_pos:
        values.append(args.right_pos)
    if len(values) != EXPECTED_SNAPSHOT_COUNT:
        message = "compare requires exactly two snapshots (left and right)"
        raise CliUsageError(message)
    return Path(values[0]).expanduser(), Path(values[1]).expanduser()


def _safe_compare_identity(value: object) -> str:
    """Keep comparison diagnostics free of anonymous row bodies."""
    if not isinstance(value, str):
        return "<anonymous>"
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return "<anonymous>"
    if isinstance(parsed, list) and len(parsed) == IDENTITY_COMPONENT_COUNT:
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    if (
        isinstance(parsed, list)
        and len(parsed) == LEGACY_IDENTITY_COMPONENT_COUNT
        and parsed[:2] != ["published_id", "row"]
    ):
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    return "<anonymous>"


def _safe_compare_diagnostics(
    diagnostics: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Project kernel diagnostics without exposing duplicate row signatures."""
    safe: list[dict[str, object]] = []
    for item in diagnostics:
        projected = dict(item)
        details = item.get("details")
        if isinstance(details, Mapping):
            details_copy = dict(details)
            if "identity" in details_copy:
                details_copy["identity"] = _safe_compare_identity(
                    details_copy["identity"]
                )
            details_copy.pop("signatures", None)
            details_copy.pop("rows", None)
            projected["details"] = details_copy
        safe.append(projected)
    return merge_diagnostics(safe)


def _duplicate_facts_for_compare(
    rows: Sequence[Mapping[str, Any]],
    *,
    identity_rows: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[
    dict[str, Mapping[str, Any]],
    dict[str, list[dict[str, object]]],
    list[dict[str, object]],
]:
    """Select the first row per canonical identity and retain duplicate facts."""
    identity_source = rows if identity_rows is None else identity_rows
    report = classify_duplicates(identity_source)
    selected: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        identity = identity_json(canonical_identity(row))
        selected.setdefault(identity, row)
    projected: dict[str, list[dict[str, object]]] = {
        "identical": [],
        "conflicting": [],
    }
    diagnostics: list[dict[str, object]] = []
    for bucket, bucket_groups in projected.items():
        groups = report.get(bucket, bucket_groups)
        if not isinstance(groups, Sequence):
            continue
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            indexes = group.get("row_indexes")
            row_indexes = (
                sorted(int(index) for index in indexes)
                if isinstance(indexes, Sequence)
                and not isinstance(indexes, (str, bytes, bytearray))
                else []
            )
            identity = _safe_compare_identity(group.get("identity"))
            bucket_groups.append(
                {
                    "identity": identity,
                    "row_indexes": row_indexes,
                    "count": len(row_indexes),
                }
            )
            diagnostics.append(
                {
                    "code": (
                        "DUPLICATE_CONFLICT"
                        if bucket == "conflicting"
                        else "DUPLICATE_IDENTITY"
                    ),
                    "severity": "warning",
                    "stage": "comparison",
                    "message": (
                        "Conflicting rows share a configuration identity."
                        if bucket == "conflicting"
                        else "Identical rows share a configuration identity."
                    ),
                    "details": {
                        "identity": identity,
                        "row_indexes": row_indexes,
                        "count": len(row_indexes),
                    },
                }
            )
    return selected, projected, merge_diagnostics(diagnostics)


def _metadata_candidates(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Mapping):
        return []
    candidates: list[Mapping[str, object]] = [value]
    for key in ("metadata", "scope", "provenance", "artifact", "data", "payload"):
        nested = value.get(key)
        if isinstance(nested, Mapping):
            candidates.append(nested)
    return candidates


def _artifact_schema_declaration(value: object) -> object:
    declarations: list[object] = []
    for candidate in _metadata_candidates(value):
        declarations.extend(
            candidate[key]
            for key in ("artifact_schema_version", "schema_version")
            if key in candidate and candidate[key] is not None
        )
        schema = candidate.get("artifact_schema")
        if isinstance(schema, Mapping) and schema.get("version") is not None:
            declarations.append(schema["version"])
    unique = {
        json.dumps(item, sort_keys=True, separators=(",", ":")): item
        for item in declarations
    }
    if len(unique) == 1:
        return next(iter(unique.values()))
    if len(unique) > 1:
        return "<conflicting>"
    return None


def _semantic_projection(value: object, metric: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    candidates: list[Mapping[str, object]] = [value]
    for key in ("metric_semantics", "semantics", "metrics"):
        nested = value.get(key)
        if isinstance(nested, Mapping):
            candidate = (
                nested.get(metric) if key in {"metric_semantics", "metrics"} else nested
            )
            if isinstance(candidate, Mapping):
                candidates.append(candidate)
    projection: dict[str, object] = {}
    for candidate in candidates:
        for key in (
            "family",
            "comparator",
            "unit",
            "scope",
            "denominator",
            "metric_semantics_status",
        ):
            if key in candidate:
                projection[key] = candidate[key]
    return projection


def _semantic_declarations(
    value: object, metric: str
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    top: dict[str, object] = {}
    for candidate in _metadata_candidates(value):
        top.update(_semantic_projection(candidate, metric))
    rows = _rows(
        _select_artifact(value, artifact="leaderboard-live.json"), normalize=False
    )
    per_row: dict[str, dict[str, object]] = {}
    for row in rows:
        projection = _semantic_projection(row, metric)
        if projection:
            per_row[identity_json(canonical_identity(row))] = projection
    return top, per_row


def _semantic_warnings(
    left: object, right: object, metric: str
) -> list[dict[str, object]]:
    left_top, left_rows = _semantic_declarations(left, metric)
    right_top, right_rows = _semantic_declarations(right, metric)
    warnings: list[dict[str, object]] = []

    def add(reason: str, identity: str | None = None) -> None:
        details: dict[str, object] = {"metric": metric, "reason": reason}
        if identity is not None:
            details["identity"] = _safe_compare_identity(identity)
        warnings.append(
            {
                "code": "COMPARISON_INCOMPARABLE",
                "severity": "warning",
                "stage": "comparison",
                "message": "Metric semantic declarations differ between snapshots.",
                "details": details,
            }
        )

    if left_top != right_top:
        reason = "semantics_mismatch"
        for field in ("unit", "scope", "denominator"):
            if left_top.get(field) != right_top.get(field):
                reason = f"{field}_mismatch"
                break
        add(reason)
    for identity in sorted(set(left_rows) & set(right_rows)):
        before = left_rows[identity]
        after = right_rows[identity]
        if before != after:
            reason = "semantics_mismatch"
            for field in ("unit", "scope", "denominator"):
                if before.get(field) != after.get(field):
                    reason = f"{field}_mismatch"
                    break
            add(reason, identity)
    return merge_diagnostics(warnings)


def _schema_warnings(left: object, right: object) -> list[dict[str, object]]:
    before = _artifact_schema_declaration(left)
    after = _artifact_schema_declaration(right)
    if before is None and after is None:
        return []
    if json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True):
        return []
    return [
        {
            "code": "SCHEMA_DRIFT",
            "severity": "warning",
            "stage": "comparison",
            "message": "Artifact schema declarations differ between snapshots.",
            "details": {"before": before, "after": after},
        }
    ]


def _comparison_numeric(
    row: Mapping[str, Any] | None,
    metric: str,
    *,
    strict_semantics: bool,
) -> tuple[float | int | None, list[str]]:
    if row is None:
        return None, ["MISSING_ROW"]
    if strict_semantics:
        metrics = row.get("metrics")
        evidence = metrics.get(metric) if isinstance(metrics, Mapping) else None
        if isinstance(evidence, Mapping):
            reasons = evidence.get("blocked_reasons")
            blockers = (
                [str(reason) for reason in reasons]
                if isinstance(reasons, Sequence)
                and not isinstance(reasons, (str, bytes, bytearray))
                else []
            )
            if evidence.get("comparison_eligibility") != "eligible":
                return None, blockers or ["COMPARISON_INCOMPARABLE"]
            value = _numeric(evidence.get("normalized_value"))
            return (value, []) if value is not None else (None, ["UNPARSED_VALUE"])
        return None, ["MISSING_REQUIRED_INPUT"]
    return _numeric(row.get(metric)), []


def _legacy_compare(
    left: object,
    right: object,
    *,
    metric: str,
    strict_semantics: bool,
) -> tuple[dict[str, Any], list[dict[str, object]]]:
    left_payload = _select_artifact(left, artifact="leaderboard-live.json")
    right_payload = _select_artifact(right, artifact="leaderboard-live.json")
    left_source_rows = _rows(left_payload, normalize=False)
    right_source_rows = _rows(right_payload, normalize=False)
    left_rows = _rows(left_payload, normalize=True)
    right_rows = _rows(right_payload, normalize=True)
    left_map, left_duplicates, left_diags = _duplicate_facts_for_compare(
        left_rows, identity_rows=left_source_rows
    )
    right_map, right_duplicates, right_diags = _duplicate_facts_for_compare(
        right_rows, identity_rows=right_source_rows
    )
    keys = sorted(set(left_map) | set(right_map))
    changes: list[dict[str, Any]] = []
    for key in keys:
        before, before_reasons = _comparison_numeric(
            left_map.get(key), metric, strict_semantics=strict_semantics
        )
        after, after_reasons = _comparison_numeric(
            right_map.get(key), metric, strict_semantics=strict_semantics
        )
        delta = after - before if before is not None and after is not None else None
        change: dict[str, Any] = {
            "config": key,
            "before": before,
            "after": after,
            "delta": delta,
        }
        if strict_semantics:
            change["blocked_reasons"] = sorted(set(before_reasons + after_reasons))
        changes.append(change)
    changes.sort(
        key=lambda row: (
            row["delta"] is None,
            -(abs(row["delta"]) if row["delta"] is not None else 0),
            row["config"],
        )
    )
    diagnostics = merge_diagnostics(
        left_diags,
        right_diags,
        _schema_warnings(left, right),
        _semantic_warnings(left, right, metric),
    )
    duplicate_report = {
        "left": left_duplicates,
        "right": right_duplicates,
    }
    result: dict[str, Any] = {
        "changes": changes,
        "duplicate_report": duplicate_report,
        "left_count": len(left_rows),
        "right_count": len(right_rows),
    }
    return result, diagnostics


def _strict_snapshot(value: object) -> object:
    """Add normalized rows while preserving every snapshot metadata field."""
    if not isinstance(value, Mapping):
        return value
    projected = dict(value)
    selected = _select_artifact(value, artifact="leaderboard-live.json")
    projected["rows"] = _rows(selected, normalize=True)
    return projected


def _handle_compare(  # noqa: C901, PLR0912, PLR0915
    args: argparse.Namespace,
) -> dict[str, Any]:
    left_path, right_path = _compare_paths(args)
    try:
        left_raw = load_artifact(left_path)
        right_raw = load_artifact(right_path)
    except CliError:
        raise
    except Exception as exc:
        code = _exception_code(exc)
        message = f"could not load snapshots: {exc}"
        raise CliError(code, message) from exc
    left = _unwrap(left_raw)
    right = _unwrap(right_raw)
    left_version = _version_from(left) or _version_from(left_raw)
    if left_version is None:
        path_match = _VERSION_IN_PATH_RE.search(str(left_path))
        left_version = path_match.group(1) if path_match else None
    right_version = _version_from(right) or _version_from(right_raw)
    if right_version is None:
        path_match = _VERSION_IN_PATH_RE.search(str(right_path))
        right_version = path_match.group(1) if path_match else None
    if left_version is None or right_version is None:
        msg = "mixed_version"
        detail = (
            "both snapshots must declare benchmark_version or include a concrete "
            "version component in their paths"
        )
        raise CliError(msg, detail)
    if left_version != right_version:
        msg = "mixed_version"
        detail = (
            f"snapshots use different benchmark versions: {left_version!r} "
            f"and {right_version!r}"
        )
        raise CliError(msg, detail)
    requested = getattr(args, "version", "latest")
    if requested and requested != "latest":
        expected, _ = _resolve(requested)
        if expected != left_version:
            detail = (
                f"snapshot version {left_version!r} does not match "
                f"requested {expected!r}"
            )
            raise CliError(msg, detail)

    strict_semantics = bool(getattr(args, "strict_semantics", False))
    strict_compare = bool(getattr(args, "strict_compare", False))
    strict_mode = strict_compare
    if strict_mode:
        diff = compare_snapshots(
            _strict_snapshot(left),
            _strict_snapshot(right),
            args.metric,
        )
        result: dict[str, Any] = dict(diff)
        result.setdefault(
            "left_count",
            len(_rows(_select_artifact(left, artifact="leaderboard-live.json"))),
        )
        result.setdefault(
            "right_count",
            len(_rows(_select_artifact(right, artifact="leaderboard-live.json"))),
        )
        diagnostics_value = result.get("diagnostics", [])
        if isinstance(diagnostics_value, Sequence) and not isinstance(
            diagnostics_value, (str, bytes, bytearray)
        ):
            result["diagnostics"] = _safe_compare_diagnostics(
                [item for item in diagnostics_value if isinstance(item, Mapping)]
            )
        if isinstance(result.get("changes"), list):
            result["changes"] = sorted(
                result["changes"],
                key=lambda row: (
                    row.get("delta") is None,
                    -(abs(row["delta"]) if row.get("delta") is not None else 0),
                    str(row.get("config")),
                ),
            )[: args.limit]
        result["strict_compare"] = strict_compare
        if strict_semantics:
            result["strict_semantics"] = True
    else:
        result, diagnostics = _legacy_compare(
            left,
            right,
            metric=args.metric,
            strict_semantics=strict_semantics,
        )
        if diagnostics:
            result["diagnostics"] = diagnostics
            result["warnings"] = [
                item for item in diagnostics if item.get("severity") == "warning"
            ]
        if strict_semantics:
            result["strict_semantics"] = True
        result["changes"] = result["changes"][: args.limit]

    provenance = {
        "url": _uri_for(left_path),
        "fetched_at": _now(),
        "left": _provenance(
            source=left_raw,
            payload=left,
            version=left_version,
            snapshot=left_path,
        ),
        "right": _provenance(
            source=right_raw,
            payload=right,
            version=right_version,
            snapshot=right_path,
        ),
        "freshness": "snapshot",
    }
    filters: dict[str, Any] = {
        "left_snapshot": str(left_path),
        "right_snapshot": str(right_path),
        "metric": args.metric,
    }
    if strict_semantics:
        filters["strict_semantics"] = True
    if strict_compare:
        filters["strict_compare"] = True
    return _with_scope(
        {
            "metric": args.metric,
            "left_snapshot": str(left_path),
            "right_snapshot": str(right_path),
            **result,
        },
        command="compare",
        version=left_version,
        filters=filters,
        value_status="derived",
        provenance=provenance,
    )


def _exception_code(exc: BaseException) -> str:
    declared = getattr(exc, "code", None)
    if isinstance(declared, str) and declared:
        return declared
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "version" in name or "version" in message:
        return "version"
    if any(
        token in name or token in message
        for token in ("http", "network", "url", "timeout", "connection")
    ):
        return "network"
    if "json" in name or "decode" in name or "malformed" in name:
        return "malformed"
    if "schema" in name or "schema" in message:
        return "schema"
    return "command"


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    handlers = {
        "fetch": _handle_fetch,
        "report": _handle_report,
        "rank": _handle_rank,
        "trials": _handle_trials,
        "stats": _handle_stats,
        "schema": _handle_schema,
        "diagnose": _handle_diagnose,
        "compare": _handle_compare,
    }
    handler = handlers.get(args.command)
    if handler is None:
        message = "a command is required"
        raise CliUsageError(message)
    return handler(args)


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the CLI and return 0 (success), 1 (operation), or 2 (usage)."""
    del (
        stdin
    )  # Reserved for parity with sibling skill CLIs; this CLI is non-interactive.
    output = sys.stdout if stdout is None else stdout
    diagnostics = sys.stderr if stderr is None else stderr
    parser = build_parser()
    values = list(argv) if argv is not None else sys.argv[1:]
    known_commands = {
        "fetch",
        "report",
        "rank",
        "trials",
        "stats",
        "diagnose",
        "compare",
    }

    command = next((value for value in values if value in known_commands), "unknown")
    try:
        args = parser.parse_args(values)
        if args.command is None:
            message = "a command is required"
            raise CliUsageError(message)  # noqa: TRY301
        command = args.command
        data = _dispatch(args)
    except CliUsageError as exc:
        message = _safe_error_message(exc.message)
        _emit(_error(command, exc.code, message), stdout=output)
        print(f"deepswe-live: {exc.code}: {message}", file=diagnostics)
        return 2
    except SystemExit as exc:
        # --help remains argparse-compatible. Invalid parser errors are
        # converted by _ArgumentParser.error before reaching this branch.
        return int(exc.code) if isinstance(exc.code, int) else 2
    except Exception as exc:  # noqa: BLE001
        code = _exception_code(exc)
        message = _safe_error_message(str(exc) or type(exc).__name__)
        _emit(_error(command, code, message), stdout=output)
        print(f"deepswe-live: {code}: {message}", file=diagnostics)
        return 1
    _emit(_success(command, data), stdout=output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
