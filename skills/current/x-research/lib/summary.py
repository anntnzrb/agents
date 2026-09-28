"""Deterministic ``--summary`` projection of normalized command data."""

from typing import TypeIs

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


def _is_dict(val: object) -> TypeIs[dict[object, object]]:
    return isinstance(val, dict)


def _is_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


def summary_author(author: dict[str, object]) -> dict[str, object]:
    summary: dict[str, object] = {}
    for key in ("id", "handle", "name", "url", "verified"):
        if key in author and author[key] is not UNDEFINED:
            summary[key] = author[key]
    return summary


def summary_post(post: dict[str, object]) -> dict[str, object]:
    summary: dict[str, object] = {}
    for key in ("id", "url", "text", "created_at", "lang", "quote_id", "reply_to_id"):
        if key in post and post[key] is not UNDEFINED:
            summary[key] = post[key]
    author = post.get("author")
    if _is_dict(author):
        author_dict = {str(k): v for k, v in author.items()}
        summary["author"] = summary_author(author_dict)
    return summary


def summary_post_value(value: object) -> object:
    if _is_dict(value):
        post_dict = {str(k): v for k, v in value.items()}
        return summary_post(post_dict)
    if _is_list(value):
        return [
            summary_post({str(k): v for k, v in item.items()})
            for item in value
            if _is_dict(item)
        ]
    return None


def summary_data(_command: str, data: dict[str, object]) -> dict[str, object]:
    summary: dict[str, object] = {}
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
    if _is_dict(profile):
        profile_dict = {str(k): v for k, v in profile.items()}
        summary["profile"] = summary_author(profile_dict)
    return summary
