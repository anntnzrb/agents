"""JSONL ping, schema, and search requests."""

import json
from typing import TYPE_CHECKING

from .detail_parser import is_object, load_json
from .models import EbayLiveError
from .protocol import SearchRequest, get_schema_document

if TYPE_CHECKING:
    from typing import TextIO


def handle_rpc_line(line: str) -> dict[str, object]:  # noqa: C901 - RPC boundary dispatch.
    """Return one response, including parse and validation failures."""
    response: dict[str, object] = {
        "type": "response",
        "command": "unknown",
        "success": False,
    }
    try:
        request = load_json(line)
    except json.JSONDecodeError:
        return {
            **response,
            "error": {"code": "parse_error", "message": "Invalid JSON request"},
        }
    if not is_object(request):
        return {
            **response,
            "error": {"code": "parse_error", "message": "Request must be an object"},
        }
    try:
        request_id = request.get("id")
        if isinstance(request_id, bool) or (
            request_id is not None and not isinstance(request_id, (str, int, float))
        ):
            raise ValueError("id must be a string, number, or null")
        if "id" in request:
            response["id"] = request_id
        command = request.get("type", request.get("command"))
        if not isinstance(command, str) or not command:
            raise ValueError("Request must include a string type")
        response["command"] = command
        match command:
            case "ping":
                data: object = {"ok": True, "version": "1"}
            case "get_schema":
                data = get_schema_document()
            case "search":
                data = SearchRequest.from_mapping(request).execute()
            case _:
                return {
                    **response,
                    "error": {
                        "code": "unknown_command",
                        "message": f"Unknown command: {command}",
                    },
                }
    except (ValueError, TypeError) as exc:
        return {**response, "error": {"code": "invalid_request", "message": str(exc)}}
    except (EbayLiveError, OSError) as exc:
        return {**response, "error": {"code": "search_error", "message": str(exc)}}
    return {**response, "success": True, "data": data}


def run_rpc(*, stdin: TextIO, stdout: TextIO) -> int:
    """Read JSONL until EOF and flush each independent response."""
    for line in stdin:
        if line.strip():
            _ = stdout.write(
                json.dumps(handle_rpc_line(line), ensure_ascii=False) + "\n"
            )
            stdout.flush()
    return 0
