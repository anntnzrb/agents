#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""YouTube Data API CLI: headless OAuth bootstrap and playlist management.

yt-dlp owns media download; this CLI owns what yt-dlp cannot do: write
operations on a user account through the YouTube Data API v3.

Credential resolution order:
  1. Environment variables YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
  2. XDG file ${XDG_CONFIG_HOME:-~/.config}/yt/oauth.json with keys
     client_id, client_secret, refresh_token

The OAuth consent screen MUST be in production mode, not testing mode;
testing-mode refresh tokens expire after 7 days.

Only the Python standard library is used so the script stays dependency-free;
the API surface needed here is small and stable.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from contextlib import closing
from pathlib import Path
from typing import Protocol, TypeIs

_json_loads: Callable[[str | bytes | bytearray], object] = json.loads

type JsonValue = (
    dict[str, JsonValue] | Sequence[JsonValue] | str | int | float | bool | None
)

SCOPE = "https://www.googleapis.com/auth/youtube"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = os.environ.get("YT_TEST_TOKEN_URL", "https://oauth2.googleapis.com/token")
REDIRECT_URI = "http://localhost"
API_BASE = os.environ.get("YT_TEST_API_BASE", "https://www.googleapis.com/youtube/v3")
HTTP_TIMEOUT = 30


class _Readable(Protocol):
    def read(self) -> bytes: ...
    def close(self) -> None: ...


def _is_readable(obj: object) -> TypeIs[_Readable]:
    return callable(getattr(obj, "read", None)) and callable(
        getattr(obj, "close", None)
    )


def _is_dict(value: object) -> TypeIs[dict[str, JsonValue]]:
    return isinstance(value, dict)


def _as_dict(value: JsonValue) -> dict[str, JsonValue]:
    """Return the value when it is a JSON object, else an empty object."""
    return value if isinstance(value, dict) else {}


def _opt_str(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None


class _Args(argparse.Namespace):
    """Parsed command-line arguments."""

    command: str = ""
    sub: str = ""
    redirect_url: str | None = None


def emit(payload: object) -> None:
    """Write exactly one JSON object to stdout."""
    _ = sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")


def fail(code: str, message: str, **details: object) -> SystemExit:
    """Emit a stable JSON error object and return SystemExit for raising."""
    emit(
        {
            "ok": False,
            "error": {"code": code, "message": message, "details": details},
        }
    )
    return SystemExit(1)


def read_response(req: urllib.request.Request) -> bytes:
    """Open an HTTP request and read the whole response body."""
    open_fn: Callable[..., object] = urllib.request.urlopen
    opened = open_fn(req, timeout=HTTP_TIMEOUT)
    if not _is_readable(opened):
        raise fail("NETWORK_ERROR", "response object is not readable")
    with closing(opened):
        return opened.read()


def decode_object(body: str | bytes, context: str) -> dict[str, JsonValue]:
    """Decode a JSON object body or fail with a stable error object."""
    try:
        value = _json_loads(body)
    except json.JSONDecodeError as exc:
        raise fail("BAD_JSON", f"{context}: invalid JSON response") from exc
    if not _is_dict(value):
        raise fail("BAD_JSON", f"{context}: response is not a JSON object")
    return value


def post_form(url: str, form: dict[str, str]) -> dict[str, JsonValue]:
    """POST an application/x-www-form-urlencoded body and decode the JSON reply."""
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, method="POST")  # noqa: S310
    return decode_object(read_response(req), "token endpoint")


def xdg_config() -> Path:
    """Return the XDG credential file path."""
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "yt" / "oauth.json"


def load_config() -> dict[str, str]:
    """Resolve credentials from the environment, then the XDG file."""
    keys = ("client_id", "client_secret", "refresh_token")
    env = {k: os.environ.get(f"YT_{k.upper()}", "") for k in keys}
    if all(env.values()):
        return env
    path = xdg_config()
    if path.is_file():
        data = decode_object(path.read_text(encoding="utf-8"), str(path))
        merged = {k: env[k] or (_opt_str(data.get(k)) or "") for k in keys}
        if all(merged.values()):
            return merged
    raise fail(
        "NO_CREDENTIALS",
        (
            "set YT_CLIENT_ID/YT_CLIENT_SECRET/YT_REFRESH_TOKEN"
            " or run: cli.py auth bootstrap"
        ),
        env_file=str(path),
    )


def api(
    path: str,
    method: str,
    token: str,
    body: dict[str, JsonValue] | None = None,
    params: dict[str, str] | None = None,
) -> dict[str, JsonValue]:
    """Call the YouTube Data API and decode the JSON response."""
    url = f"{API_BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)  # noqa: S310
    req.add_header("Authorization", f"Bearer {token}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        raw = read_response(req)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise fail(
            "API_ERROR", f"{method} {path}: HTTP {exc.code}", response=detail
        ) from exc
    return decode_object(raw, f"{method} {path}") if raw else {}


