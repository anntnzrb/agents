"""Boundary validation and normalization for FxTwitter v2 payloads."""
# ruff: noqa: C901, CPY001, D107, D202, EM101, PERF203, PLR0911, PLR0912, PLR0913, PLR2004

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

_METRIC_FIELDS = ("replies", "reposts", "likes", "quotes", "bookmarks", "views")
_MEDIA_COLLECTIONS = ("all", "photos", "videos")
_MEDIA_OBJECTS = ("external", "mosaic", "broadcast")


class ContractError(ValueError):
    """Raised when an untrusted provider payload violates the public contract."""

    def __init__(
        self,
        code: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details or {})


def _actual_type(value: object) -> str:
    """Return a stable, JSON-safe type label for an error detail."""

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "array"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _error(
    code: str,
    message: str,
    *,
    field: str,
    expected: str,
    value: object = None,
    index: int | None = None,
) -> ContractError:
    details: dict[str, object] = {
        "field": field,
        "expected": expected,
        "actual_type": _actual_type(value),
    }
    if index is not None:
        details["index"] = index
    return ContractError(code, message, details)


def _object(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _error(
            "malformed_payload",
            f"{field} must be an object",
            field=field,
            expected="object",
            value=value,
        )
    return value


def _required_string(
    obj: Mapping[str, object],
    key: str,
    *,
    field: str | None = None,
    allow_empty: bool = False,
) -> str:
    path = field or key
    if key not in obj:
        raise _error(
            "missing_field",
            f"{path} is required",
            field=path,
            expected="string",
        )
    value = obj[key]
    if not isinstance(value, str):
        raise _error(
            "invalid_field",
            f"{path} must be a string",
            field=path,
            expected="string",
            value=value,
        )
    if not allow_empty and not value:
        raise _error(
            "invalid_field",
            f"{path} must not be empty",
            field=path,
            expected="non-empty string",
            value=value,
        )
    return value


def _optional_string(
    obj: Mapping[str, object],
    key: str,
    *,
    allow_empty: bool = False,
) -> str | None:
    if key not in obj:
        return None
    value = obj[key]
    if not isinstance(value, str):
        return None
    if not allow_empty and not value:
        return None
    return value


def _number(value: object) -> int | float | None:
    """Return a finite, non-negative JSON number, excluding booleans."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value < 0:
        return None
    return value


def _provider_code(payload: Mapping[str, object]) -> int | None:
    """Validate an API-level status code when FxTwitter supplies one."""

    if "code" not in payload or payload["code"] is None:
        return None
    raw_code = payload["code"]
    if isinstance(raw_code, bool) or not isinstance(raw_code, (int, float)):
        raise _error(
            "invalid_provider_status",
            "provider code must be a number",
            field="code",
            expected="number",
            value=raw_code,
        )
    if isinstance(raw_code, float) and not math.isfinite(raw_code):
        raise _error(
            "invalid_provider_status",
            "provider code must be finite",
            field="code",
            expected="finite number",
            value=raw_code,
        )
    if int(raw_code) != raw_code:
        raise _error(
            "invalid_provider_status",
            "provider code must be an integer status",
            field="code",
            expected="integer",
            value=raw_code,
        )
    code = int(raw_code)
    if code >= 400:
        raise ContractError(
            "provider_error",
            f"provider returned status code {code}",
            {"provider_status": code, "field": "code"},
        )
    return code


def _normalize_verification(raw: object) -> bool | None:
    if isinstance(raw, Mapping):
        value = raw.get("verified")
        return value if isinstance(value, bool) else None
    return raw if isinstance(raw, bool) else None


def normalize_profile(raw: object) -> dict[str, object]:
    """Narrow an FxTwitter profile to stable author identity fields."""

    obj = _object(raw, field="author")
    result: dict[str, object] = {}

    for source, target in (
        ("id", "id"),
        ("screen_name", "handle"),
        ("name", "name"),
        ("url", "url"),
    ):
        value = _optional_string(obj, source)
        if value is not None:
            result[target] = value

    verified = _normalize_verification(obj.get("verification"))
    if verified is None and "verified" in obj:
        verified = _normalize_verification(obj.get("verified"))
    if verified is not None:
        result["verified"] = verified

    if not any(key in result for key in ("id", "handle")):
        raise ContractError(
            "invalid_author",
            "author must include an id or screen_name",
            {
                "field": "author",
                "expected": "object with id or screen_name",
                "actual_type": "object",
            },
        )
    return result


def _normalize_media_item(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, Mapping):
        return None
    item: dict[str, object] = {}
    for key in (
        "type",
        "url",
        "id",
        "format",
        "thumbnail_url",
        "transcode_url",
        "altText",
    ):
        value = raw.get(key)
        if isinstance(value, str) and value:
            item[key] = value
    for key in ("width", "height", "duration", "filesize"):
        value = _number(raw.get(key))
        if value is not None:
            item[key] = value

    media_type = item.get("type")
    url = item.get("url")
    if not isinstance(media_type, str) or not isinstance(url, str):
        return None

    formats = raw.get("formats")
    if isinstance(formats, list):
        normalized_formats: list[dict[str, object]] = []
        for candidate in formats:
            if not isinstance(candidate, Mapping):
                continue
            normalized: dict[str, object] = {}
            for key in ("container", "codec", "url"):
                value = candidate.get(key)
                if isinstance(value, str) and value:
                    normalized[key] = value
            for key in ("bitrate", "size", "height", "width"):
                value = _number(candidate.get(key))
                if value is not None:
                    normalized[key] = value
            if isinstance(normalized.get("url"), str):
                normalized_formats.append(normalized)
        if normalized_formats:
            item["formats"] = normalized_formats
    elif isinstance(formats, Mapping):
        normalized_formats_obj: dict[str, str] = {}
        for key in ("webp", "jpeg"):
            value = formats.get(key)
            if isinstance(value, str) and value:
                normalized_formats_obj[key] = value
        if normalized_formats_obj:
            item["formats"] = normalized_formats_obj

    return item


def _normalize_media_object(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, Mapping):
        return None
    normalized = _normalize_media_item(raw)
    if normalized is None:
        return None
    if isinstance(raw.get("state"), str) and raw["state"]:
        normalized["state"] = raw["state"]
    if isinstance(raw.get("title"), str) and raw["title"]:
        normalized["title"] = raw["title"]
    return normalized


def _normalize_media(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, Mapping):
        return None
    media: dict[str, object] = {}
    for key in _MEDIA_COLLECTIONS:
        candidates = raw.get(key)
        if not isinstance(candidates, list):
            continue
        items = [
            item
            for item in (_normalize_media_item(v) for v in candidates)
            if item is not None
        ]
        if items:
            media[key] = items
    for key in _MEDIA_OBJECTS:
        normalized = _normalize_media_object(raw.get(key))
        if normalized is not None:
            media[key] = normalized
    return media or None


def normalize_post(raw: object) -> dict[str, object]:
    """Validate and normalize one FxTwitter status object."""

    obj = _object(raw, field="post")
    result: dict[str, object] = {
        "id": _required_string(obj, "id", field="post.id"),
        "url": _required_string(obj, "url", field="post.url"),
        "text": _required_string(obj, "text", field="post.text", allow_empty=True),
        "created_at": _required_string(obj, "created_at", field="post.created_at"),
    }
    if "author" not in obj:
        raise _error(
            "missing_field",
            "post.author is required",
            field="post.author",
            expected="object",
        )
    result["author"] = normalize_profile(obj["author"])

    metrics_source: Mapping[str, object] = obj
    nested_metrics = obj.get("metrics")
    if isinstance(nested_metrics, Mapping):
        metrics_source = nested_metrics
    metrics: dict[str, int | float] = {}
    for key in _METRIC_FIELDS:
        value = _number(metrics_source.get(key))
        if value is not None:
            metrics[key] = value
    if metrics:
        result["metrics"] = metrics

    lang = _optional_string(obj, "lang")
    if lang is not None:
        result["lang"] = lang

    media = _normalize_media(obj.get("media"))
    if media is not None:
        result["media"] = media

    quote_id = _optional_string(obj, "quote_id")
    if quote_id is None and isinstance(obj.get("quote"), Mapping):
        quote_id = _optional_string(obj["quote"], "id")
    if quote_id is not None:
        result["quote_id"] = quote_id

    reply_to_id = _optional_string(obj, "reply_to_id")
    if reply_to_id is None and isinstance(obj.get("replying_to"), Mapping):
        reply_to_id = _optional_string(obj["replying_to"], "status")
    if reply_to_id is not None:
        result["reply_to_id"] = reply_to_id

    return result


def normalize_status_payload(payload: object) -> dict[str, object]:
    """Normalize the exact-post response as ``{"post": ...}``."""

    root = _object(payload, field="payload")
    _provider_code(root)
    if "status" not in root:
        raise _error(
            "missing_field",
            "status payload must include status",
            field="status",
            expected="object",
        )
    status = root["status"]
    if not isinstance(status, Mapping):
        raise _error(
            "invalid_status",
            "status payload status must be an object",
            field="status",
            expected="object",
            value=status,
        )
    return {"post": normalize_post(status)}


def _required_results(
    root: Mapping[str, object], *, field: str = "results"
) -> list[object]:
    if field not in root:
        raise _error(
            "missing_field",
            f"page payload must include {field}",
            field=field,
            expected="array",
        )
    results = root[field]
    if not isinstance(results, list):
        raise _error(
            "invalid_results",
            f"{field} must be an array",
            field=field,
            expected="array",
            value=results,
        )
    return results


def _bottom_cursor(root: Mapping[str, object]) -> tuple[str | None, str]:
    """Return a usable bottom cursor and its provider completeness signal."""

    if "cursor" not in root:
        return None, "missing"
    cursor = root["cursor"]
    if cursor is None:
        return None, "exhausted"
    if isinstance(cursor, Mapping):
        if "bottom" not in cursor:
            return None, "invalid"
        bottom = cursor["bottom"]
        if bottom is None:
            return None, "exhausted"
        if isinstance(bottom, str) and bottom:
            return bottom, "usable"
        return None, "invalid"
    if isinstance(cursor, str) and cursor:
        return cursor, "usable"
    return None, "invalid"


def _validate_count(requested_count: object) -> int:
    if isinstance(requested_count, bool) or not isinstance(requested_count, int):
        raise ContractError(
            "invalid_count",
            "requested_count must be an integer from 1 to 100",
            {
                "field": "requested_count",
                "expected": "integer 1..100",
                "actual_type": _actual_type(requested_count),
            },
        )
    if requested_count < 1 or requested_count > 100:
        raise ContractError(
            "invalid_count",
            "requested_count must be between 1 and 100",
            {
                "field": "requested_count",
                "expected": "integer 1..100",
                "value": requested_count,
            },
        )
    return requested_count


def normalize_page_payload(payload: object, requested_count: int) -> dict[str, object]:
    """Normalize one bounded timeline/search result page."""

    count = _validate_count(requested_count)
    root = _object(payload, field="payload")
    _provider_code(root)
    raw_results = _required_results(root)
    posts: list[dict[str, object]] = []
    for index, raw_post in enumerate(raw_results):
        try:
            posts.append(normalize_post(raw_post))
        except ContractError as exc:
            details = dict(exc.details)
            details.setdefault("index", index)
            raise ContractError(exc.code, exc.message, details) from exc
    if len(posts) > count:
        posts = posts[:count]

    result: dict[str, object] = {
        "posts": posts,
        "requested_count": count,
        "returned_count": len(posts),
    }
    if "profile" in root and root["profile"] is not None:
        result["profile"] = normalize_profile(root["profile"])

    bottom, cursor_state = _bottom_cursor(root)
    if cursor_state == "usable":
        result["cursor"] = bottom
        result["has_more"] = True
        result["complete"] = False
        result["complete_reason"] = "bounded_page"
    elif cursor_state == "exhausted":
        result["complete"] = True
        result["complete_reason"] = "provider_exhausted"
    else:
        result["complete"] = False
        result["complete_reason"] = "provider_incomplete"
    return result


def _normalize_status_list(
    raw: object,
    *,
    field: str,
    allow_null: bool = True,
) -> list[dict[str, object]]:
    if raw is None and allow_null:
        return []
    if not isinstance(raw, list):
        raise _error(
            "invalid_results",
            f"conversation {field} must be an array",
            field=field,
            expected="array",
            value=raw,
        )
    normalized: list[dict[str, object]] = []
    for index, item in enumerate(raw):
        try:
            normalized.append(normalize_post(item))
        except ContractError as exc:
            details = dict(exc.details)
            details.update({"field": field, "index": index})
            raise ContractError(exc.code, exc.message, details) from exc
    return normalized


def normalize_conversation_payload(payload: object) -> dict[str, object]:
    """Normalize one conversation page, retaining only the bottom cursor."""

    root = _object(payload, field="payload")
    _provider_code(root)
    if "status" not in root:
        raise _error(
            "missing_field",
            "conversation payload must include status",
            field="status",
            expected="object",
        )
    status = root["status"]
    if not isinstance(status, Mapping):
        raise _error(
            "invalid_status",
            "conversation status must be an object",
            field="status",
            expected="object",
            value=status,
        )

    if "thread" not in root:
        raise _error(
            "missing_field",
            "conversation payload must include thread",
            field="thread",
            expected="array",
        )
    if "replies" not in root:
        raise _error(
            "missing_field",
            "conversation payload must include replies",
            field="replies",
            expected="array",
        )

    result: dict[str, object] = {
        "target": normalize_post(status),
        "thread": _normalize_status_list(root["thread"], field="thread"),
        "replies": _normalize_status_list(root["replies"], field="replies"),
    }

    bottom, cursor_state = _bottom_cursor(root)
    if cursor_state == "usable":
        result["cursor"] = bottom
        result["has_more"] = True
        result["complete"] = False
        result["complete_reason"] = "bounded_page"
    elif cursor_state == "exhausted":
        result["complete"] = True
        result["complete_reason"] = "provider_exhausted"
    else:
        result["complete"] = False
        result["complete_reason"] = "provider_incomplete"
    return result


__all__ = [
    "ContractError",
    "normalize_conversation_payload",
    "normalize_page_payload",
    "normalize_post",
    "normalize_profile",
    "normalize_status_payload",
]
