# Copyright (c) 2026
"""Command projections over the LiveBench discovery/transport/parser pipeline."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .cache import CacheStore, sha256_bytes
from .contracts import (
    Diagnostic,
    RawArtifact,
    ResolvedRelease,
    raise_expected,
    utc_now,
)
from .diagnostics import diagnostics_dict, make_diagnostic
from .discovery import APP_URL, ReleaseDiscovery, discover_releases
from .identity import canonical_token, category_id, model_id, subtask_id, variant_id
from .normalization import numeric_value
from .parsing import ParsedReleaseAssets, parse_release_assets
from .release import plan_targets, resolve_release
from .semantics import (
    CATEGORY_FORMULA,
    OVERALL_DEFINITION,
    OVERALL_FORMULA,
    derive_mean,
    derive_selected_cost,
)
from .transport import FetchError, fetch_target
from .validation import DuplicateReport, duplicate_groups, validate_assets


@dataclass
class ReleaseContext:
    """Represent ReleaseContext in the LiveBench adapter."""

    discovery: ReleaseDiscovery
    release: ResolvedRelease
    parsed: ParsedReleaseAssets
    rows: list[dict[str, object]]
    catalog: dict[str, object]
    diagnostics: list[Diagnostic]


def load_context(  # noqa: PLR0913
    *,
    release_selector: str | None,
    snapshot: Path | None,
    cache_dir: Path | None,
    allow_stale: bool,
    timeout: float,
    table_url: str | None = None,
    categories_url: str | None = None,
    cost_url: str | None = None,
    opener: object | None = None,
) -> ReleaseContext:
    """Load context for the LiveBench adapter."""
    if snapshot is not None:
        loaded = _load_snapshot(snapshot, release_selector)
        if loaded is not None:
            return loaded
        raise_expected(
            "SNAPSHOT_INVALID",
            "Explicit snapshot could not be loaded as a LiveBench release asset set.",
            {"snapshot_path": str(snapshot)},
        )
    discovery = discover_releases(
        snapshot=None, cache=CacheStore(cache_dir), timeout=timeout, opener=opener
    )  # type: ignore[arg-type]
    explicit = {
        key: value
        for key, value in {
            "table": table_url,
            "category": categories_url,
            "cost": cost_url,
        }.items()
        if value
    }
    release = resolve_release(release_selector, discovery, explicit_asset_urls=explicit)
    targets = plan_targets(
        release,
        discovery,
        table_url=table_url,
        categories_url=categories_url,
        cost_url=cost_url,
    )
    store = CacheStore(cache_dir)
    artifacts: dict[str, RawArtifact] = {}
    diagnostics = list(discovery.warnings)
    for target in targets:
        try:
            artifacts[target.artifact_kind] = fetch_target(
                target, store, timeout=timeout, allow_stale=allow_stale, opener=opener
            )  # type: ignore[arg-type]
        except FetchError as exc:
            if (
                target.artifact_kind == "cost_table"
                and exc.details.get("http_status") == 404  # noqa: PLR2004
            ):
                diagnostics.append(
                    make_diagnostic(
                        "PARTIAL_EXTRACTION",
                        (
                            "Cost asset is absent for the selected release; "
                            "published cost is unavailable."
                        ),
                        severity="warning",
                        stage="fetch",
                        details={
                            "attempted_url": target.url,
                            "http_status": 404,
                            "cost_status": "absent",
                        },
                    )
                )
                continue
            raise
    if any(artifact.stale for artifact in artifacts.values()):
        diagnostics.append(
            make_diagnostic(
                "STALE_DATA",
                (
                    "A failed refresh was served from cache because "
                    "--allow-stale was explicit."
                ),
                severity="warning",
                stage="fetch",
                details={"freshness_mode": "stale-cache"},
            )
        )
    if any(artifact.historical for artifact in artifacts.values()):
        diagnostics.append(
            make_diagnostic(
                "HISTORICAL_SNAPSHOT",
                "Explicit snapshot artifact selected.",
                severity="warning",
                stage="fetch",
            )
        )
    parsed = parse_release_assets(
        release.release_id,
        artifacts["score_table"],
        artifacts["category_map"],
        artifacts.get("cost_table"),
    )
    diagnostics.extend(validate_assets(parsed))
    rows = normalize_rows(parsed, release)
    diagnostics.extend(_row_diagnostics(rows))
    if rows and all(row.get("_duplicate_conflict") for row in rows):
        raise_expected(
            "COMPARISON_INCOMPARABLE",
            "Conflicting duplicate identities left no usable model rows.",
            {"release_id": release.release_id},
        )
    catalog = build_catalog(parsed, release, rows)
    return ReleaseContext(discovery, release, parsed, rows, catalog, diagnostics)


def normalize_rows(  # noqa: PLR0915
    parsed: ParsedReleaseAssets, release: ResolvedRelease
) -> list[dict[str, object]]:
    """Normalize rows for the LiveBench adapter."""
    cost_by_identity: dict[tuple[str, str | None, str | None], dict[str, object]] = {}
    cost_by_model: dict[str, list[dict[str, object]]] = {}
    for row in parsed.cost_rows:
        slug = str(row.get("model") or "").strip()
        provider = _explicit(row, "provider")
        variant = _explicit(row, "variant", "model_variant")
        key = (slug, provider, variant)
        cost_by_identity.setdefault(key, row)
        cost_by_model.setdefault(slug, []).append(row)
    rows: list[dict[str, object]] = []
    mapped_tasks = {task for tasks in parsed.categories.values() for task in tasks}
    for row_index, source_row in enumerate(parsed.score_rows):
        slug = str(source_row.get("model") or "").strip()
        provider = _explicit(source_row, "provider")
        variant = _explicit(source_row, "variant", "model_variant")
        model_variant = variant_id(slug, provider, variant)
        artifact = parsed.artifacts["score_table"]
        categories: dict[str, object] = {}
        used_category_keys: set[str] = set()
        subtasks: list[dict[str, object]] = []
        all_category_values: list[tuple[str, Mapping[str, object]]] = []
        for raw_label, task_keys in parsed.categories.items():
            cat_key = canonical_token(raw_label)
            if cat_key in used_category_keys:
                suffix = 2
                while f"{cat_key}~{suffix}" in used_category_keys:
                    suffix += 1
                cat_key = f"{cat_key}~{suffix}"
            used_category_keys.add(cat_key)
            cat_tasks: list[str] = []
            cat_values: list[tuple[str, Mapping[str, object]]] = []
            for task in task_keys:
                cat_tasks.append(task)
                path = f"csv[row=model={slug},column={task}]"
                unit_hint, definition = _score_semantics(parsed.raw_fields, task)
                score, score_diags = numeric_value(
                    source_row.get(task),
                    path=path,
                    artifact=artifact,
                    unit_hint=unit_hint,
                    definition=definition,
                    semantics="known",
                    placeholder_zero=_placeholder_zero_declared(parsed.raw_fields),
                )
                score_dict = score.as_dict()
                score_dict["metric_id"] = subtask_id(task)
                score_dict["raw_label"] = task
                score_dict["category_id"] = category_id(raw_label)
                subtasks.append(
                    {
                        "subtask_id": subtask_id(task),
                        "raw_label": task,
                        "category_id": category_id(raw_label),
                        "score": score_dict,
                        "source_path": path,
                        "diagnostic_codes": [item.code for item in score_diags],
                    }
                )
                cat_values.append((path, score_dict))
            category_score = derive_mean(
                cat_values,
                formula=CATEGORY_FORMULA,
                definition_source_path=f"category_map[{raw_label!r}]",
            )
            category_score["metric_id"] = f"livebench:category-score:{cat_key}"
            categories[cat_key] = {
                "raw_label": raw_label,
                "category_id": category_id(raw_label),
                "score": category_score,
                "subtask_keys": cat_tasks,
                "source_path": f"category_map[{raw_label!r}]",
            }
            all_category_values.append((f"categories.{cat_key}.score", category_score))
        metadata_columns = {
            "model",
            "provider",
            "variant",
            "model_variant",
            "organization",
        }
        for column in parsed.score_headers:
            if column in metadata_columns or column in mapped_tasks:
                continue
            path = f"csv[row=model={slug},column={column}]"
            unknown, unknown_diags = numeric_value(
                source_row.get(column),
                path=path,
                artifact=artifact,
                semantics="unknown",
                placeholder_zero=_placeholder_zero_declared(parsed.raw_fields),
            )
            subtasks.append(
                {
                    "subtask_id": subtask_id(column),
                    "raw_label": column,
                    "category_id": None,
                    "score": unknown.as_dict(),
                    "source_path": path,
                    "unknown_category": True,
                    "diagnostic_codes": [
                        "UNKNOWN_CATEGORY",
                        "UNKNOWN_SCORE_SEMANTICS",
                        *[item.code for item in unknown_diags],
                    ],
                }
            )
        overall = derive_mean(
            all_category_values,
            formula=OVERALL_FORMULA,
            definition_source_path="ui:Overall — mean of category averages",
        )
        overall["definition"] = OVERALL_DEFINITION
        overall["metric_id"] = "livebench:overall"
        cost_source = cost_by_identity.get((slug, provider, variant))
        if cost_source is None:
            candidates = cost_by_model.get(slug, [])
            cost_source = candidates[0] if len(candidates) == 1 else None
        cost = normalize_cost(
            cost_source,
            parsed.artifacts.get("cost_table"),
            slug,
            parsed.categories,
            overall.get("normalized_value"),
        )
        record = {
            "source": "livebench",
            "release": {
                "id": release.release_id,
                "date": release.date,
                "latest": release.latest,
                "generated_at": release.generated_at,
                "task_count": sum(len(items) for items in parsed.categories.values()),
                "task_count_population": "mapped_category_task_keys",
                "task_count_kind": "derived_from_category_map",
                "category_count": len(parsed.categories),
                "category_count_population": "category_map_keys",
                "category_count_kind": "derived_from_category_map",
                "asset_set_id": (
                    f"livebench:release:{release.release_id}:"
                    f"{parsed.artifacts['score_table'].sha256[:16]}"
                ),
            },
            "model": slug,
            "model_id": model_id(slug),
            "provider": provider,
            "variant": variant,
            "model_variant_id": model_variant,
            "organization": source_row.get("organization"),
            "overall": overall,
            "categories": categories,
            "subtasks": subtasks,
            "cost": cost,
            "raw_fields": {
                key: value
                for key, value in source_row.items()
                if key not in {"model", *mapped_tasks}
            },
            "dependencies": overlap_metadata(),
            "independence_class": "independent",
            "value_status": "published",
            "provenance": [
                artifact.provenance(parser="livebench.csv")
                for artifact in parsed.artifacts.values()
            ],
            "source_evidence": [
                artifact.provenance(parser="livebench.csv")
                for artifact in parsed.artifacts.values()
            ],
            "_row_index": row_index,
        }
        rows.append(record)
    return rows


def normalize_cost(
    source_row: Mapping[str, object] | None,
    artifact: RawArtifact | None,
    slug: str,
    categories: Mapping[str, Sequence[str]],
    selected_score: object,
) -> dict[str, object]:
    """Normalize cost for the LiveBench adapter."""
    if source_row is None or artifact is None:
        return {
            "status": "absent",
            "cost_per_question": {
                "raw_value": None,
                "normalized_value": None,
                "unit": "per_question",
                "value_status": "missing",
                "missing_reason": "SOURCE_FIELD_ABSENT",
                "source_path": None,
            },
            "cost_per_successful_task": {
                "raw_value": None,
                "normalized_value": None,
                "unit": "per_successful_task",
                "value_status": "missing",
                "missing_reason": "SOURCE_FIELD_ABSENT",
                "source_path": None,
            },
            "published": {},
            "derived": {},
        }
    result: dict[str, object] = {"status": "published", "published": {}, "derived": {}}
    for field, unit in (
        ("cost_per_question", "per_question"),
        ("cost_per_successful_task", "per_successful_task"),
    ):
        path = f"cost_csv[row=model={slug},column={field}]"
        value, _ = numeric_value(
            source_row.get(field),
            path=path,
            artifact=artifact,
            unit_hint=unit,
            semantics="known",
        )
        result[field] = value.as_dict()
        published = result["published"]
        if isinstance(published, dict):
            published[field] = value.as_dict()
    task_keys = [task for tasks in categories.values() for task in tasks]
    result["derived"] = {
        "selected_scope": derive_selected_cost(
            source_row,
            task_keys,
            selected_score if isinstance(selected_score, (int, float)) else None,
            source_path_prefix=f"cost_csv[row=model={slug},column",
        )
    }
    result["raw_fields"] = {
        str(key): value
        for key, value in source_row.items()
        if key not in {"model", "cost_per_question", "cost_per_successful_task"}
    }
    return result


def build_catalog(
    parsed: ParsedReleaseAssets,
    release: ResolvedRelease,
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Build catalog for the LiveBench adapter."""
    categories: dict[str, object] = {}
    used_category_keys: set[str] = set()
    for label, tasks in parsed.categories.items():
        key = canonical_token(label)
        if key in used_category_keys:
            suffix = 2
            while f"{key}~{suffix}" in used_category_keys:
                suffix += 1
            key = f"{key}~{suffix}"
        used_category_keys.add(key)
        categories[key] = {
            "category_id": category_id(label),
            "raw_label": label,
            "subtask_keys": list(tasks),
            "task_count": len(tasks),
            "task_count_population": "category_map_array",
            "task_count_kind": "derived_from_category_map",
            "source_path": f"category_map[{label!r}]",
            "metric_semantics_status": "known",
        }
    models = [
        {
            "model": row.get("model"),
            "model_id": row.get("model_id"),
            "provider": row.get("provider"),
            "variant": row.get("variant"),
            "model_variant_id": row.get("model_variant_id"),
            "raw_fields": row.get("raw_fields", {}),
            "source_path": f"score_table[row={row.get('_row_index')}]",
        }
        for row in rows
    ]
    return {
        "source": "livebench",
        "release": release.as_dict(),
        "categories": categories,
        "models": models,
        "subtasks": [
            {
                "subtask_id": subtask_id(task),
                "raw_label": task,
                "categories": [
                    category_id(label)
                    for label, tasks in parsed.categories.items()
                    if task in tasks
                ],
            }
            for task in parsed.score_headers
            if task != "model"
        ],
        "columns": {
            "score_table": list(parsed.score_headers),
            "cost_table": list(parsed.cost_headers),
        },
        "category_count": {
            "value": len(parsed.categories),
            "kind": "derived_from_category_map",
            "population": "category_map_keys",
        },
        "task_count": {
            "value": sum(len(tasks) for tasks in parsed.categories.values()),
            "kind": "derived_from_category_map",
            "population": "mapped_category_task_keys",
        },
        "model_row_count": {
            "value": len(rows),
            "kind": "derived_from_score_table",
            "population": "score_table_rows",
        },
        "raw_fields": parsed.raw_fields,
    }