def access_token(cfg: dict[str, str]) -> str:
    """Exchange the refresh token for a fresh access token."""
    try:
        payload = post_form(
            TOKEN_URL,
            {
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "refresh_token": cfg["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise fail(
            "TOKEN_REFRESH_FAILED",
            (
                "refresh token rejected; re-run auth bootstrap"
                " (revoked, expired, or testing-mode app)"
            ),
            response=detail,
        ) from exc
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise fail("TOKEN_REFRESH_FAILED", "token endpoint returned no access_token")
    return token


def cmd_auth_bootstrap(args: _Args) -> None:
    """Run the two-step headless consent flow."""
    client_id = os.environ.get("YT_CLIENT_ID", "")
    client_secret = os.environ.get("YT_CLIENT_SECRET", "")
    if not args.redirect_url:
        if not client_id:
            raise fail(
                "NO_CLIENT_ID", "export YT_CLIENT_ID (and YT_CLIENT_SECRET) first"
            )
        query = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "scope": SCOPE,
                "access_type": "offline",
                "prompt": "consent",
            }
        )
        emit(
            {
                "ok": True,
                "step": "authorize",
                "instructions": [
                    "open the URL on ANY device with a browser (phone is fine)",
                    "authorize with the Google account owning the channel",
                    "the browser redirects to a dead localhost URL; that is expected",
                    (
                        "copy the FULL address-bar URL and re-run:"
                        " cli.py auth bootstrap --redirect-url 'URL'"
                    ),
                ],
                "url": f"{AUTH_URL}?{query}",
            }
        )
        return
    parsed = urllib.parse.urlparse(args.redirect_url)
    code = urllib.parse.parse_qs(parsed.query).get("code", [""])[0]
    if not code:
        raise fail("NO_CODE", "redirect URL contains no code parameter")
    try:
        tokens = post_form(
            TOKEN_URL,
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise fail(
            "CODE_EXCHANGE_FAILED", "authorization code rejected", response=detail
        ) from exc
    refresh = tokens.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        raise fail(
            "NO_REFRESH_TOKEN",
            (
                "no refresh token returned; consent may already exist"
                " (prompt=consent is set, so re-check account choice)"
            ),
        )
    record = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh,
    }
    path = xdg_config()
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    emit(
        {
            "ok": True,
            "step": "done",
            "stored_at": str(path),
            "env": {
                "YT_CLIENT_ID": client_id,
                "YT_CLIENT_SECRET": client_secret,
                "YT_REFRESH_TOKEN": refresh,
            },
            "warning": (
                "production-mode consent screen required;"
                " testing-mode tokens expire in 7 days"
            ),
        }
    )


def cmd_auth_status() -> None:
    """Verify credentials by fetching the owning channel."""
    cfg = load_config()
    token = access_token(cfg)
    data = api("channels", "GET", token, params={"part": "snippet", "mine": "true"})
    title: str | None = None
    items = data.get("items")
    if isinstance(items, list) and items:
        snippet = _as_dict(_as_dict(items[0]).get("snippet"))
        title = _opt_str(snippet.get("title"))
    emit({"ok": True, "channel": title})


def paged(token: str, path: str, params: dict[str, str]) -> list[dict[str, JsonValue]]:
    """Collect every page of a list endpoint."""
    items: list[dict[str, JsonValue]] = []
    page = ""
    while True:
        if page:
            params["pageToken"] = page
        data = api(path, "GET", token, params=params)
        raw_items = data.get("items")
        if isinstance(raw_items, list):
            items.extend(item for item in raw_items if isinstance(item, dict))
        next_page = data.get("nextPageToken")
        page = next_page if isinstance(next_page, str) else ""
        if not page:
            return items


def item_title(item: dict[str, JsonValue]) -> str:
    """Return the snippet title of a playlist item, or an empty string."""
    return _opt_str(_as_dict(item.get("snippet")).get("title")) or ""


def playlist_summary(item: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Project one playlist item into its stable summary fields."""
    return {
        "id": _opt_str(item.get("id")) or "",
        "title": item_title(item),
        "privacy": _opt_str(_as_dict(item.get("status")).get("privacyStatus")),
    }


def cmd_playlists_list() -> None:
    """List the authenticated user's playlists."""
    token = access_token(load_config())
    items = paged(
        token,
        "playlists",
        {"part": "snippet,status", "mine": "true", "maxResults": "50"},
    )
    emit({"ok": True, "playlists": [playlist_summary(it) for it in items]})


def arguments() -> _Args:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    auth = sub.add_parser("auth")
    asub = auth.add_subparsers(dest="sub", required=True)
    boot = asub.add_parser(
        "bootstrap", help="one-time headless consent; prints env vars"
    )
    _ = boot.add_argument("--redirect-url", default=None)
    _ = asub.add_parser("status", help="verify credentials against the API")
    pl = sub.add_parser("playlists")
    psub = pl.add_subparsers(dest="sub", required=True)
    _ = psub.add_parser("list")
    return parser.parse_args(namespace=_Args())


def main() -> None:
    """Dispatch the parsed subcommand."""
    args = arguments()
    if args.command == "auth" and args.sub == "bootstrap":
        cmd_auth_bootstrap(args)
    elif args.command == "auth" and args.sub == "status":
        cmd_auth_status()
    elif args.command == "playlists" and args.sub == "list":
        cmd_playlists_list()


if __name__ == "__main__":
    main()
