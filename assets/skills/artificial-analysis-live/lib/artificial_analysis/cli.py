from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from .rsc import (
    BASE_URL,
    CODING_CAPABILITY_URL,
    ExtractionError,
    build_full_url,
    build_snapshot_payload,
    endpoint_slugs,
    extract_lists,
    fetch_rsc,
    load_cache_metadata,
    load_cached_body,
    load_last_good_snapshot,
    load_snapshot,
    parse_json_frames,
    sanity_check,
    save_cache,
    save_last_good_snapshot,
    snapshot_slugs,
    write_outputs,
)

PROTOCOL_VERSION = "1"

DEFAULT_OUTPUT_JSON = Path("artifacts/artificial-analysis/full-data.json")
DEFAULT_OUTPUT_ENDPOINTS = Path("artifacts/artificial-analysis/endpoints.txt")
DEFAULT_OUTPUT_URL = Path("artifacts/artificial-analysis/full-url.txt")
DEFAULT_CODING_OUTPUT_JSON = Path("artifacts/artificial-analysis/coding-data.json")


class CliUsageError(RuntimeError):
    """Raised when agent-provided command inputs are invalid."""


def _default_cache_dir() -> Path:
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg_cache) if xdg_cache else Path.home() / ".cache"
    return base / "artificial-analysis"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="artificial-analysis",
        description="AI-first extractor for Artificial Analysis provider endpoint data.",
    )
    parser.add_argument(
        "--mode",
        choices=("cli", "rpc"),
        default="cli",
        help="cli: one-shot JSON output. rpc: JSONL request/response loop.",
    )

    subparsers = parser.add_subparsers(dest="command")

    fetch_parser = subparsers.add_parser(
        "fetch", help="Fetch live RSC data and write snapshot outputs."
    )
    fetch_parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    fetch_parser.add_argument(
        "--output-endpoints", type=Path, default=DEFAULT_OUTPUT_ENDPOINTS
    )
    fetch_parser.add_argument("--output-url", type=Path, default=DEFAULT_OUTPUT_URL)
    fetch_parser.add_argument("--cache-dir", type=Path, default=_default_cache_dir())
    fetch_parser.add_argument("--timeout-seconds", type=float, default=60.0)
    fetch_parser.add_argument("--min-endpoints", type=int, default=700)
    fetch_parser.add_argument("--min-providers", type=int, default=40)
    fetch_parser.add_argument(
        "--strict", action="store_true", help="Disable last-good fallback."
    )
    fetch_parser.set_defaults(handler=_handle_fetch)

    stats_parser = subparsers.add_parser(
        "stats", help="Show snapshot counts and top providers."
    )
    stats_parser.add_argument(
        "snapshot", nargs="?", type=Path, default=DEFAULT_OUTPUT_JSON
    )
    stats_parser.add_argument("--top", type=int, default=10)
    stats_parser.set_defaults(handler=_handle_stats)

    diff_parser = subparsers.add_parser(
        "diff", help="Diff endpoint and provider changes between snapshots."
    )
    diff_parser.add_argument("old_snapshot", type=Path)
    diff_parser.add_argument("new_snapshot", type=Path)
    diff_parser.set_defaults(handler=_handle_diff)

    harness_parser = subparsers.add_parser(
        "harness",
        help="Rank unique models by Harness = 50% Agentic Index + 50% Coding Index.",
    )
    harness_parser.add_argument(
        "snapshot", nargs="?", type=Path, default=DEFAULT_OUTPUT_JSON
    )
    harness_parser.add_argument(
        "--model", type=str, default=None, help="Model slug/name contains filter."
    )
    harness_parser.add_argument(
        "--creator", type=str, default=None, help="Creator/lab name contains filter."
    )
    harness_parser.add_argument(
        "--open-weights-only",
        action="store_true",
        help="Return only open-weights models.",
    )
    harness_parser.add_argument("--limit", type=int, default=50)
    harness_parser.set_defaults(handler=_handle_harness)

    coding_parser = subparsers.add_parser(
        "coding",
        help="Fetch/query Coding Index capability rows, including coding-only output token composition.",
    )
    coding_parser.add_argument(
        "--output-json", type=Path, default=DEFAULT_CODING_OUTPUT_JSON
    )
    coding_parser.add_argument("--timeout-seconds", type=float, default=60.0)
    coding_parser.add_argument(
        "--model", type=str, default=None, help="Model slug/name contains filter."
    )
    coding_parser.add_argument(
        "--creator", type=str, default=None, help="Creator/lab name contains filter."
    )
    coding_parser.add_argument(
        "--open-weights-only",
        action="store_true",
        help="Return only open-weights models.",
    )
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
    coding_parser.add_argument(
        "--order", type=str, default="auto", choices=("auto", "asc", "desc")
    )
    coding_parser.add_argument("--limit", type=int, default=50)
    coding_parser.add_argument(
        "--include-benchmark-counts",
        action="store_true",
        help="Include per-benchmark token counts for Coding Index components.",
    )
    coding_parser.set_defaults(handler=_handle_coding)

    query_parser = subparsers.add_parser(
        "query", help="Query model/provider benchmark rows from a snapshot."
    )
    query_parser.add_argument(
        "snapshot", nargs="?", type=Path, default=DEFAULT_OUTPUT_JSON
    )
    query_parser.add_argument(
        "--model", type=str, default=None, help="Model slug/name contains filter."
    )
    query_parser.add_argument(
        "--provider", type=str, default=None, help="Provider slug/name contains filter."
    )
    query_parser.add_argument(
        "--endpoint", type=str, default=None, help="Endpoint slug contains filter."
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
    query_parser.add_argument(
        "--order", type=str, default="auto", choices=("auto", "asc", "desc")
    )
    query_parser.add_argument("--limit", type=int, default=20)
    query_parser.set_defaults(handler=_handle_query)

    qa_parser = subparsers.add_parser(
        "qa",
        help="Minimal NL question command that maps intent to query filters/sort.",
    )
    qa_parser.add_argument(
        "question", type=str, help="Natural-language question about models/providers."
    )
    qa_parser.add_argument(
        "snapshot", nargs="?", type=Path, default=DEFAULT_OUTPUT_JSON
    )
    qa_parser.add_argument(
        "--model", type=str, default=None, help="Override inferred model filter."
    )
    qa_parser.add_argument(
        "--provider", type=str, default=None, help="Override inferred provider filter."
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
        "--limit", type=int, default=None, help="Override inferred result limit."
    )
    qa_parser.set_defaults(handler=_handle_qa)

    schema_parser = subparsers.add_parser(
        "schema", help="Print machine-readable capability schema."
    )
    schema_parser.set_defaults(handler=_handle_schema)

    return parser


def _normalize_argv(argv: Sequence[str] | None) -> list[str]:
    values = list(argv) if argv is not None else sys.argv[1:]
    if not values:
        return ["fetch"]

    known_subcommands = {
        "fetch",
        "stats",
        "diff",
        "harness",
        "coding",
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
        token = values[index]
        if token == "--mode" and index + 1 < len(values):
            global_prefix.extend(values[index : index + 2])
            index += 2
            continue
        if token.startswith("--mode="):
            global_prefix.append(token)
            index += 1
            continue
        break

    return [*global_prefix, "fetch", *values[index:]]


def _emit_json(payload: dict[str, Any], *, stdout: TextIO) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), file=stdout)


