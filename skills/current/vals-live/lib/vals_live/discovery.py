# Copyright 2026 Vals-live contributors.
"""Runtime discovery of Vals benchmark, version, and model catalogs."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from html import unescape
from typing import cast

from .contracts import Catalog, Diagnostic, ParsedDocument
from .diagnostics import make
from .identity import canonical_url, stable_id

_BENCHMARK_HREF = re.compile(
    r"href\s*=\s*(['\"])(/benchmarks/[^'\"?#]+)", re.IGNORECASE
)
_MODEL_HREF = re.compile(r"href\s*=\s*(['\"])(/models/[^'\"?#]+)", re.IGNORECASE)


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _walk(value: object, path: str = "$") -> Iterable[tuple[Mapping[str, object], str]]:
    if isinstance(value, Mapping):
        mapping = cast("Mapping[str, object]", value)
        yield mapping, path
        for key, child in mapping.items():
            if isinstance(child, (Mapping, list)):
                yield from _walk(cast("object", child), f"{path}.{key}")
    elif isinstance(value, list):
        seq = cast("Sequence[object]", value)
        for index, child in enumerate(seq):
            if isinstance(child, (Mapping, list)):
                yield from _walk(cast("object", child), f"{path}[{index}]")


def _is_model(item: Mapping[str, object]) -> bool:
    return any(
        key in item
        for key in (
            "model",
            "model_name",
            "model_key",
            "model_slug",
            "provider",
            "release_date",
        )
    ) and not any(
        key in item
        for key in (
            "benchmark",
            "benchmark_id",
            "benchmarkName",
            "benchmark_name",
            "industry",
        )
    )


def _is_benchmark(item: Mapping[str, object]) -> bool:
    if _is_model(item):
        return False
    return any(
        key in item
        for key in (
            "benchmark_id",
            "benchmarkName",
            "benchmark_name",
            "benchmark",
            "benchmarkSlug",
            "benchmark_slug",
            "slug",
        )
    ) and (
        any(
            key in item
            for key in (
                "industry",
                "family",
                "tasks",
                "metadata",
                "version",
                "archived",
                "benchmark_id",
            )
        )
        or str(item.get("url", "")).find("/benchmarks/") >= 0
        or str(item.get("canonical_url", "")).find("/benchmarks/") >= 0
    )


def _url_from(item: Mapping[str, object]) -> str | None:
    value = item.get("canonical_url") or item.get("url") or item.get("href")
    if isinstance(value, str) and value:
        if value.startswith("/"):
            return "https://www.vals.ai" + value
        return value
    slug = item.get("slug") or item.get("benchmark_slug") or item.get("benchmarkSlug")
    if isinstance(slug, str) and slug:
        return f"https://www.vals.ai/benchmarks/{slug}"
    return None


def _benchmark_entry(
    item: Mapping[str, object], path: str, source_url: str
) -> dict[str, object] | None:
    name = (
        _text(item.get("benchmark"))
        or _text(item.get("benchmarkName"))
        or _text(item.get("benchmark_name"))
        or _text(item.get("name"))
        or _text(item.get("label"))
    )
    slug = (
        _text(item.get("slug"))
        or _text(item.get("benchmark_slug"))
        or _text(item.get("benchmarkSlug"))
    )
    url = _url_from(item)
    source_id = item.get("benchmark_id") or item.get("id")
    if not name and not slug and not url and not source_id:
        return None
    if not name:
        name = slug or str(source_id)
    benchmark_id, basis = stable_id(
        "vals", source_id=source_id, url=url, label=slug or name, kind="benchmark"
    )
    known = {
        "benchmark",
        "benchmarkName",
        "benchmark_name",
        "name",
        "label",
        "slug",
        "benchmark_slug",
        "benchmarkSlug",
        "benchmark_id",
        "id",
        "url",
        "href",
        "canonical_url",
        "industry",
        "category",
        "family",
        "version",
        "updated",
        "updated_at",
        "archived",
        "visible",
        "noindex",
        "canonical",
        "canonicalUrl",
        "dataset_type",
        "proprietary",
        "academic",
        "tasks",
        "total_models",
        "models",
        "methodology_url",
        "description",
        "metrics",
        "score_definition",
        "use_cost_per_test",
        "runner",
        "mode",
        "partner",
        "partners",
    }
    raw_metadata = {
        str(key): value for key, value in item.items() if str(key) not in known
    }
    status = (
        "archived"
        if item.get("archived") is True or item.get("status") == "archived"
        else ("active" if item.get("visible") is not False else "unknown")
    )
    task_value = item.get("task_count") or item.get("total_tasks")
    task_count = (
        task_value
        if isinstance(task_value, (int, float, str))
        and not isinstance(task_value, bool)
        else None
    )
    entry: dict[str, object] = {
        "source": "vals",
        "benchmark_id": benchmark_id,
        "source_id": source_id,
        "identity_basis": basis,
        "display_name": name,
        "slug": slug,
        "canonical_url": canonical_url(url or source_url),
        "original_url": url or source_url,
        "discovered_from": source_url,
        "category": item.get("industry") or item.get("category"),
        "benchmark_type": item.get("benchmark_type") or item.get("dataset_type"),
        "status": status,
        "proprietary": item.get("proprietary"),
        "academic": item.get("academic"),
        "updated_at": item.get("updated") or item.get("updated_at"),
        "version": item.get("version"),
        "task_count": task_count,
        "task_count_population": "detail_models"
        if item.get("total_models") is not None
        else ("task_keys" if isinstance(item.get("tasks"), Mapping) else None),
        "task_count_kind": "published" if task_count is not None else None,
        "methodology_url": item.get("methodology_url"),
        "metric_semantics_status": "known"
        if item.get("score_definition") or item.get("metrics")
        else "unknown",
        "raw_metadata": raw_metadata,
        "raw_fields": dict(item),
        "source_path": path,
        "archive": {
            "archived": bool(item.get("archived")),
            "canonical": item.get("canonical") or item.get("canonicalUrl"),
            "noindex": item.get("noindex"),
        },
    }
    return entry


def _model_entry(
    item: Mapping[str, object], path: str, source_url: str
) -> dict[str, object] | None:
    name = (
        _text(item.get("model"))
        or _text(item.get("model_name"))
        or _text(item.get("model_key"))
        or _text(item.get("model_slug"))
        or _text(item.get("name"))
    )
    if not name:
        return None
    source_id = item.get("model_id") or item.get("id") or item.get("slug")
    url = item.get("url") or item.get("href")
    if isinstance(url, str) and url.startswith("/"):
        url = "https://www.vals.ai" + url
    model_key = f"vals:model:{source_id or name}"
    known = {
        "model",
        "model_name",
        "model_key",
        "model_slug",
        "name",
        "model_id",
        "id",
        "slug",
        "url",
        "href",
        "provider",
        "company",
        "variant",
        "harness",
        "release_date",
        "is_open_source",
        "open_source",
        "release",
        "release_id",
    }
    return {
        "source": "vals",
        "model": name,
        "model_id": model_key,
        "source_id": source_id,
        "provider": item.get("provider") or item.get("company"),
        "variant": item.get("variant"),
        "harness": item.get("harness"),
        "model_variant_id": (
            f"{model_key}:variant:{item.get('provider') or 'unknown'}:"
            f"{item.get('variant') or 'unknown'}"
        ),
        "url": url,
        "release_date": item.get("release_date"),
        "raw_metadata": {str(k): v for k, v in item.items() if str(k) not in known},
        "raw_fields": dict(item),
        "source_path": path,
        "discovered_from": source_url,
    }


def _add_benchmark(
    catalog: Catalog,
    entry: dict[str, object] | None,
    seen: set[str],
    *,
    active: bool = False,
    detail: bool = False,
) -> None:
    if not entry:
        return
    benchmark_id = str(entry["benchmark_id"])
    if benchmark_id in seen:
        return
    seen.add(benchmark_id)
    catalog.entries.append(entry)
    if active:
        catalog.active_selector_entries.append(entry)
    if detail:
        catalog.all_detail_anchors.append(entry)


def _add_model(
    catalog: Catalog, model: dict[str, object] | None, seen: set[str]
) -> None:
    if not model:
        return
    model_id = str(model["model_id"])
    if model_id in seen:
        return
    seen.add(model_id)
    catalog.models.append(model)


def _discover_root_benchmarks(
    root: Mapping[str, object],
    source_url: str,
    catalog: Catalog,
    seen_benchmarks: set[str],
) -> None:
    for key in ("data", "active_selector_entries", "benchmarks"):
        value = root.get(key)
        if not isinstance(value, list):
            continue
        items_seq = cast("Sequence[object]", value)
        for index, item in enumerate(items_seq):
            if isinstance(item, Mapping):
                entry = _benchmark_entry(
                    cast("Mapping[str, object]", item), f"$.{key}[{index}]", source_url
                )
                _add_benchmark(catalog, entry, seen_benchmarks, active=True)


def _discover_root_versions(
    root: Mapping[str, object], source_url: str, catalog: Catalog
) -> None:
    versions = root.get("versions") or root.get("version_selector_entries")
    if not isinstance(versions, list):
        return
    versions_seq = cast("Sequence[object]", versions)
    for index, item in enumerate(versions_seq):
        if isinstance(item, Mapping):
            version: dict[str, object] = dict(cast("Mapping[str, object]", item))
            version["source_path"] = f"$.versions[{index}]"
            version["discovered_from"] = source_url
            catalog.version_selector_entries.append(version)


def _preserve_root_populations(root: Mapping[str, object], catalog: Catalog) -> None:
    for key in (
        "all_detail_anchors",
        "active_selector_entries",
        "version_selector_entries",
        "models",
    ):
        value = root.get(key)
        if isinstance(value, list):
            catalog.raw_metadata[key] = value


def _discover_root_metadata(
    root: object,
    source_url: str,
    catalog: Catalog,
    seen_benchmarks: set[str],
) -> None:
    if not isinstance(root, Mapping):
        return
    root_map = cast("Mapping[str, object]", root)
    _discover_root_benchmarks(root_map, source_url, catalog, seen_benchmarks)
    _discover_root_versions(root_map, source_url, catalog)
    _preserve_root_populations(root_map, catalog)


def _discover_html_links(
    body_text: str,
    source_url: str,
    catalog: Catalog,
    seen_benchmarks: set[str],
    seen_models: set[str],
) -> None:
    for index, match in enumerate(_BENCHMARK_HREF.finditer(body_text)):
        href = unescape(match.group(2))
        slug = href.rsplit("/", 1)[-1]
        entry = _benchmark_entry(
            {"slug": slug, "url": f"https://www.vals.ai{href}", "name": slug},
            f"html.a[{index}]",
            source_url,
        )
        _add_benchmark(catalog, entry, seen_benchmarks, detail=True)
    for index, match in enumerate(_MODEL_HREF.finditer(body_text)):
        href = unescape(match.group(2))
        slug = href.rsplit("/", 1)[-1]
        model = _model_entry(
            {"slug": slug, "name": slug, "url": f"https://www.vals.ai{href}"},
            f"html.a[{index}]",
            source_url,
        )
        _add_model(catalog, model, seen_models)


def _catalog_diagnostics(catalog: Catalog, source_url: str) -> None:
    for entry in catalog.entries:
        if entry.get("metric_semantics_status") == "unknown":
            diag = make(
                "UNKNOWN_SCORE_SEMANTICS",
                ("Benchmark metadata does not publish a recognized score definition."),
                stage="discover",
                severity="warning",
                details={
                    "benchmark_id": entry.get("benchmark_id"),
                    "display_name": entry.get("display_name"),
                },
            )
            catalog.diagnostics.append(
                Diagnostic(
                    code=str(diag["code"]),
                    severity=str(diag["severity"]),
                    stage=str(diag["stage"]),
                    message=str(diag["message"]),
                    details=cast("dict[str, object]", diag.get("details", {})),
                )
            )
    if not catalog.entries and not catalog.models:
        diag = make(
            "PARTIAL_EXTRACTION",
            "No benchmark or model catalog entries were discovered.",
            stage="discover",
            severity="error",
            details={"source_url": source_url},
        )
        catalog.diagnostics.append(
            Diagnostic(
                code=str(diag["code"]),
                severity=str(diag["severity"]),
                stage=str(diag["stage"]),
                message=str(diag["message"]),
                details=cast("dict[str, object]", diag.get("details", {})),
            )
        )


def discover(document: ParsedDocument) -> Catalog:
    """Discover benchmark and model entries from decoded source data."""
    root = document.root
    source_url = document.artifact.source_url
    catalog = Catalog()
    seen_benchmarks: set[str] = set()
    seen_models: set[str] = set()
    for item, path in _walk(root):
        if _is_benchmark(item):
            _add_benchmark(
                catalog,
                _benchmark_entry(item, path, source_url),
                seen_benchmarks,
                active=item.get("status") == "active",
                detail=True,
            )
        if _is_model(item):
            _add_model(catalog, _model_entry(item, path, source_url), seen_models)
    _discover_root_metadata(root, source_url, catalog, seen_benchmarks)
    body_text = document.artifact.body.decode("utf-8", errors="replace")
    _discover_html_links(body_text, source_url, catalog, seen_benchmarks, seen_models)
    _catalog_diagnostics(catalog, source_url)
    return catalog


def select_benchmark(
    catalog: Catalog, selector: str | None
) -> dict[str, object] | None:
    """Resolve one exact benchmark selector."""
    if not selector:
        return None
    value = selector.strip()
    canonical = canonical_url(value)
    for entry in catalog.entries:
        choices = {
            str(entry.get("benchmark_id")),
            str(entry.get("source_id")),
            str(entry.get("slug")),
            str(entry.get("display_name")),
            str(entry.get("canonical_url")),
            str(entry.get("original_url")),
        }
        if value in choices or canonical in {
            str(entry.get("canonical_url")),
            str(entry.get("original_url")),
        }:
            return entry
    return None


def select_model(catalog: Catalog, selector: str | None) -> dict[str, object] | None:
    """Resolve one exact model selector."""
    if not selector:
        return None
    value = selector.strip()
    canonical = canonical_url(value)
    for entry in catalog.models:
        choices = {
            str(entry.get("model_id")),
            str(entry.get("source_id")),
            str(entry.get("model")),
            str(entry.get("url")),
        }
        if value in choices or canonical == canonical_url(str(entry.get("url") or "")):
            return entry
    return None
