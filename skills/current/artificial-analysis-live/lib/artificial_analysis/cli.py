# ruff: noqa: ANN401, C901, CPY001, D103, FBT003, PERF401, PLR0911, PLR0912, PLR0915
"""Command-line and RPC interfaces for Artificial Analysis snapshots."""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import NoReturn, TextIO
from .contracts import compact_json
from .diagnose import diagnose
from .diagnostics import redact, redact_query
from .diff import schema_aware_diff
from .overlap import overlap_metadata
from .rsc import (
    BASE_URL,
    CODING_CAPABILITY_URL,
    MODEL_API_KEY_ENV,
    MODEL_API_URL,
    CacheError,
    ExtractionError,
    FetchResult,
    atomic_write,
    build_full_url,
    build_snapshot_payload,
    endpoint_slugs,
    extract_evaluation_rows,
    extract_lists,
    fetch_models,
    fetch_page,
    fetch_rsc,
    load_cache_metadata,
    load_cached_artifact,
    load_last_good_snapshot,
    load_snapshot,
    normalize_official_models,
    parse_json_frames,
    parse_next_payload,
    sanity_check,
    save_cache,
    save_last_good_snapshot,
    snapshot_slugs,
    write_outputs,
)
from .values import parse_numeric

PROTOCOL_VERSION = "1"

DEFAULT_ARTIFACT_DIR = Path(tempfile.gettempdir()) / "artifacts" / "artificial-analysis"
DEFAULT_OUTPUT_JSON = DEFAULT_ARTIFACT_DIR / "full-data.json"
DEFAULT_OUTPUT_ENDPOINTS = DEFAULT_ARTIFACT_DIR / "endpoints.txt"
DEFAULT_OUTPUT_URL = DEFAULT_ARTIFACT_DIR / "full-url.txt"
DEFAULT_CODING_OUTPUT_JSON = DEFAULT_ARTIFACT_DIR / "coding-data.json"
DEFAULT_SNAPSHOT_MAX_AGE = timedelta(hours=24)
MIN_QUOTED_VALUE_LENGTH = 2
SCHEMA_V2 = 2
NOT_MODIFIED = 304


def _finite_number(value: object) -> bool:
    """Return whether value is a rankable, non-boolean finite scalar."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _numeric_scalar(value: object) -> bool:
    """Recognize numeric values including non-finite values for evidence."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def _evidence_record(  # noqa: PLR0913
    raw_value: object,
    *,
    source_path: str | None,
    source_field: str | None,
    artifact_hash: str | None = None,
    value_status: str = "published",
    semantics: str = "known",
    unit: str | None = None,
    normalization: str | None = None,
    blocked_reasons: tuple[str, ...] = (),
    formula: str | None = None,
    input_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Project ``values.parse_numeric`` into the additive CLI evidence shape."""
    parsed = parse_numeric(
        raw_value,
        unit=unit,
        normalization=normalization,
        source_path=source_path,
        source_field=source_field,
        value_status=value_status,
        metric_semantics_status=semantics,
        blocked_reasons=blocked_reasons,
        parser="artificial-analysis.cli",
        parser_version="1",
        sha256=artifact_hash,
    )
    evidence = parsed.to_dict()
    if value_status == "derived" and evidence.get("normalized_value") is None:
        # ``parse_numeric`` classifies a null/raw-unparseable value as missing
        # or unparsed.  A declared derived path still describes provenance as
        # derived; only its usability is unavailable.
        reasons = [
            reason
            for reason in evidence.get("blocked_reasons", [])
            if reason not in {"missing_value", "unparsed_value"}
        ]
        if "MISSING_REQUIRED_INPUT" not in reasons:
            reasons.append("MISSING_REQUIRED_INPUT")
        evidence["value_status"] = "derived"
        evidence["comparison_eligibility"] = "blocked"
        evidence["blocked_reasons"] = reasons
    # Keep the values.py names and expose the concise contract aliases.  This
    # lets old consumers use source_field/value_status while new consumers can
    # inspect field/status without a translation table.
    evidence.update(
        {
            "raw": evidence.get("raw_value"),
            "normalized": evidence.get("normalized_value"),
            "field": evidence.get("source_field"),
            "version": evidence.get("parser_version"),
            "artifact_hash": evidence.get("sha256"),
            "status": evidence.get("value_status"),
            "semantics": evidence.get("metric_semantics_status"),
            "eligibility": evidence.get("comparison_eligibility"),
            "blockers": list(evidence.get("blocked_reasons") or []),
        },
    )
    if formula is not None:
        evidence["formula"] = formula
        evidence["input_paths"] = list(input_paths)
    return evidence


def _lookup_path(row: dict[str, Any], path: str) -> object:
    current: object = row
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _source_hash_from_payload(payload: dict[str, Any]) -> str | None:
    for container_key in ("source", "meta"):
        container = payload.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in ("sha256", "artifact_hash", "source_hash"):
            value = container.get(key)
            if isinstance(value, str) and value:
                return value
        nested = container.get("source")
        if isinstance(nested, dict):
            value = nested.get("sha256")
            if isinstance(value, str) and value:
                return value
    return None


def _attach_row_evidence(  # noqa: PLR0913
    row: dict[str, Any],
    *,
    metric_paths: tuple[str, ...] = (),
    source_prefix: str = "$",
    artifact_hash: str | None = None,
    derived_paths: dict[str, tuple[str, tuple[str, ...]]] | None = None,
    raw_values: dict[str, object] | None = None,
    unknown_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Attach evidence for source and derived scalars without changing values."""
    evidence = row.get("metric_evidence")
    metric_evidence = dict(evidence) if isinstance(evidence, dict) else {}
    derived_paths = derived_paths or {}
    raw_values = raw_values or {}
    unknown_set = set(unknown_paths)

    def add(path: str, value: object, *, unknown: bool = False) -> None:
        if path in metric_evidence:
            return
        formula_and_inputs = derived_paths.get(path)
        if formula_and_inputs is not None:
            formula, input_paths = formula_and_inputs
            metric_evidence[path] = _evidence_record(
                value,
                source_path=f"{source_prefix}.{path}",
                source_field=path.rsplit(".", 1)[-1],
                artifact_hash=artifact_hash,
                value_status="derived",
                semantics="known",
                formula=formula,
                input_paths=input_paths,
            )
            return
        metric_evidence[path] = _evidence_record(
            raw_values.get(path, value),
            source_path=f"{source_prefix}.{path}",
            source_field=path.rsplit(".", 1)[-1],
            artifact_hash=artifact_hash,
            semantics="unknown" if (unknown or path in unknown_set) else "known",
        )

    for path in metric_paths:
        add(
            path,
            _lookup_path(row, path),
            unknown=path.startswith(("raw_fields.", "unknowns.")),
        )

    def walk(node: object, prefix: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"metric_evidence", "raw_metadata"}:
                    continue
                path = f"{prefix}.{key}" if prefix else key
                if _numeric_scalar(value):
                    add(
                        path,
                        value,
                        unknown=prefix.startswith(("raw_fields", "unknowns")),
                    )
                elif isinstance(value, dict):
                    walk(value, path)
                elif isinstance(value, list):
                    for index, item in enumerate(value):
                        walk(item, f"{path}[{index}]")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{prefix}[{index}]")

    walk(row, "")
    row["metric_evidence"] = metric_evidence
    return row


def _attach_payload_evidence(
    payload: dict[str, Any],
    *,
    artifact_hash: str | None = None,
) -> dict[str, Any]:
    """Attach evidence for payload-level derived scalar fields."""
    existing = payload.get("metric_evidence")
    metric_evidence = dict(existing) if isinstance(existing, dict) else {}

    def walk(node: object, prefix: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"metric_evidence", "raw_metadata"}:
                    continue
                path = f"{prefix}.{key}" if prefix else key
                if _numeric_scalar(value):
                    if path not in metric_evidence:
                        metric_evidence[path] = _evidence_record(
                            value,
                            source_path=f"$.{path}",
                            source_field=key,
                            artifact_hash=artifact_hash,
                            value_status="derived",
                        )
                elif isinstance(value, (dict, list)):
                    walk(value, path)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{prefix}[{index}]")

    walk(payload, "")
    payload["metric_evidence"] = metric_evidence
    return payload


def _snapshot_overlap(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Expose declarations without inventing overlap from source similarity."""
    if not isinstance(snapshot, dict):
        return overlap_metadata()
    meta = snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {}
    source = snapshot.get("overlap")
    if not isinstance(source, dict):
        source = meta.get("overlap") if isinstance(meta.get("overlap"), dict) else {}
    declarations = source.get("declared_joins", source.get("overlap_claims"))
    left = source.get("left")
    right = source.get("right")
    dependencies = source.get("dependencies", meta.get("dependencies", []))
    independence = source.get("independence", meta.get("independence", []))
    return overlap_metadata(
        left=left,
        right=right,
        declarations=declarations,
        dependencies=dependencies if isinstance(dependencies, list) else [],
        independence=independence if isinstance(independence, list) else [],
    )


class CliUsageError(RuntimeError):
    """Raised when agent-provided command inputs are invalid."""


def _raise_cli_usage_error(message: str) -> NoReturn:
    raise CliUsageError(message)


def _raise_extraction_error(
    message: str,
    cause: BaseException | None = None,
) -> NoReturn:
    if cause is None:
        raise ExtractionError(message)
    raise ExtractionError(message) from cause


def _default_cache_dir() -> Path:
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg_cache) if xdg_cache else Path.home() / ".cache"
    return base / "artificial-analysis"


def _parse_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}

    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (
            len(value) >= MIN_QUOTED_VALUE_LENGTH
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        values[key] = value
    return values


def _dotenv_candidates() -> list[Path]:
    candidates: list[Path] = []
    if configured_path := os.environ.get("ARTIFICIAL_ANALYSIS_ENV_FILE"):
        candidates.append(Path(configured_path).expanduser())

    skill_root = Path(__file__).resolve().parents[2]
    candidates.append(skill_root / ".env")
    if skills_dir := os.environ.get("SKILLS_DIR"):
        candidates.append(
            Path(skills_dir).expanduser() / "artificial-analysis-live" / ".env",
        )

    for ancestor in (Path.cwd(), *Path.cwd().parents):
        candidate = ancestor / "skills" / "artificial-analysis-live" / ".env"
        if candidate.exists():
            candidates.append(candidate)
            break
    return candidates


def _load_dotenv() -> None:
    if os.environ.get(MODEL_API_KEY_ENV):
        return
    for path in _dotenv_candidates():
        for key, value in _parse_env_file(path).items():
            os.environ.setdefault(key, value)
        if os.environ.get(MODEL_API_KEY_ENV):
            return


def _required_api_key() -> str:
    _load_dotenv()
    api_key = os.environ.get(MODEL_API_KEY_ENV)
    if not api_key:
        message = (
            "ARTIFICIAL_ANALYSIS_API_KEY required; inject it in the process or set "
            "ARTIFICIAL_ANALYSIS_ENV_FILE to a permissions-restricted external file."
        )
        _raise_cli_usage_error(message)
    return api_key


def _add_cli_error_flags(
    parser: argparse.ArgumentParser, *, suppress_defaults: bool = False
) -> None:
    default = argparse.SUPPRESS if suppress_defaults else False
    parser.add_argument(
        "--json-errors",
        action="store_true",
        default=default,
        help="Emit one compact JSON error object on stdout.",
    )
    parser.add_argument(
        "--legacy-errors",
        action="store_true",
        default=default,
        help="Keep human-readable stderr errors instead of JSON errors.",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for CLI mode."""
    parser = argparse.ArgumentParser(
        prog="artificial-analysis",
        description=(
            "AI-first extractor for Artificial Analysis provider endpoint data."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("cli", "rpc"),
        default="cli",
        help="cli: one-shot JSON output. rpc: JSONL request/response loop.",
    )
    _add_cli_error_flags(parser)
    subparsers = parser.add_subparsers(dest="command")
    _add_fetch_parser(subparsers)
    _add_stats_parser(subparsers)
    _add_diff_parser(subparsers)
    _add_diagnose_parser(subparsers)
    _add_harness_parser(subparsers)
    _add_coding_parser(subparsers)
    _add_evaluation_parser(subparsers)
    _add_reasoning_parser(subparsers)
    _add_query_parser(subparsers)
    _add_qa_parser(subparsers)
    _add_schema_parser(subparsers)
    for command_parser in subparsers.choices.values():
        _add_cli_error_flags(command_parser, suppress_defaults=True)
    return parser


def _add_fetch_parser(subparsers: argparse._SubParsersAction) -> None:
    fetch_parser = subparsers.add_parser(
        "fetch",
        help=(
            "Fetch live RSC and authenticated official model data, then write "
            "a snapshot."
        ),
    )
    fetch_parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    fetch_parser.add_argument(
        "--output-endpoints",
        type=Path,
        default=DEFAULT_OUTPUT_ENDPOINTS,
    )
    fetch_parser.add_argument("--output-url", type=Path, default=DEFAULT_OUTPUT_URL)
    fetch_parser.add_argument("--cache-dir", type=Path, default=_default_cache_dir())
    fetch_parser.add_argument("--timeout-seconds", type=float, default=60.0)
    fetch_parser.add_argument("--min-endpoints", type=int, default=700)
    fetch_parser.add_argument("--min-providers", type=int, default=40)
    fetch_parser.add_argument(
        "--stale-policy",
        choices=("error", "allow-last-good"),
        default="error",
        help="Refresh failure policy; stale fallback is opt-in.",
    )
    fetch_parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="Alias for --stale-policy allow-last-good.",
    )
    fetch_parser.add_argument(
        "--strict",
        action="store_true",
        help="Alias for --stale-policy error.",
    )
    fetch_parser.set_defaults(handler=_handle_fetch)


def _add_stats_parser(subparsers: argparse._SubParsersAction) -> None:
    stats_parser = subparsers.add_parser(
        "stats",
        help="Show snapshot counts and top providers.",
    )
    stats_parser.add_argument(
        "snapshot",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
    )
    stats_parser.add_argument("--top", type=int, default=10)
    stats_parser.set_defaults(handler=_handle_stats)


def _add_diff_parser(subparsers: argparse._SubParsersAction) -> None:
    diff_parser = subparsers.add_parser(
        "diff",
        help="Diff endpoint and provider changes between snapshots.",
    )
    diff_parser.add_argument("old_snapshot", type=Path)
    diff_parser.add_argument("new_snapshot", type=Path)
    diff_parser.add_argument(
        "--schema-aware",
        action="store_true",
        help="Include deterministic model, metric, schema, and diagnostic changes.",
    )
    diff_parser.set_defaults(handler=_handle_diff)


def _add_diagnose_parser(subparsers: argparse._SubParsersAction) -> None:
    diagnose_parser = subparsers.add_parser(
        "diagnose",
        help="Inspect local snapshot/cache health without fetching.",
    )
    diagnose_parser.add_argument("snapshot", nargs="?", type=Path)
    diagnose_parser.add_argument("--snapshot", dest="snapshot_path", type=Path)
    diagnose_parser.add_argument("--cache-dir", type=Path, default=None)
    diagnose_parser.set_defaults(handler=_handle_diagnose)


def _add_model_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model slug/name contains filter.",
    )
    parser.add_argument(
        "--creator",
        type=str,
        default=None,
        help="Creator/lab name contains filter.",
    )
    parser.add_argument(
        "--open-weights-only",
        action="store_true",
        help="Return only open-weights models.",
    )


