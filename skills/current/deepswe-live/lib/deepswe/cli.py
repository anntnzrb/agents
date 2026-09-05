"""Command-line interface for published DeepSWE benchmark artifacts."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, TextIO, cast, override
from urllib.parse import quote as url_quote

if TYPE_CHECKING:
    from numbers import Real

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

    code: str
    message: str

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

    @override
    def error(self, message: str) -> NoReturn:
        raise CliUsageError(message)


_SEMVER_RE = re.compile(
    r"^v?(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)"
    + r"(?:\.(?P<patch>0|[1-9][0-9]*))?(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
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
            + "version such as v1.1"
        )
        raise argparse.ArgumentTypeError(message)
    match = _SEMVER_RE.fullmatch(value)
    if match is None:
        message = "version must be latest or a semantic version such as v1.1"
        raise argparse.ArgumentTypeError(message)
    # Artifact paths are versioned with the v-prefixed spelling.
    return value if value.startswith("v") else f"v{value}"


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
    _ = parser.add_argument(
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
        _ = parser.add_argument(
            "--snapshot",
            type=Path,
            help="read this local JSON artifact instead of fetching",
        )
    _ = parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="directory for fetched artifacts",
    )
    _ = parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="conditional-request cache directory",
    )
    _ = parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=30.0,
        help="HTTP timeout in seconds",
    )
    _ = parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="permit an explicitly stale cached artifact after a fetch failure",
    )


def _add_quality_options(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument(
        "--min-pass-at-1",
        type=_threshold,
        default=None,
        help="exclude rows below this pass@1 threshold",
    )
    _ = parser.add_argument(
        "--min-attempted",
        type=_nonnegative_int,
        default=None,
        help="exclude rows with fewer attempted samples",
    )
    _ = parser.add_argument(
        "--min-tasks",
        type=_nonnegative_int,
        default=None,
        help="exclude rows with fewer attempted tasks",
    )
    _ = parser.add_argument("--limit", type=_nonnegative_int, default=10)


def _add_strict_semantics_option(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument(
        "--strict-semantics",
        action="store_true",
        help="block values without known source semantics from comparisons",
    )


def _add_strict_duplicates_option(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument(
        "--strict-rank",
        "--strict-duplicates",
        dest="strict_duplicates",
        action="store_true",
        help="block conflicting duplicate identities while ranking",
    )


def _add_strict_compare_option(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument(
        "--strict-compare",
        "--strict",
        dest="strict_compare",
        action="store_true",
        help="block incompatible schemas, semantics, and duplicate identities",
    )


def _add_trial_filter_options(parser: argparse.ArgumentParser) -> None:
    _ = parser.add_argument("--source", default="deep-swe")
    _ = parser.add_argument("--eval-scope", default="full")
    included = parser.add_mutually_exclusive_group()
    _ = included.add_argument(
        "--included-only",
        dest="included_only",
        action="store_true",
        default=True,
        help="retain only trials included in the published score (default)",
    )
    _ = included.add_argument(
        "--all",
        "--include-excluded",
        dest="included_only",
        action="store_false",
        help="include excluded trials",
    )
    _ = parser.add_argument("--limit", type=_nonnegative_int, default=None)


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
    _ = fetch.add_argument(
        "--trials",
        action="store_true",
        help="also fetch the optional raw trials artifact",
    )

    report = commands.add_parser("report", help="build the primary decision report")
    _add_fetch_options(report, snapshot=True)
    _add_quality_options(report)
    _add_strict_semantics_option(report)

    _ = report.add_argument(
        "--pareto-axis",
        action="append",
        default=None,
        metavar="METRIC:ORDER",
        help="add a Pareto axis; ORDER is min/asc or max/desc (repeatable)",
    )
    _ = report.add_argument(
        "--efficiency",
        action="append",
        default=None,
        metavar="NAME=NUMERATOR/DENOMINATOR",
        help="derive an explicit ratio under each row (repeatable)",
    )
    rank = commands.add_parser("rank", help="rank published leaderboard rows")
    _add_fetch_options(rank, snapshot=True)
    _ = rank.add_argument(
        "metric_pos", nargs="?", help="metric to rank (default: pass_at_1)"
    )
    _ = rank.add_argument("--metric", dest="metric_opt", help="metric to rank")
    _ = rank.add_argument(
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
    _ = stats.add_argument(
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
    _ = diagnose.add_argument(
        "--trials",
        action="store_true",
        help="inspect the optional raw trials artifact explicitly",
    )

    schema = commands.add_parser("schema", help="describe the CLI response schema")
    _add_version_option(schema)

    compare = commands.add_parser("compare", help="compare two same-version snapshots")
    _ = compare.add_argument("left_pos", nargs="?", help="older/left snapshot path")
    _ = compare.add_argument("right_pos", nargs="?", help="newer/right snapshot path")
    _ = compare.add_argument(
        "--left", "--before", dest="left_opt", help="older/left snapshot path"
    )
    _ = compare.add_argument(
        "--right", "--after", dest="right_opt", help="newer/right snapshot path"
    )
    _ = compare.add_argument(
        "--snapshot",
        dest="snapshots",
        action="append",
        type=Path,
        help="left then right snapshot (may be supplied twice)",
    )
    _add_version_option(compare)
    _ = compare.add_argument("--metric", default="pass_at_1")
    _ = compare.add_argument("--limit", type=_nonnegative_int, default=10)
    _add_strict_semantics_option(compare)
    _add_strict_compare_option(compare)

    return parser


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _safe_error_message(value: object) -> str:
    redacted = redact(str(value))
    text = redacted if isinstance(redacted, str) else str(redacted)
    return text[:512]


def _emit(value: Mapping[str, object], *, stdout: TextIO) -> None:
    print(_compact_json(value), file=stdout)


def _success(command: str, data: Mapping[str, object]) -> dict[str, object]:
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "data": dict(data),
    }


def _error(command: str, code: str, message: str) -> dict[str, object]:
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "error": {"code": code, "message": _safe_error_message(message)},
    }


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return cast("Mapping[str, object]", value)
    return None


def _unwrap(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast("Mapping[str, object]", value)
        if mapping.get("ok") is True:
            data = mapping.get("data")
            if isinstance(data, Mapping):
                return cast("Mapping[str, object]", data)
        return mapping
    return value


def _first(mapping: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _version_from(value: object, fallback: str | None = None) -> str | None:
    if isinstance(value, Mapping):
        mapping = cast("Mapping[str, object]", value)
        candidate = _first(mapping, "benchmark_version", "version", "release")
        if isinstance(candidate, Mapping):
            candidate_mapping = cast("Mapping[str, object]", candidate)
            candidate = _first(
                candidate_mapping, "benchmark_version", "version", "name"
            )
        if candidate is not None:
            value = candidate
        else:
            for key in ("scope", "metadata", "provenance"):
                nested = mapping.get(key)
                found = _version_from(nested, None)
                if found:
                    return found
            value = None
    if isinstance(value, str):
        try:
            return _version_arg(value)
        except argparse.ArgumentTypeError:
            return value
    return fallback


def _resolve(raw: str | None) -> tuple[str, Mapping[str, object]]:
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
    version = _version_from(resolved)
    if version is None:
        version = DEFAULT_VERSION if requested == "latest" else requested
    return version, resolved


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
) -> dict[str, object]:
    result: dict[str, object] = {}
    candidates: list[Mapping[str, object]] = []
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
        _ = result.setdefault("url", _uri_for(snapshot))
        _ = result.setdefault("snapshot", True)
        _ = result.setdefault("snapshot_path", str(snapshot.expanduser()))
        try:
            _ = result.setdefault(
                "fetched_at",
                datetime.fromtimestamp(snapshot.stat().st_mtime, UTC).isoformat(),
            )
        except OSError:
            _ = result.setdefault("fetched_at", _now())
        _ = result.setdefault("freshness", "snapshot")
    else:
        _ = result.setdefault("url", _artifact_url(version, artifact))
        _ = result.setdefault("fetched_at", _now())

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
    filters: Mapping[str, object],
    value_status: str,
) -> dict[str, object]:
    if value_status not in {"published", "published_raw", "derived"}:
        value_status = "derived"
    scope: dict[str, object] = {
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
    filters: Mapping[str, object],
    value_status: str,
    source: object = None,
    payload: object = None,
    artifact: str = "leaderboard-live.json",
    snapshot: Path | None = None,
    provenance: Mapping[str, object] | None = None,
) -> dict[str, object]:
    del command
    mapping: dict[str, object]
    if isinstance(value, Mapping):
        val_map = cast("Mapping[object, object]", value)
        mapping = {str(k): v for k, v in val_map.items()}
    else:
        mapping = {"result": value}
    existing_scope = _as_mapping(mapping.get("scope")) or {}
    merged_filters: dict[str, object] = dict(
        _as_mapping(existing_scope.get("filters_applied")) or {}
    )
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
        prov = _provenance(
            source=source,
            payload=payload,
            version=actual_version,
            artifact=artifact,
            snapshot=snapshot,
        )
    else:
        prov = dict(provenance)
    dependency = dependency_summary()
    _ = mapping.setdefault("dependencies", dependency["dependencies"])
    _ = mapping.setdefault("independence_class", dependency["independence_class"])
    mapping["provenance"] = prov
    return mapping


def _value_payload(value: object, *, artifact: str) -> object:
    unwrapped = _unwrap(value)
    if isinstance(unwrapped, (str, Path)):
        path = Path(unwrapped).expanduser()
        if path.exists():
            try:
                return _unwrap(load_artifact(path))
            except Exception as exc:
                code = "malformed"
                message = f"could not load {artifact}: {exc}"
                raise CliError(code, message) from exc
        return unwrapped
    mapping = _as_mapping(unwrapped)
    if mapping is not None:
        for key in ("payload", "data", "content", "json"):
            nested = mapping.get(key)
            if isinstance(nested, (Mapping, list)):
                return _unwrap(cast("object", nested))
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
    return unwrapped


def _select_from_aliases(
    src_map: Mapping[str, object],
    aliases: Sequence[str],
    artifact: str,
    source: object,
) -> object:
    for key in aliases:
        if key in src_map:
            value = src_map[key]
            selected = _value_payload(value, artifact=artifact)
            if selected is not value or isinstance(selected, Path):
                return selected
            if isinstance(selected, list):
                return cast("list[object]", selected)
            if isinstance(selected, Mapping) and selected is not source:
                return cast("Mapping[str, object]", selected)
    return None


def _select_artifact(
    source: object, *, artifact: str, version: str | None = None
) -> object:
    del version
    if not isinstance(source, Mapping):
        return source
    src_map = cast("Mapping[str, object]", source)
    stem = artifact.removesuffix(".json")
    aliases = (
        artifact,
        stem,
        stem.replace("-live", ""),
        "leaderboard" if "leaderboard" in stem else "trials",
    )
    artifacts = _as_mapping(src_map.get("artifacts"))
    if artifacts is not None:
        for key in aliases:
            if key in artifacts:
                return _value_payload(artifacts[key], artifact=artifact)
    selected = _select_from_aliases(src_map, aliases, artifact, cast("object", source))
    if selected is not None:
        return selected
    path = _first(
        src_map,
        f"{stem}_path",
        f"{stem.replace('-', '_')}_path",
        "leaderboard_path" if "leaderboard" in stem else "trials_path",
    )
    if path is not None:
        return _value_payload(path, artifact=artifact)
    # A direct artifact object commonly has rows/data at its top level.
    return src_map


def _rows(
    value: object, *, trials: bool = False, normalize: bool | None = None
) -> list[dict[str, object]]:
    should_normalize = not trials if normalize is None else normalize
    unwrapped = _unwrap(value)
    if isinstance(unwrapped, list):
        rows: list[dict[str, object]] = [
            {str(k): v for k, v in cast("Mapping[object, object]", row).items()}
            for row in cast("list[object]", unwrapped)
            if isinstance(row, Mapping)
        ]
        return normalize_rows(rows, source_path="$.rows") if should_normalize else rows
    mapping = _as_mapping(unwrapped)
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
            rows = [
                {str(k): v for k, v in cast("Mapping[object, object]", row).items()}
                for row in cast("list[object]", candidate)
                if isinstance(row, Mapping)
            ]
            return (
                normalize_rows(rows, source_path=f"$.{key}")
                if should_normalize
                else rows
            )
        if isinstance(candidate, Mapping):
            nested = _rows(
                cast("Mapping[str, object]", candidate),
                trials=trials,
                normalize=should_normalize,
            )
            if nested:
                return nested
    if any(key in mapping for key in ("model", "config", "pass_at_1", "trial_id")):
        rows = [
            {str(k): v for k, v in cast("Mapping[object, object]", mapping).items()}
        ]
        return normalize_rows(rows, source_path="$") if should_normalize else rows
    return []


def _context_payload(payload: object, *, artifact: str) -> object:
    """Normalize leaderboard payloads while preserving raw trial payloads."""
    if artifact == "trials.json":
        return payload
    if isinstance(payload, Mapping):
        return normalize_payload(cast("Mapping[str, object]", payload))
    if isinstance(payload, Sequence) and not isinstance(
        payload, (str, bytes, bytearray)
    ):
        return normalize_payload(cast("Sequence[Mapping[str, object]]", payload))
    return normalize_payload(None)


def _fetch_context(
    args: argparse.Namespace, *, artifact: str, include_trials: bool
) -> dict[str, object]:
    raw_version = cast("object", getattr(args, "version", "latest"))
    version_str = str(raw_version) if isinstance(raw_version, str) else "latest"
    version, resolved = _resolve(version_str)

    raw_out = cast("object", getattr(args, "output_dir", None))
    output_dir = (
        raw_out
        if isinstance(raw_out, Path)
        else (
            Path(str(raw_out)).expanduser()
            if isinstance(raw_out, str) and raw_out
            else _default_output_dir()
        )
    )

    raw_cache = cast("object", getattr(args, "cache_dir", None))
    cache_dir = (
        raw_cache
        if isinstance(raw_cache, Path)
        else (
            Path(str(raw_cache)).expanduser()
            if isinstance(raw_cache, str) and raw_cache
            else _default_cache_dir()
        )
    )

    raw_timeout = cast("object", getattr(args, "timeout", 30.0))
    timeout = (
        float(raw_timeout)
        if isinstance(raw_timeout, (int, float)) and not isinstance(raw_timeout, bool)
        else 30.0
    )

    allow_stale = bool(cast("object", getattr(args, "allow_stale", False)))
    try:
        source = fetch_artifacts(
            version,
            output_dir=output_dir,
            cache_dir=cache_dir,
            include_trials=include_trials,
            timeout=timeout,
            allow_stale=allow_stale,
        )
    except CliError:
        raise
    except Exception as exc:
        raise CliError(_exception_code(exc), str(exc)) from exc
    payload = _select_artifact(source, artifact=artifact, version=version)
    return {
        "source": source,
        "payload": _context_payload(payload, artifact=artifact),
        "version": _version_from(source, version) or version,
        "resolved": resolved,
        "artifact": artifact,
        "snapshot": None,
    }


def _snapshot_context(args: argparse.Namespace, *, artifact: str) -> dict[str, object]:
    path_value = cast("object", getattr(args, "snapshot", None))
    if path_value is None:
        cmd_val = cast("object", getattr(args, "command", "command"))
        message = f"{cmd_val} requires --snapshot when loading a local artifact"
        raise CliUsageError(message)
    path = (
        path_value
        if isinstance(path_value, Path)
        else Path(str(path_value)).expanduser()
    )
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
    requested_val = cast("object", getattr(args, "version", "latest"))
    requested = str(requested_val) if isinstance(requested_val, str) else "latest"
    if version is None:
        code = "version"
        message = (
            "snapshot must declare benchmark_version in payload metadata or "
            + "include a concrete version component in its path"
        )
        raise CliError(code, message)
    if requested and requested != "latest":
        expected, _ = _resolve(requested)
        if version != expected:
            code = "mixed_version"
            message = (
                f"snapshot benchmark version {version!r} does not match "
                + f"requested {expected!r}"
            )
            raise CliError(code, message)
    selected = _select_artifact(payload, artifact=artifact, version=version)
    return {
        "source": raw,
        "payload": _context_payload(selected, artifact=artifact),
        "version": version,
        "resolved": {"benchmark_version": version},
        "snapshot": True,
        "artifact": artifact,
        "snapshot_path": path,
    }


def _context(
    args: argparse.Namespace, *, artifact: str, include_trials: bool
) -> dict[str, object]:
    if getattr(args, "snapshot", None) is not None:
        return _snapshot_context(args, artifact=artifact)
    return _fetch_context(args, artifact=artifact, include_trials=include_trials)


def _quality_filters(args: argparse.Namespace) -> dict[str, object]:
    filters: dict[str, object] = {"quality_exclusion": "none"}
    for name, key in (
        ("min_pass_at_1", "min_pass_at_1"),
        ("min_attempted", "min_attempted"),
        ("min_tasks", "min_tasks"),
    ):
        value = cast("object", getattr(args, name, None))
        if value is not None:
            filters[key] = value
    if len(filters) > 1:
        filters["quality_exclusion"] = "explicit_thresholds"
    pareto_axes = cast("object", getattr(args, "pareto_axis", None))
    efficiencies = cast("object", getattr(args, "efficiency", None))
    if pareto_axes is not None:
        filters["pareto_axes"] = pareto_axes
    if efficiencies is not None:
        filters["efficiency"] = efficiencies
    if bool(getattr(args, "strict_semantics", False)):
        filters["strict_semantics"] = True
    if bool(getattr(args, "strict_duplicates", False)):
        filters["strict_duplicates"] = True
    if pareto_axes is not None or efficiencies is not None:
        filters["analysis_options"] = "explicit"
    return filters


def _analysis_result(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        val_map = cast("Mapping[object, object]", value)
        return {str(k): v for k, v in val_map.items()}
    return {"result": value}


def _handle_fetch(args: argparse.Namespace) -> dict[str, object]:
    is_trials = bool(getattr(args, "trials", False))
    context = _fetch_context(
        args,
        artifact="trials.json" if is_trials else "leaderboard-live.json",
        include_trials=is_trials,
    )
    source = context["source"]
    data = _fetch_output(source)
    artifact = str(context["artifact"])
    filters: dict[str, object]
    status: str
    if is_trials:
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
        version=str(context["version"]) if context.get("version") is not None else None,
        filters=filters,
        value_status=status,
        source=source,
        payload=context["payload"],
        artifact=artifact,
    )


def _handle_report(args: argparse.Namespace) -> dict[str, object]:
    context = _context(args, artifact="leaderboard-live.json", include_trials=False)
    min_pass = cast("Real | None", getattr(args, "min_pass_at_1", None))
    min_att = cast("Real | None", getattr(args, "min_attempted", None))
    min_tsk = cast("Real | None", getattr(args, "min_tasks", None))
    lim = cast("int | None", getattr(args, "limit", None))
    p_axes = cast(
        "Sequence[str | Mapping[str, object]] | None",
        getattr(args, "pareto_axis", None),
    )
    eff_specs = cast(
        "Sequence[str | Mapping[str, object]] | None",
        getattr(args, "efficiency", None),
    )
    strict_sem = bool(getattr(args, "strict_semantics", False))
    raw_payload = context["payload"]
    payload_arg: Mapping[str, object] | Sequence[Mapping[str, object]] | None = None
    if isinstance(raw_payload, Mapping):
        payload_arg = cast("Mapping[str, object]", raw_payload)
    elif isinstance(raw_payload, Sequence) and not isinstance(
        raw_payload, (str, bytes, bytearray)
    ):
        payload_arg = cast("Sequence[Mapping[str, object]]", raw_payload)
    try:
        result = build_report(
            payload_arg,
            min_pass_at_1=min_pass,
            min_attempted=min_att,
            min_tasks=min_tsk,
            limit=lim,
            pareto_axes=p_axes,
            efficiency_specs=eff_specs,
            strict_semantics=strict_sem,
        )
    except Exception as exc:
        raise CliError(_exception_code(exc), str(exc)) from exc
    filters: dict[str, object] = {
        "artifact": "leaderboard-live.json",
        **_quality_filters(args),
    }
    snap = context.get("snapshot_path")
    snap_path = snap if isinstance(snap, Path) else None
    return _with_scope(
        _analysis_result(result),
        command="report",
        version=str(context["version"]) if context.get("version") is not None else None,
        filters=filters,
        value_status="derived",
        source=context["source"],
        payload=context["payload"],
        artifact=str(context["artifact"]),
        snapshot=snap_path,
    )


def _fetch_output(source: object) -> dict[str, object]:
    """Project fetch metadata without dumping the optional raw trial payload."""
    if not isinstance(source, Mapping):
        return {"artifacts": source}
    src_map = cast("Mapping[object, object]", source)
    data: dict[str, object] = {str(k): v for k, v in src_map.items()}
    artifacts = data.get("artifacts")
    if isinstance(artifacts, Mapping):
        art_map = cast("Mapping[object, object]", artifacts)
        projected: dict[str, object] = {}
        for name, value in art_map.items():
            if isinstance(value, Mapping):
                val_map = cast("Mapping[object, object]", value)
                projected[str(name)] = {
                    str(key): item
                    for key, item in val_map.items()
                    if key
                    not in {"data", "payload", "raw", "body", "raw_body", "raw_bytes"}
                }
            else:
                projected[str(name)] = value
        data["artifacts"] = projected
    for key in ("payloads", "leaderboard", "trials"):
        _ = data.pop(key, None)
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
        merged = (
            {str(k): v for k, v in cast("Mapping[object, object]", existing).items()}
            if isinstance(existing, Mapping)
            else {}
        )
        merged.update(unknown)
        data["raw_metadata"] = merged
        for key in unknown:
            _ = data.pop(key, None)
    return data


def _handle_rank(args: argparse.Namespace) -> dict[str, object]:
    context = _context(args, artifact="leaderboard-live.json", include_trials=False)
    metric_opt = cast("str | None", getattr(args, "metric_opt", None))
    metric_pos = cast("str | None", getattr(args, "metric_pos", None))
    metric = metric_opt or metric_pos or "pass_at_1"
    order = str(getattr(args, "order", "desc"))
    min_pass = cast("Real | None", getattr(args, "min_pass_at_1", None))
    min_att = cast("Real | None", getattr(args, "min_attempted", None))
    min_tsk = cast("Real | None", getattr(args, "min_tasks", None))
    lim = cast("int | None", getattr(args, "limit", None))
    strict_sem = bool(getattr(args, "strict_semantics", False))
    strict_dup = bool(getattr(args, "strict_duplicates", False))
    rows = _rows(context["payload"])
    try:
        result = rank_rows(
            rows,
            metric,
            order,
            min_pass_at_1=min_pass,
            min_attempted=min_att,
            min_tasks=min_tsk,
            limit=lim,
            strict_semantics=strict_sem,
            strict_duplicates=strict_dup,
        )
    except Exception as exc:
        raise CliError(_exception_code(exc), str(exc)) from exc
    filters: dict[str, object] = {
        "artifact": "leaderboard-live.json",
        "metric": metric,
        "order": order,
        **_quality_filters(args),
    }
    snap = context.get("snapshot_path")
    snap_path = snap if isinstance(snap, Path) else None
    return _with_scope(
        _analysis_result(result),
        command="rank",
        version=str(context["version"]) if context.get("version") is not None else None,
        filters=filters,
        value_status="derived",
        source=context["source"],
        payload=context["payload"],
        artifact=str(context["artifact"]),
        snapshot=snap_path,
    )


def _handle_trials(args: argparse.Namespace) -> dict[str, object]:
    context = _context(args, artifact="trials.json", include_trials=True)
    rows = _rows(context["payload"], trials=True)
    source_val = str(getattr(args, "source", "deep-swe"))
    eval_scope_val = str(getattr(args, "eval_scope", "full"))
    included_only_val = bool(getattr(args, "included_only", True))
    limit_val = cast("int | None", getattr(args, "limit", None))
    try:
        result = filter_trials(
            rows,
            source=source_val,
            eval_scope=eval_scope_val,
            included_only=included_only_val,
            limit=limit_val,
        )
    except Exception as exc:
        raise CliError(_exception_code(exc), str(exc)) from exc
    filters: dict[str, object] = {
        "artifact": "trials.json",
        "source": source_val,
        "eval_scope": eval_scope_val,
        "included_in_score": included_only_val,
    }
    snap = context.get("snapshot_path")
    snap_path = snap if isinstance(snap, Path) else None
    return _with_scope(
        _analysis_result(result),
        command="trials",
        version=str(context["version"]) if context.get("version") is not None else None,
        filters=filters,
        value_status="published_raw",
        source=context["source"],
        payload=context["payload"],
        artifact=str(context["artifact"]),
        snapshot=snap_path,
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
    rows: Sequence[Mapping[str, object]], *, strict_semantics: bool = False
) -> dict[str, object]:
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
                evidence = (
                    cast("Mapping[str, object]", metrics).get(field)
                    if isinstance(metrics, Mapping)
                    else None
                )
                if isinstance(evidence, Mapping):
                    evidence_map = cast("Mapping[str, object]", evidence)
                    value = evidence_map.get("normalized_value")
                    if evidence_map.get("comparison_eligibility") != "eligible":
                        reasons = evidence_map.get("blocked_reasons")
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
    result: dict[str, object] = {
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


def _handle_stats(args: argparse.Namespace) -> dict[str, object]:
    is_trials = bool(getattr(args, "trials", False))
    artifact = "trials.json" if is_trials else "leaderboard-live.json"
    context = _context(args, artifact=artifact, include_trials=is_trials)
    payload = context["payload"]
    strict_sem = bool(getattr(args, "strict_semantics", False))
    source_val = str(getattr(args, "source", "deep-swe"))
    eval_scope_val = str(getattr(args, "eval_scope", "full"))
    included_only_val = bool(getattr(args, "included_only", True))
    limit_val = cast("int | None", getattr(args, "limit", None))

    result: dict[str, object]
    status: str
    payload_map = _as_mapping(payload)
    if (
        payload_map is not None
        and isinstance(payload_map.get("stats"), Mapping)
        and not is_trials
        and not strict_sem
    ):
        stats_map = cast("Mapping[object, object]", payload_map["stats"])
        result = {str(k): v for k, v in stats_map.items()}
        status = "published"
    elif is_trials:
        rows = _rows(
            payload,
            trials=True,
            normalize=strict_sem,
        )
        try:
            filtered = filter_trials(
                rows,
                source=source_val,
                eval_scope=eval_scope_val,
                included_only=included_only_val,
                limit=limit_val,
            )
        except Exception as exc:
            raise CliError(_exception_code(exc), str(exc)) from exc
        selected = _rows(filtered, trials=True, normalize=False)
        result = _stats_for_rows(selected, strict_semantics=strict_sem)
        result["input_count"] = filtered.get("input_count", len(rows))
        result["matched_count"] = filtered.get("matched_count", len(selected))
        status = "published_raw"
    else:
        rows = _rows(payload)
        result = _stats_for_rows(rows, strict_semantics=strict_sem)
        status = "derived"
    filters: dict[str, object] = {
        "artifact": artifact,
        "source": source_val if is_trials else "published leaderboard",
        "eval_scope": eval_scope_val if is_trials else None,
        "included_in_score": included_only_val if is_trials else None,
    }
    if strict_sem:
        filters["strict_semantics"] = True
    filters = {key: value for key, value in filters.items() if value is not None}
    snap = context.get("snapshot_path")
    snap_path = snap if isinstance(snap, Path) else None
    return _with_scope(
        result,
        command="stats",
        version=str(context["version"]) if context.get("version") is not None else None,
        filters=filters,
        value_status=status,
        source=context["source"],
        payload=payload,
        artifact=artifact,
        snapshot=snap_path,
    )


def _diagnose_metadata(
    context: Mapping[str, object], *, artifact: str
) -> tuple[Mapping[str, object] | None, Path | None]:
    source = context.get("source")
    if isinstance(source, Mapping):
        source_map = cast("Mapping[str, object]", source)
        artifacts = source_map.get("artifacts")
        if isinstance(artifacts, Mapping):
            art_map = cast("Mapping[str, object]", artifacts)
            candidate = art_map.get(artifact)
            if isinstance(candidate, Mapping):
                cand_map = cast("Mapping[str, object]", candidate)
                local_path = cand_map.get("local_path")
                path = (
                    Path(str(local_path)).expanduser()
                    if isinstance(local_path, (str, Path))
                    else None
                )
                return cand_map, path
        return source_map, None
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
        for group in groups:
            group_map = cast("Mapping[str, object]", group)
            indexes = group_map.get("row_indexes")
            row_indexes = (
                sorted(
                    int(index)
                    for index in indexes
                    if isinstance(index, (int, float, str))
                )
                if isinstance(indexes, Sequence)
                and not isinstance(indexes, (str, bytes, bytearray))
                else []
            )
            identity = group_map.get("identity")
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


def _handle_diagnose(args: argparse.Namespace) -> dict[str, object]:
    is_trials = bool(getattr(args, "trials", False))
    artifact = "trials.json" if is_trials else "leaderboard-live.json"
    context = _context(args, artifact=artifact, include_trials=is_trials)
    metadata, materialized_path = _diagnose_metadata(context, artifact=artifact)
    snapshot = context.get("snapshot_path")
    source_path = snapshot if isinstance(snapshot, Path) else materialized_path
    version = context.get("version")
    expected_version = version if isinstance(version, str) else None
    try:
        result_diag = diagnose_payload(
            context["payload"],
            artifact_name=artifact,
            expected_version=expected_version,
            path=source_path,
            metadata=metadata,
        )
    except Exception as exc:
        raise CliError(_exception_code(exc), str(exc)) from exc
    result = dict(result_diag)
    duplicate_report, duplicate_diagnostics = _diagnose_duplicates(
        context["payload"], trials=is_trials
    )
    result["duplicate_report"] = duplicate_report
    if duplicate_diagnostics:
        existing_diags = result.get("diagnostics")
        diags_list = (
            [
                cast("Mapping[str, object]", item)
                for item in existing_diags
                if isinstance(item, Mapping)
            ]
            if isinstance(existing_diags, Sequence)
            and not isinstance(existing_diags, (str, bytes, bytearray))
            else []
        )
        result["diagnostics"] = merge_diagnostics(diags_list, duplicate_diagnostics)
    filters: dict[str, object] = {
        "artifact": artifact,
        "operation": "diagnose",
        "trials_explicit": is_trials,
    }
    status = "published_raw" if is_trials else "published"
    snap_path = snapshot if isinstance(snapshot, Path) else None
    return _with_scope(
        result,
        command="diagnose",
        version=expected_version,
        filters=filters,
        value_status=status,
        source=context["source"],
        payload=context["payload"],
        artifact=artifact,
        snapshot=snap_path,
    )


def _schema_data(version: str) -> dict[str, object]:
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
            "artifact_base": ARTIFACT_BASE,
            "benchmark_version": version,
        },
        "report_options": {
            "pareto_axis": "repeatable METRIC:ORDER; omitted uses default axes",
            "efficiency": "repeatable NAME=NUMERATOR/DENOMINATOR; derived only",
        },
    }


def _handle_schema(args: argparse.Namespace) -> dict[str, object]:
    raw_ver = cast("object", getattr(args, "version", "latest"))
    version, _ = _resolve(str(raw_ver) if isinstance(raw_ver, str) else "latest")
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
    snapshots = getattr(args, "snapshots", None)
    if isinstance(snapshots, Sequence) and not isinstance(
        snapshots, (str, bytes, bytearray)
    ):
        values.extend(snap for snap in snapshots if isinstance(snap, (str, Path)))
    left_opt = getattr(args, "left_opt", None)
    if left_opt is not None and isinstance(left_opt, (str, Path)):
        values.append(left_opt)
    right_opt = getattr(args, "right_opt", None)
    if right_opt is not None and isinstance(right_opt, (str, Path)):
        values.append(right_opt)
    left_pos = getattr(args, "left_pos", None)
    if left_pos is not None and isinstance(left_pos, (str, Path)):
        values.append(left_pos)
    right_pos = getattr(args, "right_pos", None)
    if right_pos is not None and isinstance(right_pos, (str, Path)):
        values.append(right_pos)
    if len(values) != EXPECTED_SNAPSHOT_COUNT:
        message = "compare requires exactly two snapshots (left and right)"
        raise CliUsageError(message)
    return Path(values[0]).expanduser(), Path(values[1]).expanduser()


def _safe_compare_identity(value: object) -> str:
    """Keep comparison diagnostics free of anonymous row bodies."""
    if not isinstance(value, str):
        return "<anonymous>"
    try:
        parsed = cast("object", json.loads(value))
    except (TypeError, ValueError):
        return "<anonymous>"
    if isinstance(parsed, list):
        parsed_list = cast("list[object]", parsed)
        if len(parsed_list) == IDENTITY_COMPONENT_COUNT:
            return json.dumps(parsed_list, ensure_ascii=False, separators=(",", ":"))
        if len(parsed_list) == LEGACY_IDENTITY_COMPONENT_COUNT and parsed_list[2] != [
            "published_id",
            "row",
        ]:
            return json.dumps(parsed_list, ensure_ascii=False, separators=(",", ":"))
    return "<anonymous>"


def _safe_compare_diagnostics(
    diagnostics: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Project kernel diagnostics without exposing duplicate row signatures."""
    safe: list[dict[str, object]] = []
    for item in diagnostics:
        projected: dict[str, object] = dict(item)
        details = item.get("details")
        if isinstance(details, Mapping):
            details_copy: dict[str, object] = {
                str(k): v for k, v in cast("Mapping[object, object]", details).items()
            }
            if "identity" in details_copy:
                details_copy["identity"] = _safe_compare_identity(
                    details_copy["identity"]
                )
            _ = details_copy.pop("signatures", None)
            _ = details_copy.pop("rows", None)
            projected["details"] = details_copy
        safe.append(projected)
    return merge_diagnostics(safe)


