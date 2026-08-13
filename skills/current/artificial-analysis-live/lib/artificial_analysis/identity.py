# Copyright (c) 2026 anntnzrb
"""Source-local identity and lossless field helpers for Artificial Analysis.

The upstream pages have used both camelCase and snake_case names over time.  This
module keeps the normalized projection deliberately small while retaining every
field which is not part of that projection under ``raw_fields``.  Source names
are never rewritten in that raw projection, which makes drift and reconciliation
observable without making consumers depend on a particular page revision.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Callable, Iterable, Mapping, MutableSequence

from .diagnostics import Diagnostic

DUPLICATE_SOURCE_FIELD = "DUPLICATE_SOURCE_FIELD"
DUPLICATE_SOURCE_ROW = "DUPLICATE_SOURCE_ROW"
IDENTITY_SCHEMA_VERSION = 1


def camel_to_snake(value: object) -> object:
    """Convert a source key to the stable normalized spelling.

    The conversion intentionally mirrors the historical RSC normalizer.  It is
    kept here so collision detection and row normalization use exactly one
    spelling function.
    """
    if not isinstance(value, str):
        return value
    result: list[str] = []
    previous_lower = False
    previous_lower_or_digit = False
    for char in value.replace("-", "_"):
        if char.isupper():
            if previous_lower_or_digit:
                result.append("_")
            result.append(char.lower())
            previous_lower = False
            previous_lower_or_digit = False
            continue
        if char.isdigit() and previous_lower:
            result.append("_")
        result.append(char)
        previous_lower = char.islower()
        previous_lower_or_digit = previous_lower or char.isdigit()
    return "".join(result)


def source_hash(value: object) -> str | None:
    """Hash source bytes/text when a caller has them available."""
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    if isinstance(value, str):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    return None


def source_metadata(
    *,
    source_path: str | None = None,
    source_hash: str | None = None,
    parser: str | None = None,
    source_url: str | None = None,
) -> dict[str, object]:
    """Return a compact, JSON-safe source metadata object.

    Omitted values stay omitted.  This is useful for old call sites where the
    parser only receives already-decoded frames and cannot know the input path.
    """
    result: dict[str, object] = {}
    if source_path:
        result["source_path"] = source_path
    if source_hash:
        result["source_hash"] = source_hash
    if parser:
        result["parser"] = parser
    if source_url:
        result["source_url"] = source_url
    return result


def _safe_equal(left: object, right: object) -> bool:
    """Compare values without allowing NaN to masquerade as equal data."""
    if isinstance(left, float) and math.isnan(left):
        return False
    if isinstance(right, float) and math.isnan(right):
        return False
    try:
        return left == right
    except (TypeError, ValueError):
        return False


def _json_key(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError, OverflowError):
        return repr(value)


def _append_diagnostic(
    diagnostics: MutableSequence[Diagnostic] | None,
    diagnostic: Diagnostic,
) -> None:
    if diagnostics is None:
        return
    if any(item == diagnostic for item in diagnostics):
        return
    diagnostics.append(diagnostic)


def _field_collision_diagnostic(
    *,
    normalized: str,
    source_fields: list[str],
    values: list[object],
    source_path: str | None,
    path: str,
) -> Diagnostic:
    identical = all(_safe_equal(values[0], value) for value in values[1:])
    return Diagnostic(
        code=DUPLICATE_SOURCE_FIELD,
        severity="warning" if identical else "error",
        stage="normalize",
        message=(
            f"Source fields {', '.join(sorted(source_fields))} normalize to "
            f"the same field {normalized!r}."
        ),
        source_path=source_path or path or None,
        details={
            "normalized_field": normalized,
            "source_fields": sorted(source_fields),
            "classification": "identical" if identical else "conflicting",
        },
    )


def normalize_mapping(  # noqa: PLR0913
    value: Mapping[object, object],
    *,
    known_fields: Iterable[str] | None = None,
    path: str = "",
    source_path: str | None = None,
    source_hash: str | None = None,
    parser: str | None = None,
    source_url: str | None = None,
    diagnostics: MutableSequence[Diagnostic] | None = None,
) -> dict[str, object]:
    """Normalize known source fields and retain unknown fields losslessly.

    ``known_fields`` contains normalized field names.  If it is omitted, all
    string keys are projected (useful for a nested object whose public schema is
    intentionally source-shaped).  Unknown keys are copied verbatim into the
    returned ``raw_fields`` mapping.  When camel/snake spellings collide, the
    first deterministic winner remains in the normalized object and every other
    spelling/value remains visible under ``raw_fields`` together with a stable
    diagnostic; no value is silently overwritten.
    """
    normalized_fields = (
        {str(item) for item in known_fields} if known_fields is not None else None
    )
    source_items = [
        (str(key), item) for key, item in value.items() if isinstance(key, str)
    ]
    groups: dict[str, list[tuple[str, object]]] = {}
    for key, item in source_items:
        normalized = str(camel_to_snake(key))
        groups.setdefault(normalized, []).append((key, item))

    result: dict[str, object] = {}
    raw_fields: dict[str, object] = {}
    for normalized, entries in groups.items():
        # Prefer an exact normalized spelling.  Otherwise preserve source order;
        # source order is deterministic for decoded JSON and avoids max/overwrite
        # behavior when two records disagree.
        winner_index = next(
            (index for index, (key, _) in enumerate(entries) if key == normalized),
            0,
        )
        winner_key, winner_value = entries[winner_index]
        is_known = normalized_fields is None or normalized in normalized_fields
        if is_known:
            result[normalized] = copy.deepcopy(winner_value)
        else:
            raw_fields[winner_key] = copy.deepcopy(winner_value)

        if len(entries) > 1:
            _append_diagnostic(
                diagnostics,
                _field_collision_diagnostic(
                    normalized=normalized,
                    source_fields=[key for key, _ in entries],
                    values=[item for _, item in entries],
                    source_path=source_path,
                    path=(f"{path}.{normalized}" if path else normalized),
                ),
            )
            # Preserve all non-winning spellings exactly as supplied.  The
            # winning spelling is also retained when it is not the canonical
            # spelling, so the raw projection remains a complete source record.
            for index, (key, item) in enumerate(entries):
                if index != winner_index or key != normalized:
                    raw_fields[key] = copy.deepcopy(item)

    if raw_fields:
        existing = result.get("raw_fields")
        if isinstance(existing, dict):
            existing = dict(existing) | raw_fields
            result["raw_fields"] = existing
        else:
            result["raw_fields"] = raw_fields

    metadata = source_metadata(
        source_path=source_path,
        source_hash=source_hash,
        parser=parser,
        source_url=source_url,
    )
    if metadata:
        result["raw_metadata"] = metadata
    return result


def identity_metadata(  # noqa: PLR0913
    *,
    kind: str,
    slug: str,
    model_slug: str | None = None,
    host_slug: str | None = None,
    endpoint_slug: str | None = None,
    source_path: str | None = None,
    source_hash: str | None = None,
) -> dict[str, object]:
    """Build a stable structured identity for a canonical row."""
    identity: dict[str, object] = {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "kind": kind,
        "slug": slug,
    }
    if kind == "model":
        identity["model_slug"] = model_slug or slug
    elif kind == "endpoint":
        identity["endpoint_slug"] = endpoint_slug or slug
        if host_slug:
            identity["host_slug"] = host_slug
        if model_slug:
            identity["model_slug"] = model_slug
    metadata = source_metadata(source_path=source_path, source_hash=source_hash)
    if metadata:
        identity["source"] = metadata
    return identity


def model_identity(
    slug: str,
    *,
    source_path: str | None = None,
    source_hash: str | None = None,
) -> dict[str, object]:
    """Return the canonical structured identity for a model."""
    return identity_metadata(
        kind="model",
        slug=slug,
        model_slug=slug,
        source_path=source_path,
        source_hash=source_hash,
    )


def endpoint_identity(
    host_slug: str,
    model_slug: str,
    *,
    endpoint_slug: str | None = None,
    source_path: str | None = None,
    source_hash: str | None = None,
) -> dict[str, object]:
    """Return the canonical structured identity for a provider endpoint."""
    slug = endpoint_slug or f"{host_slug}_{model_slug}"
    return identity_metadata(
        kind="endpoint",
        slug=slug,
        endpoint_slug=slug,
        host_slug=host_slug,
        model_slug=model_slug,
        source_path=source_path,
        source_hash=source_hash,
    )


# Explicit names read naturally at call sites and keep compatibility with
# callers that use either ``canonical_*`` or shorter identity names.
canonical_model_identity = model_identity
canonical_endpoint_identity = endpoint_identity


def _comparable(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            key: _comparable(item)
            for key, item in value.items()
            if key not in {"raw_metadata", "source"}
        }
    if isinstance(value, list):
        return [_comparable(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_comparable(item) for item in value)
    return value


def classify_duplicate_rows(
    rows: Iterable[object],
    *,
    identity: Callable[[object], str | None],
    source_path: str | None = None,
    diagnostics: MutableSequence[Diagnostic] | None = None,
) -> list[object]:
    """Collapse identical rows and retain conflicting rows with diagnostics.

    The returned order is first-seen order.  Identical repeats are represented
    once.  Conflicting rows are all retained so a caller can block a snapshot or
    expose the disagreement instead of silently selecting a maximum value.
    """
    selected: list[object] = []
    by_identity: dict[str, list[object]] = {}
    for row in rows:
        key = identity(row)
        if key is None:
            selected.append(row)
            continue
        group = by_identity.setdefault(key, [])
        if not group:
            group.append(row)
            selected.append(row)
            continue
        if any(
            _safe_equal(_comparable(row), _comparable(existing)) for existing in group
        ):
            classification = "identical"
        else:
            classification = "conflicting"
            group.append(row)
            selected.append(row)
        _append_diagnostic(
            diagnostics,
            Diagnostic(
                code=DUPLICATE_SOURCE_ROW,
                severity="warning" if classification == "identical" else "error",
                stage="identity",
                message=f"Duplicate source row for identity {key!r}.",
                source_path=source_path,
                details={"identity": key, "classification": classification},
            ),
        )
    return selected


normalize_source_mapping = normalize_mapping
canonical_identity = identity_metadata


# Friendly aliases used by boundary parsers.
normalize_source_fields = normalize_mapping
classify_duplicates = classify_duplicate_rows


__all__ = [
    "DUPLICATE_SOURCE_FIELD",
    "DUPLICATE_SOURCE_ROW",
    "IDENTITY_SCHEMA_VERSION",
    "camel_to_snake",
    "canonical_endpoint_identity",
    "canonical_identity",
    "canonical_model_identity",
    "classify_duplicate_rows",
    "classify_duplicates",
    "endpoint_identity",
    "identity_metadata",
    "model_identity",
    "normalize_mapping",
    "normalize_source_fields",
    "normalize_source_mapping",
    "source_hash",
    "source_metadata",
]