def build_releases_data(discovery: ReleaseDiscovery) -> dict[str, object]:
    """Build releases data for the LiveBench adapter."""
    return {
        "scope": {
            "source": "livebench",
            "release": None,
            "catalog": "release_selector",
        },
        "value_status": "published",
        "releases": discovery.releases,
        "latest": discovery.latest_id,
        "warnings": diagnostics_dict(discovery.warnings),
        "diagnostics": diagnostics_dict(discovery.warnings),
        "provenance": {
            "authority_url": discovery.authority_url,
            "sha256": discovery.authority_sha256,
            "fetched_at": discovery.discovered_at,
            "observed_at": discovery.discovered_at,
            "parser": "livebench.discovery",
            "parser_version": "1",
            "freshness": {
                "mode": "snapshot"
                if discovery.raw_metadata.get("snapshot_path")
                else "fresh",
                "historical": bool(discovery.raw_metadata.get("snapshot_path")),
                "stale": False,
            },
        },
    }


def project_data(
    context: ReleaseContext,
    *,
    model: str | None = None,
    models: Sequence[str] = (),
    category: str | None = None,
    include_rank: bool = False,
) -> dict[str, object]:
    """Project data for the LiveBench adapter."""
    rows = list(context.rows)
    if model:
        rows = select_models(rows, [model])
        if not rows:
            raise_expected(
                "MODEL_NOT_FOUND",
                "No exact model or variant matched the selector.",
                {"selector": model, "release": context.release.release_id},
            )
    if models:
        rows = select_models(rows, list(models))
        missing = [
            selector
            for selector in models
            if not select_models(context.rows, [selector])
        ]
        if missing:
            raise_expected(
                "MODEL_NOT_FOUND",
                "One or more exact model selectors did not match.",
                {"selectors": missing, "release": context.release.release_id},
            )
    if category is not None:
        key = canonical_token(category)
        matches = [
            name
            for name, metadata in context.catalog["categories"].items()
            if name == key or metadata.get("raw_label") == category
        ]
        if not matches:
            raise_expected(
                "UNKNOWN_CATEGORY",
                "The requested category is not present in this release.",
                {"selector": category, "release": context.release.release_id},
            )
        rows = [project_category(row, key) for row in rows]
    if include_rank:
        rank_rows(rows)
    scope = {
        "source": "livebench",
        "release": context.release.as_dict(),
        "model_variant": None,
        "score_definition": OVERALL_DEFINITION,
        "task_count": context.catalog["task_count"]["value"],
        "task_count_population": context.catalog["task_count"]["population"],
        "task_count_kind": context.catalog["task_count"]["kind"],
        "category_count": context.catalog["category_count"]["value"],
        "category_count_population": context.catalog["category_count"]["population"],
        "category_count_kind": context.catalog["category_count"]["kind"],
        "filters_applied": {
            "model": model,
            "models": list(models),
            "category": category,
        },
    }
    warnings = diagnostics_dict(context.diagnostics)
    return {
        "scope": scope,
        "value_status": "published",
        "rows": rows,
        "warnings": warnings,
        "diagnostics": warnings,
        "catalog": context.catalog,
        "provenance": {
            "authority": {
                "url": context.discovery.authority_url,
                "sha256": context.discovery.authority_sha256,
                "fetched_at": context.discovery.discovered_at,
            },
            "artifacts": [
                artifact.provenance(
                    parser="livebench.csv"
                    if kind != "category_map"
                    else "livebench.json"
                )
                for kind, artifact in context.parsed.artifacts.items()
            ],
            "freshness": _freshness(context),
        },
    }


