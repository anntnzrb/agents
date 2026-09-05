#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Browse and search Reddit via the public JSON API."""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.response
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable

USAGE = (
    "usage: reddit <browse|search|post|post-url|user|user-posts|user-comments|"
    + "user-analysis|explain> ..."
)
RAW_FLAG = "raw=1"

PREVIEW_CAP = 500
SELF_PREVIEW_CAP = 240
_MIN_QUOTED_LEN = 2
_MIN_POST_ARGS = 2

JsonValue = (
    dict[str, "JsonValue"] | Sequence["JsonValue"] | str | int | float | bool | None
)

NETWORK_SECURITY_MARKER = "blocked by network security"
BROWSE_SORTS = frozenset({"hot", "new", "top", "rising", "controversial"})
TIME_RANGES = frozenset({"day", "week", "month", "year", "all"})

LISTING_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "subreddit",
    "author",
    "score",
    "num_comments",
    "url",
    "permalink",
    "created_utc",
    "flair",
    "selftext_preview",
    "over_18",
    "is_self",
)
_UNKNOWN_TERM_DEFINITION = (
    "Unknown term in the built-in glossary. "
    + "Search Reddit or the web for current community usage."
)

COMMENT_FIELDS: tuple[str, ...] = (
    "id",
    "author",
    "score",
    "body",
    "created_utc",
    "permalink",
    "depth",
)
WHITESPACE_RE = re.compile(r"\s+")
HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
HTML_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")

GLOSSARY = {
    "karma": "Score derived from upvotes on posts and comments. Usually split into post karma and comment karma.",  # noqa: E501 - glossary prose
    "cake day": "The anniversary of a Reddit account creation date, shown with a cake icon.",  # noqa: E501 - glossary prose
    "ama": "Ask Me Anything. A Q&A thread where a person invites questions from the community.",  # noqa: E501 - glossary prose
    "op": "Original Poster: the author of the post or sometimes the parent comment under discussion.",  # noqa: E501 - glossary prose
    "tldr": "Too Long; Did Not Read. A short summary of a longer post or comment.",
    "eli5": "Explain Like I Am Five. A request or community norm for simple, plain-language explanations.",  # noqa: E501 - glossary prose
    "throwaway": "A temporary account, often created for privacy-sensitive posting.",
    "flair": "A label or badge attached to a post or username inside a subreddit.",
    "nsfw": "Not Safe For Work. Content that may be explicit or inappropriate in some settings.",  # noqa: E501 - glossary prose
    "crosspost": "A repost of the same submission into another subreddit using the native crosspost flow.",  # noqa: E501 - glossary prose
    "shadowban": "A state where activity is hidden or heavily limited without an obvious visible ban message.",  # noqa: E501 - glossary prose
    "modmail": "Shared moderator inbox for communication between subreddit mods and users.",  # noqa: E501 - glossary prose
}


# ---------- env loading ----------


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
    """Load the Reddit user agent from env files unless already exported."""
    skill_dir = Path(__file__).resolve().parents[1]
    candidates: list[Path | None] = []
    if os.environ.get("REDDIT_ENV_FILE"):
        candidates.append(Path(os.environ["REDDIT_ENV_FILE"]).expanduser())
    candidates.append(skill_dir / ".env")
    if os.environ.get("SKILLS_DIR"):
        candidates.append(
            Path(os.environ["SKILLS_DIR"]).expanduser() / "reddit" / ".env",
        )
    candidates.append(ancestor_env("reddit"))
    for candidate in candidates:
        if candidate is not None and parse_env_file(candidate):
            return


# ---------- arg helpers ----------


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


def alias_pair(pair: str) -> str:
    """Rewrite a legacy option alias to its canonical key."""
    aliases = {
        "time=": "t=",
        "comment_limit=": "limit=",
        "comment_sort=": "sort=",
        "comment_depth=": "depth=",
    }
    for old, new in aliases.items():
        if pair.startswith(old):
            return f"{new}{pair[len(old) :]}"
    return pair


def consume_raw_flag(args: list[str]) -> tuple[bool, list[str]]:
    """Split the raw output flag from command arguments."""
    raw_mode = RAW_FLAG in args
    return raw_mode, [a for a in args if a != RAW_FLAG]


