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
import re
import ssl
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
VIDEO_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{11}")
VIDEO_BATCH = 50


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


def _opt_int(value: JsonValue) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class _Args(argparse.Namespace):
    """Parsed command-line arguments."""

    command: str = ""
    sub: str = ""
    manifest: str | None = None
    target: str | None = None
    file: str | None = None
    privacy: str = "private"
    redirect_url: str | None = None
    query: str = ""
    limit: int = 5

    def __init__(self) -> None:
        super().__init__()
        self.videos: list[str] = []


def ensure_ca_bundle() -> None:
    """Point urllib at a CA bundle when the platform default store is absent.

    Foreign Python builds (uv standalone) on NixOS cannot find the system
    certificates because OpenSSL's compiled-in default paths do not match the
    distro layout. Honored only when SSL_CERT_FILE is unset; a no-op on macOS
    and conventional Linux distributions.
    """
    if os.environ.get("SSL_CERT_FILE"):
        return
    paths = ssl.get_default_verify_paths()
    if paths.cafile and Path(paths.cafile).exists():
        return
    for candidate in (
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/ssl/certs/ca-bundle.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
    ):
        if Path(candidate).exists():
            os.environ["SSL_CERT_FILE"] = candidate
            return


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


def cmd_auth_status(_args: _Args) -> None:
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


def playlist_items(token: str, pid: str) -> list[dict[str, JsonValue]]:
    """Collect every item of a playlist."""
    return paged(
        token,
        "playlistItems",
        {"part": "snippet", "playlistId": pid, "maxResults": "50"},
    )


def item_video_id(item: dict[str, JsonValue]) -> str | None:
    """Return the video id a playlist item points at, when present."""
    snippet = _as_dict(item.get("snippet"))
    return _opt_str(_as_dict(snippet.get("resourceId")).get("videoId"))


def normalize_video_id(raw: str) -> str | None:
    """Extract a bare 11-character video id from an id or a supported URL.

    Accepted forms: bare id, youtube.com/watch?v=ID, youtu.be/ID, and
    youtube.com/shorts/ID; extra query parameters are ignored.
    """
    text = raw.strip()
    if VIDEO_ID_PATTERN.fullmatch(text):
        return text
    parsed = urllib.parse.urlparse(text)
    host = parsed.netloc.lower()
    candidate = ""
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        if parsed.path == "/watch":
            candidate = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith("/shorts/"):
            candidate = parsed.path.removeprefix("/shorts/").split("/")[0]
    return candidate if VIDEO_ID_PATTERN.fullmatch(candidate) else None


def parse_video_ids(raws: Sequence[str]) -> list[str]:
    """Normalize every input to a bare video id or fail before any API call."""
    ids: list[str] = []
    for raw in raws:
        vid = normalize_video_id(raw)
        if vid is None:
            raise fail(
                "INVALID_VIDEO",
                (
                    f"cannot parse a video id from {raw!r}; accepted forms:"
                    " bare id, youtube.com/watch?v=ID, youtu.be/ID,"
                    " youtube.com/shorts/ID"
                ),
            )
        ids.append(vid)
    return ids


def find_playlist(token: str, target: str) -> dict[str, JsonValue]:
    """Resolve one of the user's playlists by exact id or title prefix."""
    mine = paged(
        token,
        "playlists",
        {"part": "snippet,status", "mine": "true", "maxResults": "50"},
    )
    for it in mine:
        if _opt_str(it.get("id")) == target or item_title(it).startswith(target):
            return it
    raise fail("NOT_FOUND", f"no playlist matching {target!r}")