def select_models(
    rows: Sequence[dict[str, object]], selectors: Sequence[str]
) -> list[dict[str, object]]:
    """Select models for the LiveBench adapter."""
    wanted = {str(selector).strip() for selector in selectors if str(selector).strip()}
    return [
        row
        for row in rows
        if str(row.get("model")) in wanted
        or str(row.get("model_id")) in wanted
        or str(row.get("model_variant_id")) in wanted
    ]


def project_category(row: dict[str, object], key: str) -> dict[str, object]:
    """Project category for the LiveBench adapter."""
    projected = dict(row)
    categories = row.get("categories")
    projected["selected_category"] = (
        categories.get(key) if isinstance(categories, Mapping) else None
    )
    projected["categories"] = (
        {key: categories[key]}
        if isinstance(categories, Mapping) and key in categories
        else {}
    )
    return projected


def rank_rows(rows: list[dict[str, object]]) -> None:
    """Rank rows for the LiveBench adapter."""
    eligible: list[tuple[float, dict[str, object]]] = []
    for row in rows:
        overall = row.get("overall")
        value = (
            overall.get("normalized_value") if isinstance(overall, Mapping) else None
        )
        blocked = row.get("comparison_eligibility") == "blocked" or row.get(
            "_duplicate_conflict"
        )
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and not blocked
        ):
            eligible.append((float(value), row))
        else:
            row["rank"] = None
            row["rank_status"] = "blocked"
    eligible.sort(key=lambda item: (-item[0], str(item[1].get("model_variant_id"))))
    for index, (_, row) in enumerate(eligible, 1):
        row["rank"] = index
        row["rank_status"] = "eligible"


