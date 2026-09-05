# Copyright (c) 2026
"""Strict source-local parsers for LiveBench release assets."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from .contracts import Diagnostic, RawArtifact, SkillError, raise_expected
from .diagnostics import make_diagnostic
from .extraction import ParsedDocument, extract_artifact


@dataclass
class ParsedReleaseAssets:
    """Represent ParsedReleaseAssets in the LiveBench adapter."""

    release_id: str
    categories: dict[str, list[str]]
    score_rows: list[dict[str, object]]
    score_headers: list[str]
    cost_rows: list[dict[str, object]]
    cost_headers: list[str]
    artifacts: dict[str, RawArtifact]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    raw_fields: dict[str, object] = field(default_factory=dict)


def parse_release_assets(
    release_id: str,
    table: RawArtifact,
    category: RawArtifact,
    cost: RawArtifact | None = None,
) -> ParsedReleaseAssets:
    """Parse release assets for the LiveBench adapter."""
    diagnostics: list[Diagnostic] = []
    table_doc, table_diags = extract_artifact(table)
    category_doc, category_diags = extract_artifact(category)
    diagnostics.extend(table_diags)
    diagnostics.extend(category_diags)
    if table_doc is None:
        raise_expected(
            "MALFORMED_PAYLOAD",
            "Score table payload was unusable.",
            {"artifact_kind": "score_table", "source_url": table.source_url},
        )
    if category_doc is None:
        raise_expected(
            "MALFORMED_PAYLOAD",
            "Category map payload was unusable.",
            {"artifact_kind": "category_map", "source_url": category.source_url},
        )
    score_rows, score_headers, score_unknown = _rows_from_document(
        table_doc, "model", table
    )
    categories = _category_map(category_doc.root, category)
    cost_rows: list[dict[str, object]] = []
    cost_headers: list[str] = []
    cost_unknown: dict[str, object] = {}
    artifacts = {"score_table": table, "category_map": category}
    if cost is not None:
        cost_doc, cost_diags = extract_artifact(cost)
        diagnostics.extend(cost_diags)
        if cost_doc is not None:
            try:
                cost_rows, cost_headers, cost_unknown = _rows_from_document(
                    cost_doc, "model", cost
                )
            except SkillError as exc:
                diagnostics.append(
                    make_diagnostic(
                        "MALFORMED_PAYLOAD",
                        exc.message,
                        severity="warning",
                        stage="parse",
                        artifact=cost.artifact_id,
                        details=exc.details,
                    )
                )
        artifacts["cost_table"] = cost
    if (
        table.release_id != release_id
        or category.release_id != release_id
        or (cost is not None and cost.release_id != release_id)
    ):
        raise_expected(
            "MIXED_RELEASE",
            "Release assets do not share the resolved release identity.",
            {
                "resolved_release": release_id,
                "assets": {
                    kind: artifact.release_id for kind, artifact in artifacts.items()
                },
            },
        )
    if "model" not in score_headers:
        raise_expected(
            "SCHEMA_DRIFT",
            "Score table must contain a model identity column.",
            {"headers": score_headers},
        )
    mapped_tasks = {task for tasks in categories.values() for task in tasks}
    missing_tasks = sorted(mapped_tasks.difference(score_headers))
    if missing_tasks:
        diagnostics.append(
            make_diagnostic(
                "SCHEMA_DRIFT",
                "Category mapping references score columns that are absent.",
                severity="warning",
                stage="validate",
                artifact=category.artifact_id,
                details={"missing_columns": missing_tasks},
            )
        )
    unmapped_columns = [
        header
        for header in score_headers
        if header != "model" and header not in mapped_tasks
    ]
    if unmapped_columns:
        diagnostics.append(
            make_diagnostic(
                "UNKNOWN_CATEGORY",
                "Score columns are not present in the category map.",
                severity="warning",
                stage="validate",
                artifact=table.artifact_id,
                details={"unmapped_columns": unmapped_columns},
            )
        )
    raw_fields: dict[str, object] = {
        "score_table": score_unknown,
        "cost_table": cost_unknown,
        "unmapped_score_columns": unmapped_columns,
        "category_map": {"raw_labels": list(categories)},
    }
    return ParsedReleaseAssets(
        release_id,
        categories,
        score_rows,
        score_headers,
        cost_rows,
        cost_headers,
        artifacts,
        diagnostics,
        raw_fields,
    )


def _rows_from_document(  # noqa: C901
    document: ParsedDocument, identity_field: str, artifact: RawArtifact
) -> tuple[list[dict[str, object]], list[str], dict[str, object]]:
    root = document.root
    if isinstance(root, Mapping):
        root_map = cast("Mapping[str, object]", root)
        candidate = (
            root_map.get("rows") or root_map.get("data") or root_map.get("models")
        )
        if isinstance(candidate, list):
            root = cast("list[object]", cast("object", candidate))
    if not isinstance(root, list):
        raise_expected(
            "MALFORMED_PAYLOAD",
            "Tabular payload must contain a list of rows.",
            {"artifact_kind": artifact.artifact_kind},
        )
    entries = cast("list[object]", cast("object", root))
    rows: list[dict[str, object]] = []
    headers: list[str] = []
    for index, row in enumerate(entries):
        if not isinstance(row, Mapping):
            raise_expected(
                "MALFORMED_PAYLOAD",
                "Tabular payload contains a non-object row.",
                {"row_index": index, "artifact_kind": artifact.artifact_kind},
            )
        row_map = cast("Mapping[str, object]", row)
        normalized = {str(key): value for key, value in row_map.items()}
        if not headers:
            headers = list(normalized)
        for key in normalized:
            if key not in headers:
                headers.append(key)
        identity = normalized.get(identity_field)
        if identity is None or not str(identity).strip():
            raise_expected(
                "MISSING_REQUIRED_IDENTITY",
                "A tabular row has no model identity.",
                {"row_index": index, "artifact_kind": artifact.artifact_kind},
            )
        rows.append(normalized)
    if not rows:
        raise_expected(
            "MALFORMED_PAYLOAD",
            "Tabular payload contains no usable rows.",
            {"artifact_kind": artifact.artifact_kind},
        )
    return rows, headers, {}


def _category_map(root: object, artifact: RawArtifact) -> dict[str, list[str]]:
    if isinstance(root, Mapping):
        root_map = cast("Mapping[str, object]", root)
        candidate = root_map.get("categories")
        if isinstance(candidate, Mapping):
            root = cast("Mapping[str, object]", candidate)
    if not isinstance(root, Mapping):
        raise_expected(
            "MALFORMED_PAYLOAD",
            "Category payload must be an object mapping labels to task arrays.",
            {"source_url": artifact.source_url},
        )
    root_map = cast("Mapping[str, object]", root)
    result: dict[str, list[str]] = {}
    for raw_label, task_values in root_map.items():
        label = str(raw_label)
        if not isinstance(task_values, Sequence) or isinstance(
            task_values, (str, bytes)
        ):
            raise_expected(
                "MALFORMED_PAYLOAD",
                "Category task entries must be arrays.",
                {"category": label},
            )
        tasks = [str(task) for task in task_values if str(task)]
        if not tasks:
            result[label] = []
        else:
            result[label] = tasks
    if not result:
        raise_expected(
            "MALFORMED_PAYLOAD",
            "Category map contains no categories.",
            {"source_url": artifact.source_url},
        )
    return result


def parse_release_list(document: object) -> list[dict[str, object]]:
    """Parse a fixture or discovered bundle release list without an allow-list."""
    root = document
    if isinstance(root, Mapping):
        root_map = cast("Mapping[str, object]", root)
        root = (
            root_map.get("releases") or root_map.get("data") or root_map.get("entries")
        )
    if not isinstance(root, Sequence) or isinstance(root, (str, bytes)):
        raise_expected(
            "MALFORMED_PAYLOAD",
            "Release catalog must contain an array of entries.",
            {},
        )
    entries: list[dict[str, object]] = []
    for index, item in enumerate(root):
        if isinstance(item, str):
            entries.append({"id": item, "date": item, "index": index})
        elif isinstance(item, Mapping):
            release = {
                str(key): value
                for key, value in cast("Mapping[str, object]", item).items()
            }
            identifier = (
                release.get("id") or release.get("release") or release.get("date")
            )
            if identifier is None or not str(identifier).strip():
                continue
            release["id"] = str(identifier)
            _ = release.setdefault("date", str(identifier))
            release["index"] = index
            entries.append(release)
    if not entries:
        raise_expected(
            "MALFORMED_PAYLOAD",
            "Release catalog contains no valid release IDs.",
            {},
        )
    return entries
