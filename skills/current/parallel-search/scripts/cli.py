#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Web search, extraction, and deep research via the Parallel API."""

from __future__ import annotations

import html as _html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.response
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable

USAGE = (
    "usage: parallel-search <search|extract|task-create|task-status|task-result|"
    "findall-search|memory-retrieve|raw> ..."
)

PREVIEW_LIMIT = 500
PROVIDER = "parallel"
_MIN_QUOTED_LEN = 2
JsonValue = (
    dict[str, "JsonValue"] | Sequence["JsonValue"] | str | int | float | bool | None
)


def parse_env_file(path: Path) -> bool:
    """Load KEY=value pairs from an env file into the process environment."""
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("export "):
            text = text[7:].lstrip()
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (
            len(value) >= _MIN_QUOTED_LEN
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        os.environ[key] = value
    return True


def ancestor_env(skill_name: str) -> Path | None:
    """Locate a skill .env file in the current directory or its ancestors."""
    here = Path.cwd().resolve()
    for directory in (here, *here.parents):
        candidate = directory / "skills" / skill_name / ".env"
        if candidate.is_file():
            return candidate
        root_env = directory / ".env"
        if root_env.is_file():
            return root_env
    return None


def load_env() -> None:
    """Load API credentials from env files unless already exported."""
    if os.environ.get("PARALLEL_API_KEY"):
        return
    skill_dir = Path(__file__).resolve().parents[1]
    candidates: list[Path | None] = []
    if os.environ.get("PARALLEL_ENV_FILE"):
        candidates.append(Path(os.environ["PARALLEL_ENV_FILE"]).expanduser())
    candidates.append(skill_dir / ".env")
    if os.environ.get("SKILLS_DIR"):
        candidates.append(
            Path(os.environ["SKILLS_DIR"]).expanduser() / "parallel-search" / ".env",
        )
    candidates.append(ancestor_env("parallel-search"))
    for candidate in candidates:
        if candidate is not None and parse_env_file(candidate):
            return


def pairs(items: list[str]) -> list[tuple[str, str]]:
    """Split key=value arguments into pairs."""
    out: list[tuple[str, str]] = []
    for item in items:
        if "=" in item:
            key, value = item.split("=", 1)
            out.append((key, value))
        else:
            out.append((item, ""))
    return out


def json_print(payload: object) -> None:
    """Print a payload as compact JSON."""
    print(json.dumps(payload, separators=(",", ":")))


def usage_error(message: str) -> int:
    """Print a usage error and return the usage exit code."""
    print(message, file=sys.stderr)
    return 2


def looks_like_html(text: str) -> bool:
    """Detect an HTML error page from its leading markup."""
    head = text.lstrip()[:200].lower()
    return head.startswith(("<!doctype html", "<html", "<?xml"))


def html_to_text(body: bytes) -> str:
    """Strip markup from an HTML error body."""
    text = body.decode("utf-8", errors="replace")
    text = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def emit_provider_error(
    *,
    status: int | None,
    message: str,
    body: bytes,
) -> int:
    """Emit a compact provider error envelope and return its exit code."""
    body_bytes = len(body)
    decoded = body.decode("utf-8", errors="replace") if body else ""
    if decoded and looks_like_html(decoded):
        preview = html_to_text(body)
    else:
        preview = decoded.strip()
    if len(preview) > PREVIEW_LIMIT:
        preview = preview[:PREVIEW_LIMIT]
    truncated = bool(body) and (
        body_bytes > PREVIEW_LIMIT or len(decoded) > PREVIEW_LIMIT
    )
    err = {
        "error.provider": PROVIDER,
        "error.status": status,
        "error.message": message,
        "error.body_bytes": body_bytes,
        "error.body_preview": preview,
        "error.body_truncated": truncated,
    }
    print(json.dumps(err, separators=(",", ":")), file=sys.stderr)
    return 22 if status is not None else 1


def _read_url_response(req: urllib.request.Request) -> bytes:
    """Read a URL response body, closing the connection."""
    opened = cast("object", urllib.request.urlopen(req, timeout=120))
    with cast("urllib.response.addinfourl", opened) as response:
        return response.read()


def _read_http_error(exc: urllib.error.HTTPError) -> bytes:
    """Read an HTTP error body and release the error response."""
    try:
        return exc.read()
    finally:
        exc.close()


def _make_api_request(
    url: str,
    api_key: str,
    body_data: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    method: str | None = None,
) -> tuple[bytes | None, int]:
    """Execute an HTTP request to the Parallel API and handle errors."""
    req_headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if headers:
        req_headers.update(headers)

    data = json.dumps(body_data).encode("utf-8") if body_data is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers=req_headers,
        method=method,
    )
    try:
        body = _read_url_response(req)
    except urllib.error.HTTPError as exc:
        rc = emit_provider_error(
            status=exc.code,
            message=f"HTTP {exc.code}",
            body=_read_http_error(exc),
        )
        return None, rc
    except urllib.error.URLError as exc:
        rc = emit_provider_error(
            status=None,
            message=f"network error: {exc.reason}",
            body=b"",
        )
        return None, rc
    else:
        return body, 0