def _row_diagnostics(rows: Sequence[dict[str, object]]) -> list[Diagnostic]:
    duplicate = duplicate_groups(
        [
            {
                "model": row.get("model"),
                "provider": row.get("provider"),
                "variant": row.get("variant"),
                "overall": row.get("overall"),
            }
            for row in rows
        ]
    )
    diagnostics = list(duplicate.diagnostics)
    diagnostics.extend(_numeric_diagnostics(rows))
    _mark_duplicate_conflicts(rows, duplicate)
    if duplicate.conflicting_groups and not (
        len(rows) > sum(len(group) for group in duplicate.conflicting_groups)
    ):
        diagnostics.append(
            make_diagnostic(
                "COMPARISON_INCOMPARABLE",
                (
                    "All model rows have conflicting duplicate identities; "
                    "no ranking is safe."
                ),
                severity="blocker",
                stage="validate",
            )
        )
    return diagnostics


def _numeric_diagnostics(
    rows: Sequence[dict[str, object]],
) -> list[Diagnostic]:
    known_codes = {
        "MALFORMED_PAYLOAD",
        "NUMERIC_AMBIGUITY",
        "OUT_OF_RANGE",
        "PLACEHOLDER_VALUE",
        "UNKNOWN_SCORE_SEMANTICS",
    }
    seen_values: set[tuple[str, str | None]] = set()
    diagnostics: list[Diagnostic] = []
    for row in rows:
        subtasks = row.get("subtasks")
        if not isinstance(subtasks, list):
            continue
        for subtask in subtasks:
            if not isinstance(subtask, Mapping):
                continue
            path = (
                str(subtask.get("source_path")) if subtask.get("source_path") else None
            )
            codes = subtask.get("diagnostic_codes")
            if not isinstance(codes, list):
                continue
            for raw_code in codes:
                code = str(raw_code)
                key = (code, path)
                if code not in known_codes or key in seen_values:
                    continue
                seen_values.add(key)
                diagnostics.append(
                    make_diagnostic(
                        code,
                        (
                            f"Numeric value at {path or 'unknown source path'} "
                            "requires attention."
                        ),
                        severity="warning",
                        stage="normalize",
                        path=path,
                    )
                )
    return diagnostics


