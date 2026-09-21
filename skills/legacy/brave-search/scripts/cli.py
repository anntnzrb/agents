#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Search the web via the Brave Search API."""

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
    "usage: brave-search <web|news|local|image|video|summarizer-key|summarize|raw> ..."
)
ENDPOINTS: dict[str, str] = {
    "web": "/web/search",
    "news": "/news/search",
    "local": "/local/search",
    "image": "/images/search",
    "video": "/videos/search",
}
DEFAULT_COUNTS: dict[str, int] = {
    "web": 5,
    "news": 5,
    "local": 5,
    "image": 10,
    "video": 10,
}
COUNT_MIN = 1
COUNT_MAX = 20
PREVIEW_LIMIT = 500
PROVIDER = "brave-search"
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
    return None


def load_env() -> None:
    """Load API credentials from env files unless already exported."""
    if os.environ.get("BRAVE_API_KEY") or os.environ.get("BRAVE_SEARCH_API_KEY"):
        return
    skill_dir = Path(__file__).resolve().parents[1]
    candidates: list[Path | None] = []
    if os.environ.get("BRAVE_SEARCH_ENV_FILE"):
        candidates.append(Path(os.environ["BRAVE_SEARCH_ENV_FILE"]).expanduser())
    candidates.append(skill_dir / ".env")
    if os.environ.get("SKILLS_DIR"):
        candidates.append(
            Path(os.environ["SKILLS_DIR"]).expanduser() / "brave-search" / ".env",
        )
    candidates.append(ancestor_env("brave-search"))
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


def _str(value: object) -> str | None:
    """Return the value if it is a string, else None."""
    if isinstance(value, str):
        return value
    return None


def _read_url_response(req: urllib.request.Request) -> bytes:
    """Read a URL response body, closing the connection."""
    opened = cast("object", urllib.request.urlopen(req, timeout=60))
    with cast("urllib.response.addinfourl", opened) as response:
        return response.read()


def _read_http_error(exc: urllib.error.HTTPError) -> bytes:
    """Read an HTTP error body and release the error response."""
    try:
        return exc.read()
    finally:
        exc.close()


def _project_cluster(cluster: list[JsonValue]) -> list[dict[str, JsonValue]]:
    """Project a result cluster to compact rows."""
    projected: list[dict[str, JsonValue]] = []
    for cluster_entry in cluster:
        if not isinstance(cluster_entry, dict):
            continue
        compact: dict[str, JsonValue] = {}
        for field in ("title", "url", "description"):
            value = _str(cluster_entry.get(field))
            if value is not None:
                compact[field] = value
        if compact:
            projected.append(compact)
    return projected


def project_web_results(payload: JsonValue) -> list[dict[str, JsonValue]]:
    """Project web results to compact rows."""
    out: list[dict[str, JsonValue]] = []
    if not isinstance(payload, dict):
        return []
    web = payload.get("web")
    web_results = web.get("results") if isinstance(web, dict) else None
    raw_results: JsonValue = web_results or payload.get("results") or []
    results: list[JsonValue] = raw_results if isinstance(raw_results, list) else []
    for item in results:
        if not isinstance(item, dict):
            continue
        entry: dict[str, JsonValue] = {}
        for field in ("title", "url", "description", "age", "page_age"):
            value = _str(item.get(field))
            if value is not None:
                entry[field] = value
        profile = item.get("profile")
        source = profile.get("name") if isinstance(profile, dict) else None
        if isinstance(source, str):
            entry["source"] = source
        if "cluster" in item and isinstance(item["cluster"], list):
            entry["cluster"] = _project_cluster(item["cluster"])
        out.append(entry)
    return out


def project_news_results(payload: JsonValue) -> list[dict[str, JsonValue]]:
    """Project news results to compact rows."""
    out: list[dict[str, JsonValue]] = []
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    for item in results:
        if not isinstance(item, dict):
            continue
        entry: dict[str, JsonValue] = {}
        for field in ("title", "url", "description", "age", "page_age"):
            value = _str(item.get(field))
            if value is not None:
                entry[field] = value
        profile = item.get("profile")
        source = profile.get("name") if isinstance(profile, dict) else None
        if isinstance(source, str):
            entry["source"] = source
        out.append(entry)
    return out


def project_local_results(payload: JsonValue) -> list[dict[str, JsonValue]]:
    """Project local results to compact rows."""
    out: list[dict[str, JsonValue]] = []
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    locations = results.get("locations") if isinstance(results, dict) else None
    if not isinstance(locations, list):
        return []
    for item in locations:
        if not isinstance(item, dict):
            continue
        entry: dict[str, JsonValue] = {}
        for field in ("title", "url", "description", "age", "page_age"):
            value = _str(item.get(field))
            if value is not None:
                entry[field] = value
        profile = item.get("profile")
        source = profile.get("name") if isinstance(profile, dict) else None
        if isinstance(source, str):
            entry["source"] = source
        out.append(entry)
    return out


