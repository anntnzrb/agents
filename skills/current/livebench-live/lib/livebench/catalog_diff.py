# Copyright (c) 2026
"""Order-independent release/category/subtask/model/schema diffing."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .cache import sha256_bytes
from .contracts import raise_expected, utc_now


def load_snapshot_catalog(path: str) -> tuple[dict[str, object], dict[str, object]]:
    """Load snapshot catalog for the LiveBench adapter."""
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise_expected(
            "SNAPSHOT_INVALID",
            "Catalog snapshot is not valid JSON.",
            {"path": path, "error": str(exc)},
        )
    if not isinstance(payload, Mapping):
        raise_expected(
            "SNAPSHOT_INVALID",
            "Catalog snapshot root must be an object.",
            {"path": path},
        )
    schema_version = payload.get("schema_version")
    if schema_version is not None and str(schema_version) != "1":
        raise_expected(
            "SNAPSHOT_INVALID",
            "Catalog snapshot schema version is unsupported.",
            {"path": path, "schema_version": schema_version},
        )
    catalog = payload.get("catalog")
    if not isinstance(catalog, Mapping):
        catalog = payload
    return {str(key): value for key, value in catalog.items()}, {
        "source_url": payload.get("source_url") or f"fixture://{source}",
        "fetched_at": payload.get("fetched_at") or utc_now(),
        "sha256": sha256_bytes(source.read_bytes()),
        "release": payload.get("release") or payload.get("release_id"),
        "freshness": payload.get("freshness") or {},
    }


def diff_catalog(
    left: Mapping[str, object], right: Mapping[str, object]
) -> dict[str, object]:
    """Diff catalog for the LiveBench adapter."""
    left_entries = _entries(left)
    right_entries = _entries(right)
    left_ids = set(left_entries)
    right_ids = set(right_entries)
    added = sorted(right_ids - left_ids)
    removed = sorted(left_ids - right_ids)
    renamed: list[dict[str, object]] = []
    changed: list[dict[str, object]] = []
    schema_changes: list[str] = []
    for identifier in sorted(left_ids & right_ids):
        before = left_entries[identifier]
        after = right_entries[identifier]
        old_name = (
            before.get("raw_label")
            or before.get("display_name")
            or before.get("model")
            or identifier
        )
        new_name = (
            after.get("raw_label")
            or after.get("display_name")
            or after.get("model")
            or identifier
        )
        if old_name != new_name:
            renamed.append(
                {"id": identifier, "old_name": old_name, "new_name": new_name}
            )
        for path, old_value, new_value in _changed_paths(before, after):
            changed.append(
                {
                    "id": identifier,
                    "path": path,
                    "before": old_value,
                    "after": new_value,
                }
            )
    schema_changes.extend(_schema_changes(left, right))
    return {
        "added": added,
        "removed": removed,
        "renamed": renamed,
        "changed_metadata": changed,
        "schema_changes": sorted(set(schema_changes)),
        "possible_renames": [],
        "warnings": [],
    }


def _entries(catalog: Mapping[str, object]) -> dict[str, dict[str, object]]:
    entries: dict[str, dict[str, object]] = {}
    for field, prefix in (
        ("categories", "category"),
        ("models", "model"),
        ("subtasks", "subtask"),
    ):
        value = catalog.get(field)
        if isinstance(value, Mapping):
            for key, item in value.items():
                if isinstance(item, Mapping):
                    identifier = str(
                        item.get(f"{prefix}_id")
                        or item.get("model_id")
                        or item.get("subtask_id")
                        or key
                    )
                    entries[f"{field}:{identifier}"] = {
                        str(k): v for k, v in item.items()
                    }
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for index, item in enumerate(value):
                if not isinstance(item, Mapping):
                    continue
                identifier = str(
                    item.get(f"{prefix}_id")
                    or item.get("model_id")
                    or item.get("subtask_id")
                    or item.get("id")
                    or index
                )
                entries[f"{field}:{identifier}"] = {str(k): v for k, v in item.items()}
    if not entries:
        release = catalog.get("release") or catalog.get("release_id")
        if release is not None:
            entries["release"] = {"id": str(release), "display_name": str(release)}
    return entries


def _changed_paths(
    before: Mapping[str, object], after: Mapping[str, object], prefix: str = ""
) -> list[tuple[str, object, object]]:
    changes: list[tuple[str, object, object]] = []
    keys = set(before) | set(after)
    for key in sorted(keys):
        path = f"{prefix}.{key}" if prefix else str(key)
        if key not in before or key not in after:
            continue
        left = before[key]
        right = after[key]
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            changes.extend(_changed_paths(left, right, path))
        elif left != right:
            changes.append((path, left, right))
    return changes


def _schema_changes(
    left: Mapping[str, object], right: Mapping[str, object]
) -> list[str]:
    changes: list[str] = []

    def walk(a: object, b: object, path: str) -> None:
        """Walk for the LiveBench adapter."""
        if isinstance(a, Mapping) and isinstance(b, Mapping):
            for key in sorted(set(a) | set(b)):
                child = f"{path}.{key}" if path else str(key)
                if key not in a:
                    changes.append(f"added:{child}")
                elif key not in b:
                    changes.append(f"removed:{child}")
                else:
                    walk(a[key], b[key], child)
        elif isinstance(a, list) and isinstance(b, list):
            if a and b and type(a[0]) is not type(b[0]):
                changes.append(f"type:{path}")
        elif type(a) is not type(b):
            changes.append(f"type:{path}")

    walk(left, right, "")
    return changes