def _mark_duplicate_conflicts(
    rows: Sequence[dict[str, object]], duplicate: DuplicateReport
) -> None:
    for indexes in duplicate.conflicting_groups:
        for index in indexes:
            if index < len(rows):
                rows[index]["_duplicate_conflict"] = True
                rows[index]["comparison_eligibility"] = "blocked"


def _freshness(context: ReleaseContext) -> dict[str, object]:
    modes = {artifact.freshness_mode for artifact in context.parsed.artifacts.values()}
    if "stale-cache" in modes:
        return {"mode": "stale-cache", "historical": False, "stale": True}
    if "snapshot" in modes:
        return {"mode": "snapshot", "historical": True, "stale": False}
    if "revalidated" in modes:
        return {"mode": "revalidated", "historical": False, "stale": False}
    return {"mode": "fresh", "historical": False, "stale": False}


def overlap_metadata() -> list[dict[str, object]]:
    """Overlap metadata for the LiveBench adapter."""
    return [
        {
            "source": "livebench",
            "index_name": "LiveBench Coding",
            "canonical_benchmark_id": "livebench:category:coding",
            "relationship": "conceptual_overlap_coding_agent_work",
            "population": "release/category scoped",
            "release": None,
            "certainty": "requirements_claim",
            "evidence": {"source_url": APP_URL, "source_path": "category_map"},
        },
        {
            "source": "livebench",
            "index_name": "LiveBench Agentic Coding",
            "canonical_benchmark_id": "livebench:category:agentic-coding",
            "relationship": "conceptual_overlap_coding_agent_work",
            "population": "release/category scoped",
            "release": None,
            "certainty": "requirements_claim",
            "evidence": {"source_url": APP_URL, "source_path": "category_map"},
        },
    ]