def project_image_results(payload: JsonValue) -> list[dict[str, JsonValue]]:
    """Project image results to compact rows."""
    out: list[dict[str, JsonValue]] = []
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    for item in results:
        if not isinstance(item, dict):
            continue
        thumbnail = item.get("thumbnail")
        thumb: dict[str, JsonValue] = thumbnail if isinstance(thumbnail, dict) else {}
        properties = item.get("properties")
        props: dict[str, JsonValue] = properties if isinstance(properties, dict) else {}
        entry: dict[str, JsonValue] = {
            "title": _str(item.get("title")),
            "url": _str(item.get("url")),
            "source": _str(item.get("source")),
            "thumbnail_url": _str(thumb.get("src")),
            "image_url": _str(props.get("url")),
            "width": props.get("width"),
            "height": props.get("height"),
            "page_fetched": _str(item.get("page_fetched")),
            "confidence": item.get("confidence"),
        }
        entry = {k: v for k, v in entry.items() if v is not None}
        out.append(entry)
    return out


def project_video_results(payload: JsonValue) -> list[dict[str, JsonValue]]:
    """Project video results to compact rows."""
    out: list[dict[str, JsonValue]] = []
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    for item in results:
        if not isinstance(item, dict):
            continue
        thumbnail = item.get("thumbnail")
        thumb: dict[str, JsonValue] = thumbnail if isinstance(thumbnail, dict) else {}
        entry: dict[str, JsonValue] = {
            "title": _str(item.get("title")),
            "url": _str(item.get("url")),
            "description": _str(item.get("description")),
            "age": _str(item.get("age")),
            "page_age": _str(item.get("page_age")),
            "duration": _str(item.get("duration")),
            "creator": _str(item.get("creator")),
            "publisher": _str(item.get("publisher")),
            "thumbnail_url": _str(thumb.get("src")),
        }
        entry = {k: v for k, v in entry.items() if v is not None}
        out.append(entry)
    return out


PROJECTORS: dict[str, Callable[[JsonValue], list[dict[str, JsonValue]]]] = {
    "web": project_web_results,
    "news": project_news_results,
    "local": project_local_results,
    "image": project_image_results,
    "video": project_video_results,
}