def _duplicate_facts_for_compare(
    rows: Sequence[Mapping[str, object]],
    *,
    identity_rows: Sequence[Mapping[str, object]] | None = None,
) -> tuple[
    dict[str, Mapping[str, object]],
    dict[str, list[dict[str, object]]],
    list[dict[str, object]],
]:
    """Select the first row per canonical identity and retain duplicate facts."""
    identity_source = rows if identity_rows is None else identity_rows
    report = classify_duplicates(identity_source)
    selected: dict[str, Mapping[str, object]] = {}
    for row in rows:
        identity = identity_json(canonical_identity(row))
        _ = selected.setdefault(identity, row)
    projected: dict[str, list[dict[str, object]]] = {
        "identical": [],
        "conflicting": [],
    }
    diagnostics: list[dict[str, object]] = []
    for bucket, bucket_groups in projected.items():
        groups = report.get(bucket, bucket_groups)
        for group in groups:
            group_map = cast("Mapping[str, object]", group)
            indexes = group_map.get("row_indexes")
            row_indexes = (
                sorted(
                    int(index)
                    for index in indexes
                    if isinstance(index, (int, float, str))
                )
                if isinstance(indexes, Sequence)
                and not isinstance(indexes, (str, bytes, bytearray))
                else []
            )
            identity = _safe_compare_identity(group_map.get("identity"))
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
    val_map = cast("Mapping[str, object]", value)
    candidates: list[Mapping[str, object]] = [val_map]
    for key in ("metadata", "scope", "provenance", "artifact", "data", "payload"):
        nested = val_map.get(key)
        if isinstance(nested, Mapping):
            candidates.append(cast("Mapping[str, object]", nested))
    return candidates