def catalog_data(context: ReleaseContext) -> dict[str, object]:
    """Catalog data for the LiveBench adapter."""
    data = project_data(context)
    data["rows"] = context.catalog["models"]
    data["value_status"] = "published"
    return data


def snapshot_manifest(
    context: ReleaseContext, output: Path | None = None
) -> dict[str, object]:
    """Snapshot manifest for the LiveBench adapter."""
    artifacts = {
        kind: {
            "artifact_id": artifact.artifact_id,
            "source_url": artifact.source_url,
            "discovered_from": artifact.discovered_from,
            "release_id": artifact.release_id,
            "sha256": artifact.sha256,
            "byte_length": artifact.byte_length,
            "raw_bytes_ref": artifact.raw_bytes_ref,
            "fetched_at": artifact.fetched_at,
            "observed_at": artifact.observed_at,
            "etag": artifact.headers.get("etag"),
            "last_modified": artifact.headers.get("last-modified"),
            "content_type": artifact.content_type,
        }
        for kind, artifact in context.parsed.artifacts.items()
    }
    manifest = {
        "schema_version": "1",
        "source": "livebench",
        "snapshot_id": (
            "snapshot:sha256:"
            f"{sha256_bytes(json.dumps(artifacts, sort_keys=True).encode())}"
        ),
        "release": context.release.as_dict(),
        "artifacts": artifacts,
        "catalog": context.catalog,
        "freshness": {"mode": "snapshot", "historical": True, "stale": False},
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(manifest, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )
    return manifest


def _explicit(row: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _placeholder_zero_declared(raw_fields: Mapping[str, object]) -> bool:
    metadata = raw_fields.get("source_metadata")
    if not isinstance(metadata, Mapping):
        return False
    return any(
        marker in str(value).casefold()
        for value in metadata.values()
        for marker in ("placeholder", "loading")
    )


def _score_semantics(
    raw_fields: Mapping[str, object], task: str
) -> tuple[str | None, str | None]:
    definitions = raw_fields.get("definitions")
    if isinstance(definitions, Mapping) and task in definitions:
        definition = definitions[task]
        if isinstance(definition, Mapping):
            unit = definition.get("unit")
            description = definition.get("definition")
            return (
                str(unit) if unit is not None else None,
                str(description) if description is not None else None,
            )
        if definition is None:
            return None, None
    return "source-defined", "LiveBench release score subtask"


def _attach_snapshot_metadata(
    parsed_assets: ParsedReleaseAssets, payload: Mapping[str, object]
) -> None:
    for key in ("source_metadata", "definitions", "raw_metadata"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            parsed_assets.raw_fields[key] = dict(value)


def _load_snapshot(path: Path, requested_release: str | None) -> ReleaseContext | None:
    try:
        body = path.read_bytes()
        parsed = json.loads(body.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, Mapping):
        return None
    release_obj = parsed.get("release") or parsed.get("resolved_release")
    if isinstance(release_obj, Mapping):
        release_id = str(
            release_obj.get("id")
            or release_obj.get("release_id")
            or parsed.get("release_id")
            or "fixture-release"
        )
        release_date = (
            str(release_obj.get("date"))
            if release_obj.get("date") is not None
            else release_id
        )
    else:
        release_id = str(release_obj or parsed.get("release_id") or "fixture-release")
        release_date = release_id
    if (
        requested_release
        and requested_release.casefold() != "latest"
        and requested_release != release_id
    ):
        raise_expected(
            "MIXED_RELEASE",
            "Snapshot release does not match the requested release.",
            {"requested_release": requested_release, "snapshot_release": release_id},
        )
    # Direct normalized fixture records are accepted for deterministic
    # source-local tests.
    if (
        isinstance(parsed.get("score_rows"), list)
        and isinstance(parsed.get("categories"), Mapping)
        and not isinstance(parsed.get("artifacts") or parsed.get("assets"), Mapping)
    ):
        score_rows = [
            dict(row) for row in parsed["score_rows"] if isinstance(row, Mapping)
        ]
        cost_rows = (
            [
                dict(row)
                for row in parsed.get("cost_rows", [])
                if isinstance(row, Mapping)
            ]
            if isinstance(parsed.get("cost_rows", []), list)
            else []
        )
        categories = {
            str(key): [str(task) for task in value]
            for key, value in parsed["categories"].items()
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        }
        assets = _fixture_artifacts(path, release_id, score_rows, cost_rows, categories)
        parsed_assets = parse_release_assets(
            release_id,
            assets["score_table"],
            assets["category_map"],
            assets.get("cost_table"),
        )
        _attach_snapshot_metadata(parsed_assets, parsed)
        diagnostics = [
            make_diagnostic(
                "HISTORICAL_SNAPSHOT",
                "An explicit historical snapshot is being used.",
                severity="warning",
                stage="discover",
                details={"path": str(path)},
            )
        ]
        diagnostics.extend(validate_assets(parsed_assets))
        rows = normalize_rows(
            parsed_assets, _fixture_release(release_id, release_date, path)
        )
        diagnostics.extend(_row_diagnostics(rows))
        if rows and all(row.get("_duplicate_conflict") for row in rows):
            raise_expected(
                "COMPARISON_INCOMPARABLE",
                "Conflicting duplicate identities left no usable model rows.",
                {"release_id": release_id},
            )
        discovery = _fixture_discovery(path, release_id, parsed)
        release = _fixture_release(release_id, release_date, path)
        return ReleaseContext(
            discovery,
            release,
            parsed_assets,
            rows,
            build_catalog(parsed_assets, release, rows),
            diagnostics,
        )
    artifacts = parsed.get("artifacts") or parsed.get("assets")
    if isinstance(artifacts, Mapping):
        assets = _fixture_artifacts_from_refs(path, release_id, artifacts)
        if "score_table" not in assets or "category_map" not in assets:
            raise_expected(
                "SOURCE_UNAVAILABLE",
                "Snapshot release asset is missing or unreadable.",
                {"release_id": release_id, "attempted_assets": list(artifacts)},
            )
        parsed_assets = parse_release_assets(
            release_id,
            assets["score_table"],
            assets["category_map"],
            assets.get("cost_table"),
        )
        _attach_snapshot_metadata(parsed_assets, parsed)
        release = _fixture_release(release_id, release_date, path)
        diagnostics = [
            make_diagnostic(
                "HISTORICAL_SNAPSHOT",
                "An explicit historical snapshot is being used.",
                severity="warning",
                stage="discover",
                details={"path": str(path)},
            )
        ]
        diagnostics.extend(validate_assets(parsed_assets))
        rows = normalize_rows(parsed_assets, release)
        diagnostics.extend(_row_diagnostics(rows))
        if rows and all(row.get("_duplicate_conflict") for row in rows):
            raise_expected(
                "COMPARISON_INCOMPARABLE",
                "Conflicting duplicate identities left no usable model rows.",
                {"release_id": release_id},
            )
        return ReleaseContext(
            _fixture_discovery(path, release_id, parsed),
            release,
            parsed_assets,
            rows,
            build_catalog(parsed_assets, release, rows),
            diagnostics,
        )
    return None


def _fixture_release(release_id: str, date: str, path: Path) -> ResolvedRelease:
    digest = sha256_bytes(path.read_bytes())
    return ResolvedRelease(
        requested="snapshot",
        release_id=release_id,
        latest=True,
        date=date,
        source_defined=True,
        authority_url=f"fixture://{path}",
        authority_sha256=digest,
        discovered_at=utc_now(),
        metadata={"snapshot_path": str(path)},
    )


def _fixture_discovery(
    path: Path, release_id: str, payload: Mapping[str, object]
) -> ReleaseDiscovery:
    entries = payload.get("releases")
    releases = (
        [dict(item) for item in entries if isinstance(item, Mapping)]
        if isinstance(entries, list)
        else [{"id": release_id, "date": release_id}]
    )
    if not any(str(item.get("id")) == release_id for item in releases):
        releases.append({"id": release_id, "date": release_id})
    return ReleaseDiscovery(
        releases,
        release_id,
        f"fixture://{path}",
        sha256_bytes(path.read_bytes()),
        utc_now(),
        raw_metadata={"snapshot_path": str(path)},
    )


def _fixture_artifacts(
    path: Path,
    release_id: str,
    score_rows: list[dict[str, object]],
    cost_rows: list[dict[str, object]],
    categories: Mapping[str, Sequence[str]],
) -> dict[str, RawArtifact]:
    score_buf = io.StringIO()
    fields: list[str] = ["model"]
    for row in score_rows:
        for key in row:
            if key not in fields:
                fields.append(str(key))
    writer = csv.DictWriter(score_buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(score_rows)
    category_body = json.dumps(categories, ensure_ascii=False).encode("utf-8")
    artifacts: dict[str, RawArtifact] = {
        "score_table": _fixture_artifact(
            path,
            release_id,
            "score_table",
            score_buf.getvalue().encode("utf-8"),
            "text/csv",
        ),
        "category_map": _fixture_artifact(
            path, release_id, "category_map", category_body, "application/json"
        ),
    }
    if cost_rows:
        cost_buf = io.StringIO()
        cost_fields: list[str] = ["model"]
        for row in cost_rows:
            for key in row:
                if key not in cost_fields:
                    cost_fields.append(str(key))
        writer = csv.DictWriter(cost_buf, fieldnames=cost_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(cost_rows)
        artifacts["cost_table"] = _fixture_artifact(
            path,
            release_id,
            "cost_table",
            cost_buf.getvalue().encode("utf-8"),
            "text/csv",
        )
    return artifacts


def _fixture_artifact(
    path: Path, release_id: str, kind: str, body: bytes, content_type: str
) -> RawArtifact:
    digest = sha256_bytes(body)
    now = utc_now()
    return RawArtifact(
        f"livebench:{release_id}:{kind}:sha256:{digest}",
        "livebench",
        release_id,
        kind,
        f"fixture://{path}#{kind}",
        f"fixture://{path}",
        body,
        200,
        content_type,
        {},
        now,
        now,
        digest,
        len(body),
        str(path),
        "snapshot",
        stale=False,
        historical=True,
        cache_reused=False,
        generated_at=None,
    )


def _fixture_artifacts_from_refs(
    path: Path,
    release_id: str,
    refs: Mapping[object, object],
) -> dict[str, RawArtifact]:
    result: dict[str, RawArtifact] = {}
    aliases = {
        "table": "score_table",
        "categories": "category_map",
        "category": "category_map",
        "cost": "cost_table",
        "score_table": "score_table",
        "category_map": "category_map",
        "cost_table": "cost_table",
    }
    for raw_kind, ref in refs.items():
        kind = aliases.get(str(raw_kind))
        if kind is None:
            continue
        body: bytes | None = None
        content_type = "application/json" if kind == "category_map" else "text/csv"
        source_url = f"fixture://{path}#{kind}"
        if isinstance(ref, Mapping):
            if ref.get("body") is not None:
                body = str(ref["body"]).encode("utf-8")
            elif ref.get("path") is not None or ref.get("raw_bytes_ref") is not None:
                raw_path = ref.get("path") or ref.get("raw_bytes_ref")
                ref_path = Path(str(raw_path))
                try:
                    body = (
                        (path.parent / ref_path).resolve().read_bytes()
                        if not ref_path.is_absolute()
                        else ref_path.read_bytes()
                    )
                except OSError:
                    body = None
            source_url = str(ref.get("url") or ref.get("source_url") or source_url)
            content_type = str(ref.get("content_type") or content_type)
        elif isinstance(ref, str):
            ref_path = Path(ref)
            try:
                body = (
                    (path.parent / ref_path).resolve().read_bytes()
                    if not ref_path.is_absolute()
                    else ref_path.read_bytes()
                )
            except OSError:
                body = (
                    ref.encode("utf-8")
                    if (ref.lstrip().startswith("{") or "\n" in ref)
                    else None
                )
        if body is None:
            continue
        ref_release = (
            str(ref.get("release_id") or release_id)
            if isinstance(ref, Mapping)
            else release_id
        )
        result[kind] = _fixture_artifact(path, ref_release, kind, body, content_type)
    return result
