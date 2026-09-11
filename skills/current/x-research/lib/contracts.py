"""Input validation and provider payload normalization contracts."""

import math
import re
from typing import Any
from urllib.parse import urlsplit

from models import UNDEFINED, CliError, ContractError
from provider import _preprocess_url_input

SAFE_HANDLE_RE = re.compile(r"[A-Za-z0-9_]+")
NUMERIC_ID_RE = re.compile(r"[0-9]+")
STATUS_PATH_RE = re.compile(r"/[A-Za-z0-9_]+/status/([0-9]+)/?")
METRIC_FIELDS = ("replies", "reposts", "likes", "quotes", "bookmarks", "views")
MEDIA_COLLECTIONS = ("all", "photos", "videos")
MEDIA_OBJECTS = ("external", "mosaic", "broadcast")

_HTTPS_DEFAULT_PORT = 443
_COUNT_MIN = 1
_COUNT_MAX = 100


def actual_type(value: object) -> str:
    """Return the JavaScript ``typeof``-style name for a value."""
    if value is None:
        return "null"
    if value is UNDEFINED:
        return "undefined"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _make_contract_error(  # noqa: PLR0913 - mirrors makeContractError(code, message, field, expected, value, index)
    code: str,
    message: str,
    field: str,
    expected: str,
    value: Any,
    *,
    index: int | None = None,
) -> ContractError:
    details: dict[str, Any] = {
        "field": field,
        "expected": expected,
        "actual_type": actual_type(value),
        "value": value,
    }
    if index is not None:
        details["index"] = index
    return ContractError(code=code, message=message, details=details)


def validate_handle(raw: object) -> str:
    if not isinstance(raw, str) or not raw or SAFE_HANDLE_RE.fullmatch(raw) is None:
        raise CliError(
            code="invalid_handle",
            message="handle must contain only letters, digits, and underscores",
            details={"handle": raw},
        )
    return raw


def validate_numeric_id(raw: object, field: str = "id") -> str:
    if not isinstance(raw, str) or not raw or NUMERIC_ID_RE.fullmatch(raw) is None:
        raise CliError(
            code="invalid_field",
            message=f"{field} must be a numeric ID",
            details={"field": field, "value": raw},
        )
    return raw