def _artifact_schema_declaration(value: object) -> object:
    declarations: list[object] = []
    for candidate in _metadata_candidates(value):
        decl = candidate.get("artifact_schema_version")
        if decl is not None:
            declarations.append(decl)
        for key in ("artifact_schema_version", "schema_version"):
            if key in candidate and candidate[key] is not None:
                schema = candidate.get("artifact_schema")
                if isinstance(schema, Mapping):
                    schema_map = cast("Mapping[str, object]", schema)
                    ver = schema_map.get("version")
                    if ver is not None:
                        declarations.append(ver)
    unique = {
        json.dumps(item, sort_keys=True, separators=(",", ":")): item
        for item in declarations
    }
    if len(unique) == 1:
        return next(iter(unique.values()))
    if len(unique) > 1:
        return "conflicting"
    return None


def _semantic_projection(value: object, metric: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    val_map = cast("Mapping[str, object]", value)
    candidates: list[Mapping[str, object]] = [val_map]
    for key in ("metric_semantics", "semantics", "metrics"):
        nested = val_map.get(key)
        if isinstance(nested, Mapping):
            nested_map = cast("Mapping[str, object]", nested)
            cand_obj = (
                nested_map.get(metric)
                if key in ("metric_semantics", "metrics")
                else nested_map
            )
            if isinstance(cand_obj, Mapping):
                candidates.append(cast("Mapping[str, object]", cand_obj))
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
    row: Mapping[str, object] | None,
    metric: str,
    *,
    strict_semantics: bool,
) -> tuple[float | int | None, list[str]]:
    if row is None:
        return None, ["MISSING_ROW"]
    if strict_semantics:
        metrics = row.get("metrics")
        evidence = (
            cast("Mapping[str, object]", metrics).get(metric)
            if isinstance(metrics, Mapping)
            else None
        )
        if isinstance(evidence, Mapping):
            evidence_map = cast("Mapping[str, object]", evidence)
            reasons = evidence_map.get("blocked_reasons")
            blockers = (
                [str(reason) for reason in reasons]
                if isinstance(reasons, Sequence)
                and not isinstance(reasons, (str, bytes, bytearray))
                else []
            )
            if evidence_map.get("comparison_eligibility") != "eligible":
                return None, blockers or ["COMPARISON_INCOMPARABLE"]
            value = _numeric(evidence_map.get("normalized_value"))
            return (value, []) if value is not None else (None, ["UNPARSED_VALUE"])
        return None, ["MISSING_REQUIRED_INPUT"]
    return _numeric(row.get(metric)), []


