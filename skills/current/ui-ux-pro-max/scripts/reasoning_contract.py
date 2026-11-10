#!/usr/bin/env python3
"""Closed, non-executable grammar for design-system decision rules."""

import json
import re
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

CONDITION_SIGNALS: dict[str, tuple[str, ...]] = {
    "if_booking": ("booking", "appointment", "calendar"),
    "if_boutique": ("boutique",),
    "if_casual": ("casual", "playful"),
    "if_checkout": ("checkout", "payment", "purchase"),
    "if_children": ("child", "children", "kids"),
    "if_collaboration": ("collaboration", "multiplayer", "co-edit"),
    "if_competitive": ("competitive", "leaderboard"),
    "if_content_focused": ("content", "article", "reading", "documentation"),
    "if_conversion_focused": ("conversion", "sales", "signup", "purchase"),
    "if_creative_field": ("creative", "artist", "portfolio"),
    "if_crop_focused": ("crop", "farm", "agriculture"),
    "if_dashboard": ("dashboard", "operations", "monitoring"),
    "if_data_heavy": ("data heavy", "data-heavy", "analytics", "large dataset"),
    "if_delivery": ("delivery", "courier", "shipping"),
    "if_discovery_focused": ("discover", "discovery", "browse", "directory"),
    "if_engagement_metric": ("engagement", "retention", "contribution"),
    "if_experience_focused": ("experience", "immersive", "journey"),
    "if_gamification": ("gamification", "badges", "streak"),
    "if_health": ("health", "medical", "patient"),
    "if_hero_needed": ("hero", "showcase", "launch"),
    "if_large_dataset": ("large dataset", "thousands", "millions"),
    "if_light_mode_needed": ("light mode", "light theme"),
    "if_low_performance": ("low performance", "low-end", "slow device"),
    "if_luxury": ("luxury", "premium", "high-end"),
    "if_medication": ("medication", "medicine", "prescription"),
    "if_meditation": ("meditation", "breathing", "mindfulness"),
    "if_minimal_portfolio": ("minimal portfolio", "simple portfolio"),
    "if_mobile": ("mobile", "phone", "tablet", "ios", "android"),
    "if_personalized": ("personalized", "personalised", "recommendation"),
    "if_pre_launch": ("pre-launch", "prelaunch", "coming soon", "waitlist"),
    "if_salary_focused": ("salary", "compensation", "pay range"),
    "if_team_collaboration": ("team collaboration", "team workspace"),
    "if_trust_needed": ("trust", "secure", "verified", "authority"),
    "if_ux_focused": ("ux", "usability", "accessibility", "accessible"),
    "if_video_ready": ("video ready", "product video", "demo video"),
}

ALLOWED_CONDITIONS = {"must_have", *CONDITION_SIGNALS}
ACTION_PREFIXES = {"constraint", "style", "pattern", "mode"}
TOKEN_ACTION_PREFIXES = {"constraint", "style"}
TOKEN_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CONDITION_PATTERNS = {
    condition: tuple(
        re.compile(r"(?<!\w)" + re.escape(signal) + r"(?!\w)") for signal in signals
    )
    for condition, signals in CONDITION_SIGNALS.items()
}


class ActivatedRule(TypedDict):
    """A condition and its actions that matched a query."""

    condition: str
    actions: list[str]


class AppliedDecisionRules(TypedDict):
    """The mutations and audit trail produced by decision rules."""

    activated: list[ActivatedRule]
    style_ids: list[str]
    constraints: list[str]
    pattern: str | None
    mode: str | None


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate decision-rule key: {key}")
        result[key] = value
    return result


def parse_decision_rules(raw: str | None) -> dict[str, list[str]]:
    """Parse the canonical condition-to-action-array representation."""
    try:
        decoded = cast(
            "object",
            json.loads(raw or "{}", object_pairs_hook=_object_without_duplicates),
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid decision-rule JSON: {error}") from error
    if not isinstance(decoded, dict):
        # Preserve the upstream exception type for malformed rule data.
        raise ValueError("decision rules must be a JSON object")  # noqa: TRY004
    # JSON object keys are strings; the hook preserves values as unknown objects.
    entries = cast("dict[str, object]", decoded)
    rules: dict[str, list[str]] = {}
    for condition, actions in entries.items():
        if condition not in ALLOWED_CONDITIONS:
            raise ValueError(f"unknown decision-rule condition: {condition}")
        if not isinstance(actions, list) or not actions:
            raise ValueError(f"{condition} must map to a non-empty action array")
        validated = [
            _validate_action(action) for action in cast("list[object]", actions)
        ]
        if len(validated) != len(set(validated)):
            raise ValueError(f"{condition} contains duplicate actions")
        rules[condition] = validated
    return rules


def _validate_action(action: object) -> str:
    if not isinstance(action, str) or ":" not in action:
        raise ValueError(f"action must use a known prefix: {action}")
    prefix, value = action.split(":", 1)
    if prefix not in ACTION_PREFIXES:
        raise ValueError(f"unknown decision-rule action: {action}")
    if prefix in TOKEN_ACTION_PREFIXES and not TOKEN_RE.fullmatch(value):
        raise ValueError(f"invalid {prefix} action value: {value}")
    if prefix == "pattern" and not value.strip():
        raise ValueError("pattern action must name a pattern")
    if prefix == "mode" and value not in {"dark", "light"}:
        raise ValueError("mode action must be dark or light")
    return action


def apply_decision_rules(
    rules: Mapping[str, Sequence[str]], query: str | None
) -> AppliedDecisionRules:
    """Return deterministic mutations and an audit trail; never execute data."""
    normalized = str(query or "").casefold()
    result: AppliedDecisionRules = {
        "activated": [],
        "style_ids": [],
        "constraints": [],
        "pattern": None,
        "mode": None,
    }
    for condition, actions in rules.items():
        active = condition == "must_have" or any(
            pattern.search(normalized)
            for pattern in CONDITION_PATTERNS.get(condition, ())
        )
        if not active:
            continue
        result["activated"].append({"condition": condition, "actions": list(actions)})
        for action in actions:
            prefix, value = action.split(":", 1)
            if prefix == "style" and value not in result["style_ids"]:
                result["style_ids"].append(value)
            elif prefix == "constraint" and value not in result["constraints"]:
                result["constraints"].append(value)
            elif prefix == "pattern":
                result["pattern"] = value
            elif prefix == "mode":
                result["mode"] = value
    return result
