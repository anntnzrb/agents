# Copyright (c) 2026 anntnzrb
"""Declarative benchmark overlap checks for Artificial Analysis.

Overlap is intentionally conservative.  A warning is emitted only when both
canonical component identifiers and releases are declared exactly by the
caller.  The module never infers overlap from names, scores, or similar
strings, and it never changes a published value.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

OVERLAP_DOUBLE_COUNTING_RISK = "OVERLAP_DOUBLE_COUNTING_RISK"
REQUIREMENTS_CLAIM_CERTAINTY = "requirements_claim"
UNKNOWN_CERTAINTY = "unknown"


def _as_mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _identity(value: object) -> tuple[str, str] | None:
    """Read an explicitly declared canonical component id and release.

    We accept a small set of wire aliases used by source pages, but do not
    normalize, case-fold, or otherwise derive either value.  Both values are
    mandatory so a component name alone cannot create an overlap warning.
    """
    mapping = _as_mapping(value)
    if mapping is None:
        return None
    component = None
    for key in (
        "canonical_id",
        "component_id",
        "benchmark_id",
        "canonical_component_id",
    ):
        component = _text(mapping.get(key))
        if component is not None:
            break
    release = None
    for key in ("release", "release_id", "benchmark_release", "version"):
        release = _text(mapping.get(key))
        if release is not None:
            break
    if component is None or release is None:
        return None
    return component, release


def _claim_endpoints(claim: object) -> tuple[tuple[str, str], tuple[str, str]] | None:
    mapping = _as_mapping(claim)
    if mapping is None:
        return None
    left = mapping.get("left")
    right = mapping.get("right")
    if left is None:
        left = mapping.get("source")
    if right is None:
        right = mapping.get("target")
    if left is None:
        left = mapping.get("from")
    if right is None:
        right = mapping.get("to")
    left_identity = _identity(left)
    right_identity = _identity(right)
    if left_identity is None or right_identity is None:
        # A compact declaration may put the endpoint fields at the claim root.
        left_identity = _identity(mapping.get("component_a"))
        right_identity = _identity(mapping.get("component_b"))
    if left_identity is None or right_identity is None:
        left_component = _text(mapping.get("left_canonical_id"))
        left_release = _text(mapping.get("left_release"))
        right_component = _text(mapping.get("right_canonical_id"))
        right_release = _text(mapping.get("right_release"))
        if (
            left_component is not None
            and left_release is not None
            and right_component is not None
            and right_release is not None
        ):
            left_identity = (left_component, left_release)
            right_identity = (right_component, right_release)
    if left_identity is None or right_identity is None:
        return None
    return left_identity, right_identity


def _claim_is_overlap(claim: object) -> bool:
    mapping = _as_mapping(claim)
    if mapping is None:
        return False
    # A declared dependency/join is an overlap claim.  Explicit false values
    # remain false and are treated as independence declarations.
    for key in ("overlap", "joins", "shared", "double_counting_risk"):
        value = mapping.get(key)
        if value is False:
            return False
        if value is True:
            return True
    relation = mapping.get("relation") or mapping.get("kind") or mapping.get("type")
    if isinstance(relation, str) and relation in {
        "overlap",
        "join",
        "dependency",
        "depends_on",
        "shared_component",
    }:
        return True
    # An object with two exact endpoints is itself a declarative join unless it
    # explicitly says it is independent.
    independent = mapping.get("independent")
    if independent is True or mapping.get("independence") is True:
        return False
    return _claim_endpoints(claim) is not None


def _iter_claims(value: object) -> Iterable[object]:
    if isinstance(value, Mapping):
        for key in (
            "declared_overlaps",
            "overlap_claims",
            "overlaps",
            "declared_joins",
            "joins",
            "dependencies",
            "dependency_claims",
        ):
            nested = value.get(key)
            if isinstance(nested, Sequence) and not isinstance(
                nested, (str, bytes, bytearray)
            ):
                yield from nested
            elif isinstance(nested, Mapping):
                yield nested
        # A single endpoint-pair claim is also accepted.
        if _claim_endpoints(value) is not None:
            yield value
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        yield from value


def _pair_matches(
    left: tuple[str, str],
    right: tuple[str, str],
    candidate_left: tuple[str, str],
    candidate_right: tuple[str, str],
) -> bool:
    return (left == candidate_left and right == candidate_right) or (
        left == candidate_right and right == candidate_left
    )


def overlap_warnings(
    left: object,
    right: object,
    *,
    declared_joins: object = None,
    declarations: object = None,
) -> list[dict[str, object]]:
    """Return exact declared overlap warnings for two component records.

    Missing/partial declarations intentionally return ``[]``.  The caller can
    expose an ``unknown`` status through :func:`overlap_metadata`; lack of a
    claim is never evidence of independence and is never guessed from text.
    """
    left_identity = _identity(left)
    right_identity = _identity(right)
    if left_identity is None or right_identity is None:
        return []
    claims = declared_joins if declared_joins is not None else declarations
    if claims is None:
        return []
    for claim in _iter_claims(claims):
        endpoints = _claim_endpoints(claim)
        if endpoints is None or not _claim_is_overlap(claim):
            continue
        claim_left, claim_right = endpoints
        if not _pair_matches(left_identity, right_identity, claim_left, claim_right):
            continue
        return [
            {
                "code": OVERLAP_DOUBLE_COUNTING_RISK,
                "certainty": REQUIREMENTS_CLAIM_CERTAINTY,
                "left": {"canonical_id": left_identity[0], "release": left_identity[1]},
                "right": {
                    "canonical_id": right_identity[0],
                    "release": right_identity[1],
                },
            },
        ]
    return []


def detect_overlap(
    left: object,
    right: object,
    *,
    declared_joins: object = None,
    declarations: object = None,
) -> list[dict[str, object]]:
    """Alias for :func:`overlap_warnings` used by projection callers."""
    return overlap_warnings(
        left,
        right,
        declared_joins=declared_joins,
        declarations=declarations,
    )


def declarative_dependencies(
    *,
    component_id: str | None = None,
    release: str | None = None,
    depends_on: Iterable[object] = (),
    independent_of: Iterable[object] = (),
) -> dict[str, object]:
    """Build a JSON-safe local dependency/independence declaration."""
    result: dict[str, object] = {
        "component_id": component_id,
        "release": release,
        "dependencies": list(depends_on),
        "independence": list(independent_of),
    }
    return result


def overlap_metadata(  # noqa: PLR0913
    *,
    left: object = None,
    right: object = None,
    declared_joins: object = None,
    declarations: object = None,
    dependencies: Iterable[object] = (),
    independence: Iterable[object] = (),
) -> dict[str, object]:
    """Return stable overlap metadata suitable for a command payload."""
    warnings = (
        overlap_warnings(
            left,
            right,
            declared_joins=declared_joins,
            declarations=declarations,
        )
        if left is not None and right is not None
        else []
    )
    return {
        "warnings": warnings,
        "status": "declared" if warnings else UNKNOWN_CERTAINTY,
        "certainty": REQUIREMENTS_CLAIM_CERTAINTY if warnings else UNKNOWN_CERTAINTY,
        "dependencies": list(dependencies),
        "independence": list(independence),
    }


# Friendly aliases keep the declarative vocabulary discoverable for callers.
build_overlap_metadata = overlap_metadata
build_dependencies = declarative_dependencies
dependency_summary = declarative_dependencies
check_overlap = overlap_warnings

__all__ = [
    "OVERLAP_DOUBLE_COUNTING_RISK",
    "REQUIREMENTS_CLAIM_CERTAINTY",
    "UNKNOWN_CERTAINTY",
    "build_dependencies",
    "build_overlap_metadata",
    "check_overlap",
    "declarative_dependencies",
    "dependency_summary",
    "detect_overlap",
    "overlap_metadata",
    "overlap_warnings",
]