def _str(value: object) -> str | None:
    """Return the value if it is a string, else None."""
    if isinstance(value, str):
        return value
    return None


def project_search_results(payload: JsonValue) -> list[dict[str, JsonValue]]:
    """Project web search results to compact rows."""
    if not isinstance(payload, dict):
        return []
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return []
    out: list[dict[str, JsonValue]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        entry: dict[str, JsonValue] = {}
        for field in ("title", "url", "publish_date"):
            val = _str(item.get(field))
            if val is not None:
                entry[field] = val
        excerpts = item.get("excerpts")
        if isinstance(excerpts, list):
            valid_excerpts = [e for e in excerpts if isinstance(e, str)]
            if valid_excerpts:
                entry["excerpts"] = valid_excerpts
        out.append(entry)
    return out


def project_extract_results(payload: JsonValue) -> list[dict[str, JsonValue]]:
    """Project extraction results to compact rows."""
    if not isinstance(payload, dict):
        return []
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return []
    out: list[dict[str, JsonValue]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        entry: dict[str, JsonValue] = {}
        for field in ("url", "title", "full_content"):
            val = _str(item.get(field))
            if val is not None:
                entry[field] = val
        excerpts = item.get("excerpts")
        if isinstance(excerpts, list):
            valid_excerpts = [e for e in excerpts if isinstance(e, str)]
            if valid_excerpts:
                entry["excerpts"] = valid_excerpts
        error = item.get("error")
        if isinstance(error, dict):
            entry["error"] = error
        out.append(entry)
    return out


def _build_source_policy(pairs_dict: dict[str, str]) -> dict[str, object]:
    """Extract and build source policy options from arguments dictionary."""
    policy: dict[str, object] = {}
    if "include_domains" in pairs_dict:
        policy["include_domains"] = [
            d.strip() for d in pairs_dict["include_domains"].split(",") if d.strip()
        ]
    if "exclude_domains" in pairs_dict:
        policy["exclude_domains"] = [
            d.strip() for d in pairs_dict["exclude_domains"].split(",") if d.strip()
        ]
    if "after_date" in pairs_dict:
        policy["after_date"] = pairs_dict["after_date"]
    return policy


def _parse_search_params(
    args: list[str],
) -> tuple[dict[str, object], bool] | int:
    """Parse search CLI arguments into a request payload."""
    query = args[0]
    p_dict = dict(pairs(args[1:]))
    raw_mode = p_dict.get("raw") in ("1", "")
    mode = p_dict.get("mode", "turbo")

    req_body: dict[str, object] = {"search_queries": [query], "mode": mode}
    if "objective" in p_dict:
        req_body["objective"] = p_dict["objective"]

    advanced_settings: dict[str, object] = {}
    if "max_results" in p_dict:
        try:
            advanced_settings["max_results"] = int(p_dict["max_results"])
        except ValueError:
            return usage_error(f"invalid max_results: {p_dict['max_results']!r}")
    else:
        advanced_settings["max_results"] = 5

    policy = _build_source_policy(p_dict)
    if policy:
        advanced_settings["source_policy"] = policy
    req_body["advanced_settings"] = advanced_settings

    return req_body, raw_mode


def run_search(base_url: str, api_key: str, args: list[str]) -> int:
    """Execute a web search query."""
    if not args:
        return usage_error(
            "usage: parallel-search search <query> [mode=turbo|fast|basic|advanced] "
            "[max_results=N] [include_domains=d1,d2] [exclude_domains=d1,d2] "
            "[after_date=YYYY-MM-DD] [objective=text] [raw=1]",
        )
    parsed = _parse_search_params(args)
    if isinstance(parsed, int):
        return parsed
    req_body, raw_mode = parsed

    body, rc = _make_api_request(f"{base_url}/v1/search", api_key, body_data=req_body)
    if rc != 0 or body is None:
        return rc

    if raw_mode:
        _ = sys.stdout.buffer.write(body)
        return 0

    try:
        payload = cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        return emit_provider_error(
            status=None,
            message=f"invalid JSON in response: {exc.msg}",
            body=body,
        )

    envelope: dict[str, JsonValue] = {
        "type": "search",
        "query": args[0],
        "mode": cast("str", req_body.get("mode", "turbo")),
        "results": project_search_results(payload),
    }
    json_print(envelope)
    return 0


def _parse_extract_params(
    args: list[str],
) -> tuple[dict[str, object], list[str], bool]:
    """Parse extract CLI arguments into request data."""
    urls = [u.strip() for u in args[0].split(",") if u.strip()]
    p_dict = dict(pairs(args[1:]))
    raw_mode = p_dict.get("raw") in ("1", "")
    full_content = p_dict.get("full_content") in ("1", "true", "")

    req_body: dict[str, object] = {"urls": urls}
    if "objective" in p_dict:
        req_body["objective"] = p_dict["objective"]
    if full_content:
        req_body["advanced_settings"] = {
            "full_content": {"max_chars_per_result": 50000},
        }
    return req_body, urls, raw_mode


def run_extract(base_url: str, api_key: str, args: list[str]) -> int:
    """Execute content extraction from URLs."""
    if not args:
        return usage_error(
            "usage: parallel-search extract <url1,url2...> [objective=text] "
            "[full_content=1] [raw=1]",
        )
    req_body, urls, raw_mode = _parse_extract_params(args)
    if not urls:
        return usage_error("no valid URLs provided")

    body, rc = _make_api_request(f"{base_url}/v1/extract", api_key, body_data=req_body)
    if rc != 0 or body is None:
        return rc

    if raw_mode:
        _ = sys.stdout.buffer.write(body)
        return 0

    try:
        payload = cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        return emit_provider_error(
            status=None,
            message=f"invalid JSON in response: {exc.msg}",
            body=body,
        )

    envelope: dict[str, JsonValue] = {
        "type": "extract",
        "urls": urls,
        "results": project_extract_results(payload),
    }
    json_print(envelope)
    return 0


def _parse_task_create_params(
    args: list[str],
) -> tuple[dict[str, object], bool]:
    """Parse task-create arguments into request payload."""
    task_input = args[0]
    p_dict = dict(pairs(args[1:]))
    raw_mode = p_dict.get("raw") in ("1", "")
    processor = p_dict.get("processor", "lite-fast")

    req_body: dict[str, object] = {
        "input": task_input,
        "processor": processor,
    }
    if "previous_interaction_id" in p_dict:
        req_body["previous_interaction_id"] = p_dict["previous_interaction_id"]
    if "memory_scope_key" in p_dict:
        req_body["memory_scope_key"] = p_dict["memory_scope_key"]

    return req_body, raw_mode


def run_task_create(base_url: str, api_key: str, args: list[str]) -> int:
    """Create an asynchronous deep research or data extraction task."""
    if not args:
        return usage_error(
            "usage: parallel-search task-create <objective_or_input> "
            "[processor=lite-fast|core-fast|pro|ultra] "
            "[previous_interaction_id=trun_xxx] [memory_scope_key=xxx] [raw=1]",
        )
    req_body, raw_mode = _parse_task_create_params(args)
    body, rc = _make_api_request(
        f"{base_url}/v1/tasks/runs",
        api_key,
        body_data=req_body,
    )
    if rc != 0 or body is None:
        return rc

    if raw_mode:
        _ = sys.stdout.buffer.write(body)
        return 0

    try:
        payload = cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        return emit_provider_error(
            status=None,
            message=f"invalid JSON in response: {exc.msg}",
            body=body,
        )

    json_print(payload)
    return 0


def run_task_status(base_url: str, api_key: str, args: list[str]) -> int:
    """Check the status of a task run."""
    if not args:
        return usage_error("usage: parallel-search task-status <run_id>")
    run_id = args[0]
    body, rc = _make_api_request(
        f"{base_url}/v1/tasks/runs/{run_id}",
        api_key,
        method="GET",
    )
    if rc != 0 or body is None:
        return rc
    try:
        payload = cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        return emit_provider_error(
            status=None,
            message=f"invalid JSON in response: {exc.msg}",
            body=body,
        )
    json_print(payload)
    return 0


def run_task_result(base_url: str, api_key: str, args: list[str]) -> int:
    """Fetch the completed result of a task run."""
    if not args:
        return usage_error("usage: parallel-search task-result <run_id>")
    run_id = args[0]
    body, rc = _make_api_request(
        f"{base_url}/v1/tasks/runs/{run_id}/result",
        api_key,
        method="GET",
    )
    if rc != 0 or body is None:
        return rc
    try:
        payload = cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        return emit_provider_error(
            status=None,
            message=f"invalid JSON in response: {exc.msg}",
            body=body,
        )
    json_print(payload)
    return 0


def run_findall_search(base_url: str, api_key: str, args: list[str]) -> int:
    """Synchronous fast entity discovery search."""
    if not args:
        return usage_error(
            "usage: parallel-search findall-search <query> "
            "[entity_type=companies|people] [limit=N]",
        )
    query = args[0]
    p_dict = dict(pairs(args[1:]))
    entity_type = p_dict.get("entity_type", "companies")
    limit = 10
    if "limit" in p_dict:
        try:
            limit = int(p_dict["limit"])
        except ValueError:
            return usage_error(f"invalid limit: {p_dict['limit']!r}")

    req_body: dict[str, object] = {
        "query": query,
        "entity_type": entity_type,
        "match_limit": limit,
    }
    headers = {"parallel-beta": "search-extract-2025-10-10"}
    body, rc = _make_api_request(
        f"{base_url}/v1beta/findall/entity-search",
        api_key,
        body_data=req_body,
        headers=headers,
    )
    if rc != 0 or body is None:
        return rc
    try:
        payload = cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        return emit_provider_error(
            status=None,
            message=f"invalid JSON in response: {exc.msg}",
            body=body,
        )
    json_print(payload)
    return 0


def _parse_memory_retrieve_params(
    args: list[str],
) -> tuple[dict[str, object], int] | int:
    """Parse memory-retrieve arguments into request payload."""
    query = args[0] if args else ""
    p_dict = dict(pairs(args[1:] if args else []))
    limit = 10
    if "limit" in p_dict:
        try:
            limit = int(p_dict["limit"])
        except ValueError:
            return usage_error(f"invalid limit: {p_dict['limit']!r}")

    req_body: dict[str, object] = {"limit": limit}
    if query:
        req_body["query"] = query
    if "kind" in p_dict:
        req_body["kind"] = p_dict["kind"]
    if "memory_scope_key" in p_dict:
        req_body["memory_scope_key"] = p_dict["memory_scope_key"]

    return req_body, 0


def run_memory_retrieve(base_url: str, api_key: str, args: list[str]) -> int:
    """Retrieve saved research/tasks from Parallel Memory."""
    parsed = _parse_memory_retrieve_params(args)
    if isinstance(parsed, int):
        return parsed
    req_body, _ = parsed

    headers = {"parallel-beta": "search-extract-2025-10-10"}
    body, rc = _make_api_request(
        f"{base_url}/v1beta/memory/retrieve",
        api_key,
        body_data=req_body,
        headers=headers,
    )
    if rc != 0 or body is None:
        return rc
    try:
        payload = cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        return emit_provider_error(
            status=None,
            message=f"invalid JSON in response: {exc.msg}",
            body=body,
        )
    json_print(payload)
    return 0


def run_raw(base_url: str, api_key: str, args: list[str]) -> int:
    """Fetch or post a raw API path."""
    if not args:
        return usage_error(
            "usage: parallel-search raw <GET|POST> </path> [key=value ...]",
        )
    method = "GET"
    pos = 0
    if args[0].upper() in {"GET", "POST", "PUT", "DELETE"}:
        method = args[0].upper()
        pos = 1
        if len(args) <= pos:
            return usage_error("missing endpoint path")

    path = args[pos]
    if not path.startswith("/"):
        path = f"/{path}"

    extra = pairs(args[pos + 1 :])
    url = f"{base_url}{path}"

    body_data: dict[str, object] | None = None
    if method in {"POST", "PUT"}:
        body_data = dict(extra)
    elif extra:
        url = f"{url}?{urllib.parse.urlencode(extra)}"

    body, rc = _make_api_request(
        url,
        api_key,
        body_data=body_data,
        method=method,
    )
    if rc != 0 or body is None:
        return rc
    _ = sys.stdout.buffer.write(body)
    return 0


def main(argv: list[str]) -> int:
    """Route Parallel Search commands and preserve exit codes."""
    if not argv or argv[0] in {"-h", "--help"}:
        print(USAGE)
        return 0 if argv and argv[0] in {"-h", "--help"} else 2

    load_env()
    api_key = os.environ.get("PARALLEL_API_KEY")
    if not api_key:
        return usage_error(
            "PARALLEL_API_KEY required (export it, use this skill's .env, "
            "or set PARALLEL_ENV_FILE)",
        )

    base_url = os.environ.get("PARALLEL_BASE_URL", "https://api.parallel.ai").rstrip(
        "/",
    )
    cmd, args = argv[0], argv[1:]

    runners: dict[str, Callable[[str, str, list[str]], int]] = {
        "search": run_search,
        "extract": run_extract,
        "task-create": run_task_create,
        "task-status": run_task_status,
        "task-result": run_task_result,
        "findall-search": run_findall_search,
        "memory-retrieve": run_memory_retrieve,
        "raw": run_raw,
    }
    runner = runners.get(cmd)
    if runner is None:
        return usage_error(USAGE)
    return runner(base_url, api_key, args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
