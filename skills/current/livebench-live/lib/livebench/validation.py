# Copyright (c) 2026
"""Strict release joins, identity checks, and duplicate-row classification."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .contracts import raise_expected
from .diagnostics import make_diagnostic
from .identity import canonical_token, identity_tuple

if TYPE_CHECKING:
    from .contracts import Diagnostic
    from .parsing import ParsedReleaseAssets


@dataclass
class DuplicateReport:
    """Represent DuplicateReport in the LiveBench adapter."""

    identical_groups: list[list[int]]
    conflicting_groups: list[list[int]]
    diagnostics: list[Diagnostic]


def validate_assets(parsed: ParsedReleaseAssets) -> list[Diagnostic]:
    """Validate assets for the LiveBench adapter."""
    diagnostics = list(parsed.diagnostics)
    if not parsed.categories:
        raise_expected(
            "MALFORMED_PAYLOAD",
            "Release category map is empty.",
            {"release_id": parsed.release_id},
        )
    collisions: dict[str, str] = {}
    for raw_label in parsed.categories:
        key = canonical_token(raw_label)
        prior = collisions.get(key)
        if prior is not None and prior != raw_label:
            diagnostics.append(
                make_diagnostic(
                    "DUPLICATE_SOURCE_FIELD",
                    (
                        "Two category labels canonicalize to one key; both raw "
                        "labels are retained."
                    ),
                    severity="blocker",
                    stage="validate",
                    details={"canonical_key": key, "labels": [prior, raw_label]},
                )
            )
        collisions[key] = raw_label
    if not parsed.score_rows:
        raise_expected(
            "MALFORMED_PAYLOAD",
            "Release score table has no rows.",
            {"release_id": parsed.release_id},
        )
    diagnostics.extend(validate_duplicates(parsed.score_rows))
    return diagnostics


def validate_duplicates(rows: list[dict[str, object]]) -> list[Diagnostic]:
    """Validate duplicates for the LiveBench adapter."""
    groups: dict[tuple[str, str | None, str | None], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        groups[identity_tuple(row)].append(index)
    diagnostics: list[Diagnostic] = []
    for identity, indexes in groups.items():
        if len(indexes) < 2:  # noqa: PLR2004
            continue
        signatures = {
            json.dumps(
                {str(k): value for k, value in rows[index].items()},
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
            for index in indexes
        }
        identical = len(signatures) == 1
        diagnostics.append(
            make_diagnostic(
                "DUPLICATE_MODEL_VARIANT",
                "Duplicate model/provider/variant identity appears in the score table.",
                severity="warning" if identical else "blocker",
                stage="validate",
                details={
                    "identity": {
                        "model": identity[0],
                        "provider": identity[1],
                        "variant": identity[2],
                    },
                    "row_indexes": indexes,
                    "byte_identical": identical,
                    "comparison": "collapse_for_ranking" if identical else "excluded",
                },
            )
        )
    return diagnostics


def duplicate_groups(rows: list[dict[str, object]]) -> DuplicateReport:
    """Duplicate groups for the LiveBench adapter."""
    groups: dict[tuple[str, str | None, str | None], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        groups[identity_tuple(row)].append(index)
    identical_groups: list[list[int]] = []
    conflicting_groups: list[list[int]] = []
    diagnostics = validate_duplicates(rows)
    for indexes in groups.values():
        if len(indexes) < 2:  # noqa: PLR2004
            continue
        signatures = {
            json.dumps(
                {str(k): value for k, value in rows[index].items()},
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
            for index in indexes
        }
        (identical_groups if len(signatures) == 1 else conflicting_groups).append(
            indexes
        )
    return DuplicateReport(identical_groups, conflicting_groups, diagnostics)


def enforce_release(expected: str, values: list[str | None]) -> None:
    """Enforce release for the LiveBench adapter."""
    mismatched = sorted({value for value in values if value != expected})
    if mismatched:
        raise_expected(
            "MIXED_RELEASE",
            "Rows or artifacts do not match the selected release.",
            {"expected": expected, "observed": mismatched},
        )
