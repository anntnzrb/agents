"""Stable machine-output schema and output projection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

SCHEMA_VERSION = "1.0"
ACQUISITION_TYPES = [
    "ownership_key",
    "direct_ownership",
    "gift",
    "subscription_access",
    "account",
    "bundle",
    "unknown",
]
EVIDENCE_STATUSES = [
    "verified",
    "estimated",
    "headline",
    "blocked",
    "unknown",
]

OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://local.invalid/game-deals-live/output.schema.json",
    "title": "game-deals-live output",
    "type": "object",
    "required": [
        "schema_version",
        "command",
        "provider_snapshots",
        "provider_failures",
        "offers",
        "bundle_history",
        "verification_queue",
        "critical_verification_items",
        "rankings",
        "warnings",
        "timestamps",
    ],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "command": {"enum": ["lookup", "provider.gg", "stores"]},
        "query": {"type": ["string", "null"]},
        "request": {"type": "object"},
        "identity": {"type": ["object", "null"]},
        "provider_snapshots": {"type": "array", "items": {"type": "object"}},
        "provider_failures": {"type": "array", "items": {"type": "object"}},
        "offers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "provider",
                    "store",
                    "seller",
                    "price",
                    "original_price",
                    "regular_price",
                    "price_comparable",
                    "acquisition_type",
                    "evidence_status",
                    "evidence",
                    "claimed_region",
                    "exclusions",
                    "coupon",
                    "mandatory_fees",
                    "tax",
                    "subscription_period",
                    "preselected_extras",
                ],
                "properties": {
                    "price_comparable": {"type": "boolean"},
                    "acquisition_type": {"enum": ACQUISITION_TYPES},
                    "evidence_status": {"enum": EVIDENCE_STATUSES},
                    "evidence": {"type": "array", "items": {"type": "object"}},
                },
            },
        },
        "bundle_history": {"type": "array", "items": {"type": "object"}},
        "verification_queue": {"type": "array", "items": {"type": "object"}},
        "critical_verification_items": {"type": "array", "items": {"type": "object"}},
        "rankings": {
            "type": "object",
            "required": [
                "overall",
                "absolute_cheapest",
                "cheapest_ownership",
                "cheapest_verified",
            ],
        },
        "warnings": {"type": "array", "items": {"type": "object"}},
        "timestamps": {"type": "object"},
    },
}


def llm_projection(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop bulky raw responses while preserving normalized evidence."""
    projected = deepcopy(payload)
    for snapshot in projected.get("provider_snapshots", []):
        snapshot.pop("data", None)
    return projected
