# Copyright 2026 Vals-live contributors.
"""Source-specific Vals page parsing and duplicate-path handling."""

from collections.abc import Mapping
from typing import TYPE_CHECKING, TypeIs

from .diagnostics import make
from .discovery import discover
from .normalization import normalize_document_records

if TYPE_CHECKING:
    from .contracts import Catalog, ParsedDocument


def _is_mapping(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _is_mapping_or_list(value: object) -> TypeIs[Mapping[str, object] | list[object]]:
    return isinstance(value, (Mapping, list))


def _find_mappings(
    root: object, keys: set[str], path: str = "$"
) -> list[tuple[str, Mapping[str, object]]]:
    found: list[tuple[str, Mapping[str, object]]] = []
    if _is_mapping(root):
        if any(key in root for key in keys):
            found.append((path, root))
        for key, value in root.items():
            if _is_mapping_or_list(value):
                found.extend(_find_mappings(value, keys, f"{path}.{key}"))
    elif _is_list(root):
        for index, value in enumerate(root):
            if _is_mapping_or_list(value):
                found.extend(_find_mappings(value, keys, f"{path}[{index}]"))
    return found


def benchmark_metadata(
    document: ParsedDocument,
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    """Extract and reconcile benchmark metadata candidates."""
    diagnostics: list[dict[str, object]] = []
    candidates = _find_mappings(
        document.root, {"benchmark_id", "family", "benchmarkName", "benchmark_name"}
    )
    if not candidates:
        return None, diagnostics
    normalized: list[dict[str, object]] = []
    for path, item in candidates:
        metadata = dict(item)
        meta_sub = metadata.get("metadata")
        if _is_mapping(meta_sub):
            metadata = dict(meta_sub)
        entry: dict[str, object] = {"path": path}
        entry.update(metadata)
        normalized.append(entry)
    primary = normalized[0]
    comparable_keys = (
        "benchmark_id",
        "family",
        "version",
        "updated",
        "benchmark",
        "benchmarkName",
        "benchmark_name",
        "slug",
    )
    conflicts = [
        candidate
        for candidate in normalized[1:]
        if any(
            candidate.get(key) != primary.get(key)
            for key in comparable_keys
            if candidate.get(key) is not None and primary.get(key) is not None
        )
    ]
    if conflicts:
        diagnostics.append(
            make(
                "SCHEMA_DRIFT",
                (
                    "Duplicate Vals metadata paths disagree; all candidates "
                    "remain in provenance."
                ),
                stage="parse",
                severity="warning",
                details={"candidates": normalized},
            )
        )
        diagnostics.append(
            make(
                "PARTIAL_EXTRACTION",
                "Conflicting metadata paths prevented silent precedence.",
                stage="parse",
                severity="warning",
                details={"paths": [item["path"] for item in normalized]},
            )
        )
        primary["metadata_candidates"] = normalized
    else:
        primary["metadata_candidates"] = normalized
    doc_root = document.root if _is_mapping(document.root) else None
    root_methodology: object = (
        doc_root.get("index_methodology") if doc_root is not None else None
    )
    if root_methodology is None and doc_root is not None:
        doc_root_map = doc_root
        root_methodology = {
            key: doc_root_map[key]
            for key in (
                "formula",
                "components",
                "weights",
                "denominator",
                "subset_selection",
                "benchmark_versions",
            )
            if key in doc_root_map
        }
    if _is_mapping(root_methodology) and root_methodology:
        primary["index_methodology"] = dict(root_methodology)
    return primary, diagnostics


def parse_catalog(document: ParsedDocument) -> tuple[Catalog, list[dict[str, object]]]:
    """Build a discovered benchmark/model catalog with diagnostics."""
    catalog = discover(document)
    diagnostics = list(document.diagnostics)
    diagnostics.extend(item.as_dict() for item in catalog.diagnostics)
    return catalog, diagnostics


def parse_records(
    document: ParsedDocument, *, catalog: Catalog | None = None
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object] | None]:
    """Normalize document records and retain metadata-only model identities."""
    metadata, metadata_diags = benchmark_metadata(document)
    if metadata is None and catalog and len(catalog.entries) == 1:
        metadata = catalog.entries[0]
    records, diagnostics = normalize_document_records(document, benchmark_hint=metadata)
    diagnostics = metadata_diags + diagnostics
    if not records and metadata is not None:
        models_val = metadata.get("models")
        if _is_list(models_val):
            for index, model in enumerate(models_val):
                if isinstance(model, str):
                    records.append(
                        {
                            "source": "vals",
                            "model": model,
                            "model_id": f"vals:model:{model}",
                            "provider": None,
                            "variant": None,
                            "model_variant_id": (
                                f"vals:model:{model}:variant:unknown-unknown-unknown"
                            ),
                            "benchmark_id": metadata.get("benchmark_id"),
                            "benchmark_name": metadata.get("benchmark")
                            or metadata.get("benchmarkName"),
                            "benchmark_version": metadata.get("version"),
                            "metrics": {},
                            "raw_fields": {},
                            "value_status": "missing",
                            "missing_reason": "SOURCE_FIELD_ABSENT",
                            "source_evidence": [],
                            "source_path": f"$.models[{index}]",
                        }
                    )
    return records, diagnostics, metadata


def parse(
    document: ParsedDocument,
) -> tuple[
    Catalog,
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object] | None,
]:
    """Parse catalog, records, metadata, and diagnostics as one projection."""
    catalog, catalog_diags = parse_catalog(document)
    records, record_diags, metadata = parse_records(document, catalog=catalog)
    diagnostics = catalog_diags + record_diags
    if (
        records
        and record_diags
        and any(item.get("severity") in {"warning", "blocker"} for item in record_diags)
    ):
        diagnostics.append(
            make(
                "PARTIAL_EXTRACTION",
                (
                    "Some fields were usable while others were missing, "
                    "ambiguous, or unparsed."
                ),
                stage="parse",
                severity="warning",
                details={"rows": len(records)},
            )
        )
    if _is_mapping(document.root):
        categories = document.root.get("categories")
        if _is_mapping(categories) and categories:
            cat_map = categories
            diagnostics.append(
                make(
                    "UNKNOWN_CATEGORY",
                    (
                        "Category labels are source-defined and retained "
                        "without a fixed taxonomy."
                    ),
                    stage="parse",
                    severity="warning",
                    details={"labels": list(cat_map.keys())},
                )
            )
    return catalog, records, diagnostics, metadata
