"""Deterministic ``--summary`` projection of normalized command data."""

from typing import Any

from models import UNDEFINED

SUMMARY_ROOT_FIELDS = (
    "requested_id",
    "requested_url",
    "handle",
    "query",
    "feed",
    "ranking_mode",
    "requested_count",
    "returned_count",
    "cursor",
    "has_more",
    "complete",
    "complete_reason",
    "provider",
    "official",
    "auth_mode",
    "source_url",
    "endpoint",
    "fetched_at",
    "provider_status",
)


def summary_author(author: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("id", "handle", "name", "url", "verified"):
        if key in author and author[key] is not UNDEFINED:
            summary[key] = author[key]
    return summary


def summary_post(post: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("id", "url", "text", "created_at", "lang", "quote_id", "reply_to_id"):
        if key in post and post[key] is not UNDEFINED:
            summary[key] = post[key]
    author = post.get("author")
    if "author" in post and isinstance(author, dict):
        summary["author"] = summary_author(author)
    return summary


def summary_post_value(value: object) -> Any:
    if isinstance(value, dict):
        return summary_post(value)
    if isinstance(value, list):
        return [summary_post(item) for item in value if isinstance(item, dict)]
    return None


def summary_data(_command: str, data: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in SUMMARY_ROOT_FIELDS:
        if key in data and data[key] is not UNDEFINED:
            summary[key] = data[key]
    for key in ("post", "posts", "target", "thread", "replies"):
        if key not in data or data[key] is UNDEFINED:
            continue
        projected = summary_post_value(data[key])
        if projected is not None:
            summary[key] = projected
    profile = data.get("profile")
    if "profile" in data and isinstance(profile, dict):
        summary["profile"] = summary_author(profile)
    return summary