def _envelope(command: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "version": PROTOCOL_VERSION,
        "command": command,
        "data": data,
    }


def _fetch_payload(args: argparse.Namespace) -> dict[str, Any]:
    cache_meta = load_cache_metadata(args.cache_dir)
    sent_etag = cache_meta.etag if cache_meta is not None else None

    result = fetch_rsc(timeout_seconds=args.timeout_seconds, if_none_match=sent_etag)
    response_etag = result.headers.get("etag") or sent_etag

    reused_cached_body = False
    if result.status_code == 304:
        body = load_cached_body(args.cache_dir, cache_meta)
        if body is None:
            raise ExtractionError(
                "Upstream returned 304 but no cached payload is available."
            )
        reused_cached_body = True
    else:
        body = result.body

    fallback_used = False
    fallback_source: str | None = None
    fallback_reason: str | None = None

    try:
        frames = parse_json_frames(body)
        models, hosts, hosts_models = extract_lists(frames)
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
            fetched_at=result.fetched_at,
            status_code=result.status_code,
            etag=response_etag,
        )
    except ExtractionError as exc:
        if args.strict:
            raise

        fallback_reason = str(exc)
        fallback_payload = load_last_good_snapshot(args.cache_dir)
        fallback_source = "cache:last-good"

        if fallback_payload is None and args.output_json.exists():
            fallback_payload = load_snapshot(args.output_json)
            fallback_source = f"file:{args.output_json}"

        if fallback_payload is None:
            raise ExtractionError(
                f"Fresh parse failed and no last-good snapshot exists ({exc})."
            ) from exc

        slugs = snapshot_slugs(fallback_payload)
        sanity_check(
            slugs=slugs,
            min_endpoints=args.min_endpoints,
            min_providers=args.min_providers,
        )
        payload = fallback_payload
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

    if not fallback_used:
        save_cache(
            cache_dir=args.cache_dir,
            fetched_at=result.fetched_at,
            status_code=result.status_code,
            etag=response_etag,
            body=None if result.status_code == 304 else body,
        )
        save_last_good_snapshot(args.cache_dir, payload)

    return {
        "source": {
            "url": BASE_URL,
            "status_code": result.status_code,
            "etag_sent": sent_etag,
            "etag_received": response_etag,
            "reused_cached_payload": reused_cached_body,
        },
        "counts": payload.get("meta", {}).get("counts", {}),
        "outputs": {
            "json": str(args.output_json),
            "endpoints": str(args.output_endpoints),
            "url": str(args.output_url),
        },
        "cache": {
            "dir": str(args.cache_dir),
        },
        "fallback": {
            "used": fallback_used,
            "source": fallback_source,
            "reason": fallback_reason,
            "strict": bool(args.strict),
        },
    }