def playlist_ref(playlist: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Project the resolved playlist into the id/title pair outputs carry."""
    return {
        "id": _opt_str(playlist.get("id")) or "",
        "title": item_title(playlist),
    }


def cmd_playlists_list(_args: _Args) -> None:
    """List the authenticated user's playlists."""
    token = access_token(load_config())
    items = paged(
        token,
        "playlists",
        {"part": "snippet,status", "mine": "true", "maxResults": "50"},
    )
    emit({"ok": True, "playlists": [playlist_summary(it) for it in items]})


def read_manifest(path: str) -> dict[str, list[str]]:
    """Group video IDs by playlist title; columns: title<TAB>video_id[<TAB>note]."""
    groups: dict[str, list[str]] = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        title, video_id, *_rest = line.split("\t")
        groups.setdefault(title.strip(), []).append(video_id.strip())
    return groups


def ensure_playlist(
    token: str, title: str, by_title: dict[str, str], privacy: str
) -> str:
    """Return the id of the named playlist, creating it when missing."""
    pid = by_title.get(title)
    if pid is not None:
        return pid
    created = api(
        "playlists",
        "POST",
        token,
        params={"part": "snippet,status"},
        body={
            "snippet": {"title": title, "description": ""},
            "status": {"privacyStatus": privacy},
        },
    )
    created_id = _opt_str(created.get("id"))
    if created_id is None:
        raise fail("API_ERROR", f"created playlist {title!r} has no id")
    return created_id


def existing_video_ids(token: str, pid: str) -> set[str]:
    """Collect the video IDs already present in a playlist."""
    have: set[str] = set()
    for it in playlist_items(token, pid):
        vid = item_video_id(it)
        if vid is not None:
            have.add(vid)
    return have


def insert_video(token: str, pid: str, vid: str) -> None:
    """Insert one video into a playlist."""
    _ = api(
        "playlistItems",
        "POST",
        token,
        params={"part": "snippet"},
        body={
            "snippet": {
                "playlistId": pid,
                "resourceId": {"kind": "youtube#video", "videoId": vid},
            }
        },
    )


def cmd_playlists_apply(args: _Args) -> None:
    """Create missing playlists and insert missing videos, idempotently."""
    if not args.manifest:
        raise fail(
            "NO_MANIFEST",
            "pass a manifest TSV: playlist_title<TAB>video_id[<TAB>note]",
        )
    token = access_token(load_config())
    wanted = read_manifest(args.manifest)
    mine = paged(
        token,
        "playlists",
        {"part": "snippet,status", "mine": "true", "maxResults": "50"},
    )
    by_title: dict[str, str] = {}
    for it in mine:
        pid = _opt_str(it.get("id"))
        title = item_title(it)
        if pid is not None and title:
            by_title[title] = pid
    results: list[dict[str, JsonValue]] = []
    for title, video_ids in sorted(wanted.items()):
        pid = ensure_playlist(token, title, by_title, args.privacy)
        have = existing_video_ids(token, pid)
        added: list[str] = []
        for vid in video_ids:
            if vid in have:
                continue
            insert_video(token, pid, vid)
            added.append(vid)
        results.append(
            {
                "title": title,
                "id": pid,
                "added": added,
                "skipped": len(video_ids) - len(added),
            }
        )
    emit({"ok": True, "results": results})


def cmd_playlists_notes(args: _Args) -> None:
    """Replace a playlist description with file contents."""
    target = args.target
    file = args.file
    if not target or not file:
        raise fail(
            "MISSING_ARGS",
            "need playlist id/title prefix and --file with the notes text",
        )
    token = access_token(load_config())
    notes = Path(file).read_text(encoding="utf-8")
    match = find_playlist(token, target)
    snippet = _as_dict(match.get("snippet"))
    snippet["description"] = notes
    _ = api(
        "playlists",
        "PUT",
        token,
        params={"part": "snippet"},
        body={"id": _opt_str(match.get("id")) or "", "snippet": snippet},
    )
    emit(
        {
            "ok": True,
            "updated": _opt_str(snippet.get("title")) or "",
            "id": _opt_str(match.get("id")) or "",
        }
    )


def require_target(args: _Args) -> str:
    """Return the playlist target argument or fail with a stable error."""
    if not args.target:
        raise fail("MISSING_ARGS", "need a playlist id or title prefix")
    return args.target


def cmd_playlists_items(args: _Args) -> None:
    """List a playlist's contents: position, video id, title."""
    target = require_target(args)
    token = access_token(load_config())
    playlist = find_playlist(token, target)
    pid = _opt_str(playlist.get("id")) or ""
    entries: list[dict[str, JsonValue]] = []
    for it in playlist_items(token, pid):
        snippet = _as_dict(it.get("snippet"))
        entries.append(
            {
                "position": _opt_int(snippet.get("position")),
                "id": item_video_id(it),
                "title": _opt_str(snippet.get("title")),
            }
        )
    emit({"ok": True, "playlist": playlist_ref(playlist), "items": entries})


def cmd_playlists_add(args: _Args) -> None:
    """Insert videos into a playlist, skipping ones already present."""
    target = require_target(args)
    ids = parse_video_ids(args.videos)
    token = access_token(load_config())
    playlist = find_playlist(token, target)
    pid = _opt_str(playlist.get("id")) or ""
    have = existing_video_ids(token, pid)
    added: list[str] = []
    skipped: list[str] = []
    for vid in ids:
        if vid in have:
            skipped.append(vid)
            continue
        insert_video(token, pid, vid)
        have.add(vid)
        added.append(vid)
    emit(
        {
            "ok": True,
            "playlist": playlist_ref(playlist),
            "added": added,
            "skipped": skipped,
        }
    )


def cmd_playlists_remove(args: _Args) -> None:
    """Delete the playlist items pointing at each given video."""
    target = require_target(args)
    ids = parse_video_ids(args.videos)
    token = access_token(load_config())
    playlist = find_playlist(token, target)
    pid = _opt_str(playlist.get("id")) or ""
    by_video: dict[str, list[str]] = {}
    for it in playlist_items(token, pid):
        item_id = _opt_str(it.get("id"))
        vid = item_video_id(it)
        if item_id and vid:
            by_video.setdefault(vid, []).append(item_id)
    removed: list[str] = []
    missing: list[str] = []
    for vid in ids:
        item_ids = by_video.get(vid)
        if not item_ids:
            missing.append(vid)
            continue
        for item_id in item_ids:
            _ = api("playlistItems", "DELETE", token, params={"id": item_id})
        removed.append(vid)
    emit(
        {
            "ok": True,
            "playlist": playlist_ref(playlist),
            "removed": removed,
            "not_found": missing,
        }
    )


def video_summary(item: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Project one videos.list item into its stable summary fields."""
    snippet = _as_dict(item.get("snippet"))
    details = _as_dict(item.get("contentDetails"))
    return {
        "id": _opt_str(item.get("id")),
        "title": _opt_str(snippet.get("title")),
        "channel": _opt_str(snippet.get("channelTitle")),
        "duration": _opt_str(details.get("duration")),
        "publishedAt": _opt_str(snippet.get("publishedAt")),
    }


def cmd_videos_info(args: _Args) -> None:
    """Fetch snippet and contentDetails for videos, 50 ids per API call."""
    ids = parse_video_ids(args.videos)
    token = access_token(load_config())
    videos: list[dict[str, JsonValue]] = []
    for start in range(0, len(ids), VIDEO_BATCH):
        chunk = ids[start : start + VIDEO_BATCH]
        data = api(
            "videos",
            "GET",
            token,
            params={
                "part": "snippet,contentDetails",
                "id": ",".join(chunk),
                "maxResults": str(VIDEO_BATCH),
            },
        )
        raw_items = data.get("items")
        if isinstance(raw_items, list):
            videos.extend(
                video_summary(item) for item in raw_items if isinstance(item, dict)
            )
    emit({"ok": True, "videos": videos})


def cmd_search(args: _Args) -> None:
    """Search videos; each call costs 100 quota units."""
    limit = max(1, min(args.limit, 25))
    token = access_token(load_config())
    data = api(
        "search",
        "GET",
        token,
        params={
            "part": "snippet",
            "type": "video",
            "q": args.query,
            "maxResults": str(limit),
        },
    )
    results: list[dict[str, JsonValue]] = []
    raw_items = data.get("items")
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            snippet = _as_dict(item.get("snippet"))
            results.append(
                {
                    "id": _opt_str(_as_dict(item.get("id")).get("videoId")),
                    "title": _opt_str(snippet.get("title")),
                    "channel": _opt_str(snippet.get("channelTitle")),
                    "publishedAt": _opt_str(snippet.get("publishedAt")),
                }
            )
    emit({"ok": True, "results": results})


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
    appl = psub.add_parser(
        "apply", help="create/fill playlists from a manifest TSV (idempotent)"
    )
    _ = appl.add_argument("manifest")
    _ = appl.add_argument(
        "--privacy", default="private", choices=["private", "unlisted", "public"]
    )
    notes = psub.add_parser("notes", help="replace a playlist description")
    _ = notes.add_argument("target", help="playlist id or title prefix")
    _ = notes.add_argument("--file", required=True)
    items = psub.add_parser(
        "items", help="list a playlist's videos: position, video id, title"
    )
    _ = items.add_argument("target", help="playlist id or title prefix")
    addp = psub.add_parser(
        "add",
        help="add videos to a playlist, skipping ones already present",
        epilog=(
            "videos accept bare ids, youtube.com/watch?v=ID, youtu.be/ID,"
            " and youtube.com/shorts/ID forms; each insert costs 50 quota units"
        ),
    )
    _ = addp.add_argument("target", help="playlist id or title prefix")
    _ = addp.add_argument("videos", nargs="+", help="video ids or URLs")
    rem = psub.add_parser(
        "remove",
        help="remove videos from a playlist",
        epilog=(
            "videos accept bare ids, youtube.com/watch?v=ID, youtu.be/ID,"
            " and youtube.com/shorts/ID forms; each delete costs 50 quota units"
        ),
    )
    _ = rem.add_argument("target", help="playlist id or title prefix")
    _ = rem.add_argument("videos", nargs="+", help="video ids or URLs")
    vid = sub.add_parser("videos")
    vsub = vid.add_subparsers(dest="sub", required=True)
    info = vsub.add_parser(
        "info",
        help="video metadata: title, channel, duration, publishedAt",
        epilog="ids are batched 50 per API call; each call costs 1 quota unit",
    )
    _ = info.add_argument("videos", nargs="+", help="video ids or URLs")
    search = sub.add_parser(
        "search",
        help="search videos by query text",
        epilog=(
            "quota warning: each search call costs 100 units of the daily"
            " project quota (default 10000 units/day); prefer videos info"
            " when ids are already known"
        ),
    )
    _ = search.add_argument("query", help="search query text")
    _ = search.add_argument(
        "--limit",
        type=int,
        default=5,
        help="max results, default 5; values above 25 are capped to 25",
    )
    return parser.parse_args(namespace=_Args())


COMMANDS: dict[tuple[str, str], Callable[[_Args], None]] = {
    ("auth", "bootstrap"): cmd_auth_bootstrap,
    ("auth", "status"): cmd_auth_status,
    ("playlists", "list"): cmd_playlists_list,
    ("playlists", "apply"): cmd_playlists_apply,
    ("playlists", "notes"): cmd_playlists_notes,
    ("playlists", "items"): cmd_playlists_items,
    ("playlists", "add"): cmd_playlists_add,
    ("playlists", "remove"): cmd_playlists_remove,
    ("videos", "info"): cmd_videos_info,
    ("search", ""): cmd_search,
}


def main() -> None:
    """Dispatch the parsed subcommand."""
    ensure_ca_bundle()
    args = arguments()
    handler = COMMANDS.get((args.command, args.sub))
    if handler is None:
        raise fail("UNKNOWN_COMMAND", f"unhandled command {args.command!r}")
    handler(args)


if __name__ == "__main__":
    main()
