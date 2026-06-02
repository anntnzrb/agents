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
import urllib.request
from pathlib import Path
from typing import Any

USAGE = "usage: exa-search <post|search|contents|find-similar|answer|research> ..."


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
    if os.environ.get("EXA_API_KEY") or os.environ.get("EXA_APIKEY"):
        return
    skill_dir = Path(__file__).resolve().parents[1]
    candidates: list[Path | None] = []
    if os.environ.get("EXA_SEARCH_ENV_FILE"):
        candidates.append(Path(os.environ["EXA_SEARCH_ENV_FILE"]).expanduser())
    candidates.append(skill_dir / ".env")
    if os.environ.get("SKILLS_DIR"):
        candidates.append(
            Path(os.environ["SKILLS_DIR"]).expanduser() / "exa-search" / ".env"
        )
    candidates.append(ancestor_env("exa-search"))
    for candidate in candidates:
        if candidate is not None and parse_env_file(candidate):
            return


def post_json(base_url: str, path: str, api_key: str, body: bytes) -> int:
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json", "x-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            sys.stdout.buffer.write(response.read())
        return 0
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace") or f"HTTP {exc.code}"
        print(text, file=sys.stderr)
        return 22
    except urllib.error.URLError as exc:
        print(f"Exa network error: {exc.reason}", file=sys.stderr)
        return 1


def dump_body(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def parse_num(value: str) -> int | float:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("numResults must be a JSON number") from exc
    if not isinstance(parsed, int | float):
        raise ValueError("numResults must be a JSON number")
    return parsed


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(USAGE)
        return 0 if argv and argv[0] in {"-h", "--help"} else 2

    load_env()
    api_key = os.environ.get("EXA_API_KEY") or os.environ.get("EXA_APIKEY")
    if not api_key:
        print(
            "EXA_API_KEY required (export it, use this skill's .env, or set EXA_SEARCH_ENV_FILE)",
            file=sys.stderr,
        )
        return 2

    base_url = os.environ.get("EXA_BASE_URL", "https://api.exa.ai").rstrip("/")
    cmd, args = argv[0], argv[1:]

    if cmd == "post":
        if len(args) < 2:
            print("usage: exa-search post </path> '<json-body>'", file=sys.stderr)
            return 2
        path = args[0] if args[0].startswith("/") else f"/{args[0]}"
        return post_json(base_url, path, api_key, args[1].encode("utf-8"))

    if cmd == "search":
        if not args:
            print(
                "usage: exa-search search <query> [numResults] [type]", file=sys.stderr
            )
            return 2
        try:
            num_results = parse_num(args[1]) if len(args) > 1 else 5
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        payload: dict[str, Any] = {"query": args[0], "numResults": num_results}
        if len(args) > 2 and args[2]:
            payload["type"] = args[2]
        return post_json(base_url, "/search", api_key, dump_body(payload))

    if cmd == "contents":
        if not args:
            print("usage: exa-search contents <url> [url ...]", file=sys.stderr)
            return 2
        return post_json(base_url, "/contents", api_key, dump_body({"urls": args}))

    if cmd == "find-similar":
        if not args:
            print("usage: exa-search find-similar <url>", file=sys.stderr)
            return 2
        return post_json(base_url, "/findSimilar", api_key, dump_body({"url": args[0]}))

    if cmd == "answer":
        if not args:
            print("usage: exa-search answer <question>", file=sys.stderr)
            return 2
        return post_json(base_url, "/answer", api_key, dump_body({"query": args[0]}))

    if cmd == "research":
        if not args:
            print("usage: exa-search research <instructions> [model]", file=sys.stderr)
            return 2
        return post_json(
            base_url,
            "/research/v1",
            api_key,
            dump_body(
                {
                    "instructions": args[0],
                    "model": args[1] if len(args) > 1 else "exa-research",
                }
            ),
        )

    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
