#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

USAGE = "usage: context7 <search|id|docs|json> ..."


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
    if os.environ.get("CONTEXT7_API_KEY"):
        return
    skill_dir = Path(__file__).resolve().parents[1]
    candidates: list[Path | None] = []
    if os.environ.get("CONTEXT7_ENV_FILE"):
        candidates.append(Path(os.environ["CONTEXT7_ENV_FILE"]).expanduser())
    candidates.append(skill_dir / ".env")
    if os.environ.get("SKILLS_DIR"):
        candidates.append(Path(os.environ["SKILLS_DIR"]).expanduser() / "context7" / ".env")
    candidates.append(ancestor_env("context7"))
    for candidate in candidates:
        if candidate is not None and parse_env_file(candidate):
            return


def error_message(status: int, body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    message = ""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            raw = parsed.get("message") or parsed.get("error")
            if raw is not None:
                message = str(raw)
    except json.JSONDecodeError:
        pass
    message = message or text
    if not message:
        message = {
            401: "Invalid API key. Keys should start with ctx7sk.",
            404: "Library not found. Verify the library ID.",
            422: "Library unavailable for context generation. Try a different library.",
            429: "Rate limited. Retry later or add CONTEXT7_API_KEY for higher limits.",
            503: "Context7 service unavailable. Retry later.",
        }.get(status, f"Context7 request failed with HTTP {status}")
    return message


def request_get(base_url: str, path: str, params: list[tuple[str, str]], max_time: float) -> tuple[int, bytes]:
    url = f"{base_url}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    headers: dict[str, str] = {}
    if os.environ.get("CONTEXT7_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['CONTEXT7_API_KEY']}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=max_time) as response:
            return 0, response.read()
    except urllib.error.HTTPError as exc:
        print(error_message(exc.code, exc.read()), file=sys.stderr)
        return 22, b""
    except TimeoutError:
        print(f"Context7 request timed out after {int(max_time)}s", file=sys.stderr)
        return 1, b""
    except urllib.error.URLError as exc:
        print(f"Context7 network error: {exc.reason}", file=sys.stderr)
        return 1, b""


def require_args(args: list[str], usage: str, count: int) -> bool:
    if len(args) < count:
        print(usage, file=sys.stderr)
        return False
    return True


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(USAGE)
        return 0 if argv and argv[0] in {"-h", "--help"} else 2

    load_env()
    base_url = os.environ.get("CONTEXT7_BASE_URL", "https://context7.com/api/v2").rstrip("/")
    cmd, args = argv[0], argv[1:]

    if cmd == "search":
        if not require_args(args, "usage: context7 search <library-name> <query>", 2):
            return 2
        code, body = request_get(base_url, "/libs/search", [("libraryName", args[0]), ("query", " ".join(args[1:]))], 30)
        if code == 0:
            sys.stdout.buffer.write(body)
        return code

    if cmd == "id":
        if not require_args(args, "usage: context7 id <library-name> <query>", 2):
            return 2
        code, body = request_get(base_url, "/libs/search", [("libraryName", args[0]), ("query", " ".join(args[1:]))], 30)
        if code != 0:
            return code
        try:
            parsed: Any = json.loads(body)
            library_id = parsed["results"][0]["id"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            print("No matching library ID found", file=sys.stderr)
            return 1
        print(library_id)
        return 0

    if cmd in {"docs", "json"}:
        if not require_args(args, f"usage: context7 {cmd} <library-id> <query>", 2):
            return 2
        library_id = args[0] if args[0].startswith("/") else f"/{args[0]}"
        output_type = "json" if cmd == "json" else "txt"
        code, body = request_get(
            base_url,
            "/context",
            [("libraryId", library_id), ("query", " ".join(args[1:])), ("type", output_type)],
            60,
        )
        if code == 0:
            sys.stdout.buffer.write(body)
        return code

    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