def status_id_from_target(raw: object) -> dict[str, Any]:
    target_error = CliError(
        code="invalid_target",
        message="target must be a numeric ID or an https x.com/twitter.com status URL",
        details={"target": raw},
    )
    if not isinstance(raw, str) or not raw or not raw.strip():
        raise target_error
    if NUMERIC_ID_RE.fullmatch(raw):
        return {"id": raw}

    try:
        parsed = urlsplit(_preprocess_url_input(raw))
        port = parsed.port
    except ValueError:
        raise target_error from None

    if parsed.scheme != "https":
        raise target_error

    hostname = parsed.hostname
    if hostname not in {"x.com", "twitter.com"}:
        raise target_error

    # WHATWG URL normalizes the default HTTPS port away; mirror that here.
    if port == _HTTPS_DEFAULT_PORT:
        port = None

    if (
        port is not None
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise target_error

    match = STATUS_PATH_RE.fullmatch(parsed.path)
    if match is None or not match.group(1):
        raise target_error

    return {"id": match.group(1), "targetUrl": raw}


def normalize_query(raw: object) -> str:
    if not isinstance(raw, str):
        raise CliError(
            code="invalid_query",
            message="query must contain non-whitespace text",
            details={"query": raw},
        )
    query = " ".join(raw.split())
    if not query:
        raise CliError(
            code="invalid_query",
            message="query must contain non-whitespace text",
            details={"query": raw},
        )
    return query


def validate_count(requested_count: object) -> int:
    if (
        isinstance(requested_count, bool)
        or not isinstance(requested_count, (int, float))
        or not requested_count.is_integer()
    ):
        raise _make_contract_error(
            "invalid_count",
            "requested_count must be an integer from 1 to 100",
            "requested_count",
            "integer 1..100",
            requested_count,
        )
    if requested_count < _COUNT_MIN or requested_count > _COUNT_MAX:
        raise _make_contract_error(
            "invalid_count",
            "requested_count must be between 1 and 100",
            "requested_count",
            "integer 1..100",
            requested_count,
        )
    return int(requested_count)


def validate_cursor(raw: object) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise CliError(
            code="usage",
            message="cursor must not be empty",
            details={},
        )
    return raw


def validate_lang(raw: object) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise CliError(
            code="usage",
            message="lang must not be empty",
            details={},
        )
    return raw


def validate_feed(raw: object) -> str:
    if raw in {"latest", "top", "media"}:
        return str(raw)
    raise CliError(
        code="usage",
        message=f"invalid feed: {raw}",
        details={},
    )


def validate_ranking_mode(raw: object) -> str:
    if raw in {"likes", "recency"}:
        return str(raw)
    raise CliError(
        code="usage",
        message=f"invalid ranking mode: {raw}",
        details={},
    )


def validate_provider(raw: object) -> str:
    if raw == "fxtwitter":
        return str(raw)
    raise CliError(
        code="usage",
        message=f"invalid provider: {raw}",
        details={},
    )


def _get_object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _make_contract_error(
            "malformed_payload",
            f"{field} must be an object",
            field,
            "object",
            value,
        )
    return value


def _required_string(
    obj: dict[str, Any],
    key: str,
    field: str | None = None,
    allow_empty: bool = False,
) -> str:
    path = field or key
    if key not in obj or obj[key] is UNDEFINED:
        raise _make_contract_error(
            "missing_field", f"{path} is required", path, "string", UNDEFINED
        )
    val = obj[key]
    if not isinstance(val, str):
        raise _make_contract_error(
            "invalid_field", f"{path} must be a string", path, "string", val
        )
    if not allow_empty and not val:
        raise _make_contract_error(
            "invalid_field",
            f"{path} must not be empty",
            path,
            "non-empty string",
            val,
        )
    return val


def _optional_string(
    obj: dict[str, Any], key: str, allow_empty: bool = False
) -> str | None:
    if key not in obj or obj[key] is None or obj[key] is UNDEFINED:
        return None
    val = obj[key]
    if not isinstance(val, str):
        return None
    if not allow_empty and not val:
        return None
    return val


def _get_number(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
        return value
    return None


def _normalize_verification(raw: object) -> bool | None:
    if isinstance(raw, dict):
        v = raw.get("verified")
        return v if isinstance(v, bool) else None
    return raw if isinstance(raw, bool) else None


def normalize_profile(raw: object, field_name: str = "author") -> dict[str, Any]:
    obj = _get_object(raw, field_name)
    result: dict[str, Any] = {}

    id_val = _optional_string(obj, "id")
    if id_val is not None:
        result["id"] = id_val

    handle_val = _optional_string(obj, "screen_name")
    if handle_val is not None:
        result["handle"] = handle_val

    name_val = _optional_string(obj, "name")
    if name_val is not None:
        result["name"] = name_val

    url_val = _optional_string(obj, "url")
    if url_val is not None:
        result["url"] = url_val

    verified = _normalize_verification(obj.get("verification"))
    if verified is None and "verified" in obj:
        verified = _normalize_verification(obj["verified"])
    if verified is not None:
        result["verified"] = verified

    if "id" not in result and "handle" not in result:
        raise _make_contract_error(
            "invalid_author",
            "author must include an id or screen_name",
            field_name,
            "object with id or screen_name",
            raw,
        )

    return result


def _normalize_media_item(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    obj = raw
    item_type = obj.get("type")
    item_url = obj.get("url")
    if not isinstance(item_type, str) or not isinstance(item_url, str):
        return None
    item: dict[str, Any] = {"type": item_type, "url": item_url}

    for key in ("format", "thumbnail_url", "transcode_url", "altText"):
        val = obj.get(key)
        if isinstance(val, str) and val:
            item[key] = val

    for key in ("width", "height", "duration", "filesize"):
        num = _get_number(obj.get(key))
        if num is not None:
            item[key] = num

    if item_type in ("video", "gif"):
        formats = obj.get("formats")
        if isinstance(formats, list):
            normalized_formats: list[dict[str, Any]] = []
            for candidate in formats:
                if isinstance(candidate, dict):
                    normalized: dict[str, Any] = {}
                    for key in ("container", "codec", "url"):
                        val = candidate.get(key)
                        if isinstance(val, str) and val:
                            normalized[key] = val
                    for key in ("bitrate", "size", "height", "width"):
                        num = _get_number(candidate.get(key))
                        if num is not None:
                            normalized[key] = num
                    if isinstance(normalized.get("url"), str):
                        normalized_formats.append(normalized)
            if normalized_formats:
                item["formats"] = normalized_formats
        elif isinstance(formats, dict):
            normalized_formats_obj: dict[str, str] = {}
            for key in ("webp", "jpeg"):
                val = formats.get(key)
                if isinstance(val, str) and val:
                    normalized_formats_obj[key] = val
            if normalized_formats_obj:
                item["formats"] = [normalized_formats_obj]

    return item


def _normalize_media_object(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    obj = raw
    normalized = _normalize_media_item(raw)
    if normalized:
        state = obj.get("state")
        if isinstance(state, str) and state:
            normalized["state"] = state
        title = obj.get("title")
        if isinstance(title, str) and title:
            normalized["title"] = title
        return normalized
    return None


def _normalize_media(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    obj = raw
    media: dict[str, Any] = {}

    for key in MEDIA_COLLECTIONS:
        candidates = obj.get(key)
        if isinstance(candidates, list):
            items: list[dict[str, Any]] = []
            for v in candidates:
                item = _normalize_media_item(v)
                if item:
                    items.append(item)
            if items:
                media[key] = items

    for key in MEDIA_OBJECTS:
        normalized = _normalize_media_object(obj.get(key))
        if normalized:
            media[key] = normalized

    return media or None


def normalize_post(raw: object, field_name: str = "post") -> dict[str, Any]:
    obj = _get_object(raw, field_name)
    post_id = _required_string(obj, "id", f"{field_name}.id")
    url = _required_string(obj, "url", f"{field_name}.url")
    text = _required_string(obj, "text", f"{field_name}.text", allow_empty=True)
    created_at = _required_string(obj, "created_at", f"{field_name}.created_at")

    if "author" not in obj or obj["author"] is UNDEFINED:
        raise _make_contract_error(
            "missing_field",
            f"{field_name}.author is required",
            f"{field_name}.author",
            "object",
            UNDEFINED,
        )
    author = normalize_profile(obj["author"], f"{field_name}.author")

    result: dict[str, Any] = {
        "id": post_id,
        "url": url,
        "text": text,
        "created_at": created_at,
        "author": author,
    }

    metrics_obj = obj.get("metrics")
    if isinstance(metrics_obj, dict):
        metrics: dict[str, Any] = {}
        for key in METRIC_FIELDS:
            num = _get_number(metrics_obj.get(key))
            if num is not None:
                metrics[key] = num
        if metrics:
            result["metrics"] = metrics

    lang = _optional_string(obj, "lang")
    if lang is not None:
        result["lang"] = lang

    media = _normalize_media(obj.get("media"))
    if media is not None:
        result["media"] = media

    quote_id = None
    quote_obj = obj.get("quote")
    if isinstance(quote_obj, dict):
        quote_id = _optional_string(quote_obj, "id")
    if quote_id is None:
        quote_id = _optional_string(obj, "quote_id")
    if quote_id is not None:
        result["quote_id"] = quote_id

    reply_to_id = None
    replying_to_obj = obj.get("replying_to")
    if isinstance(replying_to_obj, dict):
        reply_to_id = _optional_string(replying_to_obj, "status")
    if reply_to_id is None:
        reply_to_id = _optional_string(obj, "reply_to_id")
    if reply_to_id is not None:
        result["reply_to_id"] = reply_to_id

    return result


def normalize_status_payload(payload: object) -> dict[str, Any]:
    root = _get_object(payload, "payload")
    if "status" not in root or root["status"] is UNDEFINED:
        raise _make_contract_error(
            "missing_field",
            "status payload must include status",
            "status",
            "object",
            UNDEFINED,
        )
    status = root["status"]
    if not isinstance(status, dict):
        raise _make_contract_error(
            "invalid_status",
            "status payload status must be an object",
            "status",
            "object",
            status,
        )
    return {"post": normalize_post(status)}


def _bottom_cursor(root: dict[str, Any]) -> tuple[str | None, str]:
    if "cursor" not in root or root["cursor"] is UNDEFINED:
        return None, "missing"
    cursor = root["cursor"]
    if cursor is None:
        return None, "exhausted"
    if isinstance(cursor, dict):
        if "bottom" not in cursor:
            return None, "invalid"
        bottom = cursor["bottom"]
        if bottom is None:
            return None, "exhausted"
        if isinstance(bottom, str) and bottom:
            return bottom, "usable"
        return None, "invalid"
    return None, "invalid"


def normalize_page_payload(payload: object, requested_count: object) -> dict[str, Any]:
    count = validate_count(requested_count)
    root = _get_object(payload, "payload")

    if "results" not in root or root["results"] is UNDEFINED:
        raise _make_contract_error(
            "missing_field",
            "page payload must include results",
            "results",
            "array",
            UNDEFINED,
        )
    raw_results = root["results"]
    if not isinstance(raw_results, list):
        raise _make_contract_error(
            "invalid_results",
            "results must be an array",
            "results",
            "array",
            raw_results,
        )

    posts: list[dict[str, Any]] = []
    for i, raw_post in enumerate(raw_results):
        try:
            posts.append(normalize_post(raw_post))
        except ContractError as err:
            details = dict(err.details)
            if "index" not in details:
                details["index"] = i
            raise ContractError(
                code=err.code, message=err.message, details=details
            ) from err

    limited_posts = posts[:count] if len(posts) > count else posts
    result: dict[str, Any] = {
        "posts": limited_posts,
        "requested_count": count,
        "returned_count": len(limited_posts),
        "complete": False,
        "complete_reason": "provider_incomplete",
    }

    if (
        "profile" in root
        and root["profile"] is not None
        and root["profile"] is not UNDEFINED
    ):
        result["profile"] = normalize_profile(root["profile"], "profile")

    bottom, cursor_state = _bottom_cursor(root)
    if cursor_state == "usable" and bottom:
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


def _normalize_status_list(raw: object, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise _make_contract_error(
            "invalid_results",
            f"conversation {field_name} must be an array",
            field_name,
            "array",
            raw,
        )
    normalized: list[dict[str, Any]] = []
    for i, raw_post in enumerate(raw):
        try:
            normalized.append(normalize_post(raw_post))
        except ContractError as err:
            details = dict(err.details)
            if "index" not in details:
                details["index"] = i
            raise ContractError(
                code=err.code, message=err.message, details=details
            ) from err
    return normalized


def normalize_conversation_payload(payload: object) -> dict[str, Any]:
    root = _get_object(payload, "payload")

    if "status" not in root or root["status"] is UNDEFINED:
        raise _make_contract_error(
            "missing_field",
            "conversation payload must include status",
            "status",
            "object",
            UNDEFINED,
        )
    status = root["status"]
    if not isinstance(status, dict):
        raise _make_contract_error(
            "invalid_status",
            "conversation status must be an object",
            "status",
            "object",
            status,
        )
    target = normalize_post(status)

    if "thread" not in root or root["thread"] is UNDEFINED:
        raise _make_contract_error(
            "missing_field",
            "conversation payload must include thread",
            "thread",
            "array",
            UNDEFINED,
        )
    thread = _normalize_status_list(root["thread"], "thread")

    if "replies" not in root or root["replies"] is UNDEFINED:
        raise _make_contract_error(
            "missing_field",
            "conversation payload must include replies",
            "replies",
            "array",
            UNDEFINED,
        )
    replies = _normalize_status_list(root["replies"], "replies")

    result: dict[str, Any] = {
        "target": target,
        "thread": thread,
        "replies": replies,
        "returned_count": 1 + len(thread) + len(replies),
        "complete": False,
        "complete_reason": "provider_incomplete",
    }

    bottom, cursor_state = _bottom_cursor(root)
    if cursor_state == "usable" and bottom:
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
