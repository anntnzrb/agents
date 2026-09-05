# Copyright 2026 Vals-live contributors.
"""Vals command projections and the source-local pipeline."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from argparse import Namespace

from .cache import CacheError, CacheStore, fetch
from .catalog_diff import diff
from .contracts import (
    Catalog,
    ParsedDocument,
    RawArtifact,
    scope,
    success,
)
from .diagnostics import make, merge
from .discovery import select_benchmark, select_model
from .extraction import ExtractionError, extract_document
from .identity import release_identity, snapshot_identity
from .parsing import parse
from .provenance import artifact_provenance
from .release import resolve
from .validation import overlap_metadata, rank_rows, validate_records

HTTP_ERROR_STATUS = 400
SEED_CATALOG = "https://www.vals.ai/benchmarks"
SEED_MODELS = "https://www.vals.ai/models"


class CommandError(RuntimeError):
    """Represent a command-level structured failure."""

    def __init__(
        self, code: str, message: str, details: Mapping[str, object] | None = None
    ) -> None:
        """Initialize a stable error code, message, and details mapping."""
        super().__init__(message)
        self.code: str = code
        self.details: dict[str, object] = dict(details) if details is not None else {}


@dataclass
class Pipeline:
    """Carry one extracted artifact through the command projections."""

    artifact: RawArtifact
    document: ParsedDocument
    catalog: Catalog
    rows: list[dict[str, object]]
    diagnostics: list[dict[str, object]]
    release: dict[str, object]
    metadata: dict[str, object] | None


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _as_content_type(
    path: Path, body: bytes, metadata: Mapping[str, object] | None = None
) -> str:
    value = metadata.get("content_type") if metadata else None
    if isinstance(value, str) and value:
        return value
    suffix = path.suffix.casefold()
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix == ".csv":
        return "text/csv"
    if suffix == ".json":
        return "application/json"
    first = body.lstrip()[:1]
    return "application/json" if first in {b"{", b"["} else "text/html"


def _snapshot_metadata(path: Path, body: bytes) -> dict[str, object]:
    """Parse snapshot-manifest metadata from explicit snapshot bytes."""
    if path.suffix.casefold() not in {".json", ".manifest"}:
        return {}
    try:
        value = cast("object", json.loads(body.decode("utf-8")))
    except (UnicodeDecodeError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    value_map = cast("Mapping[str, object]", value)
    candidate = value_map.get("manifest")
    if isinstance(candidate, Mapping):
        return dict(cast("Mapping[str, object]", candidate))
    return dict(value_map)


def _resolve_snapshot_bytes(
    path: Path, body: bytes, metadata: Mapping[str, object]
) -> bytes:
    """Follow a manifest raw-bytes reference, falling back to snapshot bytes."""
    raw_ref = (
        metadata.get("raw_bytes_ref")
        or metadata.get("body_path")
        or metadata.get("raw_body_path")
    )
    if not isinstance(raw_ref, str):
        return body
    raw_path = Path(raw_ref).expanduser()
    if not raw_path.is_absolute():
        raw_path = path.parent / raw_path
    try:
        return raw_path.read_bytes()
    except OSError as exc:
        msg = "SNAPSHOT_INVALID"
        raise CommandError(
            msg,
            "The snapshot raw-bytes reference could not be read.",
            {"path": str(raw_path)},
        ) from exc


def _read_snapshot(path_value: str) -> RawArtifact:
    path = Path(path_value).expanduser()
    if not path.exists() or not path.is_file():
        msg = "SNAPSHOT_INVALID"
        raise CommandError(
            msg,
            "The explicit snapshot path does not exist.",
            {"path": str(path)},
        )
    try:
        body = path.read_bytes()
    except OSError as exc:
        msg = "SNAPSHOT_INVALID"
        raise CommandError(
            msg,
            "The explicit snapshot could not be read.",
            {"path": str(path)},
        ) from exc
    metadata = _snapshot_metadata(path, body)
    # Snapshot manifests may point at immutable raw bytes rather than embedding them.
    body = _resolve_snapshot_bytes(path, body, metadata)
    digest = sha256(body).hexdigest()
    source_url = str(
        metadata.get("source_url") or metadata.get("url") or f"file://{path.resolve()}"
    )
    discovered_from = str(metadata.get("discovered_from") or source_url)
    release = metadata.get("release") or metadata.get("source_release_id")
    release_value = (
        str(release)
        if isinstance(release, (str, int, float)) and not isinstance(release, bool)
        else None
    )
    status_nested = metadata.get("error")
    if isinstance(status_nested, Mapping):
        nested_map = cast("Mapping[str, object]", status_nested)
        nested_status = nested_map.get("http_status")
    else:
        nested_status = None
    status_value = metadata.get("status_code") or nested_status or 200
    artifact = RawArtifact(
        source_url,
        discovered_from,
        body,
        status_code=int(cast("int", status_value)),
        content_type=_as_content_type(path, body, metadata),
        final_url=str(metadata.get("final_url") or source_url),
        etag=str(metadata.get("etag")) if metadata.get("etag") else None,
        last_modified=str(metadata.get("last_modified"))
        if metadata.get("last_modified")
        else None,
        fetched_at=str(metadata.get("fetched_at") or _now()),
        observed_at=str(
            metadata.get("observed_at") or metadata.get("fetched_at") or _now()
        ),
        release=release_value,
        historical=True,
        sha256=digest,
        local_path=str(path),
    )
    # Validate manifest hash when one is present.
    expected = metadata.get("sha256") or metadata.get("expected_sha256")
    if isinstance(expected, str) and expected and expected != digest:
        msg = "SNAPSHOT_INVALID"
        raise CommandError(
            msg,
            "The explicit snapshot hash does not match its bytes.",
            {"path": str(path), "expected_sha256": expected, "actual_sha256": digest},
        )
    return artifact


def _source_artifact(
    args: Namespace, *, seed: str, release: str | None = None
) -> RawArtifact:
    snapshot = cast("object", getattr(args, "snapshot", None))
    if snapshot:
        return _read_snapshot(str(snapshot))
    raw_cache_dir = cast("object", getattr(args, "cache_dir", None))
    cache_dir = Path(str(raw_cache_dir)) if raw_cache_dir is not None else None
    allow_stale = bool(cast("object", getattr(args, "allow_stale", False)))
    try:
        return fetch(
            seed,
            discovered_from=seed,
            release=release,
            cache=CacheStore(cache_dir),
            allow_stale=allow_stale,
        )
    except CacheError as exc:
        raise CommandError(exc.code, str(exc), exc.details) from exc


def _validate_artifact(artifact: RawArtifact) -> None:
    if artifact.status_code < HTTP_ERROR_STATUS:
        return
    code = (
        "SOURCE_AUTH_REQUIRED"
        if artifact.status_code in {401, 403}
        else "SOURCE_UNAVAILABLE"
    )
    raise CommandError(
        code,
        "The explicit snapshot records an unusable source response.",
        {"attempted_url": artifact.source_url, "http_status": artifact.status_code},
    )


def _annotate_release(rows: list[dict[str, object]], release: str | None) -> None:
    for row in rows:
        evidences = row.get("source_evidence", [])
        if isinstance(evidences, list):
            items = cast("list[object]", cast("object", evidences))
            for evidence in items:
                if isinstance(evidence, dict):
                    cast("dict[str, object]", evidence)["source_release"] = release
        metrics = row.get("metrics")
        if not isinstance(metrics, Mapping):
            continue
        metrics_map = cast("Mapping[str, object]", metrics)
        for metric in metrics_map.values():
            if not isinstance(metric, Mapping):
                continue
            metric_map = cast("Mapping[str, object]", metric)
            value = metric_map.get("value")
            if not isinstance(value, Mapping):
                continue
            value_map = cast("Mapping[str, object]", value)
            nested = value_map.get("source_evidence")
            if not isinstance(nested, Mapping):
                continue
            cast("dict[str, object]", nested)["source_release"] = release


def _pipeline_diagnostics(
    artifact: RawArtifact,
    diagnostics: list[dict[str, object]],
    snapshot_id: str,
    source_release: str | None,
) -> None:
    if artifact.historical:
        diagnostics.append(
            make(
                "HISTORICAL_SNAPSHOT",
                "An explicit historical snapshot was selected.",
                severity="warning",
                stage="release",
                details={
                    "snapshot_id": snapshot_id,
                    "source_release_id": source_release,
                },
            )
        )
    if artifact.stale:
        diagnostics.append(
            make(
                "STALE_DATA",
                (
                    "A failed refresh was served from cache because "
                    "--allow-stale was explicit."
                ),
                severity="warning",
                stage="transport",
                details=artifact.stale_reason or {"source_url": artifact.source_url},
            )
        )


def _pipeline(args: Namespace, *, seed: str = SEED_CATALOG) -> Pipeline:
    artifact = _source_artifact(args, seed=seed)
    _validate_artifact(artifact)
    try:
        document = extract_document(artifact)
    except ExtractionError as exc:
        raise CommandError(exc.code, str(exc), exc.details) from exc
    catalog, rows, diagnostics, metadata = parse(document)
    source_release, snapshot_id = release_identity(document.root, artifact.body)
    resolved = resolve(document.root, artifact.body, getattr(args, "release", None))
    if not resolved.get("ok"):
        details_value = resolved.get("details")
        details = (
            cast("dict[str, object]", details_value)
            if isinstance(details_value, dict)
            else {}
        )
        raise CommandError(
            str(resolved.get("code")),
            str(resolved.get("message")),
            details,
        )
    artifact.release = str(resolved.get("id")) if resolved.get("id") else None
    _annotate_release(rows, artifact.release)
    _pipeline_diagnostics(artifact, diagnostics, snapshot_id, source_release)
    if source_release and artifact.release != source_release:
        artifact.release = source_release
    return Pipeline(artifact, document, catalog, rows, diagnostics, resolved, metadata)


def _base_data(pipeline: Pipeline, **kwargs: object) -> dict[str, object]:
    benchmark_value = kwargs.get("benchmark")
    benchmark = (
        cast("Mapping[str, object]", benchmark_value)
        if isinstance(benchmark_value, Mapping)
        else None
    )
    model_variant_value = kwargs.get("model_variant")
    model_variant = (
        model_variant_value if isinstance(model_variant_value, str) else None
    )
    rows_value = kwargs.get("rows")
    rows = (
        cast("list[dict[str, object]]", cast("object", rows_value))
        if isinstance(rows_value, list)
        else None
    )
    value_status_value = kwargs.get("value_status", "published")
    value_status = str(value_status_value)
    filters_value = kwargs.get("filters")
    filters = (
        cast("Mapping[str, object]", filters_value)
        if isinstance(filters_value, Mapping)
        else None
    )
    dependencies, independence = overlap_metadata()
    release_id = pipeline.release.get("id")
    selected_rows = rows if rows is not None else pipeline.rows
    warnings = list(pipeline.diagnostics)
    return {
        "scope": scope(
            source="vals",
            benchmark=cast("str | None", benchmark.get("benchmark_id"))
            if benchmark
            else None,
            benchmark_version=cast("str | None", benchmark.get("version"))
            if benchmark
            else cast("str | None", pipeline.release.get("source_release_id")),
            release=cast("str | None", release_id),
            model_variant=model_variant,
            task_count=benchmark.get("task_count") if benchmark else None,
            task_count_population=benchmark.get("task_count_population")
            if benchmark
            else None,
            task_count_kind=benchmark.get("task_count_kind") if benchmark else None,
            filters_applied=dict(filters) if filters is not None else {},
        ),
        "value_status": value_status,
        "rows": selected_rows,
        "warnings": warnings,
        "diagnostics": warnings,
        "provenance": artifact_provenance(
            pipeline.artifact,
            parser=pipeline.document.parser,
            parser_version=pipeline.document.parser_version,
        ),
        "catalog": {
            "active_selector_entries": pipeline.catalog.active_selector_entries,
            "all_detail_anchors": pipeline.catalog.all_detail_anchors,
            "version_selector_entries": pipeline.catalog.version_selector_entries,
            "model_count": len(pipeline.catalog.models),
        },
        "dependencies": dependencies,
        "independence_class": independence,
    }


def _catalog(args: Namespace) -> dict[str, object]:
    pipeline = _pipeline(args)
    rows = pipeline.catalog.entries
    status = "published" if rows else "missing"
    if not rows:
        msg = "SOURCE_UNAVAILABLE"
        raise CommandError(
            msg,
            "No usable Vals catalog entries were discovered.",
            {"source_url": pipeline.artifact.source_url},
        )
    return success("catalog", _base_data(pipeline, rows=rows, value_status=status))


def _models(args: Namespace) -> dict[str, object]:
    pipeline = _pipeline(args, seed=SEED_MODELS)
    rows = pipeline.catalog.models
    if not rows:
        # Model profile fixtures often expose rows through the normal record parser.
        rows = [
            {
                "model": row.get("model"),
                "model_id": row.get("model_id"),
                "provider": row.get("provider"),
                "variant": row.get("variant"),
                "model_variant_id": row.get("model_variant_id"),
                "raw_fields": row.get("raw_fields", {}),
                "provenance": row.get("provenance"),
            }
            for row in pipeline.rows
            if row.get("model")
        ]
    if not rows:
        msg = "SOURCE_UNAVAILABLE"
        raise CommandError(
            msg,
            "No usable Vals model records were discovered.",
            {"source_url": pipeline.artifact.source_url},
        )
    return success("models", _base_data(pipeline, rows=rows, value_status="published"))


def _benchmark_rows(
    pipeline: Pipeline, benchmark: Mapping[str, object]
) -> list[dict[str, object]]:
    identifiers = {
        str(benchmark.get("benchmark_id")),
        str(benchmark.get("source_id")),
        str(benchmark.get("slug")),
        str(benchmark.get("display_name")),
        str(benchmark.get("benchmark")),
    }
    selected: list[dict[str, object]] = []
    for row in pipeline.rows:
        values = {
            str(row.get("benchmark_id")),
            str(row.get("benchmark_name")),
            str(row.get("benchmark")),
            str(row.get("benchmark_slug")),
        }
        if values & identifiers or not row.get("benchmark_id"):
            selected.append(row)
    return selected


def _benchmark(args: Namespace) -> dict[str, object]:
    pipeline = _pipeline(args)
    raw_selector = cast("object", getattr(args, "benchmark", None))
    selector = raw_selector if isinstance(raw_selector, str) else None
    benchmark = select_benchmark(pipeline.catalog, selector)
    if benchmark is None:
        # A detail page's metadata can be the only catalog entry.
        if (
            pipeline.metadata
            and selector
            and selector
            in {
                str(pipeline.metadata.get("benchmark_id")),
                str(pipeline.metadata.get("slug")),
                str(pipeline.metadata.get("benchmark")),
                str(pipeline.metadata.get("benchmarkName")),
            }
        ):
            benchmark = dict(pipeline.metadata)
        else:
            msg = "BENCHMARK_NOT_FOUND"
            raise CommandError(
                msg,
                "The requested Vals benchmark was not discovered.",
                {"selector": selector},
            )
    rows = _benchmark_rows(pipeline, benchmark)
    if not rows and benchmark.get("models"):
        rows = pipeline.rows
    value_status = "published" if rows else "missing"
    data = _base_data(
        pipeline,
        benchmark=benchmark,
        rows=rows,
        value_status=value_status,
        filters={"benchmark": selector},
    )
    data["benchmark"] = benchmark
    data["index_methodology"] = benchmark.get("index_methodology") or (
        pipeline.metadata.get("index_methodology")
        if pipeline.metadata
        else {
            "formula": None,
            "components": [],
            "weights": [],
            "denominator": None,
            "subset_selection": None,
            "benchmark_versions": [],
            "published_score_preserved": True,
        }
    )
    data["methodology"] = {
        "url": benchmark.get("methodology_url"),
        "definition": benchmark.get("score_definition"),
        "raw": benchmark.get("raw_metadata", {}),
    }
    if not rows and not benchmark.get("models"):
        warnings = cast("list[object]", data["warnings"])
        warnings.append(
            make(
                "PARTIAL_EXTRACTION",
                "Benchmark metadata was discovered without model metric rows.",
                stage="parse",
                details={"benchmark": benchmark.get("benchmark_id")},
            )
        )
    return success("benchmark", data)


def _model(args: Namespace) -> dict[str, object]:
    pipeline = _pipeline(args, seed=SEED_MODELS)
    raw_selector = cast("object", getattr(args, "model", None))
    selector = raw_selector if isinstance(raw_selector, str) else None
    model = select_model(pipeline.catalog, selector)
    rows = [
        row
        for row in pipeline.rows
        if str(row.get("model")) == str(selector)
        or str(row.get("model_id")) == str(selector)
        or str(row.get("model_variant_id")) == str(selector)
    ]
    if model is None and rows:
        model = {
            "model": rows[0].get("model"),
            "model_id": rows[0].get("model_id"),
            "provider": rows[0].get("provider"),
            "variant": rows[0].get("variant"),
            "model_variant_id": rows[0].get("model_variant_id"),
        }
    if model is None:
        msg = "MODEL_NOT_FOUND"
        raise CommandError(
            msg,
            "The requested Vals model was not discovered.",
            {"selector": selector},
        )
    if not rows:
        rows = [
            row for row in pipeline.rows if row.get("model_id") == model.get("model_id")
        ]
    data = _base_data(
        pipeline,
        rows=rows,
        model_variant=model.get("model_variant_id"),
        value_status="published" if rows else "missing",
        filters={"model": selector},
    )
    data["model"] = model
    return success("model", data)


def _selectors(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _metric_keys(value: object) -> list[str]:
    """Return metric keys from a metrics mapping."""
    if not isinstance(value, Mapping):
        return []
    return [str(key) for key in cast("Mapping[str, object]", value)]


def _gate_blocked(gate: object) -> bool:
    """Check whether a ranking gate reports blocked status."""
    if not isinstance(gate, Mapping):
        return False
    return cast("Mapping[str, object]", gate).get("status") == "blocked"


def _compare(args: Namespace) -> dict[str, object]:
    pipeline = _pipeline(args)
    raw_models = cast("object", getattr(args, "models", None))
    raw_benchmarks = cast("object", getattr(args, "benchmarks", None))
    model_selectors = _selectors(raw_models if isinstance(raw_models, str) else None)
    benchmark_selectors = _selectors(
        raw_benchmarks if isinstance(raw_benchmarks, str) else None
    )
    if not model_selectors:
        msg = "MISSING_REQUIRED_IDENTITY"
        raise CommandError(msg, "compare requires --models.", {})
    selected_models = set(model_selectors)
    selected_benchmarks: list[dict[str, object]] = []
    for selector in benchmark_selectors:
        item = select_benchmark(pipeline.catalog, selector)
        if item is None:
            msg = "BENCHMARK_NOT_FOUND"
            raise CommandError(
                msg,
                "A requested benchmark was not discovered.",
                {"selector": selector},
            )
        selected_benchmarks.append(item)
    rows = [
        row
        for row in pipeline.rows
        if str(row.get("model")) in selected_models
        or str(row.get("model_id")) in selected_models
        or str(row.get("model_variant_id")) in selected_models
    ]
    if selected_benchmarks:
        benchmark_ids = {
            str(item.get("benchmark_id")) for item in selected_benchmarks
        } | {str(item.get("slug")) for item in selected_benchmarks}
        rows = [
            row
            for row in rows
            if str(row.get("benchmark_id")) in benchmark_ids
            or str(row.get("benchmark_name")) in benchmark_ids
            or not row.get("benchmark_id")
        ]
    if not rows:
        msg = "SOURCE_UNAVAILABLE"
        raise CommandError(
            msg,
            "No usable rows matched the requested comparison selectors.",
            {"models": model_selectors, "benchmarks": benchmark_selectors},
        )
    rows, validation_diags, duplicate_excluded = validate_records(
        rows,
        expected_release=str(pipeline.release.get("id"))
        if pipeline.release.get("source_defined")
        else None,
    )
    diagnostics = merge(pipeline.diagnostics, validation_diags)
    if any(
        item.get("code") == "MIXED_RELEASE" and item.get("severity") == "error"
        for item in diagnostics
    ):
        msg = "MIXED_RELEASE"
        raise CommandError(
            msg,
            "The requested comparison contains mixed Vals releases.",
            {
                "releases": sorted(
                    {
                        str(row.get("release") or row.get("benchmark_version"))
                        for row in rows
                    }
                )
            },
        )
    if duplicate_excluded and len(duplicate_excluded) >= len(rows):
        msg = "DUPLICATE_MODEL_VARIANT"
        raise CommandError(
            msg,
            "Conflicting duplicate model-variant rows left no usable comparison rows.",
            {"rows": sorted(duplicate_excluded)},
        )
    fields = sorted(
        {str(field) for row in rows for field in _metric_keys(row.get("metrics"))}
    )
    rankings: dict[str, object] = {}
    for field in fields:
        rows, gate = rank_rows(rows, field=field, excluded=duplicate_excluded)
        rankings[field] = gate
    if not fields:
        diagnostics.append(
            make(
                "UNKNOWN_SCORE_SEMANTICS",
                "No recognized metric fields were published for the selected rows.",
                stage="validate",
                severity="warning",
            )
        )
    blocked = any(_gate_blocked(gate) for gate in rankings.values())
    value_status = "published" if rows else "missing"
    benchmark = selected_benchmarks[0] if len(selected_benchmarks) == 1 else None
    data = _base_data(
        pipeline,
        benchmark=benchmark,
        rows=rows,
        value_status=value_status,
        filters={"models": model_selectors, "benchmarks": benchmark_selectors},
    )
    data["warnings"] = merge(
        cast("list[dict[str, object]]", data["warnings"]), diagnostics
    )
    data["diagnostics"] = data["warnings"]
    data["rankings"] = rankings
    data["comparison_status"] = "blocked" if blocked else "eligible"
    data["comparison_blockers"] = [
        gate for gate in rankings.values() if _gate_blocked(gate)
    ]
    return success("compare", data)


def _catalog_diff(args: Namespace) -> dict[str, object]:
    raw_left = cast("object", getattr(args, "left", None))
    raw_right = cast("object", getattr(args, "right", None))
    raw_paths = cast("object", getattr(args, "paths", []))
    path_list = (
        cast("list[object]", cast("object", raw_paths))
        if isinstance(raw_paths, list)
        else []
    )
    left_path = str(raw_left) if isinstance(raw_left, str) and raw_left else None
    if left_path is None and path_list:
        left_path = str(path_list[0])
    right_path = str(raw_right) if isinstance(raw_right, str) and raw_right else None
    if right_path is None and len(path_list) > 1:
        right_path = str(path_list[1])
    if not left_path or not right_path:
        msg = "SNAPSHOT_INVALID"
        raise CommandError(
            msg,
            "catalog-diff requires --left and --right snapshots.",
            {},
        )
    left = _load_json_value(Path(str(left_path)))
    right = _load_json_value(Path(str(right_path)))
    result = diff(left, right)
    result["provenance"] = {
        "left": _snapshot_provenance(Path(str(left_path))),
        "right": _snapshot_provenance(Path(str(right_path))),
    }
    return success(
        "catalog-diff",
        {
            "scope": scope(source="vals", release=None),
            "value_status": "published",
            "rows": [],
            "warnings": [],
            "provenance": result["provenance"],
            "catalog_diff": result,
        },
    )


def _load_json_value(path: Path) -> object:
    try:
        text = path.read_text(encoding="utf-8")
        loaded = cast("object", json.loads(text))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        msg = "SNAPSHOT_INVALID"
        raise CommandError(
            msg,
            "Catalog snapshot is not valid JSON.",
            {"path": str(path)},
        ) from exc
    else:
        return loaded


def _snapshot_provenance(path: Path) -> dict[str, object]:
    body = path.read_bytes()
    freshness: dict[str, object] = {
        "mode": "snapshot",
        "historical": True,
        "stale": False,
    }
    return {
        "source_url": f"file://{path.resolve()}",
        "discovered_from": f"file://{path.resolve()}",
        "fetched_at": None,
        "sha256": sha256(body).hexdigest(),
        "content_type": "application/json",
        "historical": True,
        "stale": False,
        "freshness": freshness,
    }


def _diagnose(args: Namespace) -> dict[str, object]:
    pipeline = _pipeline(args)
    if (
        not pipeline.rows
        and not pipeline.catalog.entries
        and not pipeline.catalog.models
    ):
        msg = "SOURCE_UNAVAILABLE"
        raise CommandError(
            msg,
            "No usable Vals fields were extracted.",
            {"source_url": pipeline.artifact.source_url},
        )
    return success(
        "diagnose",
        _base_data(
            pipeline,
            rows=pipeline.rows,
            value_status="published" if pipeline.rows else "missing",
        ),
    )


def _schema() -> dict[str, object]:
    return success(
        "schema",
        {
            "schema_version": "1",
            "commands": [
                "catalog",
                "models",
                "model",
                "benchmark",
                "compare",
                "catalog-diff",
                "diagnose",
                "schema",
                "refresh",
                "snapshot",
            ],
            "canonical_listing_command": "catalog",
            "source": "vals",
            "value_statuses": ["published", "derived", "missing", "unparsed"],
            "metric_semantics_statuses": [
                "known",
                "unknown",
                "ambiguous",
                "invalid",
                "placeholder",
            ],
            "extraction_precedence": [
                "official_json",
                "official_csv",
                "embedded_json",
                "rsc",
                "json_ld",
                "html_table",
                "data_attribute",
                "plaintext",
            ],
            "freshness_modes": ["fresh", "revalidated", "stale-cache", "snapshot"],
            "envelope": {
                "success": ["ok", "schema_version", "command", "data"],
                "failure": ["ok", "schema_version", "command", "error"],
            },
            "dynamic_catalog": True,
            "raw_artifacts_content_addressed": True,
            "comparison_requires_exact_release_definition_unit_scope": True,
            "null_means": "unavailable_or_not_safely_interpretable",
        },
    )


def _cache_dir(args: Namespace) -> str | Path | None:
    """Return the cache directory override from parsed arguments."""
    raw = cast("object", getattr(args, "cache_dir", None))
    return raw if isinstance(raw, (str, Path)) else None


def _refresh(args: Namespace) -> dict[str, object]:
    pipeline = _pipeline(args)
    cache = CacheStore(_cache_dir(args))
    entry = cache.put(pipeline.artifact)
    return success(
        "refresh",
        _base_data(pipeline, rows=[], value_status="published")
        | {
            "artifacts": [
                {
                    "sha256": entry.sha256,
                    "raw_bytes_ref": str(entry.body_path),
                    "metadata_path": str(entry.metadata_path),
                }
            ]
        },
    )


def _snapshot(args: Namespace) -> dict[str, object]:
    pipeline = _pipeline(args)
    cache = CacheStore(_cache_dir(args))
    entry = cache.put(pipeline.artifact)
    manifest = cache.manifest(
        [entry],
        release=cast("str | None", pipeline.release.get("id")),
        source_url=pipeline.artifact.source_url,
    )
    data = _base_data(pipeline, rows=[], value_status="published")
    data["snapshot"] = {
        "snapshot_id": snapshot_identity(pipeline.artifact.body),
        "manifest": str(manifest),
        "historical": True,
        "stale": False,
    }
    return success("snapshot", data)


def dispatch(args: Namespace) -> dict[str, object]:
    """Dispatch a parsed command namespace to its projection handler."""
    handlers: dict[str, Callable[[Namespace], dict[str, object]]] = {
        "catalog": _catalog,
        "models": _models,
        "model": _model,
        "benchmark": _benchmark,
        "compare": _compare,
        "catalog-diff": _catalog_diff,
        "diagnose": _diagnose,
        "schema": lambda _args: _schema(),
        "refresh": _refresh,
        "snapshot": _snapshot,
    }
    raw_command = cast("object", getattr(args, "command", None))
    handler = handlers.get(raw_command if isinstance(raw_command, str) else "")
    if handler is None:
        msg = "SNAPSHOT_INVALID"
        raise CommandError(
            msg,
            "Unknown Vals command.",
            {"command": getattr(args, "command", None)},
        )
    return handler(args)
