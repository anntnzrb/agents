from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from typing import Literal, NotRequired, TextIO, TypedDict, cast

from .models import FlightLiveError, SearchRequest
from .protocol import PROTOCOL_VERSION, get_schema_document, search_flights

RequestId = str | int | float | None


class RpcErrorPayload(TypedDict):
    code: str
    message: str


class RpcSuccessResponse(TypedDict):
    type: Literal["response"]
    command: str
    success: Literal[True]
    data: object
    id: NotRequired[RequestId]


class RpcErrorResponse(TypedDict):
    type: Literal["response"]
    command: str
    success: Literal[False]
    error: RpcErrorPayload
    id: NotRequired[RequestId]


RpcResponse = RpcSuccessResponse | RpcErrorResponse


def run_rpc(*, stdin: TextIO, stdout: TextIO) -> int:
    for raw_line in stdin:
        line = raw_line.strip()
        if line == "":
            continue
        response = handle_rpc_line(line)
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


def handle_rpc_line(line: str) -> RpcResponse:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return _error_response(
            command="unknown",
            code="parse_error",
            message="Invalid JSON request.",
        )

    if not isinstance(payload, Mapping):
        return _error_response(
            command="unknown",
            code="parse_error",
            message="JSON request must be an object.",
        )

    request = cast(Mapping[str, object], payload)
    request_id = _read_request_id(request.get("id"))

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
                    command="ping",
                    data={"ok": True, "version": PROTOCOL_VERSION},
                    request_id=request_id,
                )
            case "get_schema":
                return _success_response(
                    command="get_schema",
                    data=get_schema_document(),
                    request_id=request_id,
                )
            case "search":
                req = _parse_search_request(request)
                return _success_response(
                    command="search",
                    data=search_flights(req),
                    request_id=request_id,
                )
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
    except FlightLiveError as exc:
        return _error_response(
            command=command,
            code="search_error",
            message=str(exc),
            request_id=request_id,
        )


def _parse_search_request(request: Mapping[str, object]) -> SearchRequest:
    origin = _require_str(request, "origin")
    destination = _require_str(request, "destination")
    depart_start = _require_date(request, "departStart", "depart_start")
    depart_end = _require_date(request, "departEnd", "depart_end")

    trip_type = _read_choice(
        request,
        key="tripType",
        fallback_key="trip_type",
        choices={"oneway", "roundtrip"},
        default="oneway",
    )
    cabin = _read_choice(
        request,
        key="cabin",
        fallback_key="cabin",
        choices={"economy", "premium_economy", "business", "first"},
        default="economy",
    )

    return SearchRequest(
        origin=origin,
        destination=destination,
        depart_start=depart_start,
        depart_end=depart_end,
        trip_type=cast(Literal["oneway", "roundtrip"], trip_type),
        stay_min=_read_int(request, "stayMin", "stay_min", default=None, minimum=0),
        stay_max=_read_int(request, "stayMax", "stay_max", default=None, minimum=0),
        adults=_read_int(request, "adults", "adults", default=1, minimum=1),
        children=_read_int(request, "children", "children", default=0, minimum=0),
        infants=_read_int(request, "infants", "infants", default=0, minimum=0),
        cabin=cast(Literal["economy", "premium_economy", "business", "first"], cabin),
        currency=_read_str(request, "currency", "currency", default="USD"),
        locale=_read_str(request, "locale", "locale", default="en"),
        market=_read_str(request, "market", "market", default="us"),
        nonstop=_read_bool(request, "nonstop", "nonstop", default=False),
        max_budget=_read_float(request, "maxBudget", "max_budget", default=None),
        planner_limit=_read_int(
            request,
            "plannerLimit",
            "planner_limit",
            default=20,
            minimum=1,
        ),
    )


def _read_command(request: Mapping[str, object]) -> str:
    preferred = request.get("type")
    if preferred is not None:
        if isinstance(preferred, str) and preferred.strip() != "":
            return preferred.strip()
        raise ValueError("Request object must include a string type.")

    legacy = request.get("command")
    if isinstance(legacy, str) and legacy.strip() != "":
        return legacy.strip()
    raise ValueError("Request object must include a string type.")


def _read_request_id(value: object | None) -> RequestId:
    if value is None or isinstance(value, (str, int, float)):
        return value
    raise ValueError("id must be a string, number, or null")


def _require_str(request: Mapping[str, object], key: str) -> str:
    value = request.get(key)
    if isinstance(value, str) and value.strip() != "":
        return value.strip()
    raise ValueError(f"{key} must be a non-empty string")


def _require_date(request: Mapping[str, object], key: str, fallback_key: str) -> date:
    raw = request.get(key)
    if raw is None:
        raw = request.get(fallback_key)
    if not isinstance(raw, str) or raw.strip() == "":
        raise ValueError(f"{key} must be an ISO date string")
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{key} must be an ISO date string") from exc


def _read_choice(
    request: Mapping[str, object],
    *,
    key: str,
    fallback_key: str,
    choices: set[str],
    default: str,
) -> str:
    value = request.get(key)
    if value is None:
        value = request.get(fallback_key)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    clean = value.strip()
    if clean not in choices:
        raise ValueError(f"{key} must be one of: {', '.join(sorted(choices))}")
    return clean


def _read_str(
    request: Mapping[str, object],
    key: str,
    fallback_key: str,
    *,
    default: str,
) -> str:
    value = request.get(key)
    if value is None:
        value = request.get(fallback_key)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    clean = value.strip()
    return clean if clean else default


def _read_bool(
    request: Mapping[str, object],
    key: str,
    fallback_key: str,
    *,
    default: bool,
) -> bool:
    value = request.get(key)
    if value is None:
        value = request.get(fallback_key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _read_float(
    request: Mapping[str, object],
    key: str,
    fallback_key: str,
    *,
    default: float | None,
) -> float | None:
    value = request.get(key)
    if value is None:
        value = request.get(fallback_key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")
    return float(value)


def _read_int(
    request: Mapping[str, object],
    key: str,
    fallback_key: str,
    *,
    default: int | None,
    minimum: int,
) -> int | None:
    value = request.get(key)
    if value is None:
        value = request.get(fallback_key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if value < minimum:
        raise ValueError(f"{key} must be >= {minimum}")
    return value


def _success_response(
    *,
    command: str,
    data: object,
    request_id: RequestId,
) -> RpcSuccessResponse:
    response: RpcSuccessResponse = {
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
    request_id: RequestId | None = None,
) -> RpcErrorResponse:
    response: RpcErrorResponse = {
        "type": "response",
        "command": command,
        "success": False,
        "error": {"code": code, "message": message},
    }
    if request_id is not None:
        response["id"] = request_id
    return response
