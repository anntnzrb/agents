from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, TextIO

from .models import AmazonLiveSearchError
from .protocol import (
    PROTOCOL_VERSION,
    build_llm_json,
    get_schema_document,
    search_and_filter,
)


def run_rpc(*, stdin: TextIO, stdout: TextIO) -> int:
    for raw_line in stdin:
        line = _strip_jsonl_line(raw_line)
        if line == "":
            continue
        response = handle_rpc_line(line)
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


def handle_rpc_line(line: str) -> dict[str, Any]:
    try:
        request = json.loads(line)
    except json.JSONDecodeError:
        return _error_response(
            command="unknown",
            code="parse_error",
            message="Invalid JSON request.",
        )

    if not isinstance(request, Mapping):
        return _error_response(
            command="unknown",
            code="parse_error",
            message="JSON request must be an object.",
        )

    request_id = request.get("id")
    try:
        command = _read_command(request)
    except ValueError as exc:
        return _error_response(
            command="unknown",
            code="invalid_request",
            message=str(exc),
            request_id=request_id,
        )

    try:
        match command:
            case "ping":
                return _success_response(
                    command=command,
                    data={"ok": True, "version": PROTOCOL_VERSION},
                    request_id=request_id,
                )
            case "get_schema":
                return _success_response(
                    command=command,
                    data=get_schema_document(),
                    request_id=request_id,
                )
            case "search":
                return _handle_search(request)
            case _:
                return _error_response(
                    command=command,
                    code="unknown_command",
                    message=f"Unknown command: {command}",
                    request_id=request_id,
                )
    except ValueError as exc:
        return _error_response(
            command=command,
            code="invalid_request",
            message=str(exc),
            request_id=request_id,
        )
    except (AmazonLiveSearchError, OSError) as exc:
        return _error_response(
            command=command,
            code="search_error",
            message=str(exc),
            request_id=request_id,
        )


def _handle_search(request: Mapping[str, Any]) -> dict[str, Any]:
    request_id = request.get("id")
    query = _require_string(request, "query")
    page = _read_int(request, "page", default=1, minimum=1)
    pages = _read_int(request, "pages", default=1, minimum=1)
    amazon_sort = _read_optional_string(request, "amazonSort")
    zip_code = _read_optional_string(request, "zipCode")
    min_rating = _read_optional_number(request, "minRating")
    max_price = _read_optional_number(request, "maxPrice")
    badge = _read_optional_string(request, "badge")
    title_contains = _read_optional_string(request, "titleContains")
    include = _read_terms(request, "include")
    exclude = _read_terms(request, "exclude")
    limit = _read_int(request, "limit", default=None, minimum=0)
    html_path = _read_optional_string(request, "htmlPath")
    details = _read_optional_bool(request, "details") or False
    detail_limit = _read_int(request, "detailLimit", default=None, minimum=0)
    scoring = _read_optional_bool(request, "scoring") or False

    raw_results, filtered_results, details_by_asin, detail_attempted, scores_by_asin = (
        search_and_filter(
            query=query,
            html_path=html_path,
            page=page,
            pages=pages,
            amazon_sort=amazon_sort,
            zip_code=zip_code,
            min_rating=min_rating,
            max_price=max_price,
            badge=badge,
            title_contains=title_contains,
            include=include,
            exclude=exclude,
            limit=limit,
            details=details,
            detail_limit=detail_limit,
            scoring=scoring,
        )
    )
    payload = build_llm_json(
        query=query,
        html_path=html_path,
        page=page,
        pages=pages,
        amazon_sort=amazon_sort,
        zip_code=zip_code,
        min_rating=min_rating,
        max_price=max_price,
        badge=badge,
        title_contains=title_contains,
        include=include,
        exclude=exclude,
        limit=limit,
        raw_results=raw_results,
        filtered_results=filtered_results,
        details=details,
        detail_limit=detail_limit,
        details_by_asin=details_by_asin,
        detail_attempted=detail_attempted,
        scoring=scoring,
        scores_by_asin=scores_by_asin,
    )
    return _success_response(command="search", data=payload, request_id=request_id)


def _success_response(
    *,
    command: str,
    data: Any,
    request_id: Any = None,
) -> dict[str, Any]:
    response = {
        "type": "response",
        "command": command,
        "success": True,
        "data": data,
    }
    if request_id is not None:
        response["id"] = request_id
    return response


def _error_response(
    *,
    command: str,
    code: str,
    message: str,
    request_id: Any = None,
) -> dict[str, Any]:
    response = {
        "type": "response",
        "command": command,
        "success": False,
        "error": {"code": code, "message": message},
    }
    if request_id is not None:
        response["id"] = request_id
    return response


def _read_command(request: Mapping[str, Any]) -> str:
    preferred_command = request.get("type")
    if preferred_command is not None:
        if not isinstance(preferred_command, str) or not preferred_command:
            raise ValueError("Request object must include a string type.")
        return preferred_command

    legacy_command = request.get("command")
    if not isinstance(legacy_command, str) or not legacy_command:
        raise ValueError("Request object must include a string type.")
    return legacy_command


def _strip_jsonl_line(raw_line: str) -> str:
    if raw_line.endswith("\n"):
        raw_line = raw_line[:-1]
    if raw_line.endswith("\r"):
        raw_line = raw_line[:-1]
    return raw_line


def _require_string(request: Mapping[str, Any], key: str) -> str:
    value = request.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _read_optional_string(request: Mapping[str, Any], key: str) -> str | None:
    value = request.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    value = value.strip()
    return value or None


def _read_optional_bool(request: Mapping[str, Any], key: str) -> bool | None:
    value = request.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _read_int(
    request: Mapping[str, Any],
    key: str,
    *,
    default: int | None,
    minimum: int,
) -> int | None:
    if key not in request or request[key] is None:
        return default

    value = request[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if value < minimum:
        raise ValueError(f"{key} must be >= {minimum}")
    return value


def _read_optional_number(request: Mapping[str, Any], key: str) -> float | None:
    value = request.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")
    return float(value)


def _read_terms(request: Mapping[str, Any], key: str) -> list[str]:
    value = request.get(key)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, Sequence) or isinstance(value, bytes | bytearray):
        raise ValueError(f"{key} must be a string or array of strings")

    terms: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{key} must contain only strings")
        terms.append(item)
    return terms