def validate_count(value: str) -> int | None:
    """Validate a result count within the provider bounds."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < COUNT_MIN or n > COUNT_MAX:
        return None
    return n


def _prepare_endpoint_params(
    cmd: str, extra: list[tuple[str, str]], count_value: int, raw_mode: bool
) -> tuple[list[tuple[str, str]], int] | int:
    """Validate count params and apply endpoint defaults."""
    if not any(key == "count" for key, _ in extra):
        extra = [*extra, ("count", str(count_value))]
    validated: list[tuple[str, str]] = []
    for key, value in extra:
        if key != "count":
            validated.append((key, value))
            continue
        count = validate_count(value)
        if count is None:
            return usage_error(
                f"count must be an integer {COUNT_MIN}..{COUNT_MAX} (got {value!r})",
            )
        count_value = count
        validated.append((key, value))
    if (
        cmd == "web"
        and not raw_mode
        and not any(key == "result_filter" for key, _ in validated)
    ):
        validated.append(("result_filter", "web"))
    return validated, count_value


def _emit_endpoint_result(
    *,
    cmd: str,
    query: str,
    count_value: int,
    raw_mode: bool,
    body: bytes,
) -> int:
    """Emit an endpoint response body as raw bytes or a projected envelope."""
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
        "type": cmd,
        "query": query,
        "count": count_value,
        "results": PROJECTORS[cmd](payload),
    }
    query_obj = payload.get("query") if isinstance(payload, dict) else None
    more = (
        query_obj.get("more_results_available") if isinstance(query_obj, dict) else None
    )
    if isinstance(more, bool):
        envelope["more_results_available"] = more
    json_print(envelope)
    return 0


def run_endpoint(cmd: str, base_url: str, api_key: str, args: list[str]) -> int:
    """Run a search endpoint command."""
    if not args:
        return usage_error(f"usage: brave-search {cmd} <query> [key=value ...]")
    query = args[0]
    raw_mode = False
    extra: list[tuple[str, str]] = []
    for key, value in pairs(args[1:]):
        if key == "raw":
            if value in ("1", ""):
                raw_mode = True
            continue
        extra.append((key, value))

    prepared = _prepare_endpoint_params(cmd, extra, DEFAULT_COUNTS[cmd], raw_mode)
    if isinstance(prepared, int):
        return prepared
    extra, count_value = prepared

    params = [("q", query), *extra]
    url = f"{base_url}{ENDPOINTS[cmd]}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"X-Subscription-Token": api_key})
    try:
        body = _read_url_response(req)
    except urllib.error.HTTPError as exc:
        return emit_provider_error(
            status=exc.code,
            message=f"HTTP {exc.code}",
            body=_read_http_error(exc),
        )
    except urllib.error.URLError as exc:
        return emit_provider_error(
            status=None,
            message=f"network error: {exc.reason}",
            body=b"",
        )

    return _emit_endpoint_result(
        cmd=cmd,
        query=query,
        count_value=count_value,
        raw_mode=raw_mode,
        body=body,
    )


def run_summarizer_key(base_url: str, api_key: str, args: list[str]) -> int:
    """Fetch a summarizer key for a query."""
    if not args:
        return usage_error("usage: brave-search summarizer-key <query> [key=value ...]")
    params = [("q", args[0]), ("summary", "1"), *pairs(args[1:])]
    url = f"{base_url}/web/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"X-Subscription-Token": api_key})
    try:
        body = _read_url_response(req)
    except urllib.error.HTTPError as exc:
        return emit_provider_error(
            status=exc.code,
            message=f"HTTP {exc.code}",
            body=_read_http_error(exc),
        )
    except urllib.error.URLError as exc:
        return emit_provider_error(
            status=None,
            message=f"network error: {exc.reason}",
            body=b"",
        )
    try:
        payload = cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        return emit_provider_error(
            status=None,
            message=f"invalid JSON in response: {exc.msg}",
            body=body,
        )
    summarizer = payload.get("summarizer") if isinstance(payload, dict) else None
    key = summarizer.get("key") if isinstance(summarizer, dict) else None
    if not isinstance(key, str) or not key:
        return emit_provider_error(
            status=None,
            message=(
                "summarizer.key missing in response "
                + "(Brave declined to summarize this query)"
            ),
            body=b"",
        )
    print(key)
    return 0


def run_summarize(base_url: str, api_key: str, args: list[str]) -> int:
    """Summarize web results for a summary key."""
    if not args:
        return usage_error(
            "usage: brave-search summarize <summary-key> [key=value ...]",
        )
    return raw_get(
        base_url,
        "/summarizer/search",
        api_key,
        [("key", args[0]), *pairs(args[1:])],
    )


def run_raw(base_url: str, api_key: str, args: list[str]) -> int:
    """Fetch a raw API path and stream the response body."""
    if not args:
        return usage_error("usage: brave-search raw </path> [key=value ...]")
    path = args[0] if args[0].startswith("/") else f"/{args[0]}"
    return raw_get(base_url, path, api_key, pairs(args[1:]))


def raw_get(
    base_url: str,
    path: str,
    api_key: str,
    params: list[tuple[str, str]],
) -> int:
    """Fetch a raw API path with params and stream the response body."""
    url = f"{base_url}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"X-Subscription-Token": api_key})
    try:
        body = _read_url_response(req)
    except urllib.error.HTTPError as exc:
        return emit_provider_error(
            status=exc.code,
            message=f"HTTP {exc.code}",
            body=_read_http_error(exc),
        )
    except urllib.error.URLError as exc:
        return emit_provider_error(
            status=None,
            message=f"network error: {exc.reason}",
            body=b"",
        )
    _ = sys.stdout.buffer.write(body)
    return 0


def main(argv: list[str]) -> int:
    """Route Brave Search commands and preserve exit codes."""
    if not argv or argv[0] in {"-h", "--help"}:
        print(USAGE)
        return 0 if argv and argv[0] in {"-h", "--help"} else 2

    load_env()
    api_key = os.environ.get("BRAVE_API_KEY") or os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        return usage_error(
            "BRAVE_API_KEY required (export it, use this skill's .env, "
            + "or set BRAVE_SEARCH_ENV_FILE)",
        )

    base_url = os.environ.get(
        "BRAVE_SEARCH_BASE_URL",
        "https://api.search.brave.com/res/v1",
    ).rstrip("/")
    cmd, args = argv[0], argv[1:]

    runners: dict[str, Callable[[str, str, list[str]], int]] = {
        "summarizer-key": run_summarizer_key,
        "summarize": run_summarize,
        "raw": run_raw,
    }
    if cmd in ENDPOINTS:
        return run_endpoint(cmd, base_url, api_key, args)
    runner = runners.get(cmd)
    if runner is None:
        return usage_error(USAGE)
    return runner(base_url, api_key, args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
