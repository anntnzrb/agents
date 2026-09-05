"""Conservative overlap claims for DeepSWE.

No relationship is inferred from similar labels.  A warning requires two
explicit claims with exactly equal canonical component and release values.
Warnings are observations only and never alter scores or dependencies.
"""

# Copyright 2026 DeepSWE contributors.
from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import cast

_COMPONENT_FIELDS: tuple[str, ...] = (
    "canonical_component_id",
    "canonical_benchmark_id",
    "canonical_component",
    "component_id",
    "component",
    "benchmark_id",
    "benchmark",
)
_RELEASE_FIELDS: tuple[str, ...] = (
    "release",
    "release_id",
    "benchmark_version",
    "version",
)
_CALLER_FIELDS: tuple[str, ...] = (
    "canonical_caller_id",
    "caller_id",
    "caller",
)
_SOURCE_FIELDS: tuple[str, ...] = (
    "canonical_source_id",
    "source_id",
    "source",
)


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _claims(value: object) -> list[Mapping[str, object]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        mapping = cast("Mapping[str, object]", value)
        dependencies = mapping.get("dependencies")
        if isinstance(dependencies, Sequence) and not isinstance(
            dependencies, (str, bytes, bytearray)
        ):
            items = dependencies
            return [
                cast("Mapping[str, object]", item)
                for item in items
                if isinstance(item, Mapping)
            ]
        claims = mapping.get("claims")
        if isinstance(claims, Sequence) and not isinstance(
            claims, (str, bytes, bytearray)
        ):
            claim_items = claims
            return [
                cast("Mapping[str, object]", item)
                for item in claim_items
                if isinstance(item, Mapping)
            ]
        return [mapping]
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
        entries = value
        return [
            cast("Mapping[str, object]", item)
            for item in entries
            if isinstance(item, Mapping)
        ]
    return []


def _declared(claim: Mapping[str, object], fields: Sequence[str]) -> object | None:
    for field in fields:
        if field in claim and claim[field] is not None:
            return claim[field]
    nested = claim.get("canonical")
    if isinstance(nested, Mapping):
        for field in fields:
            if field in nested and nested[field] is not None:
                return nested[field]
    return None


def _owner(claim: Mapping[str, object], fields: Sequence[str]) -> object | None:
    value = _declared(claim, fields)
    if value is None:
        return None
    # Owner IDs are compared exactly.  No case-folding, tokenization, or
    # substring matching is allowed here.
    return value


def _component_release(claim: Mapping[str, object]) -> tuple[object, object] | None:
    component = _declared(claim, _COMPONENT_FIELDS)
    release = _declared(claim, _RELEASE_FIELDS)
    if component is None or release is None:
        return None
    return component, release


def dependency_summary(claims: object = None) -> dict[str, object]:
    """Return explicit dependency claims without inventing relationships.

    With no claims the stable result is an empty dependency list and unknown
    independence.  Supplied mappings/lists are copied and retained verbatim;
    an explicitly supplied independence class is retained when present.
    """
    if claims is None:
        return {"dependencies": [], "independence_class": "unknown"}
    if isinstance(claims, Mapping):
        mapping = cast("Mapping[str, object]", claims)
        dependencies_value = mapping.get("dependencies")
        if isinstance(dependencies_value, Sequence) and not isinstance(
            dependencies_value, (str, bytes, bytearray)
        ):
            entries = dependencies_value
            dependencies = [
                copy.deepcopy(cast("Mapping[str, object]", item))
                for item in entries
                if isinstance(item, Mapping)
            ]
        else:
            dependencies = []
        independence = mapping.get("independence_class", "unknown")
        return {
            "dependencies": dependencies,
            "independence_class": independence
            if isinstance(independence, str) and independence
            else "unknown",
        }
    dependencies = [copy.deepcopy(item) for item in _claims(claims)]
    return {"dependencies": dependencies, "independence_class": "unknown"}


def detect_overlap(
    caller: object = None, source: object = None
) -> list[dict[str, object]]:
    """Warn on exact canonical component/release collisions only.

    ``caller`` and ``source`` may be dependency lists or objects containing a
    ``dependencies``/``claims`` list.  Missing claims, fuzzy labels, missing
    releases, and differing releases produce no warning.  Explicit owner IDs,
    when present on both sides, must also match exactly.
    """
    caller_claims = _claims(caller)
    source_claims = _claims(source)
    warnings: dict[str, dict[str, object]] = {}
    for left in caller_claims:
        left_pair = _component_release(left)
        if left_pair is None:
            continue
        left_caller = _owner(left, _CALLER_FIELDS)
        left_source = _owner(left, _SOURCE_FIELDS)
        for right in source_claims:
            right_pair = _component_release(right)
            if right_pair is None:
                continue
            if _json(left_pair) != _json(right_pair):
                continue
            right_caller = _owner(right, _CALLER_FIELDS)
            right_source = _owner(right, _SOURCE_FIELDS)
            if (
                left_caller is not None
                and right_caller is not None
                and _json(left_caller) != _json(right_caller)
            ):
                continue
            if (
                left_source is not None
                and right_source is not None
                and _json(left_source) != _json(right_source)
            ):
                continue
            component, release = left_pair
            warning = {
                "code": "OVERLAP_DOUBLE_COUNTING_RISK",
                "severity": "warning",
                "stage": "overlap",
                "message": "Exact canonical component and release claims overlap.",
                "component": copy.deepcopy(component),
                "release": copy.deepcopy(release),
                "caller": copy.deepcopy(left_caller),
                "source": copy.deepcopy(left_source),
                "certainty": "requirements_claim",
            }
            _ = warnings.setdefault(_json(warning), warning)
    return [warnings[key] for key in sorted(warnings)]


__all__ = ["dependency_summary", "detect_overlap"]