def _add_harness_parser(subparsers: argparse._SubParsersAction) -> None:
    harness_parser = subparsers.add_parser(
        "harness",
        help="Rank unique models by Harness = 50%% Agentic Index + 50%% Coding Index.",
    )
    harness_parser.add_argument(
        "snapshot",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
    )
    _add_model_filters(harness_parser)
    harness_parser.add_argument("--limit", type=int, default=50)
    harness_parser.set_defaults(handler=_handle_harness)


def _add_order(parser: argparse.ArgumentParser, *, default: str) -> None:
    parser.add_argument(
        "--order",
        type=str,
        default=default,
        choices=("auto", "asc", "desc"),
    )


def _add_coding_parser(subparsers: argparse._SubParsersAction) -> None:
    coding_parser = subparsers.add_parser(
        "coding",
        help=(
            "Fetch/query Coding Index capability rows, including coding-only "
            "output token composition."
        ),
    )
    coding_parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_CODING_OUTPUT_JSON,
    )
    coding_parser.add_argument("--timeout-seconds", type=float, default=60.0)
    _add_model_filters(coding_parser)
    coding_parser.add_argument(
        "--sort-by",
        type=str,
        default="coding",
        choices=(
            "coding",
            "output_tokens",
            "answer_tokens",
            "reasoning_tokens",
            "input_tokens",
            "cost",
        ),
    )
    _add_order(coding_parser, default="auto")
    coding_parser.add_argument("--limit", type=int, default=50)
    coding_parser.add_argument(
        "--include-benchmark-counts",
        action="store_true",
        help="Include per-benchmark token counts for Coding Index components.",
    )
    coding_parser.set_defaults(handler=_handle_coding)


def _add_evaluation_parser(subparsers: argparse._SubParsersAction) -> None:
    evaluation_parser = subparsers.add_parser(
        "evaluation",
        help="Extract model rows from a dedicated Artificial Analysis evaluation page.",
    )
    evaluation_parser.add_argument("url", nargs="?", help="public evaluation page URL")
    evaluation_parser.add_argument(
        "--input",
        type=Path,
        help="read a saved HTML/RSC response instead of fetching a URL",
    )
    evaluation_parser.add_argument("--output-json", type=Path)
    evaluation_parser.add_argument("--timeout-seconds", type=float, default=60.0)
    evaluation_parser.add_argument("--min-rows", type=int, default=1)
    evaluation_parser.add_argument("--sort-by", type=str)
    evaluation_parser.add_argument(
        "--order",
        choices=("auto", "asc", "desc"),
        default="auto",
    )
    evaluation_parser.add_argument("--limit", type=int)
    evaluation_parser.set_defaults(handler=_handle_evaluation)


def _add_reasoning_parser(subparsers: argparse._SubParsersAction) -> None:
    reasoning_parser = subparsers.add_parser(
        "reasoning",
        help=(
            "Profile models by reasoning selectivity (per-benchmark answer vs "
            "thinking token split)."
        ),
    )
    reasoning_parser.add_argument(
        "snapshot",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
    )
    _add_model_filters(reasoning_parser)
    reasoning_parser.add_argument(
        "--class",
        type=str,
        default=None,
        dest="classification",
        choices=(
            "selective_extreme",
            "selective",
            "moderate",
            "uniform_heavy",
            "hard_uniform_heavy",
        ),
        help="Filter by reasoning selectivity classification.",
    )
    reasoning_parser.add_argument(
        "--selective-only",
        action="store_true",
        help="Return only selective thinkers (classification starts with selective).",
    )
    reasoning_parser.add_argument(
        "--sort-by",
        type=str,
        default="harness",
        choices=(
            "harness",
            "selectivity",
            "reasoning_floor",
            "weighted_reasoning_share",
            "intelligence",
            "agentic",
            "coding",
        ),
    )
    _add_order(reasoning_parser, default="auto")
    reasoning_parser.add_argument("--limit", type=int, default=50)
    reasoning_parser.add_argument(
        "--benchmarks",
        action="store_true",
        help="Include per-benchmark reasoning share breakdown in each row.",
    )
    reasoning_parser.set_defaults(handler=_handle_reasoning)


def _add_query_parser(subparsers: argparse._SubParsersAction) -> None:
    query_parser = subparsers.add_parser(
        "query",
        help="Query model/provider benchmark rows from a snapshot.",
    )
    query_parser.add_argument(
        "snapshot",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
    )
    query_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model slug/name contains filter.",
    )
    query_parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Provider slug/name contains filter.",
    )
    query_parser.add_argument(
        "--endpoint",
        type=str,
        default=None,
        help="Endpoint slug contains filter.",
    )
    query_parser.add_argument(
        "--sort-by",
        type=str,
        default="intelligence",
        choices=(
            "harness",
            "intelligence",
            "agentic",
            "coding",
            "math",
            "price_blended",
            "speed",
            "ttfc",
            "e2e",
        ),
    )
    _add_order(query_parser, default="auto")
    query_parser.add_argument("--limit", type=int, default=20)
    query_parser.set_defaults(handler=_handle_query)


def _add_qa_parser(subparsers: argparse._SubParsersAction) -> None:
    qa_parser = subparsers.add_parser(
        "qa",
        help="Minimal NL question command that maps intent to query filters/sort.",
    )
    qa_parser.add_argument(
        "question",
        type=str,
        help="Natural-language question about models/providers.",
    )
    qa_parser.add_argument(
        "snapshot",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
    )
    qa_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override inferred model filter.",
    )
    qa_parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Override inferred provider filter.",
    )
    qa_parser.add_argument(
        "--sort-by",
        type=str,
        default=None,
        choices=(
            "harness",
            "intelligence",
            "agentic",
            "coding",
            "math",
            "price_blended",
            "speed",
            "ttfc",
            "e2e",
        ),
        help="Override inferred sort metric.",
    )
    qa_parser.add_argument(
        "--order",
        type=str,
        default=None,
        choices=("asc", "desc"),
        help="Override inferred order.",
    )
    qa_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Override inferred result limit.",
    )
    qa_parser.set_defaults(handler=_handle_qa)


def _add_schema_parser(subparsers: argparse._SubParsersAction) -> None:
    schema_parser = subparsers.add_parser(
        "schema",
        help="Print machine-readable capability schema.",
    )
    schema_parser.set_defaults(handler=_handle_schema)


def _normalize_argv(argv: Sequence[str] | None) -> list[str]:
    """Normalize optional global mode and default fetch arguments."""
    values = list(argv) if argv is not None else sys.argv[1:]
    if not values:
        return ["fetch"]

    known_subcommands = {
        "fetch",
        "stats",
        "diff",
        "diagnose",
        "harness",
        "coding",
        "evaluation",
        "reasoning",
        "query",
        "qa",
        "schema",
    }
    if any(token in known_subcommands for token in values):
        return values
    if any(token in {"-h", "--help"} for token in values):
        return values

    global_prefix: list[str] = []
    index = 0
    while index < len(values):
        argument = values[index]
        if argument == "--mode" and index + 1 < len(values):
            global_prefix.extend(values[index : index + 2])
            index += 2
            continue
        if argument.startswith("--mode="):
            global_prefix.append(argument)
            index += 1
            continue
        break

    return [*global_prefix, "fetch", *values[index:]]


def _emit_json(payload: dict[str, Any], *, stdout: TextIO) -> None:
    stdout.write(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n",
    )


def _safe_error_text(value: object) -> str:
    redacted = redact(str(value))
    text = redacted if isinstance(redacted, str) else str(redacted)
    text = re.sub(
        r"(?i)(?<![a-z0-9])[\w.-]*(?:api[-_ ]?key|secret|password|token)[\w.-]*",
        "[REDACTED]",
        text,
    )
    return text[:512]


def _emit_cli_error(
    *,
    command: str,
    code: str,
    message: object,
    stdout: TextIO,
    details: object | None = None,
) -> None:
    error: dict[str, object] = {
        "code": code,
        "message": _safe_error_text(message),
    }
    if details is not None:
        error["details"] = redact(details)
    payload: dict[str, Any] = {
        "ok": False,
        "version": PROTOCOL_VERSION,
        "command": command,
        "error": error,
    }
    stdout.write(compact_json(payload) + "\n")


def _envelope(command: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "version": PROTOCOL_VERSION,
        "command": command,
        "data": data,
    }


def _ensure_default_snapshot_fresh(path: Path, snapshot: dict[str, Any]) -> None:
    if path != DEFAULT_OUTPUT_JSON:
        return

    meta = snapshot.get("meta")
    fetched_at = meta.get("fetched_at") if isinstance(meta, dict) else None
    if not isinstance(fetched_at, str) or not fetched_at:
        message = (
            f"Default snapshot missing meta.fetched_at: {path}. "
            "Run fetch first or pass an explicit snapshot path."
        )
        _raise_extraction_error(message)

    try:
        fetched_at_dt = datetime.fromisoformat(fetched_at)
    except ValueError as exc:
        message = (
            f"Default snapshot has invalid meta.fetched_at: {path}. "
            "Run fetch first or pass an explicit snapshot path."
        )
        _raise_extraction_error(message, exc)

    if fetched_at_dt.tzinfo is None:
        fetched_at_dt = fetched_at_dt.replace(tzinfo=UTC)
    age = datetime.now(UTC) - fetched_at_dt.astimezone(UTC)
    if age > DEFAULT_SNAPSHOT_MAX_AGE:
        message = (
            f"Default snapshot is stale ({fetched_at}, older than 24h): {path}. "
            "Run fetch first or pass an explicit snapshot path."
        )
        _raise_extraction_error(message)


def _load_reader_snapshot(path: Path) -> dict[str, Any]:
    snapshot = load_snapshot(path)
    _ensure_default_snapshot_fresh(path, snapshot)
    return snapshot


def _schema_version(snapshot: dict[str, Any]) -> int:
    meta = snapshot.get("meta")
    return (
        meta.get("schema_version")
        if isinstance(meta, dict) and isinstance(meta.get("schema_version"), int)
        else 1
    )


