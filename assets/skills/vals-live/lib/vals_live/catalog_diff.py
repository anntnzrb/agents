# Copyright 2026 Vals-live contributors.
"""Conservative deterministic catalog snapshot diff."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .identity import canonical_url


def _entries(snapshot: object) -> list[dict[str, Any]]:
    if isinstance(snapshot, list):
        return [dict(item) for item in snapshot if isinstance(item, Mapping)]
    if isinstance(snapshot, Mapping):
        for key in ("entries", "catalog", "rows", "benchmarks", "data"):
            value = snapshot.get(key)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, Mapping)]
            if isinstance(value, Mapping) and key == "data":
                nested = _entries(value)
                if nested:
                    return nested
    return []


def _identity(entry: Mapping[str, object]) -> tuple[str, str]:
    source_id = entry.get("benchmark_id") or entry.get("source_id") or entry.get("id")
    if isinstance(source_id, str) and source_id:
        return "id", source_id
    url = entry.get("canonical_url") or entry.get("url") or entry.get("original_url")
    if isinstance(url, str) and url:
        return "url", canonical_url(url)
    slug = entry.get("slug")
    if isinstance(slug, str) and slug:
        return "slug", slug
    return "label", str(entry.get("display_name") or entry.get("name") or "")


def _key(entry: Mapping[str, object]) -> str:
    return f"{_identity(entry)[0]}:{_identity(entry)[1]}"


def diff(left: object, right: object) -> dict[str, Any]:
    """Classify deterministic catalog additions, renames, and schema changes."""
    before = _entries(left)
    after = _entries(right)
    left_map = {_key(item): item for item in before}
    right_map = {_key(item): item for item in after}
    added = [right_map[key] for key in sorted(right_map.keys() - left_map.keys())]
    removed = [left_map[key] for key in sorted(left_map.keys() - right_map.keys())]
    renamed: list[dict[str, object]] = []
    changed: list[dict[str, object]] = []
    schema_changes: list[dict[str, object]] = []
    for key in sorted(left_map.keys() & right_map.keys()):
        old, new = left_map[key], right_map[key]
        old_name = old.get("display_name") or old.get("name")
        new_name = new.get("display_name") or new.get("name")
        if old_name != new_name:
            renamed.append(
                {
                    "id": key,
                    "old_name": old_name,
                    "new_name": new_name,
                    "old_url": old.get("canonical_url"),
                    "new_url": new.get("canonical_url"),
                }
            )
        changed.extend(
            {
                "id": key,
                "field": field,
                "before": old.get(field),
                "after": new.get(field),
            }
            for field in (
                "canonical_url",
                "original_url",
                "category",
                "status",
                "version",
                "updated_at",
                "task_count",
                "methodology_url",
                "metric_semantics_status",
            )
            if old.get(field) != new.get(field)
        )
        old_fields = (
            set((old.get("raw_fields") or {}).keys())
            if isinstance(old.get("raw_fields"), Mapping)
            else set(old.keys())
        )
        new_fields = (
            set((new.get("raw_fields") or {}).keys())
            if isinstance(new.get("raw_fields"), Mapping)
            else set(new.keys())
        )
        schema_changes.extend(
            {"id": key, "field": field, "change": "added"}
            for field in sorted(new_fields - old_fields)
        )
        schema_changes.extend(
            {"id": key, "field": field, "change": "removed"}
            for field in sorted(old_fields - new_fields)
        )
    possible: list[dict[str, object]] = []
    for old in removed:
        for new in added:
            old_label = str(old.get("display_name") or old.get("name") or "").casefold()
            new_label = str(new.get("display_name") or new.get("name") or "").casefold()
            if (
                old_label
                and new_label
                and (old_label in new_label or new_label in old_label)
            ):
                possible.append(
                    {
                        "old": old,
                        "new": new,
                        "reason": "label_similarity_without_stable_identity",
                    }
                )
    return {
        "base_snapshot": _snapshot_id(left),
        "target_snapshot": _snapshot_id(right),
        "added": added,
        "removed": removed,
        "renamed": renamed,
        "changed_metadata": changed,
        "schema_changes": schema_changes,
        "possible_renames": possible,
        "warnings": [],
    }


def _snapshot_id(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key in ("snapshot_id", "id", "sha256"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
        provenance = value.get("provenance")
        if isinstance(provenance, Mapping) and isinstance(
            provenance.get("sha256"), str
        ):
            return str(provenance["sha256"])
    return None
