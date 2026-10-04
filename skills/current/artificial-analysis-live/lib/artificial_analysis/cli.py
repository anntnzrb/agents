# ruff: noqa: C901, D103, FBT003, PLR0915
"""Command-line and RPC interfaces for Artificial Analysis snapshots."""

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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from typing import NoReturn, TextIO

from .comparison import compare_models
from .contracts import (
    as_dict,
    as_list,
    compact_json,
    is_object_list,
    is_object_tuple,
    is_str_dict,
    parse_json,
)
from .diagnose import diagnose
from .diagnostics import redact, redact_query
from .diff import schema_aware_diff
from .evidence import (
    attach_payload_evidence,
    attach_row_evidence,
    lookup_path,
    numeric_scalar,
    source_hash_from_payload,
)
from .fetch_results import (
    materialize_fetch_result,
    result_artifact_ref,
    result_byte_length,
    result_etag,
    result_fetched_at,
    result_final_url,
    result_header,
    result_headers,
    result_last_modified,
    result_sha256,
    validate_304,
    validator_from,
)
from .overlap import overlap_metadata
from .requests import (
    DEFAULT_OUTPUT_ENDPOINTS,
    DEFAULT_OUTPUT_JSON,
    DEFAULT_OUTPUT_URL,
    EVALUATION_OPTIONS,
    QA_OPTIONS,
    QUERY_OPTIONS,
    STATS_OPTIONS,
    Option,
    decode_options,
    default_cache_dir,
    fetch_options,
    schema_options,
)
from .rsc import (
    BASE_URL,
    MODEL_API_KEY_ENV,
    MODEL_API_URL,
    CacheError,
    ExtractionError,
    FetchResult,
    atomic_write,
    build_full_url,
    build_snapshot_payload,
    endpoint_slugs,
    extract_evaluation_manifest,
    extract_evaluation_rows,
    extract_lists,
    fetch_manifest_models,
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


class _Subparsers(Protocol):
    def add_parser(self, name: str, *, help: str = ...) -> argparse.ArgumentParser: ...


PROTOCOL_VERSION = "1"

DEFAULT_SNAPSHOT_MAX_AGE = timedelta(hours=24)
MIN_QUOTED_VALUE_LENGTH = 2
SCHEMA_V2 = 2
NOT_MODIFIED = 304


def _as_dict(val: object) -> dict[str, object]:
    return as_dict(val)


def _as_list(val: object) -> list[object]:
    return as_list(val)


def _finite_number(value: object) -> bool:
    """Return whether value is a rankable, non-boolean finite scalar."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError, ValueError:
        return False


def _snapshot_overlap(
    snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    """Expose declarations without inventing overlap from source similarity."""
    if not isinstance(snapshot, dict):
        return overlap_metadata()
    meta = _as_dict(snapshot.get("meta"))
    source_val = snapshot.get("overlap")
    source: dict[str, object] = (
        source_val if is_str_dict(source_val) else as_dict(meta.get("overlap"))
    )
    declarations = source.get("declared_joins", source.get("overlap_claims"))
    left = source.get("left")
    right = source.get("right")
    dependencies = _as_list(source.get("dependencies", meta.get("dependencies", [])))
    independence = _as_list(source.get("independence", meta.get("independence", [])))
    return overlap_metadata(
        left=left,
        right=right,
        declarations=declarations,
        dependencies=dependencies,
        independence=independence,
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
    return default_cache_dir()


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
            _ = os.environ.setdefault(key, value)
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
    _ = parser.add_argument(
        "--json-errors",
        action="store_true",
        default=default,
        help="Emit one compact JSON error object on stdout.",
    )
    _ = parser.add_argument(
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
    _ = parser.add_argument(
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
    _add_evaluation_parser(subparsers)
    _add_query_parser(subparsers)
    _add_qa_parser(subparsers)
    _add_compare_parser(subparsers)
    _add_schema_parser(subparsers)
    for command_parser in subparsers.choices.values():
        _add_cli_error_flags(command_parser, suppress_defaults=True)
    return parser


def _add_fetch_parser(subparsers: _Subparsers) -> None:
    fetch_parser = subparsers.add_parser(
        "fetch",
        help=(
            "Fetch live RSC and authenticated official model data, then write "
            "a snapshot."
        ),
    )
    for option in fetch_options():
        option.add(fetch_parser)
    fetch_parser.set_defaults(handler=_handle_fetch)


def _add_stats_parser(subparsers: _Subparsers) -> None:
    stats_parser = subparsers.add_parser(
        "stats",
        help="Show snapshot counts and top providers.",
    )
    _ = stats_parser.add_argument(
        "snapshot",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
    )
    for option in STATS_OPTIONS:
        option.add(stats_parser)
    stats_parser.set_defaults(handler=_handle_stats)


def _add_diff_parser(subparsers: _Subparsers) -> None:
    diff_parser = subparsers.add_parser(
        "diff",
        help="Diff endpoint and provider changes between snapshots.",
    )
    _ = diff_parser.add_argument("old_snapshot", type=Path)
    _ = diff_parser.add_argument("new_snapshot", type=Path)
    _ = diff_parser.add_argument(
        "--schema-aware",
        action="store_true",
        help="Include deterministic model, metric, schema, and diagnostic changes.",
    )
    diff_parser.set_defaults(handler=_handle_diff)


def _add_diagnose_parser(subparsers: _Subparsers) -> None:
    diagnose_parser = subparsers.add_parser(
        "diagnose",
        help="Inspect local snapshot/cache health without fetching.",
    )
    _ = diagnose_parser.add_argument("snapshot", nargs="?", type=Path)
    _ = diagnose_parser.add_argument("--snapshot", dest="snapshot_path", type=Path)
    _ = diagnose_parser.add_argument("--cache-dir", type=Path, default=None)
    diagnose_parser.set_defaults(handler=_handle_diagnose)


def _add_evaluation_parser(subparsers: _Subparsers) -> None:
    evaluation_parser = subparsers.add_parser(
        "evaluation",
        help="Extract model rows from a dedicated Artificial Analysis evaluation page.",
    )
    _ = evaluation_parser.add_argument(
        "url", nargs="?", help="public evaluation page URL"
    )
    for option in EVALUATION_OPTIONS:
        option.add(evaluation_parser)
    evaluation_parser.set_defaults(handler=_handle_evaluation)


def _add_query_parser(subparsers: _Subparsers) -> None:
    query_parser = subparsers.add_parser(
        "query",
        help="Query model/provider benchmark rows from a snapshot.",
    )
    _ = query_parser.add_argument(
        "snapshot",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
    )
    for option in QUERY_OPTIONS:
        option.add(query_parser)
    query_parser.set_defaults(handler=_handle_query)


def _add_qa_parser(subparsers: _Subparsers) -> None:
    qa_parser = subparsers.add_parser(
        "qa",
        help="Minimal NL question command that maps intent to query filters/sort.",
    )
    _ = qa_parser.add_argument(
        "question",
        type=str,
        help="Natural-language question about models/providers.",
    )
    _ = qa_parser.add_argument(
        "snapshot",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
    )
    for option in QA_OPTIONS:
        option.add(qa_parser)
    qa_parser.set_defaults(handler=_handle_qa)


def _add_compare_parser(subparsers: _Subparsers) -> None:
    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare model family and effort variants from a snapshot.",
    )
    _ = compare_parser.add_argument(
        "snapshot",
        nargs="?",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
    )
    _ = compare_parser.add_argument(
        "--select",
        action="append",
        required=True,
        help="Repeatable selector: 'family' or 'family:effort1,effort2,...'",
    )
    compare_parser.set_defaults(handler=_handle_compare)


def _add_schema_parser(subparsers: _Subparsers) -> None:
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
        "evaluation",
        "query",
        "qa",
        "compare",
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


def _emit_json(payload: dict[str, object], *, stdout: TextIO) -> None:
    _ = stdout.write(
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
    payload: dict[str, object] = {
        "ok": False,
        "version": PROTOCOL_VERSION,
        "command": command,
        "error": error,
    }
    _ = stdout.write(compact_json(payload) + "\n")


def _envelope(command: str, data: dict[str, object]) -> dict[str, object]:
    return {
        "ok": True,
        "version": PROTOCOL_VERSION,
        "command": command,
        "data": data,
    }


def _ensure_default_snapshot_fresh(path: Path, snapshot: dict[str, object]) -> None:
    if path != DEFAULT_OUTPUT_JSON:
        return

    meta = _as_dict(snapshot.get("meta"))
    fetched_at = meta.get("fetched_at")
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


def _load_reader_snapshot(path: Path) -> dict[str, object]:
    snapshot = load_snapshot(path)
    _ensure_default_snapshot_fresh(path, snapshot)
    return snapshot


def _schema_version(snapshot: dict[str, object]) -> int:
    meta = _as_dict(snapshot.get("meta"))
    version = meta.get("schema_version")
    return version if isinstance(version, int) else 1


def _canonical_models(
    snapshot: dict[str, object],
) -> dict[str, dict[str, object]]:
    if _schema_version(snapshot) < SCHEMA_V2:
        return {}
    models_val = snapshot.get("models")
    if not is_object_list(models_val):
        _raise_extraction_error("Schema-v2 snapshot missing models list")
    result: dict[str, dict[str, object]] = {}
    for item in models_val:
        if is_str_dict(item):
            slug = item.get("slug")
            if isinstance(slug, str) and slug:
                result[slug] = item
    return result


def _model_rows(snapshot: dict[str, object]) -> list[dict[str, object]]:
    canonical = _canonical_models(snapshot)
    if canonical:
        return list(canonical.values())
    hosts_models_val = snapshot.get("hosts_models")
    if not is_object_list(hosts_models_val):
        _raise_extraction_error("Snapshot missing hosts_models list")
    result: list[dict[str, object]] = []
    for item in hosts_models_val:
        if is_str_dict(item):
            model_val = item.get("model")
            if is_str_dict(model_val) and isinstance(model_val.get("slug"), str):
                result.append(model_val)
    return result


def _cached_source_info(
    cache_dir: Path,
) -> tuple[bytes, dict[str, object]] | None:
    cached = load_cached_artifact(cache_dir, source_key=BASE_URL)
    if cached is not None:
        return cached
    return None


def _stale_allowed(args: argparse.Namespace) -> bool:
    if bool(getattr(args, "strict", False)):
        return False
    return bool(getattr(args, "allow_stale", False)) or (
        getattr(args, "stale_policy", "error") == "allow-last-good"
    )


def _mark_stale_payload(
    fallback_payload: dict[str, object],
    *,
    reason: str,
) -> dict[str, object]:
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


def _ns_path(args: object, name: str, default: Path) -> Path:
    val = getattr(args, name, default)
    if isinstance(val, Path):
        return val
    if isinstance(val, str):
        return Path(val)
    return default


def _ns_optional_path(
    args: object, name: str, default: Path | None = None
) -> Path | None:
    val = getattr(args, name, default)
    if val is None:
        return None
    if isinstance(val, Path):
        return val
    if isinstance(val, str):
        return Path(val) if val else None
    return default


def _ns_str(args: object, name: str, default: str = "") -> str:
    val = getattr(args, name, default)
    return val if isinstance(val, str) else default


def _ns_optional_str(args: object, name: str, default: str | None = None) -> str | None:
    val = getattr(args, name, default)
    return val if isinstance(val, str) else default


def _ns_int(args: object, name: str, default: int = 0) -> int:
    val = getattr(args, name, default)
    if isinstance(val, int) and not isinstance(val, bool):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, (str, bytes, bytearray)):
        try:
            return int(val)
        except ValueError:
            return default
    return default


def _ns_optional_int(args: object, name: str, default: int | None = None) -> int | None:
    val = getattr(args, name, default)
    if val is None:
        return None
    if isinstance(val, int) and not isinstance(val, bool):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, (str, bytes, bytearray)):
        try:
            return int(val)
        except ValueError:
            return default
    return default


def _ns_float(args: object, name: str, default: float = 0.0) -> float:
    val = getattr(args, name, default)
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    if isinstance(val, (str, bytes, bytearray)):
        try:
            return float(val)
        except ValueError:
            return default
    return default


def _fetch_payload(args: argparse.Namespace) -> dict[str, object]:
    api_key = _required_api_key()
    cache_dir = _ns_path(args, "cache_dir", _default_cache_dir())
    output_json = _ns_path(args, "output_json", DEFAULT_OUTPUT_JSON)
    output_endpoints = _ns_path(args, "output_endpoints", DEFAULT_OUTPUT_ENDPOINTS)
    output_url = _ns_path(args, "output_url", DEFAULT_OUTPUT_URL)
    timeout_seconds = _ns_float(args, "timeout_seconds", 60.0)
    min_endpoints = _ns_int(args, "min_endpoints", 700)
    min_providers = _ns_int(args, "min_providers", 40)

    cache_meta = load_cache_metadata(cache_dir)
    cached = _cached_source_info(cache_dir)
    cached_record = cached[1] if cached is not None else None
    sent_etag = validator_from(cache_meta, cached_record, "etag")
    sent_last_modified = validator_from(cache_meta, cached_record, "last_modified")
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
            timeout_seconds=timeout_seconds,
            if_none_match=sent_etag,
            if_modified_since=sent_last_modified,
        )
        result = materialize_fetch_result(result, fallback_url=BASE_URL)
        if result.status_code == NOT_MODIFIED:
            result = validate_304(
                result,
                cached,
                sent_etag=sent_etag,
                sent_last_modified=sent_last_modified,
            )
            reused_cached_body = True
            freshness = "cache-revalidated"
        response_etag = result_etag(result) or sent_etag
        response_last_modified = result_last_modified(result) or sent_last_modified
        official_result = materialize_fetch_result(
            fetch_models(api_key, timeout_seconds=timeout_seconds),
            fallback_url=(
                os.environ.get("ARTIFICIAL_ANALYSIS_API_BASE_URL") or MODEL_API_URL
            ),
        )
        body = result.body
        frames = parse_json_frames(body)
        raw_models, raw_hosts, raw_hosts_models = extract_lists(frames)
        models = _as_list(raw_models)
        hosts = _as_list(raw_hosts)
        hosts_models = _as_list(raw_hosts_models)
        official_models = normalize_official_models(official_result.body)
        slugs = endpoint_slugs(hosts_models)
        sanity_check(
            slugs=slugs,
            min_endpoints=min_endpoints,
            min_providers=min_providers,
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
        fallback_payload = load_last_good_snapshot(cache_dir)
        fallback_source = "cache:last-good"
        if fallback_payload is None and output_json.exists():
            try:
                fallback_payload = load_snapshot(output_json)
            except ExtractionError:
                fallback_payload = None
            else:
                fallback_source = f"file:{output_json}"
        if fallback_payload is None:
            message = f"Fresh fetch failed and no last-good snapshot exists ({exc})."
            _raise_extraction_error(message, exc)
        slugs = snapshot_slugs(fallback_payload)
        sanity_check(
            slugs=slugs,
            min_endpoints=min_endpoints,
            min_providers=min_providers,
        )
        payload = _mark_stale_payload(fallback_payload, reason=fallback_reason)
        freshness = "stale-last-good"
        fallback_used = True

    full_url = build_full_url(slugs)
    write_outputs(
        output_json=output_json,
        output_endpoints=output_endpoints,
        output_url=output_url,
        payload=payload,
        slugs=slugs,
        full_url=full_url,
    )

    if not fallback_used and result is not None:
        save_cache(
            cache_dir=cache_dir,
            fetched_at=result_fetched_at(result),
            status_code=result.status_code,
            etag=response_etag,
            last_modified=response_last_modified,
            body=None if result.status_code == NOT_MODIFIED else result.body,
            source_url=BASE_URL,
            final_url=result_final_url(result),
            headers=result_headers(result),
        )
        _ = save_last_good_snapshot(cache_dir, payload)

    rsc_source: dict[str, object] = {
        "url": redact_query(BASE_URL),
        "final_url": (
            redact_query(result_final_url(result, BASE_URL) or BASE_URL)
            if result is not None
            else None
        ),
        "status_code": result.status_code if result is not None else None,
        "etag_sent": sent_etag,
        "etag_received": response_etag,
        "last_modified_sent": sent_last_modified,
        "last_modified_received": response_last_modified,
        "sha256": result_sha256(result) if result is not None else None,
        "byte_length": result_byte_length(result) if result is not None else None,
        "artifact_ref": result_artifact_ref(result) if result is not None else None,
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
                result_final_url(
                    official_result,
                    os.environ.get("ARTIFICIAL_ANALYSIS_API_BASE_URL") or MODEL_API_URL,
                )
                or api_url,
            )
            if official_result is not None
            else None
        ),
        "status_code": (
            official_result.status_code if official_result is not None else None
        ),
        "etag_received": (
            result_etag(official_result) if official_result is not None else None
        ),
        "last_modified_received": (
            result_last_modified(official_result)
            if official_result is not None
            else None
        ),
        "sha256": (
            result_sha256(official_result) if official_result is not None else None
        ),
        "byte_length": (
            result_byte_length(official_result) if official_result is not None else None
        ),
        "artifact_ref": (
            result_artifact_ref(official_result)
            if official_result is not None
            else None
        ),
        "reused_cached_payload": False,
        "freshness": freshness if fallback_used else "fresh",
    }

    meta_payload = _as_dict(payload.get("meta"))
    counts_payload = _as_dict(meta_payload.get("counts"))

    return {
        "sources": {"rsc": rsc_source, "official_api": official_source},
        "counts": counts_payload,
        "freshness": {
            "mode": freshness,
            "stale": freshness == "stale-last-good",
            "fallback": fallback_used,
        },
        "outputs": {
            "json": str(output_json),
            "endpoints": str(output_endpoints),
            "url": str(output_url),
        },
        "cache": {"dir": str(cache_dir)},
        "fallback": {
            "used": fallback_used,
            "source": fallback_source,
            "reason": fallback_reason,
            "strict": bool(getattr(args, "strict", False)),
            "policy": ("allow-last-good" if _stale_allowed(args) else "error"),
        },
    }


def _stats_payload(args: argparse.Namespace) -> dict[str, object]:
    snapshot_path = _ns_path(args, "snapshot", DEFAULT_OUTPUT_JSON)
    top_limit = _ns_int(args, "top", 10)
    snapshot = _load_reader_snapshot(snapshot_path)
    slugs = snapshot_slugs(snapshot)
    providers = _provider_counts_from_snapshot(snapshot)
    top = sorted(providers.items(), key=lambda item: (-item[1], item[0]))[
        : max(top_limit, 0)
    ]

    models_val = _as_list(snapshot.get("models"))
    hosts_val = _as_list(snapshot.get("hosts"))
    hosts_models_val = _as_list(snapshot.get("hosts_models"))

    payload: dict[str, object] = {
        "snapshot": str(snapshot_path),
        "counts": {
            "models": len(models_val),
            "hosts": len(hosts_val),
            "hosts_models": len(hosts_models_val),
            "endpoint_slugs": len(slugs),
            "providers": len(providers),
        },
        "top_providers": [
            {"provider": name, "endpoints": count} for name, count in top
        ],
        "overlap": _snapshot_overlap(snapshot),
    }
    return attach_payload_evidence(payload)


def _diff_payload(args: argparse.Namespace) -> dict[str, object]:
    old_snapshot_path = _ns_path(args, "old_snapshot", DEFAULT_OUTPUT_JSON)
    new_snapshot_path = _ns_path(args, "new_snapshot", DEFAULT_OUTPUT_JSON)
    old_snapshot = load_snapshot(old_snapshot_path)
    new_snapshot = load_snapshot(new_snapshot_path)

    old_slugs = set(snapshot_slugs(old_snapshot))
    new_slugs = set(snapshot_slugs(new_snapshot))

    added = sorted(new_slugs - old_slugs)
    removed = sorted(old_slugs - new_slugs)

    old_provider_counts = _provider_counts_from_snapshot(old_snapshot)
    new_provider_counts = _provider_counts_from_snapshot(new_snapshot)

    provider_deltas: list[dict[str, object]] = []
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

    payload: dict[str, object] = {
        "old_snapshot": _safe_error_text(old_snapshot_path),
        "new_snapshot": _safe_error_text(new_snapshot_path),
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
    return attach_payload_evidence(payload)


def _diagnose_payload(args: argparse.Namespace) -> dict[str, object]:
    snapshot_path = _ns_optional_path(args, "snapshot_path") or _ns_optional_path(
        args, "snapshot"
    )
    cache_dir = _ns_optional_path(args, "cache_dir")
    return diagnose(snapshot_path=snapshot_path, cache_dir=cache_dir)


def _evaluation_payload(args: argparse.Namespace) -> dict[str, object]:
    input_path = _ns_optional_path(args, "input")
    url_arg = _ns_optional_str(args, "url")
    output_json_path = _ns_optional_path(args, "output_json")
    timeout_seconds = _ns_float(args, "timeout_seconds", 60.0)
    min_rows = _ns_int(args, "min_rows", 1)
    sort_by = _ns_optional_str(args, "sort_by")
    order = _ns_str(args, "order", "auto")
    limit_arg = _ns_optional_int(args, "limit")

    if input_path is not None and url_arg is not None:
        _raise_cli_usage_error("evaluation accepts either url or --input, not both")
    if input_path is None and not isinstance(url_arg, str):
        _raise_cli_usage_error("evaluation requires a URL or --input")
    if min_rows < 1:
        _raise_cli_usage_error("min_rows must be positive")
    if limit_arg is not None and limit_arg < 0:
        _raise_cli_usage_error("limit must be non-negative")

    result: FetchResult | None = None
    if input_path is not None:
        try:
            body = input_path.read_text(encoding="utf-8")
        except OSError as exc:
            message = f"Cannot read evaluation input: {input_path}"
            raise CliUsageError(message) from exc
        source_url = input_path.resolve().as_uri()
        source_status = 200
        fetched_at = datetime.now(UTC).isoformat()
        content_type: str | None = "local"
        freshness = "snapshot"
        final_url: str | None = source_url
        etag = None
        last_modified = None
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        byte_length: int | None = len(body.encode("utf-8"))
    else:
        if not isinstance(url_arg, str):
            _raise_cli_usage_error("evaluation requires --url when --input is absent")
        if urlsplit(url_arg).scheme.casefold() != "https":
            _raise_cli_usage_error("evaluation public URL must use HTTPS")
        result = materialize_fetch_result(
            fetch_page(url_arg, timeout_seconds=timeout_seconds),
            fallback_url=url_arg,
        )
        body = result.body
        source_url = redact_query(url_arg)
        source_status = result.status_code
        fetched_at = result_fetched_at(result)
        content_type = result_header(result, "content-type")
        freshness = "fresh"
        final_url = redact_query(result_final_url(result, url_arg) or url_arg)
        etag = result_etag(result)
        last_modified = result_last_modified(result)
        digest = result_sha256(result)
        byte_length = result_byte_length(result)

    frames = parse_next_payload(body)
    manifest = extract_evaluation_manifest(frames)
    population_source: dict[str, object] | None = None
    if manifest is not None and input_path is None:
        rows, population_source = fetch_manifest_models(
            manifest,
            base_url=source_url,
            timeout_seconds=timeout_seconds,
        )
        if len(rows) < min_rows:
            _raise_extraction_error(
                "Evaluation manifest has fewer than min_rows models"
            )
    else:
        rows = extract_evaluation_rows(frames, min_rows=min_rows)
    rows_digest = (
        str(population_source["sha256"]) if population_source is not None else digest
    )
    for row_index, row in enumerate(rows):
        row["value_status"] = "published"
        metric_paths = tuple(
            key
            for key, value in row.items()
            if key not in {"value_status", "raw_fields", "unknowns"}
            and (
                numeric_scalar(value)
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
            "terminalbenchv40",
            "terminalbenchv21",
            "automationbenchpartialscore",
            "intelligenceindex",
            "gdppdfallpass",
        }
        _ = attach_row_evidence(
            row,
            metric_paths=metric_paths,
            source_prefix=f"$.rows[{row_index}]",
            artifact_hash=rows_digest,
            raw_values={key: row.get(key) for key in metric_paths},
            unknown_paths=tuple(
                key for key in metric_paths if key.casefold() not in known_metric_fields
            ),
        )
    if sort_by:
        if not any(
            _nested_sort_metric(row, sort_by, reverse=False)[0] == 0 for row in rows
        ):
            _raise_cli_usage_error(
                f"No comparable published values for sort field {sort_by!r}"
            )
        reverse = order in {"auto", "desc"}
        rows.sort(
            key=lambda row: _nested_sort_metric(
                row,
                sort_by,
                reverse=reverse,
            ),
        )
    limited = rows if limit_arg is None else rows[:limit_arg]
    source: dict[str, object] = {
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
    filters: dict[str, object] = {
        "min_rows": min_rows,
        "sort_by": sort_by,
        "order": order,
        "limit": limit_arg,
    }
    payload: dict[str, object] = {
        "meta": {
            "source": source,
            "population_source": population_source,
            "coverage": (
                "manifest_models"
                if population_source is not None
                else "initial_models_only"
                if manifest is not None
                else "embedded_rows"
            ),
            "filters_applied": filters,
            "freshness": {"mode": freshness, "stale": False, "fallback": False},
        },
        "rows": rows,
        "overlap": overlap_metadata(),
        "derived": {
            "sort": {
                "formula": f"sort by {sort_by}" if sort_by else None,
                "input_paths": [f"$.rows[*].{sort_by}"] if sort_by else [],
            },
            "limit": {
                "formula": "rows[:limit]",
                "input_paths": ["$.rows"],
            },
        },
    }
    _ = attach_payload_evidence(payload, artifact_hash=digest)
    if output_json_path is not None:
        atomic_write(
            output_json_path,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )

    result_payload: dict[str, object] = {
        "value_status": "published",
        "source": source,
        "population_source": population_source,
        "coverage": (
            "manifest_models"
            if population_source is not None
            else "initial_models_only"
            if manifest is not None
            else "embedded_rows"
        ),
        "filters_applied": filters,
        "freshness": {"mode": freshness, "stale": False, "fallback": False},
        "counts": {
            "frames": len(frames),
            "matched_rows": len(rows),
            "returned_rows": len(limited),
        },
        "output_json": str(output_json_path) if output_json_path else None,
        "rows": limited,
        "overlap": overlap_metadata(),
        "derived": payload["derived"],
    }
    return attach_payload_evidence(result_payload, artifact_hash=digest)


def _nested_sort_metric(
    row: dict[str, object],
    path: str,
    *,
    reverse: bool,
) -> tuple[int, float]:
    current: object = lookup_path(row, path)
    evidence = _as_dict(row.get("metric_evidence"))
    target_evidence = evidence.get(path)
    if is_str_dict(target_evidence):
        eligibility = target_evidence.get(
            "comparison_eligibility", target_evidence.get("eligibility")
        )
        if eligibility != "eligible":
            return (1, 0.0)
        current = target_evidence.get(
            "normalized_value", target_evidence.get("normalized")
        )
    if _finite_number(current) and isinstance(current, (int, float)):
        normalized = -float(current) if reverse else float(current)
        return (0, normalized)
    return (1, 0.0)


def _matches_any(needle: str, values: Sequence[object]) -> bool:
    return any(isinstance(value, str) and needle in value.lower() for value in values)


def _query_row(
    item: object,
    canonical_models: dict[str, dict[str, object]],
    model_filter: str | None,
    provider_filter: str | None,
    endpoint_filter: str | None,
) -> dict[str, object] | None:
    if not is_str_dict(item):
        return None
    item_dict = item
    endpoint_slug = item_dict.get("slug")
    if not isinstance(endpoint_slug, str) or "_" not in endpoint_slug:
        return None
    host = _as_dict(item_dict.get("host"))
    if canonical_models:
        endpoint_model_slug = item_dict.get("model_slug")
        model = (
            canonical_models.get(endpoint_model_slug)
            if isinstance(endpoint_model_slug, str)
            else None
        )
        if model is None:
            return None
    else:
        model = _as_dict(item_dict.get("model"))

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

    timescale = _as_dict(item_dict.get("timescaleData"))
    e2e = _as_dict(item_dict.get("end_to_end_response_time_metrics"))
    blended_field = (
        "price_1m_blended_7_to_2_to_1"
        if "price_1m_blended_7_to_2_to_1" in item_dict
        else "price_1m_blended_3_to_1"
    )
    row: dict[str, object] = {
        "endpoint_slug": endpoint_slug,
        "endpoint_name": item_dict.get("name"),
        "model_slug": model_slug,
        "model_name": model_name,
        "provider_slug": provider_slug,
        "provider_name": provider_name,
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
        "price_input": item_dict.get("price_1m_input_tokens"),
        "price_output": item_dict.get("price_1m_output_tokens"),
        "price_blended": item_dict.get(blended_field),
        "speed": timescale.get("median_output_speed"),
        "ttfc": timescale.get("median_time_to_first_chunk"),
        "e2e": e2e.get("total_time"),
        "context_window_tokens": item_dict.get("context_window_tokens"),
        "host_api_id": item_dict.get("host_api_id"),
    }
    for preserved_key in ("raw_fields", "unknowns"):
        for source in (item_dict, model):
            preserved = source.get(preserved_key)
            if is_str_dict(preserved):
                row[preserved_key] = dict(preserved)
                break
            if is_object_list(preserved):
                row[preserved_key] = list(preserved)
                break
    _ = attach_row_evidence(
        row,
        metric_paths=(
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
            "price_input": item_dict.get("price_1m_input_tokens"),
            "price_output": item_dict.get("price_1m_output_tokens"),
            "price_blended": item_dict.get(blended_field),
            "speed": timescale.get("median_output_speed"),
            "ttfc": timescale.get("median_time_to_first_chunk"),
            "e2e": e2e.get("total_time"),
            "context_window_tokens": item_dict.get("context_window_tokens"),
        },
    )
    return row


def _query_payload(args: argparse.Namespace) -> dict[str, object]:
    snapshot_path = _ns_path(args, "snapshot", DEFAULT_OUTPUT_JSON)
    model_arg = _ns_optional_str(args, "model")
    provider_arg = _ns_optional_str(args, "provider")
    endpoint_arg = _ns_optional_str(args, "endpoint")
    sort_key = _ns_str(args, "sort_by", "intelligence")
    order_arg = _ns_str(args, "order", "auto")
    limit_arg = _ns_int(args, "limit", 20)

    snapshot = _load_reader_snapshot(snapshot_path)
    hosts_models_val = snapshot.get("hosts_models")
    if not is_object_list(hosts_models_val):
        _raise_extraction_error("Snapshot missing hosts_models list")
    hosts_models = hosts_models_val
    canonical_models = _canonical_models(snapshot)

    model_filter = model_arg.lower() if model_arg else None
    provider_filter = provider_arg.lower() if provider_arg else None
    endpoint_filter = endpoint_arg.lower() if endpoint_arg else None

    rows: list[dict[str, object]] = []
    for item in hosts_models:
        if row := _query_row(
            item,
            canonical_models,
            model_filter,
            provider_filter,
            endpoint_filter,
        ):
            rows.append(row)

    reverse = _resolve_reverse(sort_key=sort_key, order=order_arg)
    rows.sort(key=lambda row: _sort_metric(row, sort_key, reverse=reverse))
    limited = rows[: max(limit_arg, 0)]
    provider_counts = _provider_counts_from_rows(rows)
    model_counts: dict[str, int] = {}
    for row in rows:
        model_slug = row.get("model_slug")
        if isinstance(model_slug, str):
            model_counts[model_slug] = model_counts.get(model_slug, 0) + 1

    payload: dict[str, object] = {
        "snapshot": str(snapshot_path),
        "applied_filters": {
            "model": model_arg,
            "provider": provider_arg,
            "endpoint": endpoint_arg,
            "sort_by": sort_key,
            "order": order_arg,
            "limit": limit_arg,
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
    return attach_payload_evidence(payload)


def _resolve_reverse(*, sort_key: str, order: str) -> bool:
    if order == "asc":
        return False
    if order == "desc":
        return True
    return sort_key not in {"price_blended", "ttfc", "e2e"}


def _sort_metric(
    row: dict[str, object],
    metric: str,
    *,
    reverse: bool,
) -> tuple[int, float]:
    value: object = row.get(metric)
    evidence = _as_dict(row.get("metric_evidence"))
    target_evidence = evidence.get(metric)
    if is_str_dict(target_evidence):
        eligibility = target_evidence.get(
            "comparison_eligibility", target_evidence.get("eligibility")
        )
        if eligibility != "eligible":
            return (1, 0.0)
        value = target_evidence.get(
            "normalized_value", target_evidence.get("normalized")
        )
    if _finite_number(value) and isinstance(value, (int, float)):
        normalized = -float(value) if reverse else float(value)
        return (0, normalized)
    return (1, 0.0)


def _provider_counts_from_rows(rows: list[dict[str, object]]) -> dict[str, int]:
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


def _provider_counts_from_snapshot(snapshot: dict[str, object]) -> dict[str, int]:
    hosts_models_val = snapshot.get("hosts_models")
    if not is_object_list(hosts_models_val):
        _raise_extraction_error("Snapshot missing hosts_models list")

    counts: dict[str, int] = {}
    for item in hosts_models_val:
        if not is_str_dict(item):
            continue
        item_dict = item
        provider: str | None = None
        host = _as_dict(item_dict.get("host"))
        if isinstance(host.get("slug"), str):
            provider = str(host["slug"])
        elif isinstance(item_dict.get("slug"), str) and "_" in str(
            item_dict.get("slug")
        ):
            provider = str(item_dict["slug"]).split("_", 1)[0]

        if provider:
            counts[provider] = counts.get(provider, 0) + 1
    return counts


def _is_multi_model_question(question: str) -> bool:
    q = question.lower().strip()
    if re.search(r"\b(vs\.?|versus|against|compared\s+to)\b", q):
        return True
    return bool(re.search(r"\bcompare\b", q) and re.search(r"\b(and|with|to)\b", q))


def _qa_payload(args: argparse.Namespace) -> dict[str, object]:
    question_arg = _ns_str(args, "question")
    question = question_arg.strip()
    if not question:
        _raise_cli_usage_error("qa requires a non-empty question")
    if _is_multi_model_question(question):
        msg = (
            "Multi-model comparison questions are not supported by the 'qa' command. "
            "Use the 'compare' command with repeatable '--select' selectors instead, "
            "e.g.: compare --select '<family1>' --select '<family2>'."
        )
        _raise_cli_usage_error(msg)

    snapshot_path = _ns_path(args, "snapshot", DEFAULT_OUTPUT_JSON)
    model_arg = _ns_optional_str(args, "model")
    provider_arg = _ns_optional_str(args, "provider")
    sort_by_arg = _ns_optional_str(args, "sort_by")
    order_arg = _ns_optional_str(args, "order")
    limit_arg = _ns_optional_int(args, "limit")

    snapshot = _load_reader_snapshot(snapshot_path)
    hosts_models_val = snapshot.get("hosts_models")
    if not is_object_list(hosts_models_val):
        _raise_extraction_error("Snapshot missing hosts_models list")
    hosts_models = hosts_models_val

    inferred_model = model_arg or _infer_model(question, _model_rows(snapshot))
    inferred_provider = provider_arg or _infer_provider(question, hosts_models)
    inferred_sort_by, inferred_order = _infer_sort(question)

    sort_by = sort_by_arg or inferred_sort_by
    order = order_arg or inferred_order
    limit = limit_arg if isinstance(limit_arg, int) else _infer_limit(question)

    query_ns = argparse.Namespace(
        snapshot=snapshot_path,
        model=inferred_model,
        provider=inferred_provider,
        endpoint=None,
        sort_by=sort_by,
        order=order,
        limit=limit,
    )

    query_result = _query_payload(query_ns)

    payload: dict[str, object] = {
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
    return attach_payload_evidence(payload)


def _normalize_for_match(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _infer_model(question: str, models: list[dict[str, object]]) -> str | None:
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


def _infer_provider(question: str, hosts_models: list[object]) -> str | None:
    question_norm = _normalize_for_match(question)
    best: tuple[int, str] | None = None

    for item in hosts_models:
        if not is_str_dict(item):
            continue
        item_dict = item
        host = _as_dict(item_dict.get("host"))
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


def _handle_evaluation(args: argparse.Namespace) -> int:
    _emit_json(
        _envelope("evaluation", _evaluation_payload(args)),
        stdout=sys.stdout,
    )
    return 0


def _handle_query(args: argparse.Namespace) -> int:
    _emit_json(_envelope("query", _query_payload(args)), stdout=sys.stdout)
    return 0


def _handle_qa(args: argparse.Namespace) -> int:
    _emit_json(_envelope("qa", _qa_payload(args)), stdout=sys.stdout)
    return 0


def _compare_payload(args: argparse.Namespace) -> dict[str, object]:
    snapshot_path = _ns_path(args, "snapshot", DEFAULT_OUTPUT_JSON)
    select_arg = vars(args).get("select")
    selectors: list[str] = []
    if isinstance(select_arg, str):
        selectors = [select_arg]
    elif is_object_list(select_arg) or is_object_tuple(select_arg):
        if any(not isinstance(value, str) for value in select_arg):
            _raise_cli_usage_error("compare selectors must be strings")
        selectors = [value for value in select_arg if isinstance(value, str)]
    elif select_arg is not None:
        _raise_cli_usage_error("compare selectors must be strings")
    if not selectors:
        _raise_cli_usage_error("compare requires at least one --select selector")

    snapshot = _load_reader_snapshot(snapshot_path)
    payload = compare_models(
        snapshot,
        snapshot_path,
        selectors,
        usage_error_factory=CliUsageError,
    )
    meta = _as_dict(snapshot.get("meta"))
    historical = snapshot_path != DEFAULT_OUTPUT_JSON
    freshness = _as_dict(meta.get("freshness"))
    payload["freshness"] = {
        **freshness,
        "mode": "snapshot" if historical else freshness.get("mode", "fresh"),
        "historical": historical,
        "stale": False if historical else freshness.get("stale", False),
    }
    payload["overlap"] = _snapshot_overlap(snapshot)
    model_positions = {
        model.get("slug"): index for index, model in enumerate(_model_rows(snapshot))
    }
    rows_val = payload.get("rows")
    if is_object_list(rows_val):
        for row in rows_val:
            if is_str_dict(row):
                source_index = model_positions[row.get("slug")]
                _ = attach_row_evidence(
                    row,
                    source_prefix=f"$.models[{source_index}]",
                    artifact_hash=source_hash_from_payload(snapshot),
                )
    return payload


def _handle_compare(args: argparse.Namespace) -> int:
    _emit_json(_envelope("compare", _compare_payload(args)), stdout=sys.stdout)
    return 0


def _handle_schema(_: argparse.Namespace) -> int:
    _emit_json(_envelope("schema", _capability_schema()), stdout=sys.stdout)
    return 0


def _capability_schema() -> dict[str, object]:
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
            },
        },
        "required_for": ["fetch"],
        "commands": {
            "fetch": {
                "description": (
                    "Fetch required RSC and authenticated official-model sources, "
                    "merge schema-v2 data, validate sanity thresholds, cache RSC "
                    "by ETag, and write outputs."
                ),
                "outputs": ["full-data.json", "endpoints.txt", "full-url.txt"],
                "flags": schema_options(fetch_options()),
            },
            "stats": {
                "description": "Read a snapshot and return counts + top providers.",
                "args": ["snapshot (optional)"],
                "flags": schema_options(STATS_OPTIONS),
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
                "args": ["snapshot (optional)"],
                "flags": {
                    "snapshot": "Path to a local snapshot",
                    "cache_dir": "Path to a local cache",
                },
                "network": False,
            },
            "evaluation": {
                "description": (
                    "Extract generic model rows from a dedicated Artificial "
                    "Analysis evaluation page or saved HTML/RSC response."
                ),
                "args": ["url (optional when input is supplied)"],
                "flags": schema_options(EVALUATION_OPTIONS),
                "value_status": "published rows; filters/counts are derived",
            },
            "query": {
                "description": (
                    "Filter/sort endpoint benchmark rows by model/provider/endpoint."
                ),
                "args": ["snapshot (optional)"],
                "flags": schema_options(QUERY_OPTIONS),
            },
            "qa": {
                "description": (
                    "Minimal NL intent parser that maps a question to query "
                    "filters/sort and returns query output."
                ),
                "args": ["question", "snapshot (optional)"],
                "flags": schema_options(QA_OPTIONS),
            },
            "compare": {
                "description": (
                    "Compare canonical model family and reasoning effort variants "
                    "from a snapshot."
                ),
                "args": ["snapshot (optional)"],
                "flags": {
                    "select": (
                        "Repeatable selector: 'family' or 'family:effort1,effort2,...'"
                    ),
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
) -> dict[str, object]:
    error: dict[str, object] = {
        "code": code,
        "message": _safe_error_text(message),
    }
    if details is not None:
        error["details"] = redact(details)
    return {
        "id": redact(request_id),
        "type": "response",
        "command": _safe_error_text(command),
        "success": False,
        "error": error,
    }


def _success_response(
    request_id: object,
    command: str,
    data: dict[str, object],
) -> dict[str, object]:
    return {
        "id": request_id,
        "type": "response",
        "command": command,
        "success": True,
        "data": data,
    }


def _arg_value(args: dict[str, object], key: str, default: object = None) -> object:
    if key in args:
        return args[key]
    camel = "".join(
        part.capitalize() if i else part for i, part in enumerate(key.split("_"))
    )
    return args.get(camel, default)


def _dict_optional_str(
    args: dict[str, object], key: str, default: str | None = None
) -> str | None:
    val = _arg_value(args, key, default)
    return val if isinstance(val, str) else default


def _dict_path(args: dict[str, object], key: str, default: Path) -> Path:
    val = _arg_value(args, key, default)
    if isinstance(val, Path):
        return val
    if isinstance(val, str):
        return Path(val)
    return default


def _dict_optional_path(
    args: dict[str, object], key: str, default: Path | None = None
) -> Path | None:
    val = _arg_value(args, key, default)
    if val is None:
        return None
    if isinstance(val, Path):
        return val
    if isinstance(val, str):
        return Path(val) if val else None
    return default


def _dict_bool(args: dict[str, object], key: str, default: bool = False) -> bool:
    val = _arg_value(args, key, default)
    return bool(val)


def _fetch_namespace(args: dict[str, object]) -> argparse.Namespace:
    return argparse.Namespace(**_request_options(fetch_options(), args))


def _request_options(
    options: tuple[Option, ...], args: dict[str, object]
) -> dict[str, object]:
    try:
        return decode_options(options, args)
    except (TypeError, ValueError) as exc:
        raise CliUsageError(str(exc)) from exc


def _stats_namespace(args: dict[str, object]) -> argparse.Namespace:
    return argparse.Namespace(
        snapshot=_dict_path(args, "snapshot", DEFAULT_OUTPUT_JSON),
        **_request_options(STATS_OPTIONS, args),
    )


def _evaluation_namespace(args: dict[str, object]) -> argparse.Namespace:
    return argparse.Namespace(
        url=_dict_optional_str(args, "url"),
        **_request_options(EVALUATION_OPTIONS, args),
    )


def _diff_namespace(args: dict[str, object]) -> argparse.Namespace:
    old_snapshot = _dict_optional_str(args, "old_snapshot")
    new_snapshot = _dict_optional_str(args, "new_snapshot")
    if not old_snapshot or not new_snapshot:
        _raise_cli_usage_error("diff requires old_snapshot and new_snapshot")
    return argparse.Namespace(
        old_snapshot=Path(old_snapshot),
        new_snapshot=Path(new_snapshot),
        schema_aware=_dict_bool(args, "schema_aware", False),
    )


def _diagnose_namespace(args: dict[str, object]) -> argparse.Namespace:
    snapshot = _dict_optional_path(args, "snapshot") or _dict_optional_path(
        args, "snapshot_path"
    )
    cache_dir = _dict_optional_path(args, "cache_dir") or _dict_optional_path(
        args, "cache"
    )
    return argparse.Namespace(
        snapshot=snapshot,
        snapshot_path=None,
        cache_dir=cache_dir,
    )


def _query_namespace(args: dict[str, object]) -> argparse.Namespace:
    return argparse.Namespace(
        snapshot=_dict_path(args, "snapshot", DEFAULT_OUTPUT_JSON),
        **_request_options(QUERY_OPTIONS, args),
    )


def _qa_namespace(args: dict[str, object]) -> argparse.Namespace:
    question = _dict_optional_str(args, "question")
    if not question or not question.strip():
        _raise_cli_usage_error("qa requires question")

    return argparse.Namespace(
        question=question,
        snapshot=_dict_path(args, "snapshot", DEFAULT_OUTPUT_JSON),
        **_request_options(QA_OPTIONS, args),
    )


def _compare_namespace(args: dict[str, object]) -> argparse.Namespace:
    select_val = _arg_value(args, "select")
    selectors: list[str] = []
    if isinstance(select_val, str):
        selectors = [select_val]
    elif is_object_list(select_val):
        if any(not isinstance(value, str) for value in select_val):
            _raise_cli_usage_error("compare selectors must be strings")
        selectors = [value for value in select_val if isinstance(value, str)]
    elif select_val is not None:
        _raise_cli_usage_error("compare selectors must be strings")
    if not selectors:
        _raise_cli_usage_error("compare requires at least one --select selector")
    return argparse.Namespace(
        snapshot=_dict_path(args, "snapshot", DEFAULT_OUTPUT_JSON),
        select=selectors,
    )


def run_rpc(*, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout

    for raw_line in input_stream:
        line = raw_line.strip()
        if not line:
            continue

        try:
            request_obj = parse_json(line)
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
        if not is_str_dict(request_obj):
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

        request_dict: dict[str, object] = request_obj
        request_id = request_dict.get("id")
        command_val = request_dict.get("type") or request_dict.get("command")
        if not isinstance(command_val, str):
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
        command = command_val

        args_raw = request_dict.get("args", {})
        if not is_str_dict(args_raw):
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
        args_payload: dict[str, object] = args_raw
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
            elif command == "evaluation":
                response = _success_response(
                    request_id,
                    command,
                    _evaluation_payload(_evaluation_namespace(args_payload)),
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
            elif command == "compare":
                response = _success_response(
                    request_id,
                    command,
                    _compare_payload(_compare_namespace(args_payload)),
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
        except TypeError, ValueError:
            fallback = _error_response(
                request_id,
                command,
                "internal_error",
                "Response serialization failed.",
            )
            _ = output_stream.write(compact_json(fallback) + "\n")

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
        "evaluation",
        "query",
        "qa",
        "compare",
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
    handler_obj = getattr(args, "handler", None)
    if not callable(handler_obj):
        if json_errors:
            _emit_cli_error(
                command=command,
                code="usage_error",
                message="Missing command.",
                stdout=sys.stdout,
            )
        else:
            parser.print_usage(sys.stderr)
            _ = sys.stderr.write(f"{parser.prog}: error: missing command\n")
        return 2

    error_message: object
    try:
        handler_fn: Callable[[argparse.Namespace], object] = handler_obj
        result = handler_fn(args)
        return int(result) if isinstance(result, int) else 0
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
        _ = sys.stderr.write(f"error: {_safe_error_text(error_message)}\n")
    return status


def _exit_code(code: object) -> int:
    return code if isinstance(code, int) else 1


if __name__ == "__main__":
    raise SystemExit(main())
