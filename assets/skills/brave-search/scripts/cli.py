# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

from __future__ import annotations

import html as _html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

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


def parse_env_file(path: Path) -> bool:
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
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
    return True


def ancestor_env(skill_name: str) -> Path | None:
    here = Path.cwd().resolve()
    for directory in (here, *here.parents):
        candidate = directory / "skills" / skill_name / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_env() -> None:
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
    out: list[tuple[str, str]] = []
    for item in items:
        if "=" in item:
            key, value = item.split("=", 1)
            out.append((key, value))
        else:
            out.append((item, ""))
    return out


def json_print(payload: Any) -> None:
    print(json.dumps(payload, separators=(",", ":")))


def usage_error(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def looks_like_html(text: str) -> bool:
    head = text.lstrip()[:200].lower()
    return head.startswith(("<!doctype html", "<html", "<?xml"))


def html_to_text(body: bytes) -> str:
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
    body_bytes = len(body)
    if body:
        decoded = body.decode("utf-8", errors="replace")
    else:
        decoded = ""
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


def _str(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    return None


def project_web_results(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    results = (payload.get("web") or {}).get("results") or payload.get("results") or []
    for item in results:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {}
        for field in ("title", "url", "description", "age", "page_age"):
            value = _str(item.get(field))
            if value is not None:
                entry[field] = value
        source = (
            (item.get("profile") or {}).get("name")
            if isinstance(item.get("profile"), dict)
            else None
        )
        if isinstance(source, str):
            entry["source"] = source
        if "cluster" in item and isinstance(item["cluster"], list):
            projected = []
            for cluster_entry in item["cluster"]:
                if not isinstance(cluster_entry, dict):
                    continue
                compact = {}
                for field in ("title", "url", "description"):
                    value = _str(cluster_entry.get(field))
                    if value is not None:
                        compact[field] = value
                if compact:
                    projected.append(compact)
            entry["cluster"] = projected
        out.append(entry)
    return out


def project_news_results(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        entry = {}
        for field in ("title", "url", "description", "age", "page_age"):
            value = _str(item.get(field))
            if value is not None:
                entry[field] = value
        source = (
            (item.get("profile") or {}).get("name")
            if isinstance(item.get("profile"), dict)
            else None
        )
        if isinstance(source, str):
            entry["source"] = source
        out.append(entry)
    return out


def project_local_results(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    locations = (payload.get("results") or {}).get("locations") or []
    for item in locations:
        if not isinstance(item, dict):
            continue
        entry = {}
        for field in ("title", "url", "description", "age", "page_age"):
            value = _str(item.get(field))
            if value is not None:
                entry[field] = value
        source = (
            (item.get("profile") or {}).get("name")
            if isinstance(item.get("profile"), dict)
            else None
        )
        if isinstance(source, str):
            entry["source"] = source
        out.append(entry)
    return out


def project_image_results(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        thumb = item.get("thumbnail") if isinstance(item.get("thumbnail"), dict) else {}
        props = (
            item.get("properties") if isinstance(item.get("properties"), dict) else {}
        )
        entry: dict[str, Any] = {
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


def project_video_results(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        thumb = item.get("thumbnail") if isinstance(item.get("thumbnail"), dict) else {}
        entry: dict[str, Any] = {
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


PROJECTORS: dict[str, Any] = {
    "web": project_web_results,
    "news": project_news_results,
    "local": project_local_results,
    "image": project_image_results,
    "video": project_video_results,
}


def validate_count(value: str) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < COUNT_MIN or n > COUNT_MAX:
        return None
    return n


def run_endpoint(cmd: str, base_url: str, api_key: str, args: list[str]) -> int:
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

    if not any(k == "count" for k, _ in extra):
        extra.append(("count", str(DEFAULT_COUNTS[cmd])))

    count_value = DEFAULT_COUNTS[cmd]
    validated: list[tuple[str, str]] = []
    for key, value in extra:
        if key == "count":
            n = validate_count(value)
            if n is None:
                return usage_error(
                    f"count must be an integer {COUNT_MIN}..{COUNT_MAX} (got {value!r})",
                )
            count_value = n
        validated.append((key, value))
    extra = validated

    if (
        cmd == "web"
        and not raw_mode
        and not any(k == "result_filter" for k, _ in extra)
    ):
        extra.append(("result_filter", "web"))

    params = [("q", query), *extra]
    url = f"{base_url}{ENDPOINTS[cmd]}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"X-Subscription-Token": api_key})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        return emit_provider_error(
            status=exc.code,
            message=f"HTTP {exc.code}",
            body=exc.read(),
        )
    except urllib.error.URLError as exc:
        return emit_provider_error(
            status=None,
            message=f"network error: {exc.reason}",
            body=b"",
        )

    if raw_mode:
        sys.stdout.buffer.write(body)
        return 0

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return emit_provider_error(
            status=None,
            message=f"invalid JSON in response: {exc.msg}",
            body=body,
        )

    envelope: dict[str, Any] = {
        "type": cmd,
        "query": query,
        "count": count_value,
        "results": PROJECTORS[cmd](payload),
    }
    query_obj = payload.get("query")
    more = (
        query_obj.get("more_results_available") if isinstance(query_obj, dict) else None
    )
    if isinstance(more, bool):
        envelope["more_results_available"] = more
    json_print(envelope)
    return 0


def run_summarizer_key(base_url: str, api_key: str, args: list[str]) -> int:
    if not args:
        return usage_error("usage: brave-search summarizer-key <query> [key=value ...]")
    params = [("q", args[0]), ("summary", "1"), *pairs(args[1:])]
    url = f"{base_url}/web/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"X-Subscription-Token": api_key})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        return emit_provider_error(
            status=exc.code,
            message=f"HTTP {exc.code}",
            body=exc.read(),
        )
    except urllib.error.URLError as exc:
        return emit_provider_error(
            status=None,
            message=f"network error: {exc.reason}",
            body=b"",
        )
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return emit_provider_error(
            status=None,
            message=f"invalid JSON in response: {exc.msg}",
            body=body,
        )
    key = (
        (payload.get("summarizer") or {}).get("key")
        if isinstance(payload, dict)
        else None
    )
    if not isinstance(key, str) or not key:
        return emit_provider_error(
            status=None,
            message="summarizer.key missing in response (Brave declined to summarize this query)",
            body=b"",
        )
    print(key)
    return 0


def run_summarize(base_url: str, api_key: str, args: list[str]) -> int:
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
    url = f"{base_url}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"X-Subscription-Token": api_key})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            sys.stdout.buffer.write(response.read())
        return 0
    except urllib.error.HTTPError as exc:
        return emit_provider_error(
            status=exc.code,
            message=f"HTTP {exc.code}",
            body=exc.read(),
        )
    except urllib.error.URLError as exc:
        return emit_provider_error(
            status=None,
            message=f"network error: {exc.reason}",
            body=b"",
        )


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(USAGE)
        return 0 if argv and argv[0] in {"-h", "--help"} else 2

    load_env()
    api_key = os.environ.get("BRAVE_API_KEY") or os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        return usage_error(
            "BRAVE_API_KEY required (export it, use this skill's .env, or set BRAVE_SEARCH_ENV_FILE)",
        )

    base_url = os.environ.get(
        "BRAVE_SEARCH_BASE_URL",
        "https://api.search.brave.com/res/v1",
    ).rstrip("/")
    cmd, args = argv[0], argv[1:]

    if cmd in ENDPOINTS:
        return run_endpoint(cmd, base_url, api_key, args)
    if cmd == "summarizer-key":
        return run_summarizer_key(base_url, api_key, args)
    if cmd == "summarize":
        return run_summarize(base_url, api_key, args)
    if cmd == "raw":
        return run_raw(base_url, api_key, args)

    return usage_error(USAGE)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
