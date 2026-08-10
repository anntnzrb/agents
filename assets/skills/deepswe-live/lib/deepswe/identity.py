"""Structured, source-local identities for DeepSWE rows.

The published configuration tuple is kept as data, rather than encoded with a
separator.  This preserves ``None`` and the empty string as distinct values and
makes identities safe for rows whose labels contain delimiter characters.
"""

# Copyright 2026 DeepSWE contributors.
from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping
from typing import Any

IDENTITY_FIELDS: tuple[str, ...] = (
    "model",
    "reasoning_effort",
    "harness",
    "config",
)
PUBLISHED_ID_FIELDS: tuple[str, ...] = ("id", "name", "model_name", "trial_id")
DUPLICATE_MIN_COUNT = 2


def _json(value: object) -> str:
    """Return one deterministic compact JSON value."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _row_signature(row: object) -> str:
    """Return a canonical signature for a raw row."""
    try:
        return _json(row)
    except (TypeError, ValueError, OverflowError):
        # Inputs at the artifact boundary are JSON, but retain a deterministic
        # representation if a caller supplies a custom mapping in a unit test.
        return repr(row)


def canonical_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return the structured identity for one published row.

    Presence of *any* configuration tuple field is enough to select the full
    four-field identity.  Missing members become ``None``; ``None`` and ``""``
    are intentionally not collapsed.  Stable published identifiers are used
    only when all four tuple fields are absent.
    """
    if not isinstance(row, Mapping):
        msg = "DeepSWE row identity requires a mapping"
        raise TypeError(msg)

    if any(field in row for field in IDENTITY_FIELDS):
        return tuple(row.get(field) for field in IDENTITY_FIELDS)

    for field in PUBLISHED_ID_FIELDS:
        if field in row and row[field] is not None:
            return ("published_id", field, row[field])

    # There is no published identity to use.  Keep the result tagged so it can
    # never be confused with a four-field configuration tuple.  The complete
    # row signature avoids making unrelated anonymous rows collide while still
    # allowing byte-identical anonymous rows to be diagnosed as duplicates.
    return ("published_id", "row", _row_signature(row))


def identity_json(value: Mapping[str, Any] | tuple[Any, ...] | list[Any]) -> str:
    """Return the compact canonical JSON-array signature for an identity.

    Passing a row mapping is convenient at source boundaries; passing a tuple
    or list serializes that already-selected identity without changing it.
    """
    identity: object
    identity = canonical_identity(value) if isinstance(value, Mapping) else value
    return _json(list(identity) if isinstance(identity, tuple) else identity)


def _diagnostic(  # noqa: PLR0913
    code: str,
    message: str,
    *,
    identity: str,
    row_indexes: list[int],
    signatures: list[str],
    severity: str,
) -> dict[str, object]:
    return {
        "code": code,
        "severity": severity,
        "stage": "identity",
        "message": message,
        "details": {
            "identity": identity,
            "row_indexes": list(row_indexes),
            "signatures": list(signatures),
        },
    }


def classify_duplicates(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, object]]]:
    """Classify duplicate identities without discarding source rows.

    Repeated rows with one raw signature are ``identical``; repeated rows with
    multiple signatures are ``conflicting``.  Every group retains all raw rows,
    their original indexes, and canonical signatures.  Groups and signatures
    are sorted by canonical identity/signature so classification does not
    depend on which duplicate was encountered first.
    """
    materialized = list(rows)
    grouped: dict[str, dict[str, object]] = {}
    for index, row in enumerate(materialized):
        if not isinstance(row, Mapping):
            msg = "DeepSWE duplicate classification requires mappings"
            raise TypeError(msg)
        identity = canonical_identity(row)
        identity_signature = identity_json(identity)
        group = grouped.setdefault(
            identity_signature,
            {
                "identity": identity_signature,
                "entries": [],
            },
        )
        entries = group["entries"]
        if not isinstance(entries, list):
            msg = "duplicate entries must be a list"
            raise TypeError(msg)
        entries.append(
            {
                "index": index,
                "signature": _row_signature(row),
                "row": copy.deepcopy(dict(row)),
            }
        )

    identical: list[dict[str, object]] = []
    conflicting: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    for identity_signature in sorted(grouped):
        group = grouped[identity_signature]
        entries = group["entries"]
        if not isinstance(entries, list):
            msg = "duplicate entries must be a list"
            raise TypeError(msg)
        if len(entries) < DUPLICATE_MIN_COUNT:
            continue
        ordered_entries = sorted(
            entries,
            key=lambda entry: (str(entry["signature"]), int(entry["index"])),
        )
        row_indexes = sorted(int(entry["index"]) for entry in ordered_entries)
        signatures = [str(entry["signature"]) for entry in ordered_entries]
        raw_rows = [entry["row"] for entry in ordered_entries]
        if not all(isinstance(item, Mapping) for item in raw_rows):
            msg = "duplicate rows must be mappings"
            raise TypeError(msg)
        result_group: dict[str, object] = {
            "identity": identity_signature,
            "row_indexes": row_indexes,
            "signatures": signatures,
            "rows": raw_rows,
        }
        is_identical = len(set(signatures)) == 1
        bucket = identical if is_identical else conflicting
        bucket.append(result_group)
        diagnostics.append(
            _diagnostic(
                "DUPLICATE_IDENTITY" if is_identical else "DUPLICATE_CONFLICT",
                (
                    "Identical duplicate rows share a published identity."
                    if is_identical
                    else "Conflicting duplicate rows share a published identity."
                ),
                identity=identity_signature,
                row_indexes=row_indexes,
                signatures=signatures,
                severity="warning" if is_identical else "error",
            )
        )

    return {
        "identical": identical,
        "conflicting": conflicting,
        "diagnostics": diagnostics,
    }


__all__ = [
    "IDENTITY_FIELDS",
    "PUBLISHED_ID_FIELDS",
    "canonical_identity",
    "classify_duplicates",
    "identity_json",
]
