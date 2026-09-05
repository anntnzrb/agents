# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

"""Search public code via the grep.app API."""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.response
from typing import cast

USAGE = "usage: grep-app <search|regex> ..."


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


def request_get(base_url: str, params: list[tuple[str, str]]) -> int:
    """GET a URL with encoded params and stream the body to stdout."""
    url = base_url
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    try:
        opened = cast("object", urllib.request.urlopen(req, timeout=60))
        with cast("urllib.response.addinfourl", opened) as response:
            _ = sys.stdout.buffer.write(response.read())
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace") or f"HTTP {exc.code}"
        print(text, file=sys.stderr)
        return 22
    except urllib.error.URLError as exc:
        print(f"Grep.app network error: {exc.reason}", file=sys.stderr)
        return 1
    else:
        return 0


def main(argv: list[str]) -> int:
    """Route grep-app search and regex commands."""
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
            base_url,
            [("q", args[0]), ("regexp", "true"), *pairs(args[1:])],
        )

    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
