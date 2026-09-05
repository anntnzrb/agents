# Copyright (c) 2026 anntnzrb
"""Deterministic, additive schema-aware comparison for AA snapshots."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher
from numbers import Real
from typing import Final, cast

from .contracts import compact_json
from .diagnostics import redact

_STATUS_KEYS = frozenset(
    {
        "value_status",
        "metric_semantics_status",
        "comparison_eligibility",
        "status",
        "missing_reason",
        "blocked_reasons",
    },
)
_STRUCTURAL_KEYS = frozenset(
    {
        "slug",
        "id",
        "model_id",
        "model_slug",
        "name",
        "label",
        "host_id",
        "host_slug",
    },
)

RENAME_SIMILARITY_THRESHOLD: Final[float] = 0.72


def _safe(value: object) -> object:
    """Return a redacted, finite JSON projection for diff output."""
    value = redact(value)
    if isinstance(value, Mapping):
        mapping = cast("Mapping[str, object]", value)
        return {str(key): _safe(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        items = cast("list[object]", cast("object", value))
        return [_safe(item) for item in items]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _encoded(value: object) -> str:
    try:
        return compact_json(_safe(value))
    except (TypeError, ValueError):
        return compact_json(str(value))


def _mapping(value: object) -> Mapping[str, object]:
    """Narrow an arbitrary value to a string-keyed mapping."""
    if not isinstance(value, Mapping):
        return {}
    return cast("Mapping[str, object]", value)


def _rows(
    snapshot: Mapping[str, object], names: Sequence[str]
) -> list[dict[str, object]]:
    """Collect row mappings from the first present snapshot section."""
    for name in names:
        section = snapshot.get(name)
        if isinstance(section, Mapping):
            mapping = cast("Mapping[str, object]", section)
            section = list(mapping.values())
        if isinstance(section, list):
            entries = cast("list[object]", cast("object", section))
            return [
                cast("dict[str, object]", row)
                for row in entries
                if isinstance(row, Mapping)
            ]
    return []


def _nested_slug(value: object, fallback: object) -> object:
    """Read a slug from a nested mapping or fall back to a flat value."""
    if isinstance(value, Mapping):
        mapping = cast("Mapping[str, object]", value)
        return mapping.get("slug", fallback)
    return fallback


def _identity(kind: str, row: Mapping[str, object], index: int) -> str:
    for key in ("slug", "id", "model_id" if kind == "model" else "endpoint_id"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return f"{kind}:{value.strip()}"
    if kind == "endpoint":
        host_slug = _nested_slug(row.get("host"), row.get("host_slug"))
        model_slug = _nested_slug(row.get("model"), row.get("model_slug"))
        if isinstance(host_slug, str) and isinstance(model_slug, str):
            return f"endpoint:{host_slug.strip()}:{model_slug.strip()}"
    # An anonymous record must not be merged by display name.  Its canonical
    # row hash is stable when no explicit identity is published.
    digest = hashlib.sha256(_encoded(row).encode("utf-8")).hexdigest()[:16]
    return f"{kind}:anonymous:{index}:{digest}"


def _display_name(row: Mapping[str, object]) -> str | None:
    for key in ("name", "label", "model_name"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = row.get("model")
    if isinstance(nested, Mapping):
        nested_mapping = cast("Mapping[str, object]", nested)
        value = nested_mapping.get("name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _indexed(
    kind: str,
    rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for index, row in enumerate(rows):
        identity = _identity(kind, row, index)
        grouped.setdefault(identity, []).append(dict(row))
    selected: dict[str, dict[str, object]] = {}
    duplicates: list[dict[str, object]] = []
    for identity in sorted(grouped):
        values = sorted(grouped[identity], key=_encoded)
        selected[identity] = values[0]
        if len(values) > 1:
            duplicates.append(
                {
                    "kind": kind,
                    "id": identity,
                    "count": len(values),
                    "conflict": len({_encoded(item) for item in values}) > 1,
                    "row_hashes": [
                        hashlib.sha256(_encoded(item).encode("utf-8")).hexdigest()
                        for item in values
                    ],
                },
            )
    return selected, duplicates


def _leaf_values(value: object, prefix: str = "") -> dict[str, object]:
    """Flatten nested mappings to dotted-path leaf values."""
    if isinstance(value, Mapping):
        mapping = cast("Mapping[str, object]", value)
        result: dict[str, object] = {}
        if not mapping:
            result[prefix] = {}
        for key in sorted(mapping, key=str):
            path = f"{prefix}.{key}" if prefix else str(key)
            result.update(_leaf_values(mapping[key], path))
        return result
    return {prefix: value}


def _field_diff(
    before: Mapping[str, object], after: Mapping[str, object], identity: str
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    left = _leaf_values(before)
    right = _leaf_values(after)
    added: list[dict[str, object]] = []
    removed: list[dict[str, object]] = []
    changed: list[dict[str, object]] = []
    for path in sorted(set(left) | set(right)):
        if path not in left:
            added.append({"id": identity, "path": path, "value": _safe(right[path])})
        elif path not in right:
            removed.append({"id": identity, "path": path, "value": _safe(left[path])})
        elif _encoded(left[path]) != _encoded(right[path]):
            changed.append(
                {
                    "id": identity,
                    "path": path,
                    "before": _safe(left[path]),
                    "after": _safe(right[path]),
                },
            )
    return added, removed, changed


def _metric_names(row: Mapping[str, object]) -> set[str]:
    names: set[str] = set()
    evidence = row.get("metric_evidence")
    if isinstance(evidence, Mapping):
        mapping = cast("Mapping[str, object]", evidence)
        names.update(str(key) for key in mapping)
    for path, value in _leaf_values(row).items():
        leaf = path.rsplit(".", 1)[-1]
        if leaf in _STRUCTURAL_KEYS or leaf in _STATUS_KEYS:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, Real):
            names.add(path)
    return names


def _metric_value(row: Mapping[str, object], metric: str) -> object:
    if metric in row:
        return row[metric]
    current: object = row
    for piece in metric.split("."):
        if not isinstance(current, Mapping):
            current = None
            break
        mapping = cast(  # pyright: ignore[reportUnnecessaryCast]
            "Mapping[str, object]", current
        )
        if piece not in mapping:
            current = None
            break
        current = mapping[piece]
    if current is not None:
        return current
    evidence = row.get("metric_evidence")
    if isinstance(evidence, Mapping):
        evidence_mapping = cast("Mapping[str, object]", evidence)
        item = evidence_mapping.get(metric)
        if isinstance(item, Mapping):
            item_mapping = cast("Mapping[str, object]", item)
            if "normalized_value" in item_mapping:
                return item_mapping.get("normalized_value")
    return None


def _metric_diff(
    before: Mapping[str, object], after: Mapping[str, object], identity: str
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    left_names = _metric_names(before)
    right_names = _metric_names(after)
    added: list[dict[str, object]] = []
    removed: list[dict[str, object]] = []
    changed: list[dict[str, object]] = []
    statuses: list[dict[str, object]] = []
    for metric in sorted(left_names | right_names):
        left = _metric_value(before, metric)
        right = _metric_value(after, metric)
        entry: dict[str, object] = {"id": identity, "metric": metric}
        if metric not in left_names:
            entry["value"] = _safe(right)
            added.append(entry)
        elif metric not in right_names:
            entry["value"] = _safe(left)
            removed.append(entry)
        elif _encoded(left) != _encoded(right):
            entry.update({"before": _safe(left), "after": _safe(right)})
            left_evidence = _mapping(before.get("metric_evidence")).get(metric)
            right_evidence = _mapping(after.get("metric_evidence")).get(metric)
            if left_evidence is not None or right_evidence is not None:
                entry["evidence_before"] = _safe(left_evidence)
                entry["evidence_after"] = _safe(right_evidence)
            changed.append(entry)
        left_evidence = _mapping(before.get("metric_evidence")).get(metric)
        right_evidence = _mapping(after.get("metric_evidence")).get(metric)
        if isinstance(left_evidence, Mapping) or isinstance(right_evidence, Mapping):
            left_map: Mapping[str, object] = (
                cast("Mapping[str, object]", left_evidence)
                if isinstance(left_evidence, Mapping)
                else {}
            )
            right_map: Mapping[str, object] = (
                cast("Mapping[str, object]", right_evidence)
                if isinstance(right_evidence, Mapping)
                else {}
            )
            left_status = {
                key: left_map.get(key) for key in _STATUS_KEYS if key in left_map
            }
            right_status = {
                key: right_map.get(key) for key in _STATUS_KEYS if key in right_map
            }
            if _encoded(left_status) != _encoded(right_status):
                statuses.append(
                    {
                        "id": identity,
                        "metric": metric,
                        "before": _safe(left_status),
                        "after": _safe(right_status),
                    },
                )
    return added, removed, changed, statuses


def _metadata(snapshot: Mapping[str, object], key: str) -> object:
    meta = _mapping(snapshot.get("meta"))
    if key in meta:
        return meta[key]
    return snapshot.get(key)


def _metadata_change(
    old: Mapping[str, object], new: Mapping[str, object], key: str
) -> dict[str, object]:
    before = _safe(_metadata(old, key))
    after = _safe(_metadata(new, key))
    return {
        "changed": _encoded(before) != _encoded(after),
        "before": before,
        "after": after,
    }


def _diagnostics(snapshot: Mapping[str, object]) -> list[object]:
    """Collect diagnostics payloads from a snapshot."""
    value = snapshot.get("diagnostics")
    if value is None:
        value = _mapping(snapshot.get("meta")).get("diagnostics")
    if isinstance(value, list):
        items = cast("list[object]", cast("object", value))
        return sorted((_safe(item) for item in items), key=_encoded)
    return []


def _possible_renames(
    removed: Mapping[str, Mapping[str, object]],
    added: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for before_id in sorted(removed):
        before_name = _display_name(removed[before_id])
        if before_name is None:
            continue
        for after_id in sorted(added):
            after_name = _display_name(added[after_id])
            if after_name is None:
                continue
            ratio = SequenceMatcher(
                None,
                "".join(char.casefold() for char in before_name if char.isalnum()),
                "".join(char.casefold() for char in after_name if char.isalnum()),
            ).ratio()
            if ratio >= RENAME_SIMILARITY_THRESHOLD:
                candidates.append(
                    {
                        "before_id": before_id,
                        "after_id": after_id,
                        "before_name": before_name,
                        "after_name": after_name,
                        "similarity": round(ratio, 6),
                        "merge": False,
                    },
                )
    return sorted(candidates, key=lambda item: (item["before_id"], item["after_id"]))


def schema_aware_diff(
    old_snapshot: Mapping[str, object], new_snapshot: Mapping[str, object]
) -> dict[str, object]:
    """Compare snapshots without collapsing identities or exposing source secrets."""
    old_models, old_model_dupes = _indexed(
        "model", _rows(old_snapshot, ("models", "model_rows", "modelRows"))
    )
    new_models, new_model_dupes = _indexed(
        "model", _rows(new_snapshot, ("models", "model_rows", "modelRows"))
    )
    old_endpoints, old_endpoint_dupes = _indexed(
        "endpoint",
        _rows(
            old_snapshot, ("hosts_models", "hostsModels", "host_models", "endpoints")
        ),
    )
    new_endpoints, new_endpoint_dupes = _indexed(
        "endpoint",
        _rows(
            new_snapshot, ("hosts_models", "hostsModels", "host_models", "endpoints")
        ),
    )

    def identity_diff(
        old: Mapping[str, Mapping[str, object]], new: Mapping[str, Mapping[str, object]]
    ) -> dict[str, object]:
        old_ids = set(old)
        new_ids = set(new)
        added = sorted(new_ids - old_ids)
        removed = sorted(old_ids - new_ids)
        changed = sorted(
            identity
            for identity in old_ids & new_ids
            if _encoded(old[identity]) != _encoded(new[identity])
        )
        return {
            "added": added,
            "removed": removed,
            "changed": changed,
            "added_records": [
                {"id": identity, "name": _display_name(new[identity])}
                for identity in added
            ],
            "removed_records": [
                {"id": identity, "name": _display_name(old[identity])}
                for identity in removed
            ],
        }

    field_added: list[dict[str, object]] = []
    field_removed: list[dict[str, object]] = []
    field_changed: list[dict[str, object]] = []
    metric_added: list[dict[str, object]] = []
    metric_removed: list[dict[str, object]] = []
    metric_changed: list[dict[str, object]] = []
    status_changed: list[dict[str, object]] = []
    for identity in sorted(set(old_models) & set(new_models)):
        added, removed, changed = _field_diff(
            old_models[identity], new_models[identity], identity
        )
        field_added.extend(added)
        field_removed.extend(removed)
        field_changed.extend(changed)
        added, removed, changed, statuses = _metric_diff(
            old_models[identity], new_models[identity], identity
        )
        metric_added.extend(added)
        metric_removed.extend(removed)
        metric_changed.extend(changed)
        status_changed.extend(statuses)

    old_diag = _diagnostics(old_snapshot)
    new_diag = _diagnostics(new_snapshot)
    old_diag_keys = {_encoded(item): item for item in old_diag}
    new_diag_keys = {_encoded(item): item for item in new_diag}
    duplicate_before = old_model_dupes + old_endpoint_dupes
    duplicate_after = new_model_dupes + new_endpoint_dupes
    duplicate_before_keys = {_encoded(item): item for item in duplicate_before}
    duplicate_after_keys = {_encoded(item): item for item in duplicate_after}

    result: dict[str, object] = {
        "model_identities": identity_diff(old_models, new_models),
        "endpoint_identities": identity_diff(old_endpoints, new_endpoints),
        "models": identity_diff(old_models, new_models),
        "fields": {
            "added": sorted(field_added, key=_encoded),
            "removed": sorted(field_removed, key=_encoded),
            "changed": sorted(field_changed, key=_encoded),
        },
        "metrics": {
            "added": sorted(metric_added, key=_encoded),
            "removed": sorted(metric_removed, key=_encoded),
            "changed": sorted(metric_changed, key=_encoded),
        },
        "evidence": {"status_changed": sorted(status_changed, key=_encoded)},
        "statuses": {"changed": sorted(status_changed, key=_encoded)},
        "freshness": _metadata_change(old_snapshot, new_snapshot, "freshness"),
        "parser": {
            "name": _metadata_change(old_snapshot, new_snapshot, "parser"),
            "version": _metadata_change(old_snapshot, new_snapshot, "parser_version"),
        },
        "schema": _metadata_change(old_snapshot, new_snapshot, "schema_version"),
        "duplicates": {
            "before": sorted(duplicate_before, key=_encoded),
            "after": sorted(duplicate_after, key=_encoded),
            "added": sorted(
                (
                    duplicate_after_keys[key]
                    for key in duplicate_after_keys.keys()
                    - duplicate_before_keys.keys()
                ),
                key=_encoded,
            ),
            "removed": sorted(
                (
                    duplicate_before_keys[key]
                    for key in duplicate_before_keys.keys()
                    - duplicate_after_keys.keys()
                ),
                key=_encoded,
            ),
        },
        "diagnostics": {
            "before": old_diag,
            "after": new_diag,
            "added": sorted(
                (
                    new_diag_keys[key]
                    for key in new_diag_keys.keys() - old_diag_keys.keys()
                ),
                key=_encoded,
            ),
            "removed": sorted(
                (
                    old_diag_keys[key]
                    for key in old_diag_keys.keys() - new_diag_keys.keys()
                ),
                key=_encoded,
            ),
        },
        "possible_renames": _possible_renames(
            {key: old_models[key] for key in set(old_models) - set(new_models)},
            {key: new_models[key] for key in set(new_models) - set(old_models)},
        ),
    }
    # Make the output finite and redact every branch, including identity names.
    return cast("dict[str, object]", _safe(result))


__all__ = ["schema_aware_diff"]