def _stats_payload(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = load_snapshot(args.snapshot)
    slugs = snapshot_slugs(snapshot)
    providers = _provider_counts_from_snapshot(snapshot)
    top = sorted(providers.items(), key=lambda item: (-item[1], item[0]))[
        : max(args.top, 0)
    ]

    return {
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
    }


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
                }
            )

    return {
        "old_snapshot": str(args.old_snapshot),
        "new_snapshot": str(args.new_snapshot),
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
    }


def _coding_payload(args: argparse.Namespace) -> dict[str, Any]:
    result = fetch_rsc(url=CODING_CAPABILITY_URL, timeout_seconds=args.timeout_seconds)
    frames = parse_json_frames(result.body)
    models = _extract_default_data_models(frames)

    model_filter = (
        args.model.lower() if isinstance(args.model, str) and args.model else None
    )
    creator_filter = (
        args.creator.lower() if isinstance(args.creator, str) and args.creator else None
    )

    rows: list[dict[str, Any]] = []
    skipped_missing_token_counts = 0
    for model in models:
        if not isinstance(model, dict) or model.get("deleted"):
            continue

        model_slug = model.get("slug") if isinstance(model.get("slug"), str) else None
        model_name = model.get("name") if isinstance(model.get("name"), str) else None
        short_name = (
            model.get("short_name")
            if isinstance(model.get("short_name"), str)
            else model_name
        )
        creator = (
            model.get("model_creators")
            if isinstance(model.get("model_creators"), dict)
            else {}
        )
        creator_name = (
            creator.get("name") if isinstance(creator.get("name"), str) else None
        )

        if model_filter and not _matches_any(
            model_filter, [model_slug, model_name, short_name]
        ):
            continue
        if creator_filter and not _matches_any(
            creator_filter, [creator_name, creator.get("slug")]
        ):
            continue
        if args.open_weights_only and model.get("is_open_weights") is not True:
            continue

        token_counts = (
            model.get("tokenCounts")
            if isinstance(model.get("tokenCounts"), dict)
            else None
        )
        if token_counts is None:
            skipped_missing_token_counts += 1
            continue

        answer_tokens = _number_or_none(token_counts.get("answerTokens"))
        reasoning_tokens = _number_or_none(token_counts.get("reasoningTokens"))
        output_tokens = _number_or_none(token_counts.get("outputTokens"))
        input_tokens = _number_or_none(token_counts.get("inputTokens"))
        eval_cost = (
            model.get("evalCost") if isinstance(model.get("evalCost"), dict) else {}
        )

        row: dict[str, Any] = {
            "model_slug": model_slug,
            "model_name": model_name,
            "short_name": short_name,
            "creator": creator_name,
            "coding": model.get("coding_index"),
            "terminalbench_hard": model.get("terminalbench_hard"),
            "scicode": model.get("scicode"),
            "reasoning_model": model.get("reasoning_model"),
            "deprecated": model.get("deprecated"),
            "is_open_weights": model.get("is_open_weights"),
            "release_date": model.get("release_date"),
            "context_window_tokens": model.get("context_window_tokens"),
            "coding_token_counts": {
                "scope": "coding_index_only",
                "definition": "Tokens used to run the Coding Index evaluation. output_tokens = answer_tokens + reasoning_tokens.",
                "input_tokens": input_tokens,
                "answer_tokens": answer_tokens,
                "reasoning_tokens": reasoning_tokens,
                "output_tokens": output_tokens,
                "answer_share_of_output": _share(answer_tokens, output_tokens),
                "reasoning_share_of_output": _share(reasoning_tokens, output_tokens),
            },
            "coding_eval_cost": {
                "total_cost": _number_or_none(eval_cost.get("totalCost")),
                "input_cost": _number_or_none(eval_cost.get("inputCost")),
                "answer_cost": _number_or_none(eval_cost.get("answerCost")),
                "reasoning_cost": _number_or_none(eval_cost.get("reasoningCost")),
            },
        }
        if args.include_benchmark_counts:
            row["coding_component_token_counts"] = _coding_component_token_counts(model)
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
            row, sort_key_map[args.sort_by], reverse=reverse
        )
    )
    limited = rows[: max(args.limit, 0)]

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(
            {
                "meta": {
                    "source_url": CODING_CAPABILITY_URL,
                    "fetched_at": result.fetched_at,
                },
                "rows": rows,
            },
            ensure_ascii=False,
        )
    )

    return {
        "source": {
            "url": CODING_CAPABILITY_URL,
            "status_code": result.status_code,
            "fetched_at": result.fetched_at,
        },
        "output_json": str(args.output_json),
        "definition": {
            "scope": "coding_index_only",
            "warning": "These token counts are tied to the Coding Index capability page, not the global Intelligence Index token counts.",
            "components": ["terminalbench_hard", "scicode"],
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
            "skipped_missing_token_counts": skipped_missing_token_counts,
            "frames": len(frames),
        },
        "rows": limited,
    }