def _canonical_models(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if _schema_version(snapshot) < SCHEMA_V2:
        return {}
    models = snapshot.get("models")
    if not isinstance(models, list):
        _raise_extraction_error("Schema-v2 snapshot missing models list")
    return {
        slug: item
        for item in models
        if isinstance(item, dict) and isinstance(slug := item.get("slug"), str) and slug
    }


def _model_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    canonical = _canonical_models(snapshot)
    if canonical:
        return list(canonical.values())
    hosts_models = snapshot.get("hosts_models")
    if not isinstance(hosts_models, list):
        _raise_extraction_error("Snapshot missing hosts_models list")
    return [
        model
        for item in hosts_models
        if isinstance(item, dict)
        and isinstance(model := item.get("model"), dict)
        and isinstance(model.get("slug"), str)
    ]


def _creator(model: dict[str, Any]) -> dict[str, Any]:
    creator = model.get("creator")
    if isinstance(creator, dict):
        return creator
    legacy_creator = model.get("model_creators")
    return legacy_creator if isinstance(legacy_creator, dict) else {}


def _artifact_record_metadata(record: dict[str, object]) -> dict[str, object]:
    nested = record.get("metadata")
    return nested if isinstance(nested, dict) else {}


def _cached_source_info(cache_dir: Path) -> tuple[bytes, dict[str, object]] | None:
    cached = load_cached_artifact(cache_dir, source_key=BASE_URL)
    if cached is not None:
        return cached
    return None


def _result_headers(result: object) -> dict[str, str]:
    headers = getattr(result, "headers", None)
    return headers if isinstance(headers, dict) else {}


def _result_header(result: object, name: str) -> str | None:
    headers = _result_headers(result)
    value = headers.get(name)
    if isinstance(value, str) and value:
        return value
    folded_name = name.casefold()
    for key, candidate in headers.items():
        if isinstance(key, str) and key.casefold() == folded_name:
            return candidate if isinstance(candidate, str) and candidate else None
    return None


def _result_fetched_at(result: object) -> str:
    value = getattr(result, "fetched_at", None)
    return value if isinstance(value, str) else ""


def _result_etag(result: object) -> str | None:
    value = getattr(result, "etag", None)
    if isinstance(value, str) and value:
        return value
    return _result_header(result, "etag")


def _result_last_modified(result: object) -> str | None:
    value = getattr(result, "last_modified", None)
    if isinstance(value, str) and value:
        return value
    return _result_header(result, "last-modified")


def _result_final_url(result: object, fallback: str | None = None) -> str | None:
    value = getattr(result, "final_url", None)
    return value if isinstance(value, str) and value else fallback


def _result_sha256(result: object) -> str | None:
    value = getattr(result, "sha256", None)
    if isinstance(value, str) and value:
        return value
    body = getattr(result, "body", None)
    if isinstance(body, str):
        return hashlib.sha256(body.encode("utf-8")).hexdigest()
    return None


def _result_byte_length(result: object) -> int | None:
    value = getattr(result, "byte_length", None)
    if isinstance(value, int):
        return value
    body = getattr(result, "body", None)
    if isinstance(body, str):
        return len(body.encode("utf-8"))
    return None


def _result_artifact_ref(result: object) -> str | None:
    value = getattr(result, "artifact_ref", None)
    return value if isinstance(value, str) and value else None


def _materialize_fetch_result(
    result: object,
    *,
    fallback_url: str,
) -> FetchResult:
    if isinstance(result, FetchResult):
        return result
    body = getattr(result, "body", None)
    status_code = getattr(result, "status_code", None)
    fetched_at = _result_fetched_at(result)
    if not isinstance(body, str) or not isinstance(status_code, int):
        message = "FetchResult compatibility object is missing base fields"
        raise TypeError(message)
    return FetchResult(
        body=body,
        status_code=status_code,
        headers=_result_headers(result),
        fetched_at=fetched_at,
        final_url=_result_final_url(result, fallback_url),
        etag=_result_etag(result),
        last_modified=_result_last_modified(result),
        sha256=_result_sha256(result),
        byte_length=_result_byte_length(result),
        artifact_ref=_result_artifact_ref(result),
    )


def _validator_from(
    cache_meta: object,
    record: dict[str, object] | None,
    name: str,
) -> str | None:
    value: object = None
    if record is not None:
        value = _artifact_record_metadata(record).get(name)
    if not isinstance(value, str) and cache_meta is not None:
        value = getattr(cache_meta, name, None)
    return value if isinstance(value, str) and value else None


def _validate_304(
    result: FetchResult,
    cached: tuple[bytes, dict[str, object]] | None,
    *,
    sent_etag: str | None,
    sent_last_modified: str | None,
) -> FetchResult:
    if cached is None:
        _raise_cache_failure(
            "CACHE_MISSING",
            "Upstream returned 304 but no matching cached artifact exists.",
        )
    raw, record = cached
    cached_etag = _validator_from(None, record, "etag") or sent_etag
    cached_last_modified = (
        _validator_from(None, record, "last_modified") or sent_last_modified
    )
    response_etag = _result_etag(result)
    response_last_modified = _result_last_modified(result)
    if (
        response_etag is not None
        and cached_etag is not None
        and response_etag != cached_etag
    ) or (
        response_last_modified is not None
        and cached_last_modified is not None
        and response_last_modified != cached_last_modified
    ):
        _raise_cache_failure(
            "CACHE_VALIDATOR_INVALID",
            "Upstream returned a validator that does not match cached bytes.",
            {
                "etag_sent": sent_etag,
                "etag_received": response_etag,
                "last_modified_sent": sent_last_modified,
                "last_modified_received": response_last_modified,
            },
        )
    if not any(
        (
            response_etag,
            response_last_modified,
            cached_etag,
            cached_last_modified,
        ),
    ):
        _raise_cache_failure(
            "CACHE_VALIDATOR_INVALID",
            "Upstream returned 304 without a returned or known validator.",
        )
    body = raw.decode("utf-8", errors="replace")
    digest = hashlib.sha256(raw).hexdigest()
    return FetchResult(
        body=body,
        status_code=NOT_MODIFIED,
        headers=dict(_result_headers(result)),
        fetched_at=_result_fetched_at(result),
        final_url=_result_final_url(result),
        last_modified=response_last_modified or cached_last_modified,
        sha256=digest,
        byte_length=len(raw),
        artifact_ref=(
            str(record.get("raw_path")) if record.get("raw_path") is not None else None
        ),
    )


def _raise_cache_failure(
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> NoReturn:
    raise CacheError(code, message, details)


def _stale_allowed(args: argparse.Namespace) -> bool:
    if bool(getattr(args, "strict", False)):
        return False
    return bool(getattr(args, "allow_stale", False)) or (
        getattr(args, "stale_policy", "error") == "allow-last-good"
    )


def _mark_stale_payload(
    fallback_payload: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    payload = copy.deepcopy(fallback_payload)
    meta = payload.setdefault("meta", {})
    if not isinstance(meta, dict):
        meta = {}
        payload["meta"] = meta
    meta["freshness"] = {
        "mode": "stale-last-good",
        "stale": True,
        "fallback": True,
        "reason": reason,
    }
    meta["freshness_mode"] = "stale-last-good"
    return payload


def _fetch_payload(args: argparse.Namespace) -> dict[str, Any]:
    api_key = _required_api_key()
    cache_meta = load_cache_metadata(args.cache_dir)
    cached = _cached_source_info(args.cache_dir)
    cached_record = cached[1] if cached is not None else None
    sent_etag = _validator_from(cache_meta, cached_record, "etag")
    sent_last_modified = _validator_from(cache_meta, cached_record, "last_modified")
    result: FetchResult | None = None
    official_result: FetchResult | None = None
    response_etag: str | None = sent_etag
    response_last_modified: str | None = sent_last_modified
    reused_cached_body = False
    fallback_used = False
    fallback_source: str | None = None
    fallback_reason: str | None = None
    freshness = "fresh"

    try:
        result = fetch_rsc(
            timeout_seconds=args.timeout_seconds,
            if_none_match=sent_etag,
            if_modified_since=sent_last_modified,
        )
        result = _materialize_fetch_result(result, fallback_url=BASE_URL)
        if result.status_code == NOT_MODIFIED:
            result = _validate_304(
                result,
                cached,
                sent_etag=sent_etag,
                sent_last_modified=sent_last_modified,
            )
            reused_cached_body = True
            freshness = "cache-revalidated"
        response_etag = _result_etag(result) or sent_etag
        response_last_modified = _result_last_modified(result) or sent_last_modified
        official_result = _materialize_fetch_result(
            fetch_models(api_key, timeout_seconds=args.timeout_seconds),
            fallback_url=(
                os.environ.get("ARTIFICIAL_ANALYSIS_API_BASE_URL") or MODEL_API_URL
            ),
        )
        body = result.body
        frames = parse_json_frames(body)
        models, hosts, hosts_models = extract_lists(frames)
        official_models = normalize_official_models(official_result.body)
        slugs = endpoint_slugs(hosts_models)
        sanity_check(
            slugs=slugs,
            min_endpoints=args.min_endpoints,
            min_providers=args.min_providers,
        )
        payload = build_snapshot_payload(
            models=models,
            hosts=hosts,
            hosts_models=hosts_models,
            frame_count=len(frames),
            rsc_result=result,
            rsc_etag=response_etag,
            rsc_reused_cached_payload=reused_cached_body,
            official_result=official_result,
            official_models=official_models,
            rsc_freshness=freshness,
        )
    except (ExtractionError, OSError) as exc:
        if not _stale_allowed(args):
            raise
        fallback_reason = str(exc)
        fallback_payload = load_last_good_snapshot(args.cache_dir)
        fallback_source = "cache:last-good"
        if fallback_payload is None and args.output_json.exists():
            try:
                fallback_payload = load_snapshot(args.output_json)
            except ExtractionError:
                fallback_payload = None
            else:
                fallback_source = f"file:{args.output_json}"
        if fallback_payload is None:
            message = f"Fresh fetch failed and no last-good snapshot exists ({exc})."
            _raise_extraction_error(message, exc)
        slugs = snapshot_slugs(fallback_payload)
        sanity_check(
            slugs=slugs,
            min_endpoints=args.min_endpoints,
            min_providers=args.min_providers,
        )
        payload = _mark_stale_payload(fallback_payload, reason=fallback_reason)
        freshness = "stale-last-good"
        fallback_used = True

    full_url = build_full_url(slugs)
    write_outputs(
        output_json=args.output_json,
        output_endpoints=args.output_endpoints,
        output_url=args.output_url,
        payload=payload,
        slugs=slugs,
        full_url=full_url,
    )

    if not fallback_used and result is not None:
        save_cache(
            cache_dir=args.cache_dir,
            fetched_at=_result_fetched_at(result),
            status_code=result.status_code,
            etag=response_etag,
            last_modified=response_last_modified,
            body=None if result.status_code == NOT_MODIFIED else result.body,
            source_url=BASE_URL,
            final_url=_result_final_url(result),
            headers=_result_headers(result),
        )
        save_last_good_snapshot(args.cache_dir, payload)

    rsc_source: dict[str, object] = {
        "url": redact_query(BASE_URL),
        "final_url": (
            redact_query(_result_final_url(result, BASE_URL))
            if result is not None
            else None
        ),
        "status_code": result.status_code if result is not None else None,
        "etag_sent": sent_etag,
        "etag_received": response_etag,
        "last_modified_sent": sent_last_modified,
        "last_modified_received": response_last_modified,
        "sha256": _result_sha256(result) if result is not None else None,
        "byte_length": _result_byte_length(result) if result is not None else None,
        "artifact_ref": _result_artifact_ref(result) if result is not None else None,
        "reused_cached_payload": reused_cached_body,
        "freshness": freshness,
    }
    api_url = redact_query(
        os.environ.get("ARTIFICIAL_ANALYSIS_API_BASE_URL") or MODEL_API_URL,
    )
    official_source: dict[str, object] = {
        "url": api_url,
        "final_url": (
            redact_query(
                _result_final_url(
                    official_result,
                    os.environ.get("ARTIFICIAL_ANALYSIS_API_BASE_URL") or MODEL_API_URL,
                ),
            )
            if official_result is not None
            else None
        ),
        "status_code": official_result.status_code
        if official_result is not None
        else None,
        "etag_received": (
            _result_etag(official_result) if official_result is not None else None
        ),
        "last_modified_received": (
            _result_last_modified(official_result)
            if official_result is not None
            else None
        ),
        "sha256": (
            _result_sha256(official_result) if official_result is not None else None
        ),
        "byte_length": (
            _result_byte_length(official_result)
            if official_result is not None
            else None
        ),
        "artifact_ref": (
            _result_artifact_ref(official_result)
            if official_result is not None
            else None
        ),
        "reused_cached_payload": False,
        "freshness": freshness if fallback_used else "fresh",
    }

    return {
        "sources": {"rsc": rsc_source, "official_api": official_source},
        "counts": payload.get("meta", {}).get("counts", {}),
        "freshness": {
            "mode": freshness,
            "stale": freshness == "stale-last-good",
            "fallback": fallback_used,
        },
        "outputs": {
            "json": str(args.output_json),
            "endpoints": str(args.output_endpoints),
            "url": str(args.output_url),
        },
        "cache": {"dir": str(args.cache_dir)},
        "fallback": {
            "used": fallback_used,
            "source": fallback_source,
            "reason": fallback_reason,
            "strict": bool(getattr(args, "strict", False)),
            "policy": ("allow-last-good" if _stale_allowed(args) else "error"),
        },
    }


def _stats_payload(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = _load_reader_snapshot(args.snapshot)
    slugs = snapshot_slugs(snapshot)
    providers = _provider_counts_from_snapshot(snapshot)
    top = sorted(providers.items(), key=lambda item: (-item[1], item[0]))[
        : max(args.top, 0)
    ]

    payload: dict[str, Any] = {
        "snapshot": str(args.snapshot),
        "counts": {
            "models": len(snapshot.get("models", []))
            if isinstance(snapshot.get("models"), list)
            else 0,
            "hosts": len(snapshot.get("hosts", []))
            if isinstance(snapshot.get("hosts"), list)
            else 0,
            "hosts_models": len(snapshot.get("hosts_models", []))
            if isinstance(snapshot.get("hosts_models"), list)
            else 0,
            "endpoint_slugs": len(slugs),
            "providers": len(providers),
        },
        "top_providers": [
            {"provider": name, "endpoints": count} for name, count in top
        ],
        "overlap": _snapshot_overlap(snapshot),
    }
    return _attach_payload_evidence(payload)


def _diff_payload(args: argparse.Namespace) -> dict[str, Any]:
    old_snapshot = load_snapshot(args.old_snapshot)
    new_snapshot = load_snapshot(args.new_snapshot)

    old_slugs = set(snapshot_slugs(old_snapshot))
    new_slugs = set(snapshot_slugs(new_snapshot))

    added = sorted(new_slugs - old_slugs)
    removed = sorted(old_slugs - new_slugs)

    old_provider_counts = _provider_counts_from_snapshot(old_snapshot)
    new_provider_counts = _provider_counts_from_snapshot(new_snapshot)

    provider_deltas: list[dict[str, Any]] = []
    for provider in sorted(set(old_provider_counts) | set(new_provider_counts)):
        before = old_provider_counts.get(provider, 0)
        after = new_provider_counts.get(provider, 0)
        delta = after - before
        if delta != 0:
            provider_deltas.append(
                {
                    "provider": provider,
                    "before": before,
                    "after": after,
                    "delta": delta,
                },
            )

    payload: dict[str, Any] = {
        "old_snapshot": _safe_error_text(args.old_snapshot),
        "new_snapshot": _safe_error_text(args.new_snapshot),
        "counts": {
            "old_endpoints": len(old_slugs),
            "new_endpoints": len(new_slugs),
            "added": len(added),
            "removed": len(removed),
            "provider_deltas": len(provider_deltas),
        },
        "added_endpoint_slugs": added,
        "removed_endpoint_slugs": removed,
        "provider_deltas": provider_deltas,
        "overlap": _snapshot_overlap(new_snapshot),
    }
    if bool(getattr(args, "schema_aware", False)):
        payload["schema_diff"] = schema_aware_diff(old_snapshot, new_snapshot)
    return _attach_payload_evidence(payload)


def _diagnose_payload(args: argparse.Namespace) -> dict[str, Any]:
    snapshot_path = getattr(args, "snapshot_path", None) or getattr(
        args, "snapshot", None
    )
    cache_dir = getattr(args, "cache_dir", None)
    return diagnose(snapshot_path=snapshot_path, cache_dir=cache_dir)


def _coding_payload(args: argparse.Namespace) -> dict[str, Any]:
    result = _materialize_fetch_result(
        fetch_rsc(url=CODING_CAPABILITY_URL, timeout_seconds=args.timeout_seconds),
        fallback_url=CODING_CAPABILITY_URL,
    )
    frames = parse_json_frames(result.body)
    models = _extract_default_data_models(frames)

    model_filter = (
        args.model.lower() if isinstance(args.model, str) and args.model else None
    )
    creator_filter = (
        args.creator.lower() if isinstance(args.creator, str) and args.creator else None
    )

    rows: list[dict[str, Any]] = []
    for model_index, model in enumerate(models):
        if not isinstance(model, dict) or model.get("deleted"):
            continue

        model_slug = model.get("slug") if isinstance(model.get("slug"), str) else None
        model_name = model.get("name") if isinstance(model.get("name"), str) else None
        short_name = _first_string(model, "short_name", "shortName") or model_name
        creator = _first_dict(model, "model_creators", "modelCreator")
        creator_name = (
            _first_string(creator, "name") if isinstance(creator, dict) else None
        )
        coding_score = _first_number(model, "coding_index", "headlineValue")

        if model_filter and not _matches_any(
            model_filter,
            [model_slug, model_name, short_name],
        ):
            continue
        if creator_filter and not _matches_any(
            creator_filter,
            [
                creator_name,
                creator.get("slug") if isinstance(creator, dict) else None,
            ],
        ):
            continue
        is_open_weights = _first_bool(model, "is_open_weights", "isOpenWeights")
        if args.open_weights_only and is_open_weights is not True:
            continue

        token_counts = (
            model.get("tokenCounts")
            if isinstance(model.get("tokenCounts"), dict)
            else {}
        )
        task_output = (
            model.get("outputTokensPerTask")
            if isinstance(model.get("outputTokensPerTask"), dict)
            else {}
        )
        eval_cost = (
            model.get("evalCost") if isinstance(model.get("evalCost"), dict) else {}
        )
        task_cost = (
            model.get("costPerTask")
            if isinstance(model.get("costPerTask"), dict)
            else {}
        )
        is_current = "headlineValue" in model

        answer_tokens = _number_alias(token_counts, "answerTokens", "answer")
        reasoning_tokens = _number_alias(token_counts, "reasoningTokens", "reasoning")
        output_tokens = _number_alias(token_counts, "outputTokens", "output")
        input_tokens = _number_alias(token_counts, "inputTokens", "input")
        if is_current:
            answer_tokens = _number_alias(task_output, "answer")
            reasoning_tokens = _number_alias(task_output, "reasoning")
            output_tokens = _number_alias(task_output, "output")
            input_tokens = None

        published_answer_share = _number_alias(
            token_counts,
            "answer_share_of_output",
            "answerShareOfOutput",
        )
        published_reasoning_share = _number_alias(
            token_counts,
            "reasoning_share_of_output",
            "reasoningShareOfOutput",
        )
        answer_share = (
            published_answer_share
            if _finite_number(published_answer_share)
            else _share(answer_tokens, output_tokens)
        )
        reasoning_share = (
            published_reasoning_share
            if _finite_number(published_reasoning_share)
            else _share(reasoning_tokens, output_tokens)
        )
        coding_token_counts = {
            "scope": "coding_index_only",
            "definition": (
                "Tokens used to run the Coding Index evaluation. "
                "output_tokens = answer_tokens + reasoning_tokens."
            ),
            "evidence_scope": ("per_task" if is_current else "coding_evaluation_total"),
            "input_tokens": input_tokens,
            "answer_tokens": answer_tokens,
            "reasoning_tokens": reasoning_tokens,
            "output_tokens": output_tokens,
            "answer_share_of_output": answer_share,
            "reasoning_share_of_output": reasoning_share,
        }
        coding_eval_cost = {
            "scope": "coding_index_evaluation_api",
            "currency": "USD",
            "definition": (
                "Coding Index evaluation/API spend; not a plan quota or "
                "subscription price."
            ),
            "total_cost": _number_alias(eval_cost, "totalCost", "total"),
            "input_cost": _number_alias(eval_cost, "inputCost", "input"),
            "answer_cost": _number_alias(eval_cost, "answerCost", "answer"),
            "reasoning_cost": _number_alias(eval_cost, "reasoningCost", "reasoning"),
        }
        coding_task_metrics = {
            "scope": "coding_index_task",
            "currency": "USD",
            "definition": (
                "Per-benchmark-task Coding Index output, API cost, and weighted "
                "decode time."
            ),
            "output_tokens_per_task": {
                "output_tokens": _number_alias(task_output, "output", "outputTokens"),
                "answer_tokens": _number_alias(task_output, "answer", "answerTokens"),
                "reasoning_tokens": _number_alias(
                    task_output,
                    "reasoning",
                    "reasoningTokens",
                ),
            },
            "cost_per_task_usd": {
                "total_cost": _number_alias(task_cost, "total", "totalCost"),
                "input_cost": _number_alias(task_cost, "input", "inputCost"),
                "non_cache_input_cost": _number_alias(
                    task_cost,
                    "nonCacheInput",
                    "non_cache_input",
                    "nonCacheInputCost",
                ),
                "cache_read_cost": _number_alias(
                    task_cost,
                    "cacheRead",
                    "cache_read",
                    "cacheReadCost",
                ),
                "cache_write_cost": _number_alias(
                    task_cost,
                    "cacheWrite",
                    "cache_write",
                    "cacheWriteCost",
                ),
                "output_cost": _number_alias(task_cost, "output", "outputCost"),
                "reasoning_cost": _number_alias(
                    task_cost,
                    "reasoning",
                    "reasoningCost",
                ),
                "answer_cost": _number_alias(task_cost, "answer", "answerCost"),
            },
            "time_per_task_seconds": _number_or_none(model.get("timePerTaskSeconds")),
        }

        row: dict[str, Any] = {
            "model_slug": model_slug,
            "model_name": model_name,
            "short_name": short_name,
            "creator": creator_name,
            "coding": coding_score,
            "terminalbench_hard": model.get("terminalbench_hard"),
            "scicode": model.get("scicode"),
            "is_reasoning": _first_bool(model, "isReasoning", "reasoning_model"),
            "reasoning_model": _first_bool(model, "reasoning_model", "isReasoning"),
            "deprecated": model.get("deprecated"),
            "is_open_weights": is_open_weights,
            "release_date": _first_string(model, "release_date", "releaseDate"),
            "context_window_tokens": model.get("context_window_tokens"),
            "coding_token_counts": coding_token_counts,
            "coding_eval_cost": coding_eval_cost,
            "coding_task_metrics": coding_task_metrics,
        }
        if args.include_benchmark_counts:
            row["coding_component_token_counts"] = _coding_component_token_counts(model)
        for preserved_key in ("raw_fields", "unknowns"):
            preserved = model.get(preserved_key)
            if isinstance(preserved, (dict, list)):
                row[preserved_key] = copy.deepcopy(preserved)
        _attach_row_evidence(
            row,
            metric_paths=(
                "coding",
                "terminalbench_hard",
                "scicode",
                "context_window_tokens",
                "coding_token_counts.input_tokens",
                "coding_token_counts.answer_tokens",
                "coding_token_counts.reasoning_tokens",
                "coding_token_counts.output_tokens",
                "coding_token_counts.answer_share_of_output",
                "coding_token_counts.reasoning_share_of_output",
                "coding_eval_cost.total_cost",
                "coding_eval_cost.input_cost",
                "coding_eval_cost.answer_cost",
                "coding_eval_cost.reasoning_cost",
                "coding_task_metrics.output_tokens_per_task.output_tokens",
                "coding_task_metrics.output_tokens_per_task.answer_tokens",
                "coding_task_metrics.output_tokens_per_task.reasoning_tokens",
                "coding_task_metrics.cost_per_task_usd.total_cost",
                "coding_task_metrics.cost_per_task_usd.input_cost",
                "coding_task_metrics.cost_per_task_usd.non_cache_input_cost",
                "coding_task_metrics.cost_per_task_usd.cache_read_cost",
                "coding_task_metrics.cost_per_task_usd.cache_write_cost",
                "coding_task_metrics.cost_per_task_usd.output_cost",
                "coding_task_metrics.cost_per_task_usd.reasoning_cost",
                "coding_task_metrics.cost_per_task_usd.answer_cost",
                "coding_task_metrics.time_per_task_seconds",
            ),
            source_prefix=f"$.models[{model_index}]",
            artifact_hash=_result_sha256(result),
            raw_values={
                "coding": model.get("headlineValue", model.get("coding_index")),
                "terminalbench_hard": model.get("terminalbench_hard"),
                "scicode": model.get("scicode"),
                "context_window_tokens": model.get("context_window_tokens"),
            },
            derived_paths={
                "coding_token_counts.answer_share_of_output": (
                    "answer_tokens / output_tokens",
                    (
                        "$.coding_token_counts.answer_tokens",
                        "$.coding_token_counts.output_tokens",
                    ),
                )
                if not _finite_number(published_answer_share)
                else None,
                "coding_token_counts.reasoning_share_of_output": (
                    "reasoning_tokens / output_tokens",
                    (
                        "$.coding_token_counts.reasoning_tokens",
                        "$.coding_token_counts.output_tokens",
                    ),
                )
                if not _finite_number(published_reasoning_share)
                else None,
            },
        )
        rows.append(row)

    sort_key_map = {
        "coding": "coding",
        "input_tokens": "coding_token_counts.input_tokens",
        "answer_tokens": "coding_token_counts.answer_tokens",
        "reasoning_tokens": "coding_token_counts.reasoning_tokens",
        "output_tokens": "coding_token_counts.output_tokens",
        "cost": "coding_eval_cost.total_cost",
    }
    reverse = _resolve_reverse(sort_key=args.sort_by, order=args.order)
    rows.sort(
        key=lambda row: _nested_sort_metric(
            row,
            sort_key_map[args.sort_by],
            reverse=reverse,
        ),
    )
    limited = rows[: max(args.limit, 0)]

    coding_payload = {
        "meta": {
            "source_url": CODING_CAPABILITY_URL,
            "final_url": _result_final_url(result, CODING_CAPABILITY_URL),
            "fetched_at": _result_fetched_at(result),
            "etag": _result_etag(result),
            "last_modified": _result_last_modified(result),
            "sha256": _result_sha256(result),
            "byte_length": _result_byte_length(result),
            "freshness": {"mode": "fresh", "stale": False, "fallback": False},
        },
        "rows": rows,
        "overlap": overlap_metadata(),
    }
    _attach_payload_evidence(coding_payload, artifact_hash=_result_sha256(result))
    atomic_write(
        args.output_json,
        json.dumps(coding_payload, ensure_ascii=False).encode("utf-8"),
    )

    payload: dict[str, Any] = {
        "source": {
            "url": CODING_CAPABILITY_URL,
            "status_code": result.status_code,
            "fetched_at": _result_fetched_at(result),
            "sha256": _result_sha256(result),
        },
        "output_json": str(args.output_json),
        "definition": {
            "scope": "coding_index_only",
            "warning": (
                "These token counts and costs are tied to the Coding Index evaluation, "
                "not global Intelligence Index counts or plan quota."
            ),
            "components": ["terminalbench_v2_1", "scicode"],
            "output_tokens": "answer_tokens + reasoning_tokens",
        },
        "applied_filters": {
            "model": args.model,
            "creator": args.creator,
            "open_weights_only": args.open_weights_only,
            "sort_by": args.sort_by,
            "order": args.order,
            "limit": args.limit,
            "include_benchmark_counts": args.include_benchmark_counts,
        },
        "counts": {
            "matched_models": len(rows),
            "returned_models": len(limited),
            "skipped_missing_token_counts": 0,
            "frames": len(frames),
        },
        "rows": limited,
        "overlap": overlap_metadata(),
    }
    return _attach_payload_evidence(payload, artifact_hash=_result_sha256(result))


def _evaluation_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.input is not None and args.url is not None:
        _raise_cli_usage_error("evaluation accepts either url or --input, not both")
    if args.input is None and not isinstance(args.url, str):
        _raise_cli_usage_error("evaluation requires a URL or --input")
    if args.min_rows < 1:
        _raise_cli_usage_error("min_rows must be positive")
    if args.limit is not None and args.limit < 0:
        _raise_cli_usage_error("limit must be non-negative")

    result: FetchResult | None = None
    if args.input is not None:
        try:
            body = args.input.read_text(encoding="utf-8")
        except OSError as exc:
            message = f"Cannot read evaluation input: {args.input}"
            raise CliUsageError(message) from exc
        source_url = args.input.resolve().as_uri()
        source_status = 200
        fetched_at = datetime.now(UTC).isoformat()
        content_type = "local"
        freshness = "snapshot"
        final_url = source_url
        etag = None
        last_modified = None
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        byte_length = len(body.encode("utf-8"))
    else:
        if not isinstance(args.url, str):
            _raise_cli_usage_error("evaluation requires --url when --input is absent")
        if urlsplit(args.url).scheme.casefold() != "https":
            _raise_cli_usage_error("evaluation public URL must use HTTPS")
        result = _materialize_fetch_result(
            fetch_page(args.url, timeout_seconds=args.timeout_seconds),
            fallback_url=args.url,
        )
        body = result.body
        source_url = redact_query(args.url)
        source_status = result.status_code
        fetched_at = _result_fetched_at(result)
        content_type = _result_header(result, "content-type")
        freshness = "fresh"
        final_url = redact_query(_result_final_url(result, args.url))
        etag = _result_etag(result)
        last_modified = _result_last_modified(result)
        digest = _result_sha256(result)
        byte_length = _result_byte_length(result)

    frames = parse_next_payload(body)
    rows = extract_evaluation_rows(frames, min_rows=args.min_rows)
    for row_index, row in enumerate(rows):
        row["value_status"] = "published"
        metric_paths = tuple(
            key
            for key, value in row.items()
            if key not in {"value_status", "raw_fields", "unknowns"}
            and (
                _numeric_scalar(value)
                or value is None
                or key.casefold() in {"score", "value", "metric", "rank", "rating"}
            )
        )
        known_metric_fields = {
            "score",
            "value",
            "metric",
            "rating",
            "rank",
            "pass_at_1",
            "accuracy",
            "overall",
            "mean",
            "median",
        }
        _attach_row_evidence(
            row,
            metric_paths=metric_paths,
            source_prefix=f"$.rows[{row_index}]",
            artifact_hash=digest,
            raw_values={key: row.get(key) for key in metric_paths},
            unknown_paths=tuple(
                key for key in metric_paths if key.casefold() not in known_metric_fields
            ),
        )
    if args.sort_by:
        reverse = args.order in {"auto", "desc"}
        rows.sort(
            key=lambda row: _nested_sort_metric(
                row,
                args.sort_by,
                reverse=reverse,
            ),
        )
    limited = rows if args.limit is None else rows[: args.limit]
    source = {
        "url": source_url,
        "final_url": final_url,
        "status_code": source_status,
        "fetched_at": fetched_at,
        "content_type": content_type,
        "etag": etag,
        "last_modified": last_modified,
        "sha256": digest,
        "byte_length": byte_length,
        "freshness": freshness,
    }
    filters = {
        "min_rows": args.min_rows,
        "sort_by": args.sort_by,
        "order": args.order,
        "limit": args.limit,
    }
    payload: dict[str, Any] = {
        "meta": {
            "source": source,
            "filters_applied": filters,
            "freshness": {"mode": freshness, "stale": False, "fallback": False},
        },
        "rows": rows,
        "overlap": overlap_metadata(),
        "derived": {
            "sort": {
                "formula": f"sort by {args.sort_by}" if args.sort_by else None,
                "input_paths": [f"$.rows[*].{args.sort_by}"] if args.sort_by else [],
            },
            "limit": {
                "formula": "rows[:limit]",
                "input_paths": ["$.rows"],
            },
        },
    }
    _attach_payload_evidence(payload, artifact_hash=digest)
    if args.output_json is not None:
        atomic_write(
            args.output_json,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )

    result_payload: dict[str, Any] = {
        "value_status": "published",
        "source": source,
        "filters_applied": filters,
        "freshness": {"mode": freshness, "stale": False, "fallback": False},
        "counts": {
            "frames": len(frames),
            "matched_rows": len(rows),
            "returned_rows": len(limited),
        },
        "output_json": str(args.output_json) if args.output_json else None,
        "rows": limited,
        "overlap": overlap_metadata(),
        "derived": payload["derived"],
    }
    return _attach_payload_evidence(result_payload, artifact_hash=digest)


def _extract_default_data_models(frames: list[tuple[str, Any]]) -> list[Any]:
    candidates: list[list[Any]] = []

    def scan(node: object) -> None:
        if isinstance(node, dict):
            default_data = node.get("defaultData")
            if _looks_like_coding_capability_rows(default_data):
                candidates.append(default_data)
            for value in node.values():
                scan(value)
        elif isinstance(node, list):
            if _looks_like_coding_capability_rows(node):
                candidates.append(node)
            for item in node:
                scan(item)

    for _, frame in frames:
        scan(frame)

    if not candidates:
        _raise_extraction_error(
            "Coding capability payload missing recognizable coding rows.",
        )
    return max(candidates, key=len)


def _looks_like_coding_capability_rows(value: object) -> bool:
    if not isinstance(value, list):
        return False
    sample = [item for item in value[:25] if isinstance(item, dict)]
    if not sample:
        return False
    hits = sum(
        1
        for item in sample
        if isinstance(item.get("slug"), str)
        and (
            isinstance(item.get("coding_index"), int | float)
            or isinstance(item.get("headlineValue"), int | float)
        )
    )
    return hits >= max(1, len(sample) // 2)


def _first_string(mapping: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str):
            return value
    return None


def _first_number(mapping: dict[str, Any], *keys: str) -> int | float | None:
    for key in keys:
        value = mapping.get(key)
        if _finite_number(value):
            return value
    return None


def _first_bool(mapping: dict[str, Any], *keys: str) -> bool | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, bool):
            return value
    return None


def _first_dict(mapping: dict[str, Any], *keys: str) -> dict[str, Any] | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, dict):
            return value
    return None


def _number_alias(mapping: dict[str, Any], *keys: str) -> int | float | None:
    return _first_number(mapping, *keys)


def _number_or_none(value: object) -> int | float | None:
    return value if _finite_number(value) else None


def _share(part: float | None, total: float | None) -> float | None:
    if not _finite_number(part) or not _finite_number(total) or float(total) == 0:
        return None
    return round(float(part) / float(total), 6)


def _coding_component_token_counts(model: dict[str, Any]) -> dict[str, Any]:
    eval_counts = (
        model.get("eval_token_counts")
        if isinstance(model.get("eval_token_counts"), dict)
        else {}
    )
    return {
        key: eval_counts.get(key)
        for key in ("terminalbench_hard", "scicode")
        if isinstance(eval_counts.get(key), dict)
    }


def _nested_sort_metric(
    row: dict[str, Any],
    path: str,
    *,
    reverse: bool,
) -> tuple[int, float]:
    current: object = _lookup_path(row, path)
    metric_evidence = row.get("metric_evidence")
    evidence = metric_evidence.get(path) if isinstance(metric_evidence, dict) else None
    if isinstance(evidence, dict):
        if (
            evidence.get("comparison_eligibility", evidence.get("eligibility"))
            != "eligible"
        ):
            return (1, 0.0)
        current = evidence.get("normalized_value", evidence.get("normalized"))
    if _finite_number(current):
        normalized = -float(current) if reverse else float(current)
        return (0, normalized)
    return (1, 0.0)


def _harness_payload(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = _load_reader_snapshot(args.snapshot)
    models = _model_rows(snapshot)

    model_filter = (
        args.model.lower() if isinstance(args.model, str) and args.model else None
    )
    creator_filter = (
        args.creator.lower() if isinstance(args.creator, str) and args.creator else None
    )

    rows: list[dict[str, Any]] = []
    skipped_missing = 0

    for model in models:
        model_slug = model.get("slug") if isinstance(model.get("slug"), str) else None
        if not model_slug:
            continue
        if model.get("deleted") or model.get("deprecated"):
            continue

        model_name = model.get("name") if isinstance(model.get("name"), str) else None
        creator = _creator(model)
        creator_name = (
            creator.get("name") if isinstance(creator.get("name"), str) else None
        )

        if model_filter and not _matches_any(model_filter, [model_slug, model_name]):
            continue
        if creator_filter and not _matches_any(
            creator_filter,
            [creator_name, creator.get("slug")],
        ):
            continue
        if args.open_weights_only and model.get("is_open_weights") is not True:
            continue

        agentic = model.get("agentic_index")
        coding = model.get("coding_index")
        if not _finite_number(agentic) or not _finite_number(coding):
            skipped_missing += 1
            continue

        computed_harness = round((float(agentic) + float(coding)) / 2.0, 4)
        computed_gap = round(float(agentic) - float(coding), 4)
        published_harness = model.get("harness")
        published_gap = model.get("execution_gap")
        row: dict[str, Any] = {
            "rank": 0,
            "model_slug": model_slug,
            "model_name": model_name,
            "creator": creator_name,
            "harness": published_harness
            if _finite_number(published_harness)
            else computed_harness,
            "agentic": agentic,
            "coding": coding,
            "execution_gap": published_gap
            if _finite_number(published_gap)
            else computed_gap,
            "intelligence": model.get("intelligence_index"),
            "release_date": model.get("release_date"),
            "reasoning_model": model.get("reasoning_model"),
            "is_open_weights": model.get("is_open_weights"),
            "context_window_tokens": model.get("context_window_tokens"),
            "derived": {
                "harness": {
                    "value": computed_harness,
                    "formula": "0.5 * agentic + 0.5 * coding",
                    "input_paths": ["$.agentic", "$.coding"],
                },
                "execution_gap": {
                    "value": computed_gap,
                    "formula": "agentic - coding",
                    "input_paths": ["$.agentic", "$.coding"],
                },
            },
        }
        for preserved_key in ("raw_fields", "unknowns"):
            preserved = model.get(preserved_key)
            if isinstance(preserved, (dict, list)):
                row[preserved_key] = copy.deepcopy(preserved)
        _attach_row_evidence(
            row,
            metric_paths=(
                "rank",
                "harness",
                "agentic",
                "coding",
                "execution_gap",
                "intelligence",
                "context_window_tokens",
                "derived.harness.value",
                "derived.execution_gap.value",
            ),
            source_prefix=f"$.models[{len(rows)}]",
            derived_paths={
                "harness": (
                    "0.5 * agentic + 0.5 * coding",
                    ("$.agentic", "$.coding"),
                )
                if not _finite_number(published_harness)
                else None,
                "execution_gap": (
                    "agentic - coding",
                    ("$.agentic", "$.coding"),
                )
                if not _finite_number(published_gap)
                else None,
                "derived.harness.value": (
                    "0.5 * agentic + 0.5 * coding",
                    ("$.agentic", "$.coding"),
                ),
                "derived.execution_gap.value": (
                    "agentic - coding",
                    ("$.agentic", "$.coding"),
                ),
            },
            raw_values={
                "agentic": model.get("agentic_index"),
                "coding": model.get("coding_index"),
                "intelligence": model.get("intelligence_index"),
                "context_window_tokens": model.get("context_window_tokens"),
            },
        )
        rows.append(row)

    rows.sort(
        key=lambda row: (-float(row["harness"]), str(row.get("model_slug") or "")),
    )
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
        _attach_row_evidence(
            row,
            metric_paths=("rank",),
            source_prefix=f"$.rows[{index - 1}]",
            derived_paths={
                "rank": ("deterministic descending sort rank", ("$.harness",)),
            },
        )

    limited = rows[: max(args.limit, 0)]
    payload: dict[str, Any] = {
        "snapshot": str(args.snapshot),
        "definition": {
            "name": "Harness",
            "formula": "0.5 * Agentic Index + 0.5 * Coding Index",
            "execution_gap": (
                "Agentic Index - Coding Index; high positive values indicate "
                "executable-precision risk."
            ),
            "dependencies": [
                {"canonical_id": "agentic_index", "release": None},
                {"canonical_id": "coding_index", "release": None},
            ],
            "independence": [],
        },
        "applied_filters": {
            "model": args.model,
            "creator": args.creator,
            "open_weights_only": args.open_weights_only,
            "limit": args.limit,
        },
        "counts": {
            "ranked_models": len(rows),
            "returned_models": len(limited),
            "skipped_missing_agentic_or_coding": skipped_missing,
        },
        "rows": limited,
        "overlap": overlap_metadata(
            dependencies=[
                {"canonical_id": "agentic_index", "release": None},
                {"canonical_id": "coding_index", "release": None},
            ],
            independence=[],
        ),
    }
    return _attach_payload_evidence(payload)


REASONING_EXTREME_FLOOR = 0.10
REASONING_EXTREME_SELECTIVITY = 0.75
REASONING_SELECTIVE_FLOOR = 0.25
REASONING_SELECTIVE_SELECTIVITY = 0.60
REASONING_MODERATE_FLOOR = 0.50
REASONING_HARD_UNIFORM_FLOOR = 0.60
REASONING_HARD_UNIFORM_SHARE = 0.85
REASONING_UNIFORM_SHARE = 0.80


def _aggregate_only_reasoning_profile(
    model: dict[str, Any],
) -> dict[str, Any] | None:
    iitc = model.get("intelligence_index_token_counts")
    if not isinstance(iitc, dict):
        return None
    answer = _number_or_none(iitc.get("answer"))
    reasoning = _number_or_none(iitc.get("reasoning"))
    output = _number_or_none(iitc.get("output_tokens"))
    if (
        not _finite_number(answer)
        or not _finite_number(reasoning)
        or not _finite_number(output)
        or float(output) <= 0
    ):
        return None
    return {
        "reasoning_floor": None,
        "reasoning_floor_benchmark": None,
        "reasoning_ceiling": None,
        "reasoning_ceiling_benchmark": None,
        "selectivity_score": None,
        "weighted_reasoning_share": round(reasoning / output, 4),
        "classification": None,
        "benchmark_count": 0,
        "warning": (
            "Aggregate only; per-benchmark canonical_eval_token_counts unavailable."
        ),
    }


def _reasoning_shares(
    canonical: dict[str, Any],
) -> tuple[list[tuple[float, str]], int, int]:
    shares: list[tuple[float, str]] = []
    total_answer = 0
    total_reasoning = 0
    for bench_name, vals in canonical.items():
        if not isinstance(vals, dict):
            continue
        answer = vals.get("answer")
        if answer is None:
            answer = vals.get("answer_tokens")
        reasoning = vals.get("reasoning")
        if reasoning is None:
            reasoning = vals.get("reasoning_tokens")
        if (
            not _finite_number(answer)
            or not _finite_number(reasoning)
            or float(answer) + float(reasoning) <= 0
        ):
            continue
        share = float(reasoning) / (float(answer) + float(reasoning))
        shares.append((share, bench_name))
        total_answer += answer
        total_reasoning += reasoning


def _reasoning_classification(
    floor: float,
    selectivity: float,
    weighted_share: float,
) -> str:
    if floor < REASONING_EXTREME_FLOOR and selectivity > REASONING_EXTREME_SELECTIVITY:
        return "selective_extreme"
    if (
        floor < REASONING_SELECTIVE_FLOOR
        and selectivity > REASONING_SELECTIVE_SELECTIVITY
    ):
        return "selective"
    if floor < REASONING_MODERATE_FLOOR:
        return "moderate"
    if (
        floor >= REASONING_HARD_UNIFORM_FLOOR
        and weighted_share >= REASONING_HARD_UNIFORM_SHARE
    ):
        return "hard_uniform_heavy"
    if floor >= REASONING_MODERATE_FLOOR and weighted_share >= REASONING_UNIFORM_SHARE:
        return "uniform_heavy"
    return "unclassified"


def _compute_reasoning_profile(model: dict[str, Any]) -> dict[str, Any] | None:
    """Compute reasoning selectivity profile from canonical evaluation counts."""
    canonical = model.get("canonical_eval_token_counts")
    if not isinstance(canonical, dict) or not canonical:
        return _aggregate_only_reasoning_profile(model)

    shares, total_answer, total_reasoning = _reasoning_shares(canonical)
    if not shares:
        return None

    total_output = total_answer + total_reasoning
    floor = min(shares, key=lambda share: share[0])
    ceiling = max(shares, key=lambda share: share[0])
    weighted_share = total_reasoning / total_output if total_output else 0
    selectivity = ceiling[0] - floor[0]
    return {
        "reasoning_floor": round(floor[0], 4),
        "reasoning_floor_benchmark": floor[1],
        "reasoning_ceiling": round(ceiling[0], 4),
        "reasoning_ceiling_benchmark": ceiling[1],
        "selectivity_score": round(selectivity, 4),
        "weighted_reasoning_share": round(weighted_share, 4),
        "classification": _reasoning_classification(
            floor[0],
            selectivity,
            weighted_share,
        ),
        "benchmark_count": len(shares),
    }


def _reasoning_benchmarks(model: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract per-benchmark reasoning share breakdown."""
    canonical = model.get("canonical_eval_token_counts")
    if not isinstance(canonical, dict):
        return []
    result: list[dict[str, Any]] = []
    for bench_name, vals in canonical.items():
        if not isinstance(vals, dict):
            continue
        a = vals.get("answer")
        if a is None:
            a = vals.get("answer_tokens")
        r = vals.get("reasoning")
        if r is None:
            r = vals.get("reasoning_tokens")
        if not _finite_number(a) or not _finite_number(r) or float(a) + float(r) <= 0:
            continue
        output = float(a) + float(r)
        result.append(
            {
                "benchmark": bench_name,
                "answer_tokens": int(a),
                "reasoning_tokens": int(r),
                "output_tokens": int(output),
                "reasoning_share": round(float(r) / output, 4),
            },
        )
    result.sort(key=lambda b: b["reasoning_share"])
    return result


def _reasoning_row(
    model: dict[str, Any],
    args: argparse.Namespace,
    model_filter: str | None,
    creator_filter: str | None,
) -> tuple[dict[str, Any] | None, bool]:
    model_slug = model.get("slug") if isinstance(model.get("slug"), str) else None
    if not model_slug or model.get("deleted") or model.get("deprecated"):
        return None, False

    model_name = model.get("name") if isinstance(model.get("name"), str) else None
    creator = _creator(model)
    creator_name = creator.get("name") if isinstance(creator.get("name"), str) else None
    if model_filter and not _matches_any(model_filter, [model_slug, model_name]):
        return None, False
    if creator_filter and not _matches_any(
        creator_filter,
        [creator_name, creator.get("slug")],
    ):
        return None, False
    if args.open_weights_only and model.get("is_open_weights") is not True:
        return None, False

    profile = _compute_reasoning_profile(model)
    if profile is None:
        return None, True
    classification = profile.get("classification")
    if args.classification and classification != args.classification:
        return None, False
    if args.selective_only and not classification.startswith("selective"):
        return None, False

    agentic = model.get("agentic_index")
    coding = model.get("coding_index")
    computed_harness = (
        round((float(agentic) + float(coding)) / 2.0, 4)
        if _finite_number(agentic) and _finite_number(coding)
        else None
    )
    published_harness = model.get("harness")
    harness = (
        published_harness if _finite_number(published_harness) else computed_harness
    )
    profile_numeric = {
        key: value for key, value in profile.items() if _numeric_scalar(value)
    }
    derived_profile = {
        "formula": "reasoning shares derived from canonical_eval_token_counts",
        "input_paths": ["$.canonical_eval_token_counts"],
        "values": profile,
    }
    row: dict[str, Any] = {
        "model_slug": model_slug,
        "model_name": model_name,
        "creator": creator_name,
        "reasoning_model": model.get("reasoning_model"),
        "is_open_weights": model.get("is_open_weights"),
        "release_date": model.get("release_date"),
        "context_window_tokens": model.get("context_window_tokens"),
        "intelligence": model.get("intelligence_index"),
        "agentic": agentic,
        "coding": coding,
        "harness": harness,
        "reasoning_profile": profile,
        "derived": {
            "harness": {
                "value": computed_harness,
                "formula": "0.5 * agentic + 0.5 * coding",
                "input_paths": ["$.agentic", "$.coding"],
            },
            "reasoning_profile": derived_profile,
        },
    }
    if args.benchmarks:
        row["per_benchmark"] = _reasoning_benchmarks(model)
    for preserved_key in ("raw_fields", "unknowns"):
        preserved = model.get(preserved_key)
        if isinstance(preserved, (dict, list)):
            row[preserved_key] = copy.deepcopy(preserved)
    derived_paths: dict[str, tuple[str, tuple[str, ...]] | None] = {
        "harness": (
            "0.5 * agentic + 0.5 * coding",
            ("$.agentic", "$.coding"),
        )
        if not _finite_number(published_harness)
        else None,
        "derived.harness.value": (
            "0.5 * agentic + 0.5 * coding",
            ("$.agentic", "$.coding"),
        ),
    }
    for key in profile_numeric:
        derived_paths[f"reasoning_profile.{key}"] = (
            "derived from canonical_eval_token_counts",
            ("$.canonical_eval_token_counts",),
        )
        derived_paths[f"derived.reasoning_profile.values.{key}"] = (
            "derived from canonical_eval_token_counts",
            ("$.canonical_eval_token_counts",),
        )
    if args.benchmarks:
        for index, benchmark in enumerate(row.get("per_benchmark", [])):
            if isinstance(benchmark, dict):
                for key, value in benchmark.items():
                    if _numeric_scalar(value):
                        derived_paths[f"per_benchmark[{index}].{key}"] = (
                            "reasoning_tokens / (answer_tokens + reasoning_tokens)",
                            ("$.canonical_eval_token_counts",),
                        )
    _attach_row_evidence(
        row,
        metric_paths=(
            "harness",
            "intelligence",
            "agentic",
            "coding",
            "context_window_tokens",
            *tuple(f"reasoning_profile.{key}" for key in profile_numeric),
        ),
        source_prefix=f"$.models[{model_slug}]",
        raw_values={
            "intelligence": model.get("intelligence_index"),
            "agentic": agentic,
            "coding": coding,
            "context_window_tokens": model.get("context_window_tokens"),
        },
        derived_paths=derived_paths,
    )
    return row, False


def _reasoning_payload(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = _load_reader_snapshot(args.snapshot)
    models = _model_rows(snapshot)

    model_filter = (
        args.model.lower() if isinstance(args.model, str) and args.model else None
    )
    creator_filter = (
        args.creator.lower() if isinstance(args.creator, str) and args.creator else None
    )

    rows: list[dict[str, Any]] = []
    skipped_missing = 0

    for model in models:
        row, missing_profile = _reasoning_row(
            model,
            args,
            model_filter,
            creator_filter,
        )
        if missing_profile:
            skipped_missing += 1
        if row is not None:
            rows.append(row)

    sort_key_map = {
        "harness": ("harness", True),
        "selectivity": ("reasoning_profile.selectivity_score", True),
        "reasoning_floor": ("reasoning_profile.reasoning_floor", False),
        "weighted_reasoning_share": (
            "reasoning_profile.weighted_reasoning_share",
            False,
        ),
        "intelligence": ("intelligence", True),
        "agentic": ("agentic", True),
        "coding": ("coding", True),
    }
    sort_path, desc_default = sort_key_map.get(args.sort_by, ("harness", True))
    reverse = desc_default
    if args.order == "asc":
        reverse = False
    elif args.order == "desc":
        reverse = True

    rows.sort(
        key=lambda row: _nested_sort_metric(
            row,
            sort_path,
            reverse=reverse,
        ),
    )
    limited = rows[: max(args.limit, 0)]
    for index, row in enumerate(limited, start=1):
        row["rank"] = index
        _attach_row_evidence(
            row,
            metric_paths=("rank",),
            source_prefix=f"$.rows[{index - 1}]",
            derived_paths={
                "rank": (
                    "deterministic sort rank",
                    (f"$.{sort_path}",),
                ),
            },
        )

    payload: dict[str, Any] = {
        "snapshot": str(args.snapshot),
        "definition": {
            "name": "Reasoning Selectivity",
            "scope": (
                "max-effort Intelligence Index evaluation (canonical_eval_token_counts)"
            ),
            "metrics": {
                "reasoning_floor": (
                    "min(reasoning_share) across benchmarks — lower = more selective"
                ),
                "reasoning_ceiling": "max(reasoning_share) across benchmarks",
                "weighted_reasoning_share": "Σ reasoning_tokens / Σ (answer+reasoning)",
                "selectivity_score": "reasoning_ceiling - reasoning_floor",
            },
            "classifications": {
                "selective_extreme": "floor < 0.10 and selectivity_score > 0.75",
                "selective": "floor < 0.25 and selectivity_score > 0.60",
                "moderate": "0.25 <= floor < 0.50",
                "uniform_heavy": "floor >= 0.50 and weighted_reasoning_share >= 0.80",
                "hard_uniform_heavy": (
                    "floor >= 0.60 and weighted_reasoning_share >= 0.85"
                ),
            },
            "dependencies": [
                {"canonical_id": "canonical_eval_token_counts", "release": None},
            ],
            "independence": [],
        },
        "applied_filters": {
            "model": args.model,
            "creator": args.creator,
            "open_weights_only": args.open_weights_only,
            "classification": args.classification,
            "selective_only": args.selective_only,
            "sort_by": args.sort_by,
            "order": args.order,
            "limit": args.limit,
        },
        "counts": {
            "ranked_models": len(rows),
            "returned_models": len(limited),
            "skipped_missing_profile": skipped_missing,
        },
        "rows": limited,
        "overlap": _snapshot_overlap(snapshot),
    }
    return _attach_payload_evidence(payload)


def _query_row(
    item: object,
    canonical_models: dict[str, dict[str, Any]],
    model_filter: str | None,
    provider_filter: str | None,
    endpoint_filter: str | None,
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    endpoint_slug = item.get("slug")
    if not isinstance(endpoint_slug, str) or "_" not in endpoint_slug:
        return None
    host = item.get("host") if isinstance(item.get("host"), dict) else {}
    if canonical_models:
        endpoint_model_slug = item.get("model_slug")
        model = (
            canonical_models.get(endpoint_model_slug)
            if isinstance(endpoint_model_slug, str)
            else None
        )
        if model is None:
            return None
    else:
        model = item.get("model") if isinstance(item.get("model"), dict) else {}

    model_slug = model.get("slug") if isinstance(model.get("slug"), str) else None
    model_name = model.get("name") if isinstance(model.get("name"), str) else None
    provider_slug = host.get("slug") if isinstance(host.get("slug"), str) else None
    provider_name = host.get("name") if isinstance(host.get("name"), str) else None
    if model_filter and not _matches_any(model_filter, [model_slug, model_name]):
        return None
    if provider_filter and not _matches_any(
        provider_filter,
        [provider_slug, provider_name],
    ):
        return None
    if endpoint_filter and endpoint_filter not in endpoint_slug.lower():
        return None

    timescale = (
        item.get("timescaleData") if isinstance(item.get("timescaleData"), dict) else {}
    )
    e2e = (
        item.get("end_to_end_response_time_metrics")
        if isinstance(item.get("end_to_end_response_time_metrics"), dict)
        else {}
    )
    computed_harness = _harness_score(model)
    published_harness = model.get("harness")
    harness = (
        published_harness if _finite_number(published_harness) else computed_harness
    )
    blended_field = (
        "price_1m_blended_7_to_2_to_1"
        if "price_1m_blended_7_to_2_to_1" in item
        else "price_1m_blended_3_to_1"
    )
    row: dict[str, Any] = {
        "endpoint_slug": endpoint_slug,
        "endpoint_name": item.get("name"),
        "model_slug": model_slug,
        "model_name": model_name,
        "provider_slug": provider_slug,
        "provider_name": provider_name,
        "harness": harness,
        "intelligence": model.get("intelligence_index"),
        "agentic": model.get("agentic_index"),
        "coding": model.get("coding_index"),
        "math": model.get("math_index"),
        "gpqa": model.get("gpqa"),
        "mmlu_pro": model.get("mmlu_pro"),
        "livecodebench": model.get("livecodebench"),
        "ifbench": model.get("ifbench"),
        "scicode": model.get("scicode"),
        "tau2": model.get("tau_2", model.get("tau2")),
        "terminalbench_hard": model.get("terminalbench_hard"),
        "release_date": model.get("release_date"),
        "reasoning_model": model.get("reasoning_model"),
        "is_open_weights": model.get("is_open_weights"),
        "price_input": item.get("price_1m_input_tokens"),
        "price_output": item.get("price_1m_output_tokens"),
        "price_blended": item.get(blended_field),
        "speed": timescale.get("median_output_speed"),
        "ttfc": timescale.get("median_time_to_first_chunk"),
        "e2e": e2e.get("total_time"),
        "context_window_tokens": item.get("context_window_tokens"),
        "host_api_id": item.get("host_api_id"),
        "derived": {
            "harness": {
                "value": computed_harness,
                "formula": "0.5 * agentic + 0.5 * coding",
                "input_paths": ["$.agentic", "$.coding"],
            },
        },
    }
    for preserved_key in ("raw_fields", "unknowns"):
        for source in (item, model):
            preserved = source.get(preserved_key)
            if isinstance(preserved, (dict, list)):
                row[preserved_key] = copy.deepcopy(preserved)
                break
    _attach_row_evidence(
        row,
        metric_paths=(
            "harness",
            "intelligence",
            "agentic",
            "coding",
            "math",
            "gpqa",
            "mmlu_pro",
            "livecodebench",
            "ifbench",
            "scicode",
            "tau2",
            "terminalbench_hard",
            "price_input",
            "price_output",
            "price_blended",
            "speed",
            "ttfc",
            "e2e",
            "context_window_tokens",
        ),
        source_prefix=f"$.hosts_models[{endpoint_slug}]",
        raw_values={
            "intelligence": model.get("intelligence_index"),
            "agentic": model.get("agentic_index"),
            "coding": model.get("coding_index"),
            "math": model.get("math_index"),
            "gpqa": model.get("gpqa"),
            "mmlu_pro": model.get("mmlu_pro"),
            "livecodebench": model.get("livecodebench"),
            "ifbench": model.get("ifbench"),
            "scicode": model.get("scicode"),
            "tau2": model.get("tau_2", model.get("tau2")),
            "terminalbench_hard": model.get("terminalbench_hard"),
            "price_input": item.get("price_1m_input_tokens"),
            "price_output": item.get("price_1m_output_tokens"),
            "price_blended": item.get(blended_field),
            "speed": timescale.get("median_output_speed"),
            "ttfc": timescale.get("median_time_to_first_chunk"),
            "e2e": e2e.get("total_time"),
            "context_window_tokens": item.get("context_window_tokens"),
        },
        derived_paths={
            "harness": (
                "0.5 * agentic + 0.5 * coding",
                ("$.agentic", "$.coding"),
            )
            if not _finite_number(published_harness)
            else None,
            "derived.harness.value": (
                "0.5 * agentic + 0.5 * coding",
                ("$.agentic", "$.coding"),
            ),
        },
    )
    return row


def _query_payload(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = _load_reader_snapshot(args.snapshot)
    hosts_models = snapshot.get("hosts_models")
    if not isinstance(hosts_models, list):
        _raise_extraction_error("Snapshot missing hosts_models list")
    canonical_models = _canonical_models(snapshot)

    model_filter = (
        args.model.lower() if isinstance(args.model, str) and args.model else None
    )
    provider_filter = (
        args.provider.lower()
        if isinstance(args.provider, str) and args.provider
        else None
    )
    endpoint_filter = (
        args.endpoint.lower()
        if isinstance(args.endpoint, str) and args.endpoint
        else None
    )

    rows: list[dict[str, Any]] = []
    for item in hosts_models:
        if row := _query_row(
            item,
            canonical_models,
            model_filter,
            provider_filter,
            endpoint_filter,
        ):
            rows.append(row)

    sort_key = args.sort_by
    reverse = _resolve_reverse(sort_key=sort_key, order=args.order)
    rows.sort(key=lambda row: _sort_metric(row, sort_key, reverse=reverse))
    limited = rows[: max(args.limit, 0)]
    provider_counts = _provider_counts_from_rows(rows)
    model_counts: dict[str, int] = {}
    for row in rows:
        model_slug = row.get("model_slug")
        if isinstance(model_slug, str):
            model_counts[model_slug] = model_counts.get(model_slug, 0) + 1

    payload: dict[str, Any] = {
        "snapshot": str(args.snapshot),
        "applied_filters": {
            "model": args.model,
            "provider": args.provider,
            "endpoint": args.endpoint,
            "sort_by": sort_key,
            "order": args.order,
            "limit": args.limit,
        },
        "counts": {
            "matched_endpoints": len(rows),
            "returned_endpoints": len(limited),
            "matched_providers": len(provider_counts),
            "matched_models": len(model_counts),
        },
        "top_providers": [
            {"provider": name, "endpoints": count}
            for name, count in sorted(
                provider_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:10]
        ],
        "top_models": [
            {"model": name, "endpoints": count}
            for name, count in sorted(
                model_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:10]
        ],
        "rows": limited,
        "overlap": _snapshot_overlap(snapshot),
    }
    return _attach_payload_evidence(payload)


def _harness_score(model: dict[str, Any]) -> float | None:
    agentic = model.get("agentic_index")
    coding = model.get("coding_index")
    if _finite_number(agentic) and _finite_number(coding):
        return round((float(agentic) + float(coding)) / 2.0, 4)
    return None


def _matches_any(needle: str, values: list[str | None]) -> bool:
    return any(isinstance(value, str) and needle in value.lower() for value in values)


def _resolve_reverse(*, sort_key: str, order: str) -> bool:
    if order == "asc":
        return False
    if order == "desc":
        return True
    return sort_key not in {"price_blended", "ttfc", "e2e"}


def _sort_metric(
    row: dict[str, Any],
    metric: str,
    *,
    reverse: bool,
) -> tuple[int, float]:
    value: object = row.get(metric)
    metric_evidence = row.get("metric_evidence")
    evidence = (
        metric_evidence.get(metric) if isinstance(metric_evidence, dict) else None
    )
    if isinstance(evidence, dict):
        if (
            evidence.get("comparison_eligibility", evidence.get("eligibility"))
            != "eligible"
        ):
            return (1, 0.0)
        value = evidence.get("normalized_value", evidence.get("normalized"))
    if _finite_number(value):
        normalized = -float(value) if reverse else float(value)
        return (0, normalized)
    return (1, 0.0)


def _provider_counts_from_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        provider = row.get("provider_slug")
        if not isinstance(provider, str) or not provider:
            endpoint = row.get("endpoint_slug")
            if isinstance(endpoint, str) and "_" in endpoint:
                provider = endpoint.split("_", 1)[0]
        if isinstance(provider, str) and provider:
            counts[provider] = counts.get(provider, 0) + 1
    return counts


def _provider_counts_from_snapshot(snapshot: dict[str, Any]) -> dict[str, int]:
    hosts_models = snapshot.get("hosts_models")
    if not isinstance(hosts_models, list):
        _raise_extraction_error("Snapshot missing hosts_models list")

    counts: dict[str, int] = {}
    for item in hosts_models:
        if not isinstance(item, dict):
            continue
        provider: str | None = None
        host = item.get("host")
        if isinstance(host, dict) and isinstance(host.get("slug"), str):
            provider = host["slug"]
        elif isinstance(item.get("slug"), str) and "_" in item["slug"]:
            provider = item["slug"].split("_", 1)[0]

        if provider:
            counts[provider] = counts.get(provider, 0) + 1
    return counts


def _qa_payload(args: argparse.Namespace) -> dict[str, Any]:
    question = args.question.strip()
    if not question:
        _raise_cli_usage_error("qa requires a non-empty question")

    snapshot = _load_reader_snapshot(args.snapshot)
    hosts_models = snapshot.get("hosts_models")
    if not isinstance(hosts_models, list):
        _raise_extraction_error("Snapshot missing hosts_models list")

    inferred_model = args.model or _infer_model(question, _model_rows(snapshot))
    inferred_provider = args.provider or _infer_provider(question, hosts_models)
    inferred_sort_by, inferred_order = _infer_sort(question)

    sort_by = args.sort_by or inferred_sort_by
    order = args.order or inferred_order
    limit = args.limit if isinstance(args.limit, int) else _infer_limit(question)

    query_ns = argparse.Namespace(
        snapshot=args.snapshot,
        model=inferred_model,
        provider=inferred_provider,
        endpoint=None,
        sort_by=sort_by,
        order=order,
        limit=limit,
    )

    query_result = _query_payload(query_ns)

    payload: dict[str, Any] = {
        "question": question,
        "parsed_intent": {
            "model": inferred_model,
            "provider": inferred_provider,
            "sort_by": sort_by,
            "order": order,
            "limit": limit,
        },
        "query": query_result,
        "overlap": _snapshot_overlap(snapshot),
        "derived": {
            "intent": {
                "formula": "question -> model/provider/sort/order/limit",
                "input_paths": ["$.question"],
            },
        },
    }
    return _attach_payload_evidence(payload)


def _normalize_for_match(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _infer_model(question: str, models: list[dict[str, Any]]) -> str | None:
    question_norm = _normalize_for_match(question)
    best: tuple[int, str] | None = None

    for model in models:
        candidates = [model.get("slug"), model.get("name")]
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            candidate_norm = _normalize_for_match(candidate)
            if not candidate_norm:
                continue
            if candidate_norm in question_norm or question_norm in candidate_norm:
                score = len(candidate_norm)
                if best is None or score > best[0]:
                    best = (score, str(model.get("slug") or candidate))

    return best[1] if best is not None else None


def _infer_provider(question: str, hosts_models: list[Any]) -> str | None:
    question_norm = _normalize_for_match(question)
    best: tuple[int, str] | None = None

    for item in hosts_models:
        if not isinstance(item, dict):
            continue
        host = item.get("host") if isinstance(item.get("host"), dict) else {}
        candidates = [host.get("slug"), host.get("name")]
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            candidate_norm = _normalize_for_match(candidate)
            if not candidate_norm:
                continue
            if candidate_norm in question_norm or question_norm in candidate_norm:
                score = len(candidate_norm)
                if best is None or score > best[0]:
                    best = (score, str(host.get("slug") or candidate))

    return best[1] if best is not None else None


def _infer_sort(question: str) -> tuple[str, str]:
    q = question.lower()
    rules = (
        (
            ("cheap", "cheapest", "lowest price", "low price", "precio", "barato"),
            ("price_blended", "asc"),
        ),
        (
            (
                "latency",
                "first token",
                "ttfc",
                "response time",
                "rápido en",
                "latencia",
            ),
            ("ttfc", "asc"),
        ),
        (
            (
                "speed",
                "throughput",
                "tokens per second",
                "fastest",
                "rápido",
                "velocidad",
            ),
            ("speed", "desc"),
        ),
        (
            ("harness", "agent harness", "coding agent", "agentic coding"),
            ("harness", "desc"),
        ),
        (("agentic", "agent", "autonomous"), ("agentic", "desc")),
        (("coding", "code", "programming", "codificación"), ("coding", "desc")),
        (("math", "matemática", "matematica"), ("math", "desc")),
        (
            ("quality", "best", "intelligence", "benchmark", "mejor"),
            ("intelligence", "desc"),
        ),
    )
    for words, result in rules:
        if any(word in q for word in words):
            return result
    return ("intelligence", "desc")


def _infer_limit(question: str) -> int:
    match = re.search(r"\btop\s+(\d{1,3})\b", question.lower())
    if match:
        return max(1, int(match.group(1)))
    return 10


def _handle_fetch(args: argparse.Namespace) -> int:
    _emit_json(_envelope("fetch", _fetch_payload(args)), stdout=sys.stdout)
    return 0


def _handle_stats(args: argparse.Namespace) -> int:
    _emit_json(_envelope("stats", _stats_payload(args)), stdout=sys.stdout)
    return 0


def _handle_diff(args: argparse.Namespace) -> int:
    _emit_json(_envelope("diff", _diff_payload(args)), stdout=sys.stdout)
    return 0


def _handle_diagnose(args: argparse.Namespace) -> int:
    _emit_json(_envelope("diagnose", _diagnose_payload(args)), stdout=sys.stdout)
    return 0


def _handle_harness(args: argparse.Namespace) -> int:
    _emit_json(_envelope("harness", _harness_payload(args)), stdout=sys.stdout)
    return 0


def _handle_coding(args: argparse.Namespace) -> int:
    _emit_json(_envelope("coding", _coding_payload(args)), stdout=sys.stdout)
    return 0


def _handle_evaluation(args: argparse.Namespace) -> int:
    _emit_json(_envelope("evaluation", _evaluation_payload(args)), stdout=sys.stdout)
    return 0


def _handle_reasoning(args: argparse.Namespace) -> int:
    _emit_json(_envelope("reasoning", _reasoning_payload(args)), stdout=sys.stdout)
    return 0


def _handle_query(args: argparse.Namespace) -> int:
    _emit_json(_envelope("query", _query_payload(args)), stdout=sys.stdout)
    return 0


def _handle_qa(args: argparse.Namespace) -> int:
    _emit_json(_envelope("qa", _qa_payload(args)), stdout=sys.stdout)
    return 0


def _handle_schema(_: argparse.Namespace) -> int:
    _emit_json(_envelope("schema", _capability_schema()), stdout=sys.stdout)
    return 0


def _capability_schema() -> dict[str, Any]:
    return {
        "name": "artificial-analysis",
        "description": (
            "AI-only fetch/analyze tool for canonical Artificial Analysis models "
            "and provider endpoints."
        ),
        "protocol_version": PROTOCOL_VERSION,
        "default_command": "fetch",
        "sources": {
            "rsc": {"url": BASE_URL, "required_headers": ["RSC: 1"]},
            "official_api": {
                "url": MODEL_API_URL,
                "credential_env": MODEL_API_KEY_ENV,
                "required_for": ["fetch"],
            },
        },
        "commands": {
            "fetch": {
                "description": (
                    "Fetch required RSC and authenticated official-model sources, "
                    "merge schema-v2 data, validate sanity thresholds, cache RSC "
                    "by ETag, and write outputs."
                ),
                "outputs": ["full-data.json", "endpoints.txt", "full-url.txt"],
                "flags": {
                    "output_json": (
                        "Path (default <temp-dir>/artifacts/"
                        "artificial-analysis/full-data.json)"
                    ),
                    "output_endpoints": (
                        "Path (default <temp-dir>/artifacts/"
                        "artificial-analysis/endpoints.txt)"
                    ),
                    "output_url": (
                        "Path (default <temp-dir>/artifacts/"
                        "artificial-analysis/full-url.txt)"
                    ),
                    "cache_dir": "Path to ETag/Last-Modified/payload cache",
                    "timeout_seconds": "float network timeout",
                    "min_endpoints": "int sanity threshold (default 700)",
                    "min_providers": "int sanity threshold (default 40)",
                    "stale_policy": "error|allow-last-good (default error)",
                    "allow_stale": "bool alias for stale_policy allow-last-good",
                    "strict": "bool alias for stale_policy error",
                },
            },
            "stats": {
                "description": "Read a snapshot and return counts + top providers.",
                "args": ["snapshot(optional)"],
                "flags": {"top": "int top N providers (default 10)"},
            },
            "diff": {
                "description": (
                    "Diff endpoint/provider deltas; optionally include schema-aware "
                    "model, metric, evidence, and diagnostic changes."
                ),
                "args": ["old_snapshot", "new_snapshot"],
                "flags": {
                    "schema_aware": "bool opt-in additive schema-aware diff",
                },
            },
            "diagnose": {
                "description": (
                    "Inspect explicit local snapshot/cache paths without network "
                    "access and return redacted health diagnostics."
                ),
                "args": ["snapshot(optional)"],
                "flags": {
                    "snapshot": "Path to a local snapshot",
                    "cache_dir": "Path to a local cache",
                },
                "network": False,
            },
            "harness": {
                "description": (
                    "Rank unique models by Harness = 50% Agentic Index + 50% "
                    "Coding Index."
                ),
                "args": ["snapshot(optional)"],
                "flags": {
                    "model": "str contains filter on model slug/name",
                    "creator": "str contains filter on creator/lab slug/name",
                    "open_weights_only": "bool only include open-weights models",
                    "limit": "int max rows (default 50)",
                },
            },
            "coding": {
                "description": (
                    "Fetch/query Coding Index capability rows with coding-only "
                    "output token composition."
                ),
                "source_url": CODING_CAPABILITY_URL,
                "flags": {
                    "model": "str contains filter on model slug/name",
                    "creator": "str contains filter on creator/lab name",
                    "open_weights_only": "bool only include open-weights models",
                    "sort_by": (
                        "coding|output_tokens|answer_tokens|reasoning_tokens|"
                        "input_tokens|cost"
                    ),
                    "order": "auto|asc|desc",
                    "limit": "int max rows (default 50)",
                    "include_benchmark_counts": (
                        "bool include Terminal-Bench Hard and SciCode token counts"
                    ),
                },
                "token_scope": (
                    "coding_index_only; not global Intelligence Index token counts"
                ),
            },
            "evaluation": {
                "description": (
                    "Extract generic model rows from a dedicated Artificial "
                    "Analysis evaluation page or saved HTML/RSC response."
                ),
                "args": ["url(optional when input is supplied)"],
                "flags": {
                    "input": "Path to saved HTML/RSC response",
                    "output_json": "Optional path for the full extracted row set",
                    "timeout_seconds": "float network timeout",
                    "min_rows": "minimum recognizable rows (default 1)",
                    "sort_by": "optional dotted numeric field path",
                    "order": "auto|asc|desc",
                    "limit": "optional maximum returned rows",
                },
                "value_status": "published rows; filters/counts are derived",
            },
            "reasoning": {
                "description": (
                    "Profile models by reasoning selectivity using per-benchmark "
                    "canonical eval token counts."
                ),
                "args": ["snapshot(optional)"],
                "flags": {
                    "model": "str contains filter on model slug/name",
                    "creator": "str contains filter on creator/lab name",
                    "open_weights_only": "bool only include open-weights models",
                    "class": (
                        "classification filter: selective_extreme|selective|"
                        "moderate|uniform_heavy|hard_uniform_heavy"
                    ),
                    "selective_only": "bool only include selective thinkers",
                    "sort_by": (
                        "harness|selectivity|reasoning_floor|"
                        "weighted_reasoning_share|intelligence|agentic|coding"
                    ),
                    "order": "auto|asc|desc",
                    "limit": "int max rows (default 50)",
                    "benchmarks": (
                        "bool include per-benchmark reasoning share breakdown"
                    ),
                },
            },
            "query": {
                "description": (
                    "Filter/sort endpoint benchmark rows by model/provider/endpoint."
                ),
                "args": ["snapshot(optional)"],
                "flags": {
                    "model": "str contains filter on model slug/name",
                    "provider": "str contains filter on provider slug/name",
                    "endpoint": "str contains filter on endpoint slug",
                    "sort_by": (
                        "harness|intelligence|agentic|coding|math|"
                        "price_blended|speed|ttfc|e2e"
                    ),
                    "order": "auto|asc|desc",
                    "limit": "int max rows (default 20)",
                },
            },
            "qa": {
                "description": (
                    "Minimal NL intent parser that maps a question to query "
                    "filters/sort and returns query output."
                ),
                "args": ["question", "snapshot(optional)"],
                "flags": {
                    "model": "override inferred model",
                    "provider": "override inferred provider",
                    "sort_by": "override inferred metric",
                    "order": "override inferred order",
                    "limit": "override inferred limit",
                },
            },
            "schema": {
                "description": "Return this machine-readable capability schema.",
            },
            "ping": {
                "description": "RPC-only health check.",
            },
            "get_schema": {
                "description": "RPC alias for schema.",
            },
        },
        "rpc": {
            "transport": "jsonl",
            "request": {
                "fields": ["id", "type|command", "args"],
            },
            "response": {
                "success": {
                    "fields": ["id", "type=response", "command", "success", "data"],
                },
                "error": {
                    "fields": [
                        "id",
                        "type=response",
                        "command",
                        "success=false",
                        "error",
                    ],
                },
            },
        },
    }


def _error_response(
    request_id: object,
    command: str,
    code: str,
    message: object,
    details: object | None = None,
) -> dict[str, Any]:
    error: dict[str, object] = {
        "code": code,
        "message": _safe_error_text(message),
    }
    if details:
        error["details"] = redact(details)
    return {
        "id": redact(request_id),
        "type": "response",
        "command": _safe_error_text(command),
        "success": False,
        "error": error,
    }


def _success_response(
    request_id: Any,
    command: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": request_id,
        "type": "response",
        "command": command,
        "success": True,
        "data": data,
    }


def _arg_value(args: dict[str, Any], key: str, default: Any) -> Any:
    if key in args:
        return args[key]
    camel = "".join(
        part.capitalize() if i else part for i, part in enumerate(key.split("_"))
    )
    return args.get(camel, default)


def _fetch_namespace(args: dict[str, Any]) -> argparse.Namespace:
    return argparse.Namespace(
        output_json=Path(_arg_value(args, "output_json", str(DEFAULT_OUTPUT_JSON))),
        output_endpoints=Path(
            _arg_value(args, "output_endpoints", str(DEFAULT_OUTPUT_ENDPOINTS)),
        ),
        output_url=Path(_arg_value(args, "output_url", str(DEFAULT_OUTPUT_URL))),
        cache_dir=Path(_arg_value(args, "cache_dir", str(_default_cache_dir()))),
        timeout_seconds=float(_arg_value(args, "timeout_seconds", 60.0)),
        min_endpoints=int(_arg_value(args, "min_endpoints", 700)),
        min_providers=int(_arg_value(args, "min_providers", 40)),
        stale_policy=str(_arg_value(args, "stale_policy", "error")),
        allow_stale=bool(_arg_value(args, "allow_stale", False)),
        strict=bool(_arg_value(args, "strict", False)),
    )


def _stats_namespace(args: dict[str, Any]) -> argparse.Namespace:
    return argparse.Namespace(
        snapshot=Path(_arg_value(args, "snapshot", str(DEFAULT_OUTPUT_JSON))),
        top=int(_arg_value(args, "top", 10)),
    )


def _harness_namespace(args: dict[str, Any]) -> argparse.Namespace:
    return argparse.Namespace(
        snapshot=Path(_arg_value(args, "snapshot", str(DEFAULT_OUTPUT_JSON))),
        model=_arg_value(args, "model", None),
        creator=_arg_value(args, "creator", None),
        open_weights_only=bool(_arg_value(args, "open_weights_only", False)),
        limit=int(_arg_value(args, "limit", 50)),
    )


def _coding_namespace(args: dict[str, Any]) -> argparse.Namespace:
    return argparse.Namespace(
        output_json=Path(
            _arg_value(args, "output_json", str(DEFAULT_CODING_OUTPUT_JSON)),
        ),
        timeout_seconds=float(_arg_value(args, "timeout_seconds", 60.0)),
        model=_arg_value(args, "model", None),
        creator=_arg_value(args, "creator", None),
        open_weights_only=bool(_arg_value(args, "open_weights_only", False)),
        sort_by=str(_arg_value(args, "sort_by", "coding")),
        order=str(_arg_value(args, "order", "auto")),
        limit=int(_arg_value(args, "limit", 50)),
        include_benchmark_counts=bool(
            _arg_value(args, "include_benchmark_counts", False),
        ),
    )


def _evaluation_namespace(args: dict[str, Any]) -> argparse.Namespace:
    input_value = _arg_value(args, "input", None)
    return argparse.Namespace(
        url=_arg_value(args, "url", None),
        input=Path(input_value) if input_value is not None else None,
        output_json=(
            Path(_arg_value(args, "output_json", ""))
            if _arg_value(args, "output_json", None) is not None
            else None
        ),
        timeout_seconds=float(_arg_value(args, "timeout_seconds", 60.0)),
        min_rows=int(_arg_value(args, "min_rows", 1)),
        sort_by=_arg_value(args, "sort_by", None),
        order=str(_arg_value(args, "order", "auto")),
        limit=(
            int(_arg_value(args, "limit", 0))
            if _arg_value(args, "limit", None) is not None
            else None
        ),
    )


def _reasoning_namespace(args: dict[str, Any]) -> argparse.Namespace:
    return argparse.Namespace(
        snapshot=Path(_arg_value(args, "snapshot", str(DEFAULT_OUTPUT_JSON))),
        model=_arg_value(args, "model", None),
        creator=_arg_value(args, "creator", None),
        open_weights_only=bool(_arg_value(args, "open_weights_only", False)),
        classification=_arg_value(args, "class", None),
        selective_only=bool(_arg_value(args, "selective_only", False)),
        sort_by=str(_arg_value(args, "sort_by", "harness")),
        order=str(_arg_value(args, "order", "auto")),
        limit=int(_arg_value(args, "limit", 50)),
        benchmarks=bool(_arg_value(args, "benchmarks", False)),
    )


def _diff_namespace(args: dict[str, Any]) -> argparse.Namespace:
    old_snapshot = _arg_value(args, "old_snapshot", None)
    new_snapshot = _arg_value(args, "new_snapshot", None)
    if not old_snapshot or not new_snapshot:
        _raise_cli_usage_error("diff requires old_snapshot and new_snapshot")
    return argparse.Namespace(
        old_snapshot=Path(str(old_snapshot)),
        new_snapshot=Path(str(new_snapshot)),
        schema_aware=bool(_arg_value(args, "schema_aware", False)),
    )


def _diagnose_namespace(args: dict[str, Any]) -> argparse.Namespace:
    snapshot = _arg_value(args, "snapshot", _arg_value(args, "snapshot_path", None))
    cache_dir = _arg_value(args, "cache_dir", _arg_value(args, "cache", None))
    return argparse.Namespace(
        snapshot=Path(str(snapshot)) if snapshot is not None else None,
        snapshot_path=None,
        cache_dir=Path(str(cache_dir)) if cache_dir is not None else None,
    )


def _query_namespace(args: dict[str, Any]) -> argparse.Namespace:
    return argparse.Namespace(
        snapshot=Path(_arg_value(args, "snapshot", str(DEFAULT_OUTPUT_JSON))),
        model=_arg_value(args, "model", None),
        provider=_arg_value(args, "provider", None),
        endpoint=_arg_value(args, "endpoint", None),
        sort_by=str(_arg_value(args, "sort_by", "intelligence")),
        order=str(_arg_value(args, "order", "auto")),
        limit=int(_arg_value(args, "limit", 20)),
    )


def _qa_namespace(args: dict[str, Any]) -> argparse.Namespace:
    question = _arg_value(args, "question", None)
    if not isinstance(question, str) or not question.strip():
        _raise_cli_usage_error("qa requires question")

    return argparse.Namespace(
        question=question,
        snapshot=Path(_arg_value(args, "snapshot", str(DEFAULT_OUTPUT_JSON))),
        model=_arg_value(args, "model", None),
        provider=_arg_value(args, "provider", None),
        sort_by=_arg_value(args, "sort_by", None),
        order=_arg_value(args, "order", None),
        limit=_arg_value(args, "limit", None),
    )


def run_rpc(*, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout

    for raw_line in input_stream:
        line = raw_line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            _emit_json(
                _error_response(
                    None,
                    "unknown",
                    "invalid_json",
                    "Request line is not valid JSON.",
                ),
                stdout=output_stream,
            )
            continue

        if not isinstance(request, dict):
            _emit_json(
                _error_response(
                    None,
                    "unknown",
                    "invalid_request",
                    "Request must be a JSON object.",
                ),
                stdout=output_stream,
            )
            continue

        request_id = request.get("id")
        command = request.get("type") or request.get("command")
        if not isinstance(command, str):
            _emit_json(
                _error_response(
                    request_id,
                    "unknown",
                    "missing_command",
                    "Missing type/command field.",
                ),
                stdout=output_stream,
            )
            continue

        args_payload = request.get("args", {})
        if not isinstance(args_payload, dict):
            _emit_json(
                _error_response(
                    request_id,
                    command,
                    "invalid_args",
                    "args must be an object.",
                ),
                stdout=output_stream,
            )
            continue
        try:
            if command == "ping":
                response = _success_response(
                    request_id,
                    command,
                    {"ok": True, "version": PROTOCOL_VERSION},
                )
            elif command in {"schema", "get_schema"}:
                response = _success_response(request_id, command, _capability_schema())
            elif command == "fetch":
                response = _success_response(
                    request_id,
                    command,
                    _fetch_payload(_fetch_namespace(args_payload)),
                )
            elif command == "stats":
                response = _success_response(
                    request_id,
                    command,
                    _stats_payload(_stats_namespace(args_payload)),
                )
            elif command == "diff":
                response = _success_response(
                    request_id,
                    command,
                    _diff_payload(_diff_namespace(args_payload)),
                )
            elif command == "diagnose":
                response = _success_response(
                    request_id,
                    command,
                    _diagnose_payload(_diagnose_namespace(args_payload)),
                )
            elif command == "harness":
                response = _success_response(
                    request_id,
                    command,
                    _harness_payload(_harness_namespace(args_payload)),
                )
            elif command == "coding":
                response = _success_response(
                    request_id,
                    command,
                    _coding_payload(_coding_namespace(args_payload)),
                )
            elif command == "evaluation":
                response = _success_response(
                    request_id,
                    command,
                    _evaluation_payload(_evaluation_namespace(args_payload)),
                )
            elif command == "reasoning":
                response = _success_response(
                    request_id,
                    command,
                    _reasoning_payload(_reasoning_namespace(args_payload)),
                )
            elif command == "query":
                response = _success_response(
                    request_id,
                    command,
                    _query_payload(_query_namespace(args_payload)),
                )
            elif command == "qa":
                response = _success_response(
                    request_id,
                    command,
                    _qa_payload(_qa_namespace(args_payload)),
                )
            else:
                response = _error_response(
                    request_id,
                    command,
                    "unknown_command",
                    f"Unknown command: {command}",
                )
        except CliUsageError as exc:
            response = _error_response(request_id, command, "usage_error", str(exc))
        except CacheError as exc:
            response = _error_response(
                request_id,
                command,
                exc.code,
                str(exc),
                exc.details,
            )
        except ExtractionError as exc:
            response = _error_response(
                request_id,
                command,
                "extraction_error",
                str(exc),
            )
        except (ValueError, TypeError) as exc:
            response = _error_response(
                request_id,
                command,
                "invalid_args",
                str(exc),
            )
        except OSError as exc:
            response = _error_response(request_id, command, "io_error", str(exc))

        try:
            _emit_json(response, stdout=output_stream)
        except (TypeError, ValueError):
            fallback = _error_response(
                request_id,
                command,
                "internal_error",
                "Response serialization failed.",
            )
            output_stream.write(compact_json(fallback) + "\n")

    return 0


def _mode_from_argv(values: list[str]) -> str:
    if not values:
        return "cli"
    for index, argument in enumerate(values):
        if argument == "--mode" and index + 1 < len(values):
            return values[index + 1]
        if argument.startswith("--mode="):
            return argument.split("=", 1)[1]
    return "cli"


def _command_from_argv(values: Sequence[str]) -> str:
    known = {
        "fetch",
        "stats",
        "diff",
        "diagnose",
        "harness",
        "coding",
        "evaluation",
        "reasoning",
        "query",
        "qa",
        "schema",
    }
    for index, value in enumerate(values):
        if value == "--mode":
            continue
        if value.startswith("--"):
            continue
        if value in {"cli", "rpc"} and index > 0 and values[index - 1] == "--mode":
            continue
        if value in known:
            return value
        if index == 0 or (index > 0 and values[index - 1] in {"--mode", "--mode=cli"}):
            return _safe_error_text(value)
    return "fetch"


def _json_errors_requested(values: Sequence[str]) -> bool:
    return "--json-errors" in values and "--legacy-errors" not in values


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return its exit status."""
    values = list(argv) if argv is not None else sys.argv[1:]
    if _mode_from_argv(values) == "rpc":
        return run_rpc()

    json_errors = _json_errors_requested(values)
    parser = build_parser()
    normalized_argv = _normalize_argv(values)
    command = _command_from_argv(normalized_argv)

    parse_context: contextlib.AbstractContextManager[object]
    parse_context = (
        contextlib.redirect_stderr(io.StringIO())
        if json_errors
        else contextlib.nullcontext()
    )
    try:
        with parse_context:
            args = parser.parse_args(normalized_argv)
    except SystemExit as exc:
        if json_errors:
            _emit_cli_error(
                command=command,
                code="usage_error",
                message="Invalid command arguments.",
                stdout=sys.stdout,
            )
        return _exit_code(exc.code)

    json_errors = bool(getattr(args, "json_errors", False)) and not bool(
        getattr(args, "legacy_errors", False),
    )
    command = str(getattr(args, "command", command) or command)
    handler = getattr(args, "handler", None)
    if handler is None:
        if json_errors:
            _emit_cli_error(
                command=command,
                code="usage_error",
                message="Missing command.",
                stdout=sys.stdout,
            )
        else:
            parser.print_usage(sys.stderr)
            sys.stderr.write(f"{parser.prog}: error: missing command\n")
        return 2

    error_message: object
    try:
        return int(handler(args))
    except CliUsageError as caught:
        error_message = caught
        code = "usage_error"
        status = 2
    except ExtractionError as caught:
        error_message = caught
        code = "extraction_error"
        status = 2
    except OSError as caught:
        error_message = caught
        code = "io_error"
        status = 1
    except (ValueError, TypeError) as caught:
        error_message = caught
        code = "invalid_args"
        status = 2

    if json_errors:
        _emit_cli_error(
            command=command, code=code, message=error_message, stdout=sys.stdout
        )
    else:
        sys.stderr.write(f"error: {_safe_error_text(error_message)}\n")
    return status


def _exit_code(code: object) -> int:
    return code if isinstance(code, int) else 1


if __name__ == "__main__":
    raise SystemExit(main())
