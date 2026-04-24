#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USAGE = "usage: brave-search <web|news|local|image|video|summarizer-key|summarize|raw> ..."
ENDPOINTS = {
    "web": "/web/search",
    "news": "/news/search",
    "local": "/local/search",
    "image": "/images/search",
    "video": "/videos/search",
}


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
        candidates.append(Path(os.environ["SKILLS_DIR"]).expanduser() / "brave-search" / ".env")
    candidates.append(ancestor_env("brave-search"))
    for candidate in candidates:
        if candidate is not None and parse_env_file(candidate):
            return


def request_get(base_url: str, path: str, api_key: str, params: list[tuple[str, str]]) -> int:
    url = f"{base_url}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"X-Subscription-Token": api_key})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            sys.stdout.buffer.write(response.read())
        return 0
    except urllib.error.HTTPError as exc:
        body = exc.read()
        message = body.decode("utf-8", errors="replace") or f"HTTP {exc.code}"
        print(message, file=sys.stderr)
        return 22
    except urllib.error.URLError as exc:
        print(f"Brave Search network error: {exc.reason}", file=sys.stderr)
        return 1


def pairs(items: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in items:
        if "=" in item:
            key, value = item.split("=", 1)
            out.append((key, value))
        else:
            out.append((item, ""))
    return out


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(USAGE)
        return 0 if argv and argv[0] in {"-h", "--help"} else 2

    load_env()
    api_key = os.environ.get("BRAVE_API_KEY") or os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        print("BRAVE_API_KEY required (export it, use this skill's .env, or set BRAVE_SEARCH_ENV_FILE)", file=sys.stderr)
        return 2

    base_url = os.environ.get("BRAVE_SEARCH_BASE_URL", "https://api.search.brave.com/res/v1").rstrip("/")
    cmd, args = argv[0], argv[1:]

    if cmd in ENDPOINTS:
        if not args:
            print(f"usage: brave-search {cmd} <query> [key=value ...]", file=sys.stderr)
            return 2
        return request_get(base_url, ENDPOINTS[cmd], api_key, [("q", args[0]), *pairs(args[1:])])
    if cmd == "summarizer-key":
        if not args:
            print("usage: brave-search summarizer-key <query> [key=value ...]", file=sys.stderr)
            return 2
        import json
        import io

        buffer = io.BytesIO()
        url = f"{base_url}/web/search?{urllib.parse.urlencode([('q', args[0]), ('summary', '1'), *pairs(args[1:])])}"
        req = urllib.request.Request(url, headers={"X-Subscription-Token": api_key})
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                buffer.write(response.read())
        except urllib.error.HTTPError as exc:
            print(exc.read().decode("utf-8", errors="replace") or f"HTTP {exc.code}", file=sys.stderr)
            return 22
        except urllib.error.URLError as exc:
            print(f"Brave Search network error: {exc.reason}", file=sys.stderr)
            return 1
        try:
            key = json.loads(buffer.getvalue()).get("summarizer", {}).get("key")
        except json.JSONDecodeError:
            key = None
        if key is not None:
            print(key)
        return 0
    if cmd == "summarize":
        if not args:
            print("usage: brave-search summarize <summary-key> [key=value ...]", file=sys.stderr)
            return 2
        return request_get(base_url, "/summarizer/search", api_key, [("key", args[0]), *pairs(args[1:])])
    if cmd == "raw":
        if not args:
            print("usage: brave-search raw </path> [key=value ...]", file=sys.stderr)
            return 2
        path = args[0] if args[0].startswith("/") else f"/{args[0]}"
        return request_get(base_url, path, api_key, pairs(args[1:]))

    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