def _extract_default_data_models(frames: list[tuple[str, Any]]) -> list[Any]:
    candidates: list[list[Any]] = []

    def scan(node: Any) -> None:
        if isinstance(node, dict):
            default_data = node.get("defaultData")
            if _looks_like_coding_capability_rows(default_data):
                candidates.append(default_data)
            for value in node.values():
                scan(value)
        elif isinstance(node, list):
            for item in node:
                scan(item)

    for _, frame in frames:
        scan(frame)

    if not candidates:
        raise ExtractionError(
            "Coding capability payload missing defaultData rows with tokenCounts."
        )
    return max(candidates, key=len)


def _looks_like_coding_capability_rows(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    sample = [item for item in value[:25] if isinstance(item, dict)]
    if len(sample) < 2:
        return False
    hits = 0
    for item in sample:
        if (
            isinstance(item.get("slug"), str)
            and "coding_index" in item
            and isinstance(item.get("tokenCounts"), dict)
        ):
            hits += 1
    return hits >= max(2, len(sample) // 2)


def _number_or_none(value: Any) -> int | float | None:
    return value if isinstance(value, int | float) else None


def _share(part: int | float | None, total: int | float | None) -> float | None:
    if (
        not isinstance(part, int | float)
        or not isinstance(total, int | float)
        or total == 0
    ):
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
    row: dict[str, Any], path: str, *, reverse: bool
) -> tuple[int, float]:
    current: Any = row
    for part in path.split("."):
        if not isinstance(current, dict):
            current = None
            break
        current = current.get(part)
    if isinstance(current, int | float):
        normalized = -float(current) if reverse else float(current)
        return (0, normalized)
    return (1, 0.0)


def _harness_payload(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = load_snapshot(args.snapshot)
    hosts_models = snapshot.get("hosts_models")
    if not isinstance(hosts_models, list):
        raise ExtractionError("Snapshot missing hosts_models list")

    model_filter = (
        args.model.lower() if isinstance(args.model, str) and args.model else None
    )
    creator_filter = (
        args.creator.lower() if isinstance(args.creator, str) and args.creator else None
    )

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    skipped_missing = 0

    for item in hosts_models:
        if not isinstance(item, dict):
            continue
        model = item.get("model") if isinstance(item.get("model"), dict) else {}
        model_slug = model.get("slug") if isinstance(model.get("slug"), str) else None
        if not model_slug or model_slug in seen:
            continue
        seen.add(model_slug)
        if model.get("deleted") or model.get("deprecated"):
            continue

        model_name = model.get("name") if isinstance(model.get("name"), str) else None
        creator = (
            model.get("model_creators")
            if isinstance(model.get("model_creators"), dict)
            else {}
        )
        creator_name = (
            creator.get("name") if isinstance(creator.get("name"), str) else None
        )

        if model_filter and not _matches_any(model_filter, [model_slug, model_name]):
            continue
        if creator_filter and not _matches_any(
            creator_filter, [creator_name, creator.get("slug")]
        ):
            continue
        if args.open_weights_only and model.get("is_open_weights") is not True:
            continue

        agentic = model.get("agentic_index")
        coding = model.get("coding_index")
        if not isinstance(agentic, int | float) or not isinstance(coding, int | float):
            skipped_missing += 1
            continue

        harness = (float(agentic) + float(coding)) / 2.0
        rows.append(
            {
                "rank": 0,
                "model_slug": model_slug,
                "model_name": model_name,
                "creator": creator_name,
                "harness": round(harness, 4),
                "agentic": agentic,
                "coding": coding,
                "execution_gap": round(float(agentic) - float(coding), 4),
                "intelligence": model.get("intelligence_index"),
                "release_date": model.get("release_date"),
                "reasoning_model": model.get("reasoning_model"),
                "is_open_weights": model.get("is_open_weights"),
                "context_window_tokens": model.get("context_window_tokens"),
            }
        )

    rows.sort(
        key=lambda row: (-float(row["harness"]), str(row.get("model_slug") or ""))
    )
    for index, row in enumerate(rows, start=1):
        row["rank"] = index

    limited = rows[: max(args.limit, 0)]
    return {
        "snapshot": str(args.snapshot),
        "definition": {
            "name": "Harness",
            "formula": "0.5 * Agentic Index + 0.5 * Coding Index",
            "execution_gap": "Agentic Index - Coding Index; high positive values indicate executable-precision risk.",
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
    }


def _query_payload(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = load_snapshot(args.snapshot)
    hosts_models = snapshot.get("hosts_models")
    if not isinstance(hosts_models, list):
        raise ExtractionError("Snapshot missing hosts_models list")

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
        if not isinstance(item, dict):
            continue

        endpoint_slug = item.get("slug")
        model = item.get("model") if isinstance(item.get("model"), dict) else {}
        host = item.get("host") if isinstance(item.get("host"), dict) else {}
        timescale = (
            item.get("timescaleData")
            if isinstance(item.get("timescaleData"), dict)
            else {}
        )
        e2e = (
            item.get("end_to_end_response_time_metrics")
            if isinstance(item.get("end_to_end_response_time_metrics"), dict)
            else {}
        )

        if not isinstance(endpoint_slug, str) or "_" not in endpoint_slug:
            continue

        model_slug = model.get("slug") if isinstance(model.get("slug"), str) else None
        model_name = model.get("name") if isinstance(model.get("name"), str) else None
        provider_slug = host.get("slug") if isinstance(host.get("slug"), str) else None
        provider_name = host.get("name") if isinstance(host.get("name"), str) else None

        if model_filter and not _matches_any(model_filter, [model_slug, model_name]):
            continue
        if provider_filter and not _matches_any(
            provider_filter, [provider_slug, provider_name]
        ):
            continue
        if endpoint_filter and endpoint_filter not in endpoint_slug.lower():
            continue

        rows.append(
            {
                "endpoint_slug": endpoint_slug,
                "endpoint_name": item.get("name"),
                "model_slug": model_slug,
                "model_name": model_name,
                "provider_slug": provider_slug,
                "provider_name": provider_name,
                "harness": _harness_score(model),
                "intelligence": model.get("intelligence_index"),
                "agentic": model.get("agentic_index"),
                "coding": model.get("coding_index"),
                "math": model.get("math_index"),
                "gpqa": model.get("gpqa"),
                "mmlu_pro": model.get("mmlu_pro"),
                "livecodebench": model.get("livecodebench"),
                "ifbench": model.get("ifbench"),
                "scicode": model.get("scicode"),
                "tau2": model.get("tau2"),
                "terminalbench_hard": model.get("terminalbench_hard"),
                "release_date": model.get("release_date"),
                "reasoning_model": model.get("reasoning_model"),
                "is_open_weights": model.get("is_open_weights"),
                "price_input": item.get("price_1m_input_tokens"),
                "price_output": item.get("price_1m_output_tokens"),
                "price_blended": item.get("price_1m_blended_3_to_1"),
                "speed": timescale.get("median_output_speed"),
                "ttfc": timescale.get("median_time_to_first_chunk"),
                "e2e": e2e.get("total_time"),
                "context_window_tokens": item.get("context_window_tokens"),
                "host_api_id": item.get("host_api_id"),
            }
        )

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

    top_providers = [
        {"provider": name, "endpoints": count}
        for name, count in sorted(
            provider_counts.items(), key=lambda item: (-item[1], item[0])
        )[:10]
    ]
    top_models = [
        {"model": name, "endpoints": count}
        for name, count in sorted(
            model_counts.items(), key=lambda item: (-item[1], item[0])
        )[:10]
    ]

    return {
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
        "top_providers": top_providers,
        "top_models": top_models,
        "rows": limited,
    }


def _harness_score(model: dict[str, Any]) -> float | None:
    agentic = model.get("agentic_index")
    coding = model.get("coding_index")
    if isinstance(agentic, int | float) and isinstance(coding, int | float):
        return round((float(agentic) + float(coding)) / 2.0, 4)
    return None


def _matches_any(needle: str, values: list[str | None]) -> bool:
    for value in values:
        if isinstance(value, str) and needle in value.lower():
            return True
    return False


def _resolve_reverse(*, sort_key: str, order: str) -> bool:
    if order == "asc":
        return False
    if order == "desc":
        return True
    if sort_key in {"price_blended", "ttfc", "e2e"}:
        return False
    return True


def _sort_metric(
    row: dict[str, Any], metric: str, *, reverse: bool
) -> tuple[int, float]:
    value = row.get(metric)
    if isinstance(value, int | float):
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
        raise ExtractionError("Snapshot missing hosts_models list")

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
        raise CliUsageError("qa requires a non-empty question")

    snapshot = load_snapshot(args.snapshot)
    hosts_models = snapshot.get("hosts_models")
    if not isinstance(hosts_models, list):
        raise ExtractionError("Snapshot missing hosts_models list")

    inferred_model = args.model or _infer_model(question, hosts_models)
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
    return {
        "question": question,
        "parsed_intent": {
            "model": inferred_model,
            "provider": inferred_provider,
            "sort_by": sort_by,
            "order": order,
            "limit": limit,
        },
        "query": query_result,
    }


def _normalize_for_match(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _infer_model(question: str, hosts_models: list[Any]) -> str | None:
    question_norm = _normalize_for_match(question)
    best: tuple[int, str] | None = None

    for item in hosts_models:
        if not isinstance(item, dict):
            continue
        model = item.get("model") if isinstance(item.get("model"), dict) else {}
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
    if any(
        word in q
        for word in (
            "cheap",
            "cheapest",
            "lowest price",
            "low price",
            "precio",
            "barato",
        )
    ):
        return ("price_blended", "asc")
    if any(
        word in q
        for word in (
            "latency",
            "first token",
            "ttfc",
            "response time",
            "rápido en",
            "latencia",
        )
    ):
        return ("ttfc", "asc")
    if any(
        word in q
        for word in (
            "speed",
            "throughput",
            "tokens per second",
            "fastest",
            "rápido",
            "velocidad",
        )
    ):
        return ("speed", "desc")
    if any(
        word in q
        for word in ("harness", "agent harness", "coding agent", "agentic coding")
    ):
        return ("harness", "desc")
    if any(word in q for word in ("agentic", "agent", "autonomous")):
        return ("agentic", "desc")
    if any(word in q for word in ("coding", "code", "programming", "codificación")):
        return ("coding", "desc")
    if any(word in q for word in ("math", "matemática", "matematica")):
        return ("math", "desc")
    if any(
        word in q for word in ("quality", "best", "intelligence", "benchmark", "mejor")
    ):
        return ("intelligence", "desc")
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


def _handle_harness(args: argparse.Namespace) -> int:
    _emit_json(_envelope("harness", _harness_payload(args)), stdout=sys.stdout)
    return 0


def _handle_coding(args: argparse.Namespace) -> int:
    _emit_json(_envelope("coding", _coding_payload(args)), stdout=sys.stdout)
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
        "description": "AI-only fetch/analyze tool for Artificial Analysis provider endpoint data.",
        "protocol_version": PROTOCOL_VERSION,
        "default_command": "fetch",
        "source": {
            "type": "rsc",
            "url": BASE_URL,
            "required_headers": ["RSC: 1"],
        },
        "commands": {
            "fetch": {
                "description": "Fetch live RSC payload, validate sanity thresholds, cache by ETag, and write outputs.",
                "outputs": ["full-data.json", "endpoints.txt", "full-url.txt"],
                "flags": {
                    "output_json": "Path (default artifacts/artificial-analysis/full-data.json)",
                    "output_endpoints": "Path (default artifacts/artificial-analysis/endpoints.txt)",
                    "output_url": "Path (default artifacts/artificial-analysis/full-url.txt)",
                    "cache_dir": "Path to ETag/payload cache",
                    "timeout_seconds": "float network timeout",
                    "min_endpoints": "int sanity threshold (default 700)",
                    "min_providers": "int sanity threshold (default 40)",
                    "strict": "bool disable last-good fallback",
                },
            },
            "stats": {
                "description": "Read a snapshot and return counts + top providers.",
                "args": ["snapshot(optional)"],
                "flags": {"top": "int top N providers (default 10)"},
            },
            "diff": {
                "description": "Diff two snapshots for endpoint/provider deltas.",
                "args": ["old_snapshot", "new_snapshot"],
                "flags": {},
            },
            "harness": {
                "description": "Rank unique models by Harness = 50% Agentic Index + 50% Coding Index.",
                "args": ["snapshot(optional)"],
                "flags": {
                    "model": "str contains filter on model slug/name",
                    "creator": "str contains filter on creator/lab slug/name",
                    "open_weights_only": "bool only include open-weights models",
                    "limit": "int max rows (default 50)",
                },
            },
            "coding": {
                "description": "Fetch/query Coding Index capability rows with coding-only output token composition.",
                "source_url": CODING_CAPABILITY_URL,
                "flags": {
                    "model": "str contains filter on model slug/name",
                    "creator": "str contains filter on creator/lab name",
                    "open_weights_only": "bool only include open-weights models",
                    "sort_by": "coding|output_tokens|answer_tokens|reasoning_tokens|input_tokens|cost",
                    "order": "auto|asc|desc",
                    "limit": "int max rows (default 50)",
                    "include_benchmark_counts": "bool include Terminal-Bench Hard and SciCode token counts",
                },
                "token_scope": "coding_index_only; not global Intelligence Index token counts",
            },
            "query": {
                "description": "Filter/sort endpoint benchmark rows by model/provider/endpoint.",
                "args": ["snapshot(optional)"],
                "flags": {
                    "model": "str contains filter on model slug/name",
                    "provider": "str contains filter on provider slug/name",
                    "endpoint": "str contains filter on endpoint slug",
                    "sort_by": "harness|intelligence|agentic|coding|math|price_blended|speed|ttfc|e2e",
                    "order": "auto|asc|desc",
                    "limit": "int max rows (default 20)",
                },
            },
            "qa": {
                "description": "Minimal NL intent parser that maps a question to query filters/sort and returns query output.",
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
                    "fields": ["id", "type=response", "command", "success", "data"]
                },
                "error": {
                    "fields": [
                        "id",
                        "type=response",
                        "command",
                        "success=false",
                        "error",
                    ]
                },
            },
        },
    }


def _error_response(
    request_id: Any, command: str, code: str, message: str
) -> dict[str, Any]:
    return {
        "id": request_id,
        "type": "response",
        "command": command,
        "success": False,
        "error": {
            "code": code,
            "message": message,
        },
    }


def _success_response(
    request_id: Any, command: str, data: dict[str, Any]
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
            _arg_value(args, "output_endpoints", str(DEFAULT_OUTPUT_ENDPOINTS))
        ),
        output_url=Path(_arg_value(args, "output_url", str(DEFAULT_OUTPUT_URL))),
        cache_dir=Path(_arg_value(args, "cache_dir", str(_default_cache_dir()))),
        timeout_seconds=float(_arg_value(args, "timeout_seconds", 60.0)),
        min_endpoints=int(_arg_value(args, "min_endpoints", 700)),
        min_providers=int(_arg_value(args, "min_providers", 40)),
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
            _arg_value(args, "output_json", str(DEFAULT_CODING_OUTPUT_JSON))
        ),
        timeout_seconds=float(_arg_value(args, "timeout_seconds", 60.0)),
        model=_arg_value(args, "model", None),
        creator=_arg_value(args, "creator", None),
        open_weights_only=bool(_arg_value(args, "open_weights_only", False)),
        sort_by=str(_arg_value(args, "sort_by", "coding")),
        order=str(_arg_value(args, "order", "auto")),
        limit=int(_arg_value(args, "limit", 50)),
        include_benchmark_counts=bool(
            _arg_value(args, "include_benchmark_counts", False)
        ),
    )


def _diff_namespace(args: dict[str, Any]) -> argparse.Namespace:
    old_snapshot = _arg_value(args, "old_snapshot", None)
    new_snapshot = _arg_value(args, "new_snapshot", None)
    if not old_snapshot or not new_snapshot:
        raise CliUsageError("diff requires old_snapshot and new_snapshot")
    return argparse.Namespace(
        old_snapshot=Path(str(old_snapshot)), new_snapshot=Path(str(new_snapshot))
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
        raise CliUsageError("qa requires question")

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
                    None, "unknown", "invalid_json", "Request line is not valid JSON."
                ),
                stdout=output_stream,
            )
            continue

        if not isinstance(request, dict):
            _emit_json(
                _error_response(
                    None, "unknown", "invalid_request", "Request must be a JSON object."
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
                    request_id, command, "invalid_args", "args must be an object."
                ),
                stdout=output_stream,
            )
            continue

        try:
            if command == "ping":
                response = _success_response(
                    request_id, command, {"ok": True, "version": PROTOCOL_VERSION}
                )
            elif command in {"schema", "get_schema"}:
                response = _success_response(request_id, command, _capability_schema())
            elif command == "fetch":
                response = _success_response(
                    request_id, command, _fetch_payload(_fetch_namespace(args_payload))
                )
            elif command == "stats":
                response = _success_response(
                    request_id, command, _stats_payload(_stats_namespace(args_payload))
                )
            elif command == "diff":
                response = _success_response(
                    request_id, command, _diff_payload(_diff_namespace(args_payload))
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
            elif command == "query":
                response = _success_response(
                    request_id, command, _query_payload(_query_namespace(args_payload))
                )
            elif command == "qa":
                response = _success_response(
                    request_id, command, _qa_payload(_qa_namespace(args_payload))
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
        except ExtractionError as exc:
            response = _error_response(
                request_id, command, "extraction_error", str(exc)
            )
        except OSError as exc:
            response = _error_response(request_id, command, "io_error", str(exc))

        _emit_json(response, stdout=output_stream)

    return 0


def _mode_from_argv(values: list[str]) -> str:
    if not values:
        return "cli"
    for index, token in enumerate(values):
        if token == "--mode" and index + 1 < len(values):
            return values[index + 1]
        if token.startswith("--mode="):
            return token.split("=", 1)[1]
    return "cli"


def main(argv: Sequence[str] | None = None) -> int:
    values = list(argv) if argv is not None else sys.argv[1:]
    if _mode_from_argv(values) == "rpc":
        return run_rpc()

    parser = build_parser()
    normalized_argv = _normalize_argv(values)

    try:
        args = parser.parse_args(normalized_argv)
    except SystemExit as exc:
        return _exit_code(exc.code)

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: missing command", file=sys.stderr)
        return 2

    try:
        return int(handler(args))
    except ExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _exit_code(code: object) -> int:
    return code if isinstance(code, int) else 1


if __name__ == "__main__":
    raise SystemExit(main())
