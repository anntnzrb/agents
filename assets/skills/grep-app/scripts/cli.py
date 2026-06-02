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

USAGE = "usage: grep-app <search|regex> ..."


def pairs(items: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in items:
        if "=" in item:
            key, value = item.split("=", 1)
            out.append((key, value))
        else:
            out.append((item, ""))
    return out


def request_get(base_url: str, params: list[tuple[str, str]]) -> int:
    url = base_url
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            sys.stdout.buffer.write(response.read())
        return 0
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace") or f"HTTP {exc.code}"
        print(text, file=sys.stderr)
        return 22
    except urllib.error.URLError as exc:
        print(f"Grep.app network error: {exc.reason}", file=sys.stderr)
        return 1


def main(argv: list[str]) -> int:
    if argv and argv[0] in {"-h", "--help"}:
        print(USAGE)
        return 0

    base_url = os.environ.get("GREP_APP_BASE_URL", "https://grep.app/api/search")
    cmd = argv[0] if argv else "search"
    args = argv[1:] if argv else []

    if cmd == "search":
        if not args:
            print("usage: grep-app search <pattern> [key=value ...]", file=sys.stderr)
            return 2
        return request_get(base_url, [("q", args[0]), *pairs(args[1:])])

    if cmd == "regex":
        if not args:
            print("usage: grep-app regex <pattern> [key=value ...]", file=sys.stderr)
            return 2
        return request_get(
            base_url, [("q", args[0]), ("regexp", "true"), *pairs(args[1:])]
        )

    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