def split_limit_extra(
    args: list[str],
    default_limit: str,
) -> tuple[str, list[tuple[str, str]]]:
    """Split an optional limit from extra key=value arguments."""
    limit = default_limit
    extra: list[tuple[str, str]] = []
    for raw in args:
        aliased = alias_pair(raw)
        if aliased.startswith("limit="):
            limit = aliased.removeprefix("limit=")
        else:
            extra.extend(pairs([aliased]))
    return limit, extra


# ---------- output ----------


def json_print(payload: object) -> None:
    """Print a payload as compact JSON."""
    print(json.dumps(payload, separators=(",", ":")))


def _strip_html_preview(text: str) -> str:
    """Return a text-only preview with markup removed and whitespace collapsed.

    Used for compact error envelopes so the stderr line never leaks raw markup like
    ``<html>`` or stray ``&amp;`` from upstream block pages.
    """
    if not text:
        return ""
    text = HTML_SCRIPT_RE.sub(" ", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return WHITESPACE_RE.sub(" ", text).strip()


def emit_error(
    *,
    status: int | None,
    message: str,
    body: bytes,
    kind: str | None = None,
) -> None:
    """Emit a compact error envelope to stderr."""
    body_bytes = len(body)
    text = body.decode("utf-8", errors="replace") if body else ""
    preview_text = _strip_html_preview(text)
    if NETWORK_SECURITY_MARKER in preview_text.lower():
        kind = "network_security_block"
    truncated = len(preview_text) > PREVIEW_CAP
    preview = preview_text[:PREVIEW_CAP]
    error: dict[str, JsonValue] = {
        "provider": "reddit",
        "status": status,
        "message": message,
        "body_bytes": body_bytes,
        "body_preview": preview,
        "body_truncated": truncated,
    }
    if kind is not None:
        error["kind"] = kind
    payload: dict[str, JsonValue] = {"error": error}
    print(json.dumps(payload, separators=(",", ":")), file=sys.stderr)


def usage_error(message: str) -> int:
    """Print a usage error and return the usage exit code."""
    print(message, file=sys.stderr)
    return 2


# ---------- HTTP ----------


def _read_http_error(exc: urllib.error.HTTPError) -> bytes:
    """Read an HTTP error body and release the error response."""
    try:
        return exc.read()
    finally:
        exc.close()


def request_get(
    url: str,
    params: list[tuple[str, str]],
    user_agent: str,
    *,
    raw: bool,
) -> tuple[int, bytes]:
    """Fetch a URL and return its exit code and body."""
    if params:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        opened = cast("object", urllib.request.urlopen(req, timeout=60))
        with cast("urllib.response.addinfourl", opened) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        emit_error(
            status=exc.code,
            message=f"Reddit returned HTTP {exc.code}",
            body=_read_http_error(exc),
        )
        return 22, b""
    except urllib.error.URLError as exc:
        emit_error(
            status=None,
            message=f"Reddit network error: {exc.reason}",
            body=b"",
            kind="network_error",
        )
        return 1, b""
    if raw:
        _ = sys.stdout.buffer.write(body)
    return 0, body


def fetch_json(
    url: str,
    params: list[tuple[str, str]],
    user_agent: str,
) -> tuple[int, JsonValue]:
    """Fetch a URL and decode its JSON body."""
    code, body = request_get(url, params, user_agent, raw=False)
    if code != 0:
        return code, None
    try:
        return 0, cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        emit_error(
            status=None,
            message=f"Reddit returned invalid JSON: {exc}",
            body=body,
            kind="invalid_json",
        )
        return 1, None


# ---------- validation (testable hooks) ----------


def normalize_term(term: str | None) -> str:
    """Normalize a glossary term."""
    if term is None:
        msg = "term must be non-empty"
        raise ValueError(msg)
    collapsed = WHITESPACE_RE.sub(" ", term).strip().lower()
    if not collapsed:
        msg = "term must be non-empty"
        raise ValueError(msg)
    return collapsed


def validate_url(url: str) -> str:
    """Validate an http(s) URL."""
    if not url or not HTTP_URL_RE.match(url.strip()):
        msg = "url must use http:// or https:// scheme"
        raise ValueError(msg)
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        msg = "url must use http:// or https:// scheme"
        raise ValueError(msg)
    return url.strip()


def validate_time_range(value: str) -> str:
    """Validate a time range value."""
    if value not in TIME_RANGES:
        msg = f"time_range must be one of {sorted(TIME_RANGES)} (got {value!r})"
        raise ValueError(msg)
    return value


def parse_subreddits(value: str) -> list[str]:
    """Parse a subreddits= JSON list option."""
    msg = "subreddits= must be a JSON list of non-empty strings"
    try:
        parsed = cast("object", json.loads(value))
    except json.JSONDecodeError as exc:
        raise ValueError(msg) from exc
    if not isinstance(parsed, list):
        raise TypeError(msg)
    items = cast("list[JsonValue]", parsed)
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise TypeError(msg)
        stripped = item.strip()
        if not stripped:
            raise ValueError(msg)
        out.append(stripped)
    return out


def parse_non_negative_int(name: str, value: str) -> int:
    """Parse a non-negative integer option."""
    try:
        parsed = int(value)
    except ValueError as exc:
        msg = f"{name} must be an integer"
        raise ValueError(msg) from exc
    if parsed < 0:
        msg = f"{name} must be >= 0"
        raise ValueError(msg)
    return parsed


def validate_browse_args(
    args: list[str],
) -> tuple[str, str, list[str]]:
    """Parse `browse` args.

    Returns (subreddit, sort, remaining_args). Raises ValueError on usage errors.
    """
    if not args:
        msg = "usage: reddit browse <subreddit> [sort] [key=value ...]"
        raise ValueError(msg)
    subreddit = args[0]
    rest = args[1:]
    if not rest:
        return subreddit, "hot", []
    if "=" not in rest[0]:
        if rest[0] not in BROWSE_SORTS:
            msg = f"browse sort must be one of {sorted(BROWSE_SORTS)} (got {rest[0]!r})"
            raise ValueError(msg)
        sort = rest[0]
        rest = rest[1:]
    else:
        sort = "hot"
    for item in rest:
        if "=" not in item:
            msg = f"unexpected positional argument after key=value: {item!r}"
            raise ValueError(msg)
    return subreddit, sort, rest


def resolve_time(extra: list[tuple[str, str]]) -> str:
    """Resolve the time range from extra arguments."""
    for key, value in extra:
        if key in {"t", "time"}:
            return value
    return "all"


def safe_int(value: str, default: int) -> int:
    """Parse an int, returning a default on invalid input."""
    try:
        return int(value)
    except ValueError:
        return default


# ---------- projections ----------


def compact_selftext(text: str | None) -> str | None:
    """Compact selftext to a short preview."""
    if not text:
        return None
    text = WHITESPACE_RE.sub(" ", text).strip()
    if not text:
        return None
    if len(text) > SELF_PREVIEW_CAP:
        return text[:SELF_PREVIEW_CAP] + "…"
    return text


def compact_listing_result(data: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Compact a listing result to stable fields."""
    author = data.get("author")
    out: dict[str, JsonValue] = {
        "id": data.get("id"),
        "title": data.get("title"),
        "subreddit": data.get("subreddit"),
        "author": None if author in (None, "[deleted]") else author,
        "score": data.get("score"),
        "num_comments": data.get("num_comments"),
        "url": data.get("url"),
        "permalink": data.get("permalink"),
        "created_utc": data.get("created_utc"),
    }
    flair = data.get("link_flair_text")
    if flair:
        out["flair"] = flair
    selftext = data.get("selftext")
    preview = compact_selftext(selftext if isinstance(selftext, str) else None)
    if preview:
        out["selftext_preview"] = preview
    if "over_18" in data:
        out["over_18"] = data.get("over_18")
    if "is_self" in data:
        out["is_self"] = data.get("is_self")
    return out


def compact_comment(data: dict[str, JsonValue], depth: int) -> dict[str, JsonValue]:
    """Compact a comment to stable fields."""
    author = data.get("author")
    body = data.get("body")
    return {
        "id": data.get("id"),
        "author": None if author in (None, "[deleted]") else author,
        "score": data.get("score"),
        "body": WHITESPACE_RE.sub(" ", str(body)).strip() if body else None,
        "created_utc": data.get("created_utc"),
        "permalink": data.get("permalink"),
        "depth": depth,
    }


def walk_comments(node: JsonValue, depth: int, out: list[dict[str, JsonValue]]) -> None:
    """Walk a comment tree in order, collecting compact comments."""
    if not isinstance(node, dict):
        return
    kind = node.get("kind")
    if kind == "more":
        return
    if kind == "Listing":
        data = node.get("data", {})
        if isinstance(data, dict):
            children = data.get("children", [])
            if isinstance(children, list):
                for child in children:
                    walk_comments(child, depth, out)
        return
    data = node.get("data")
    if not isinstance(data, dict):
        return
    if data.get("body"):
        out.append(compact_comment(data, depth))
    replies = data.get("replies")
    if isinstance(replies, dict):
        walk_comments(replies, depth + 1, out)


def listing_children(payload: JsonValue | None) -> list[dict[str, JsonValue]]:
    """Collect listing children from a payload."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return []
    children = data.get("children", [])
    if not isinstance(children, list):
        return []
    return [c for c in children if isinstance(c, dict)]


def listing_data(
    payload: JsonValue, limit: int, cutoff: float
) -> list[dict[str, JsonValue]]:
    """Collect listing rows up to a limit and time cutoff."""
    rows: list[dict[str, JsonValue]] = []
    for child in listing_children(payload):
        data = child.get("data", {})
        if not isinstance(data, dict):
            continue
        created_raw = data.get("created_utc")
        if isinstance(created_raw, (int, str, float)):
            created = float(created_raw)
        else:
            created = 0.0
        if cutoff and created < cutoff:
            continue
        rows.append(data)
    return rows[:limit]


def compact_listing_envelope(
    *,
    kind: str,
    meta: dict[str, JsonValue],
    payload: JsonValue,
    limit: int,
    cutoff: float = 0.0,
) -> dict[str, JsonValue]:
    """Build a compact listing envelope."""
    rows = listing_data(payload, limit, cutoff)
    return {
        "type": kind,
        **meta,
        "count": len(rows),
        "results": [compact_listing_result(r) for r in rows],
    }


def compact_post_envelope(payload: JsonValue) -> dict[str, JsonValue]:
    """Build a compact post envelope with comments."""
    if not isinstance(payload, list) or not payload:
        return {"type": "post", "post": {}, "comments": []}
    post_payload = payload[0]
    comments_payload = payload[1] if len(payload) > 1 else None
    post_children = listing_children(post_payload)
    primary: dict[str, JsonValue] = {}
    if post_children:
        primary_data = post_children[0].get("data", {})
        if isinstance(primary_data, dict):
            primary = primary_data
    post: dict[str, JsonValue] = compact_listing_result(primary) if primary else {}
    comments: list[dict[str, JsonValue]] = []
    for child in listing_children(comments_payload):
        walk_comments(child, 0, comments)
    return {"type": "post", "post": post, "comments": comments}


def compact_user_profile(payload: JsonValue) -> dict[str, JsonValue]:
    """Compact a user profile to stable fields."""
    data: JsonValue = payload.get("data", {}) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        data = {}
    link_raw = data.get("link_karma")
    link = int(link_raw) if isinstance(link_raw, (int, str, float)) else 0
    comment_raw = data.get("comment_karma")
    comment = int(comment_raw) if isinstance(comment_raw, (int, str, float)) else 0
    return {
        "name": data.get("name"),
        "created_utc": data.get("created_utc"),
        "link_karma": data.get("link_karma"),
        "comment_karma": data.get("comment_karma"),
        "total_karma": link + comment,
        "verified": data.get("verified"),
        "is_gold": data.get("is_gold"),
        "is_mod": data.get("is_mod"),
    }


def compact_user_envelope(username: str, payload: JsonValue) -> dict[str, JsonValue]:
    """Build a compact user envelope."""
    return {
        "type": "user",
        "user": username,
        "profile": compact_user_profile(payload),
    }


# ---------- explain ----------


def explain_term(term: str) -> str:
    """Return the glossary definition for `term`, or a default 'unknown' message.

    Raises ValueError if the term is empty/whitespace-only.
    """
    normalized = normalize_term(term)
    candidates = [normalized, normalized.replace("-", " ")]
    for candidate in candidates:
        if candidate in GLOSSARY:
            return GLOSSARY[candidate]
    return _UNKNOWN_TERM_DEFINITION


def explain(term: str) -> int:
    """Print the glossary definition for a term."""
    try:
        normalized = normalize_term(term)
    except ValueError as exc:
        return usage_error(f"reddit explain: {exc}")
    candidates = [normalized, normalized.replace("-", " ")]
    canonical = next((c for c in candidates if c in GLOSSARY), normalized)
    definition = GLOSSARY.get(canonical, _UNKNOWN_TERM_DEFINITION)
    json_print({"term": canonical, "definition": definition})
    return 0


# ---------- user-analysis ----------


def cutoff_for(range_name: str, now: float) -> float:
    """Return the epoch cutoff for a time range."""
    return {
        "day": now - 86_400,
        "week": now - 604_800,
        "month": now - 2_592_000,
        "year": now - 31_536_000,
        "all": 0,
    }[range_name]


def _compact_analysis_comment(c: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Compact one user-analysis comment row."""
    author = c.get("author")
    body = c.get("body")
    return {
        "id": c.get("id"),
        "subreddit": c.get("subreddit"),
        "author": None if author in (None, "[deleted]") else author,
        "score": c.get("score"),
        "body_preview": compact_selftext(body if isinstance(body, str) else None),
        "permalink": c.get("permalink"),
        "created_utc": c.get("created_utc"),
    }


def user_analysis(
    base_url: str,
    user_agent: str,
    username: str,
    args: list[str],
) -> int:
    """Analyze a user's recent activity and emit a compact envelope."""
    posts_limit = 10
    comments_limit = 10
    time_range = "month"
    top_limit = 10
    fetch_limit = 100
    for pair in args:
        try:
            if pair.startswith("posts_limit="):
                posts_limit = parse_non_negative_int(
                    "posts_limit",
                    pair.removeprefix("posts_limit="),
                )
            elif pair.startswith("comments_limit="):
                comments_limit = parse_non_negative_int(
                    "comments_limit",
                    pair.removeprefix("comments_limit="),
                )
            elif pair.startswith("time_range="):
                time_range = validate_time_range(pair.removeprefix("time_range="))
            elif pair.startswith("top_subreddits_limit="):
                top_limit = parse_non_negative_int(
                    "top_subreddits_limit",
                    pair.removeprefix("top_subreddits_limit="),
                )
            elif pair == RAW_FLAG:
                continue
            else:
                detail = f"{pair!r}"
                return usage_error(
                    "reddit user-analysis: unknown user-analysis argument: " + detail,
                )
        except ValueError as exc:
            return usage_error(f"reddit user-analysis: {exc}")

    fetched: list[JsonValue] = []
    for path, params in [
        (f"/user/{username}/about.json", []),
        (f"/user/{username}/submitted.json", [("limit", str(fetch_limit))]),
        (f"/user/{username}/comments.json", [("limit", str(fetch_limit))]),
    ]:
        code, data = fetch_json(f"{base_url}{path}", params, user_agent)
        if code != 0:
            return code
        fetched.append(data)
    about, posts, comments = fetched
    now = time.time()
    cutoff = cutoff_for(time_range, now)
    recent_posts = listing_data(posts, posts_limit, cutoff)
    recent_comments = listing_data(comments, comments_limit, cutoff)
    top_source = listing_data(posts, 100, cutoff) + listing_data(comments, 100, cutoff)
    counts = Counter(
        str(item.get("subreddit"))
        for item in top_source
        if item.get("subreddit") is not None
    )
    top_subreddits = [
        {"subreddit": name, "count": count}
        for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[
            :top_limit
        ]
    ]
    json_print(
        {
            "type": "user-analysis",
            "user": username,
            "time_range": time_range,
            "profile": compact_user_profile(about),
            "posts": [compact_listing_result(p) for p in recent_posts],
            "comments": [_compact_analysis_comment(c) for c in recent_comments],
            "top_subreddits": top_subreddits,
        },
    )
    return 0


# ---------- commands ----------


def cmd_browse(base_url: str, user_agent: str, args: list[str]) -> int:
    """Browse a subreddit listing."""
    raw_mode, args = consume_raw_flag(args)
    try:
        subreddit, sort, rest = validate_browse_args(args)
    except ValueError as exc:
        return usage_error(f"reddit browse: {exc}")
    limit, extra = split_limit_extra(rest, "10")
    code, body = request_get(
        f"{base_url}/r/{subreddit}/{sort}.json",
        [("limit", limit), *extra],
        user_agent,
        raw=raw_mode,
    )
    if code != 0 or raw_mode:
        return code
    try:
        payload = cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        emit_error(
            status=None,
            message=f"Reddit returned invalid JSON: {exc}",
            body=body,
            kind="invalid_json",
        )
        return 1
    json_print(
        compact_listing_envelope(
            kind="listing",
            meta={
                "subreddit": subreddit,
                "sort": sort,
                "time": resolve_time(extra),
            },
            payload=payload,
            limit=safe_int(limit, 10),
        ),
    )
    return 0


def _parse_search_args(
    args: list[str],
) -> tuple[str, str, str, str, str, list[str], list[tuple[str, str]]]:
    """Parse search options, raising ValueError on usage errors."""
    sort = "relevance"
    time_range = "all"
    limit = "10"
    author = ""
    flair = ""
    subreddits: list[str] = []
    extra: list[tuple[str, str]] = []
    for pair in args:
        if pair.startswith("sort="):
            sort = pair.removeprefix("sort=")
        elif pair.startswith("t="):
            time_range = pair.removeprefix("t=")
        elif pair.startswith("time="):
            time_range = pair.removeprefix("time=")
        elif pair.startswith("limit="):
            limit = pair.removeprefix("limit=")
        elif pair.startswith("author="):
            author = pair.removeprefix("author=")
        elif pair.startswith("flair="):
            flair = pair.removeprefix("flair=")
        elif pair.startswith("subreddits="):
            subreddits.extend(parse_subreddits(pair.removeprefix("subreddits=")))
        else:
            extra.extend(pairs([pair]))
    return sort, time_range, limit, author, flair, subreddits, extra


def cmd_search(base_url: str, user_agent: str, args: list[str]) -> int:
    """Run a subreddit-aware search."""
    raw_mode, args = consume_raw_flag(args)
    if not args:
        return usage_error("usage: reddit search <query> [key=value ...]")
    query = args[0]
    try:
        sort, t, limit, author, flair, subreddits, extra = _parse_search_args(args[1:])
    except (ValueError, TypeError) as exc:
        return usage_error(f"reddit search: {exc}")
    full_query = query
    for subreddit in subreddits:
        full_query += f" subreddit:{subreddit}"
    if author:
        full_query += f" author:{author}"
    if flair:
        full_query += f' flair:"{flair}"'
    code, body = request_get(
        f"{base_url}/search.json",
        [
            ("q", full_query),
            ("sort", sort),
            ("t", t),
            ("limit", limit),
            *extra,
        ],
        user_agent,
        raw=raw_mode,
    )
    if code != 0 or raw_mode:
        return code
    try:
        payload = cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        emit_error(
            status=None,
            message=f"Reddit returned invalid JSON: {exc}",
            body=body,
            kind="invalid_json",
        )
        return 1
    json_print(
        compact_listing_envelope(
            kind="search",
            meta={"query": full_query, "sort": sort, "time": t},
            payload=payload,
            limit=safe_int(limit, 10),
        ),
    )
    return 0


def cmd_post(base_url: str, user_agent: str, args: list[str]) -> int:
    """Show a post with comments."""
    raw_mode, args = consume_raw_flag(args)
    if len(args) < _MIN_POST_ARGS:
        return usage_error("usage: reddit post <subreddit> <post_id> [key=value ...]")
    limit, extra = split_limit_extra(args[2:], "20")
    code, body = request_get(
        f"{base_url}/r/{args[0]}/comments/{args[1]}/.json",
        [("limit", limit), *extra],
        user_agent,
        raw=raw_mode,
    )
    if code != 0 or raw_mode:
        return code
    try:
        payload = cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        emit_error(
            status=None,
            message=f"Reddit returned invalid JSON: {exc}",
            body=body,
            kind="invalid_json",
        )
        return 1
    json_print(compact_post_envelope(payload))
    return 0


def cmd_post_url(_base_url: str, user_agent: str, args: list[str]) -> int:
    """Show a post from its URL."""
    raw_mode, args = consume_raw_flag(args)
    if not args:
        return usage_error("usage: reddit post-url <url> [key=value ...]")
    try:
        valid = validate_url(args[0])
    except ValueError as exc:
        return usage_error(f"reddit post-url: {exc}")
    clean_url = valid.split("?", 1)[0]
    if not clean_url.endswith(".json"):
        clean_url = clean_url.removesuffix(".json") + ".json"
    limit, extra = split_limit_extra(args[1:], "20")
    code, body = request_get(
        clean_url,
        [("limit", limit), *extra],
        user_agent,
        raw=raw_mode,
    )
    if code != 0 or raw_mode:
        return code
    try:
        payload = cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        emit_error(
            status=None,
            message=f"Reddit returned invalid JSON: {exc}",
            body=body,
            kind="invalid_json",
        )
        return 1
    json_print(compact_post_envelope(payload))
    return 0


def cmd_user(base_url: str, user_agent: str, args: list[str]) -> int:
    """Show a user profile."""
    raw_mode, args = consume_raw_flag(args)
    if not args:
        return usage_error("usage: reddit user <username>")
    code, body = request_get(
        f"{base_url}/user/{args[0]}/about.json",
        [],
        user_agent,
        raw=raw_mode,
    )
    if code != 0 or raw_mode:
        return code
    try:
        payload = cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        emit_error(
            status=None,
            message=f"Reddit returned invalid JSON: {exc}",
            body=body,
            kind="invalid_json",
        )
        return 1
    json_print(compact_user_envelope(args[0], payload))
    return 0


def cmd_user_posts(base_url: str, user_agent: str, args: list[str]) -> int:
    """Show recent posts by a user."""
    raw_mode, args = consume_raw_flag(args)
    if not args:
        return usage_error("usage: reddit user-posts <username> [key=value ...]")
    limit, extra = split_limit_extra(args[1:], "10")
    code, body = request_get(
        f"{base_url}/user/{args[0]}/submitted.json",
        [("limit", limit), *extra],
        user_agent,
        raw=raw_mode,
    )
    if code != 0 or raw_mode:
        return code
    try:
        payload = cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        emit_error(
            status=None,
            message=f"Reddit returned invalid JSON: {exc}",
            body=body,
            kind="invalid_json",
        )
        return 1
    json_print(
        compact_listing_envelope(
            kind="user-posts",
            meta={"user": args[0]},
            payload=payload,
            limit=safe_int(limit, 10),
        ),
    )
    return 0


def cmd_user_comments(base_url: str, user_agent: str, args: list[str]) -> int:
    """Show recent comments by a user."""
    raw_mode, args = consume_raw_flag(args)
    if not args:
        return usage_error("usage: reddit user-comments <username> [key=value ...]")
    limit, extra = split_limit_extra(args[1:], "10")
    code, body = request_get(
        f"{base_url}/user/{args[0]}/comments.json",
        [("limit", limit), *extra],
        user_agent,
        raw=raw_mode,
    )
    if code != 0 or raw_mode:
        return code
    try:
        payload = cast("JsonValue", json.loads(body))
    except json.JSONDecodeError as exc:
        emit_error(
            status=None,
            message=f"Reddit returned invalid JSON: {exc}",
            body=body,
            kind="invalid_json",
        )
        return 1
    json_print(
        compact_listing_envelope(
            kind="user-comments",
            meta={"user": args[0]},
            payload=payload,
            limit=safe_int(limit, 10),
        ),
    )
    return 0


# ---------- main ----------


def _run_user_analysis(base_url: str, user_agent: str, args: list[str]) -> int:
    """Run user-analysis with usage validation."""
    if not args:
        return usage_error(
            "usage: reddit user-analysis <username> "
            + "[posts_limit=<n>] [comments_limit=<n>] "
            + "[time_range=<day|week|month|year|all>] "
            + "[top_subreddits_limit=<n>]",
        )
    return user_analysis(base_url, user_agent, args[0], args[1:])


def _run_explain(_base_url: str, _user_agent: str, args: list[str]) -> int:
    """Run explain with usage validation."""
    if not args:
        return usage_error("usage: reddit explain <term>")
    return explain(args[0])


def main(argv: list[str]) -> int:
    """Route Reddit commands and preserve exit codes."""
    if not argv or argv[0] in {"-h", "--help"}:
        print(USAGE)
        return 0 if argv and argv[0] in {"-h", "--help"} else 2

    load_env()
    base_url = os.environ.get("REDDIT_BASE_URL", "https://www.reddit.com").rstrip("/")
    user_agent = os.environ.get("REDDIT_USER_AGENT", "agents-reddit/1.0")
    cmd, args = argv[0], argv[1:]

    runners: dict[str, Callable[[str, str, list[str]], int]] = {
        "browse": cmd_browse,
        "search": cmd_search,
        "post": cmd_post,
        "post-url": cmd_post_url,
        "user": cmd_user,
        "user-posts": cmd_user_posts,
        "user-comments": cmd_user_comments,
        "user-analysis": _run_user_analysis,
        "explain": _run_explain,
    }
    runner = runners.get(cmd)
    if runner is None:
        print(USAGE, file=sys.stderr)
        return 2
    return runner(base_url, user_agent, args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