def _legacy_compare(
    left: object,
    right: object,
    *,
    metric: str,
    strict_semantics: bool,
) -> tuple[dict[str, object], list[dict[str, object]]]:
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
    changes: list[dict[str, object]] = []
    for key in keys:
        before, before_reasons = _comparison_numeric(
            left_map.get(key), metric, strict_semantics=strict_semantics
        )
        after, after_reasons = _comparison_numeric(
            right_map.get(key), metric, strict_semantics=strict_semantics
        )
        delta = after - before if before is not None and after is not None else None
        change: dict[str, object] = {
            "config": key,
            "before": before,
            "after": after,
            "delta": delta,
        }
        if strict_semantics:
            change["blocked_reasons"] = sorted(set(before_reasons + after_reasons))
        changes.append(change)

    def change_sort_key(row: Mapping[str, object]) -> tuple[bool, float, str]:
        delta_val = row.get("delta")
        delta_num = (
            float(delta_val)
            if isinstance(delta_val, (int, float)) and not isinstance(delta_val, bool)
            else None
        )
        return (
            delta_num is None,
            -(abs(delta_num) if delta_num is not None else 0.0),
            str(row.get("config", "")),
        )

    changes.sort(key=change_sort_key)
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
    result: dict[str, object] = {
        "changes": changes,
        "duplicate_report": duplicate_report,
        "left_count": len(left_rows),
        "right_count": len(right_rows),
    }
    return result, diagnostics


def _strict_snapshot(
    value: object,
) -> Mapping[str, object] | Sequence[Mapping[str, object]]:
    """Add normalized rows while preserving every snapshot metadata field."""
    if isinstance(value, Mapping):
        val_map = cast("Mapping[object, object]", value)
        projected: dict[str, object] = {str(k): v for k, v in val_map.items()}
        selected = _select_artifact(
            cast("object", value), artifact="leaderboard-live.json"
        )
        projected["rows"] = _rows(selected, normalize=True)
        return projected
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            {str(k): v for k, v in cast("Mapping[object, object]", item).items()}
            for item in value
            if isinstance(item, Mapping)
        ]
    return {}


def _handle_compare(  # noqa: C901, PLR0912, PLR0915
    args: argparse.Namespace,
) -> dict[str, object]:
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
            + "version component in their paths"
        )
        raise CliError(msg, detail)
    if left_version != right_version:
        msg = "mixed_version"
        detail = (
            f"snapshots use different benchmark versions: {left_version!r} "
            + f"and {right_version!r}"
        )
        raise CliError(msg, detail)
    requested = cast("object", getattr(args, "version", "latest"))
    if requested and requested != "latest":
        expected, _ = _resolve(str(requested))
        if expected != left_version:
            msg = "mixed_version"
            detail = (
                f"snapshot version {left_version!r} does not match "
                + f"requested {expected!r}"
            )
            raise CliError(msg, detail)

    strict_semantics = bool(getattr(args, "strict_semantics", False))
    strict_compare = bool(getattr(args, "strict_compare", False))
    strict_mode = strict_compare
    metric = str(getattr(args, "metric", "pass_at_1"))
    limit_val = cast("int | None", getattr(args, "limit", 10))
    limit = limit_val if limit_val is not None else 10

    result: dict[str, object]
    if strict_mode:
        left_snap = _strict_snapshot(left)
        right_snap = _strict_snapshot(right)
        diff = dict(
            compare_snapshots(
                left_snap,
                right_snap,
                metric,
            )
        )
        result = dict(diff)
        _ = result.setdefault(
            "left_count",
            len(_rows(_select_artifact(left, artifact="leaderboard-live.json"))),
        )
        _ = result.setdefault(
            "right_count",
            len(_rows(_select_artifact(right, artifact="leaderboard-live.json"))),
        )
        diagnostics_value = result.get("diagnostics", [])
        if isinstance(diagnostics_value, Sequence) and not isinstance(
            diagnostics_value, (str, bytes, bytearray)
        ):
            result["diagnostics"] = _safe_compare_diagnostics(
                [
                    cast("Mapping[str, object]", item)
                    for item in diagnostics_value
                    if isinstance(item, Mapping)
                ]
            )
        changes_val = result.get("changes")
        if isinstance(changes_val, list):
            changes_list = [
                cast("Mapping[str, object]", item)
                for item in cast("list[object]", changes_val)
                if isinstance(item, Mapping)
            ]

            def diff_change_sort_key(
                row: Mapping[str, object],
            ) -> tuple[bool, float, str]:
                delta_val = row.get("delta")
                delta_num = (
                    float(delta_val)
                    if isinstance(delta_val, (int, float))
                    and not isinstance(delta_val, bool)
                    else None
                )
                return (
                    delta_num is None,
                    -(abs(delta_num) if delta_num is not None else 0.0),
                    str(row.get("config", "")),
                )

            result["changes"] = sorted(changes_list, key=diff_change_sort_key)[:limit]
        result["strict_compare"] = strict_compare
        if strict_semantics:
            result["strict_semantics"] = True
    else:
        result, diagnostics = _legacy_compare(
            left,
            right,
            metric=metric,
            strict_semantics=strict_semantics,
        )
        if diagnostics:
            result["diagnostics"] = diagnostics
            result["warnings"] = [
                item for item in diagnostics if item.get("severity") == "warning"
            ]
        if strict_semantics:
            result["strict_semantics"] = True
        changes_val = result.get("changes")
        if isinstance(changes_val, list):
            result["changes"] = cast("list[object]", changes_val)[:limit]

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
    filters: dict[str, object] = {
        "left_snapshot": str(left_path),
        "right_snapshot": str(right_path),
        "metric": metric,
    }
    if strict_semantics:
        filters["strict_semantics"] = True
    if strict_compare:
        filters["strict_compare"] = True
    return _with_scope(
        {
            "metric": metric,
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


def _dispatch(args: argparse.Namespace) -> dict[str, object]:
    handlers: dict[str, Callable[[argparse.Namespace], dict[str, object]]] = {
        "fetch": _handle_fetch,
        "report": _handle_report,
        "rank": _handle_rank,
        "trials": _handle_trials,
        "stats": _handle_stats,
        "schema": _handle_schema,
        "diagnose": _handle_diagnose,
        "compare": _handle_compare,
    }
    cmd = getattr(args, "command", None)
    if not isinstance(cmd, str):
        message = "a command is required"
        raise CliUsageError(message)
    handler = handlers.get(cmd)
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
        if getattr(args, "command", None) is None:
            message = "a command is required"
            raise CliUsageError(message)  # noqa: TRY301
        cmd_val = getattr(args, "command", None)
        command = str(cmd_val) if isinstance(cmd_val, str) else command
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
