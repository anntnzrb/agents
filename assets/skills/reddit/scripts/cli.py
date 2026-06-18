#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

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
from collections import Counter
from pathlib import Path
from typing import Any

USAGE = "usage: reddit <browse|search|post|post-url|user|user-posts|user-comments|user-analysis|explain> ..."
RAW_FLAG = "raw=1"

PREVIEW_CAP = 500
SELF_PREVIEW_CAP = 240

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
HTML_SCRIPT_RE = re.compile(
    r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
)
HTML_TAG_RE = re.compile(r"<[^>]+>")

GLOSSARY = {
    "karma": "Score derived from upvotes on posts and comments. Usually split into post karma and comment karma.",
    "cake day": "The anniversary of a Reddit account creation date, shown with a cake icon.",
    "ama": "Ask Me Anything. A Q&A thread where a person invites questions from the community.",
    "op": "Original Poster: the author of the post or sometimes the parent comment under discussion.",
    "tldr": "Too Long; Did Not Read. A short summary of a longer post or comment.",
    "eli5": "Explain Like I Am Five. A request or community norm for simple, plain-language explanations.",
    "throwaway": "A temporary account, often created for privacy-sensitive posting.",
    "flair": "A label or badge attached to a post or username inside a subreddit.",
    "nsfw": "Not Safe For Work. Content that may be explicit or inappropriate in some settings.",
    "crosspost": "A repost of the same submission into another subreddit using the native crosspost flow.",
    "shadowban": "A state where activity is hidden or heavily limited without an obvious visible ban message.",
    "modmail": "Shared moderator inbox for communication between subreddit mods and users.",
}


# ---------- env loading ----------


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
    skill_dir = Path(__file__).resolve().parents[1]
    candidates: list[Path | None] = []
    if os.environ.get("REDDIT_ENV_FILE"):
        candidates.append(Path(os.environ["REDDIT_ENV_FILE"]).expanduser())
    candidates.append(skill_dir / ".env")
    if os.environ.get("SKILLS_DIR"):
        candidates.append(
            Path(os.environ["SKILLS_DIR"]).expanduser() / "reddit" / ".env"
        )
    candidates.append(ancestor_env("reddit"))
    for candidate in candidates:
        if candidate is not None and parse_env_file(candidate):
            return


# ---------- arg helpers ----------


def pairs(items: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in items:
        if "=" in item:
            key, value = item.split("=", 1)
            out.append((key, value))
        else:
            out.append((item, ""))
    return out


def alias_pair(pair: str) -> str:
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
    raw_mode = RAW_FLAG in args
    return raw_mode, [a for a in args if a != RAW_FLAG]


def split_limit_extra(
    args: list[str], default_limit: str
) -> tuple[str, list[tuple[str, str]]]:
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


def json_print(payload: Any) -> None:
    print(json.dumps(payload, separators=(",", ":")))

def _strip_html_preview(text: str) -> str:
    """Return a text-only preview with HTML tags/entities removed and whitespace collapsed.

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
    body_bytes = len(body)
    text = body.decode("utf-8", errors="replace") if body else ""
    preview_text = _strip_html_preview(text)
    if NETWORK_SECURITY_MARKER in preview_text.lower():
        kind = "network_security_block"
    truncated = len(preview_text) > PREVIEW_CAP
    preview = preview_text[:PREVIEW_CAP]
    payload: dict[str, Any] = {
        "error": {
            "provider": "reddit",
            "status": status,
            "message": message,
            "body_bytes": body_bytes,
            "body_preview": preview,
            "body_truncated": truncated,
        }
    }
    if kind is not None:
        payload["error"]["kind"] = kind
    print(json.dumps(payload, separators=(",", ":")), file=sys.stderr)


def usage_error(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


# ---------- HTTP ----------


def request_get(
    url: str,
    params: list[tuple[str, str]],
    user_agent: str,
    *,
    raw: bool,
) -> tuple[int, bytes]:
    if params:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        emit_error(
            status=exc.code,
            message=f"Reddit returned HTTP {exc.code}",
            body=exc.read(),
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
        sys.stdout.buffer.write(body)
    return 0, body


def fetch_json(
    url: str, params: list[tuple[str, str]], user_agent: str
) -> tuple[int, Any]:
    code, body = request_get(url, params, user_agent, raw=False)
    if code != 0:
        return code, None
    try:
        return 0, json.loads(body)
    except json.JSONDecodeError as exc:
        emit_error(
            status=None,
            message=f"Reddit returned invalid JSON: {exc}",
            body=body,
            kind="invalid_json",
        )
        return 1, None


# ---------- validation (testable hooks) ----------


def normalize_term(term: str) -> str:
    if term is None:
        raise ValueError("term must be non-empty")
    collapsed = WHITESPACE_RE.sub(" ", term).strip().lower()
    if not collapsed:
        raise ValueError("term must be non-empty")
    return collapsed


def validate_url(url: str) -> str:
    if not url or not HTTP_URL_RE.match(url.strip()):
        raise ValueError("url must use http:// or https:// scheme")
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must use http:// or https:// scheme")
    return url.strip()


def validate_time_range(value: str) -> str:
    if value not in TIME_RANGES:
        raise ValueError(
            f"time_range must be one of {sorted(TIME_RANGES)} (got {value!r})"
        )
    return value


def parse_subreddits(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "subreddits= must be a JSON list of non-empty strings"
        ) from exc
    if not isinstance(parsed, list):
        raise ValueError("subreddits= must be a JSON list of non-empty strings")
    out: list[str] = []
    for item in parsed:
        if not isinstance(item, str):
            raise ValueError("subreddits= must be a JSON list of non-empty strings")
        stripped = item.strip()
        if not stripped:
            raise ValueError("subreddits= must be a JSON list of non-empty strings")
        out.append(stripped)
    return out


def parse_non_negative_int(name: str, value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be >= 0")
    return parsed


def validate_browse_args(
    args: list[str],
) -> tuple[str, str, list[str]]:
    """Parse `browse` args.

    Returns (subreddit, sort, remaining_args). Raises ValueError on usage errors.
    """
    if not args:
        raise ValueError("usage: reddit browse <subreddit> [sort] [key=value ...]")
    subreddit = args[0]
    rest = args[1:]
    if not rest:
        return subreddit, "hot", []
    if "=" not in rest[0]:
        if rest[0] not in BROWSE_SORTS:
            raise ValueError(
                f"browse sort must be one of {sorted(BROWSE_SORTS)} (got {rest[0]!r})"
            )
        sort = rest[0]
        rest = rest[1:]
    else:
        sort = "hot"
    for item in rest:
        if "=" not in item:
            raise ValueError(
                f"unexpected positional argument after key=value: {item!r}"
            )
    return subreddit, sort, rest


def resolve_time(extra: list[tuple[str, str]]) -> str:
    for key, value in extra:
        if key in {"t", "time"}:
            return value
    return "all"


def safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


# ---------- projections ----------


def compact_selftext(text: str | None) -> str | None:
    if not text:
        return None
    text = WHITESPACE_RE.sub(" ", text).strip()
    if not text:
        return None
    if len(text) > SELF_PREVIEW_CAP:
        return text[:SELF_PREVIEW_CAP] + "…"
    return text


def compact_listing_result(data: dict[str, Any]) -> dict[str, Any]:
    author = data.get("author")
    out: dict[str, Any] = {
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
    preview = compact_selftext(data.get("selftext"))
    if preview:
        out["selftext_preview"] = preview
    if "over_18" in data:
        out["over_18"] = data.get("over_18")
    if "is_self" in data:
        out["is_self"] = data.get("is_self")
    return out


def compact_comment(data: dict[str, Any], depth: int) -> dict[str, Any]:
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


def walk_comments(node: Any, depth: int, out: list[dict[str, Any]]) -> None:
    if not isinstance(node, dict):
        return
    kind = node.get("kind")
    if kind == "more":
        return
    if kind == "Listing":
        data = node.get("data", {})
        if isinstance(data, dict):
            for child in data.get("children", []):
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


def listing_children(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return []
    children = data.get("children", [])
    return [c for c in children if isinstance(c, dict)]


def listing_data(payload: Any, limit: int, cutoff: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in listing_children(payload):
        data = child.get("data", {}) if isinstance(child, dict) else {}
        if not isinstance(data, dict):
            continue
        if cutoff and float(data.get("created_utc") or 0) < cutoff:
            continue
        rows.append(data)
    return rows[:limit]


def compact_listing_envelope(
    *,
    kind: str,
    meta: dict[str, Any],
    payload: Any,
    limit: int,
    cutoff: float = 0.0,
) -> dict[str, Any]:
    rows = listing_data(payload, limit, cutoff)
    return {
        "type": kind,
        **meta,
        "count": len(rows),
        "results": [compact_listing_result(r) for r in rows],
    }


def compact_post_envelope(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list) or not payload:
        return {"type": "post", "post": {}, "comments": []}
    post_payload = payload[0] if len(payload) >= 1 else None
    comments_payload = payload[1] if len(payload) >= 2 else None
    post_children = listing_children(post_payload)
    primary = (
        post_children[0].get("data", {})
        if post_children and isinstance(post_children[0].get("data"), dict)
        else {}
    )
    post = compact_listing_result(primary) if primary else {}
    comments: list[dict[str, Any]] = []
    for child in listing_children(comments_payload):
        walk_comments(child, 0, comments)
    return {"type": "post", "post": post, "comments": comments}


def compact_user_profile(payload: Any) -> dict[str, Any]:
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        data = {}
    link = int(data.get("link_karma") or 0)
    comment = int(data.get("comment_karma") or 0)
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


def compact_user_envelope(username: str, payload: Any) -> dict[str, Any]:
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
    return (
        "Unknown term in the built-in glossary. "
        "Search Reddit or the web for current community usage."
    )


def explain(term: str) -> int:
    try:
        normalized = normalize_term(term)
    except ValueError as exc:
        return usage_error(f"reddit explain: {exc}")
    candidates = [normalized, normalized.replace("-", " ")]
    canonical = next((c for c in candidates if c in GLOSSARY), normalized)
    definition = GLOSSARY.get(
        canonical,
        "Unknown term in the built-in glossary. Search Reddit or the web for current community usage.",
    )
    json_print({"term": canonical, "definition": definition})
    return 0


# ---------- user-analysis ----------


def cutoff_for(range_name: str, now: float) -> float:
    return {
        "day": now - 86_400,
        "week": now - 604_800,
        "month": now - 2_592_000,
        "year": now - 31_536_000,
        "all": 0,
    }[range_name]


def user_analysis(
    base_url: str, user_agent: str, username: str, args: list[str]
) -> int:
    posts_limit = 10
    comments_limit = 10
    time_range = "month"
    top_limit = 10
    fetch_limit = 100
    for pair in args:
        try:
            if pair.startswith("posts_limit="):
                posts_limit = parse_non_negative_int(
                    "posts_limit", pair.removeprefix("posts_limit=")
                )
            elif pair.startswith("comments_limit="):
                comments_limit = parse_non_negative_int(
                    "comments_limit", pair.removeprefix("comments_limit=")
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
                raise ValueError(f"unknown user-analysis argument: {pair!r}")
        except ValueError as exc:
            return usage_error(f"reddit user-analysis: {exc}")

    fetched: list[Any] = []
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
    top_source = listing_data(posts, 100, cutoff) + listing_data(
        comments, 100, cutoff
    )
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
            "comments": [
                {
                    "id": c.get("id"),
                    "subreddit": c.get("subreddit"),
                    "author": (
                        None
                        if c.get("author") in (None, "[deleted]")
                        else c.get("author")
                    ),
                    "score": c.get("score"),
                    "body_preview": compact_selftext(c.get("body")),
                    "permalink": c.get("permalink"),
                    "created_utc": c.get("created_utc"),
                }
                for c in recent_comments
            ],
            "top_subreddits": top_subreddits,
        }
    )
    return 0


# ---------- commands ----------


def cmd_browse(base_url: str, user_agent: str, args: list[str]) -> int:
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
        payload = json.loads(body)
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
        )
    )
    return 0


def cmd_search(base_url: str, user_agent: str, args: list[str]) -> int:
    raw_mode, args = consume_raw_flag(args)
    if not args:
        return usage_error("usage: reddit search <query> [key=value ...]")
    query = args[0]
    sort = "relevance"
    t = "all"
    limit = "10"
    author = ""
    flair = ""
    subreddits: list[str] = []
    extra: list[tuple[str, str]] = []
    for pair in args[1:]:
        try:
            if pair.startswith("sort="):
                sort = pair.removeprefix("sort=")
            elif pair.startswith("t="):
                t = pair.removeprefix("t=")
            elif pair.startswith("time="):
                t = pair.removeprefix("time=")
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
        except ValueError as exc:
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
        [("q", full_query), ("sort", sort), ("t", t), ("limit", limit), *extra],
        user_agent,
        raw=raw_mode,
    )
    if code != 0 or raw_mode:
        return code
    try:
        payload = json.loads(body)
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
        )
    )
    return 0


def cmd_post(base_url: str, user_agent: str, args: list[str]) -> int:
    raw_mode, args = consume_raw_flag(args)
    if len(args) < 2:
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
        payload = json.loads(body)
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


def cmd_post_url(base_url: str, user_agent: str, args: list[str]) -> int:
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
        clean_url, [("limit", limit), *extra], user_agent, raw=raw_mode
    )
    if code != 0 or raw_mode:
        return code
    try:
        payload = json.loads(body)
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
    raw_mode, args = consume_raw_flag(args)
    if not args:
        return usage_error("usage: reddit user <username>")
    code, body = request_get(
        f"{base_url}/user/{args[0]}/about.json", [], user_agent, raw=raw_mode
    )
    if code != 0 or raw_mode:
        return code
    try:
        payload = json.loads(body)
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
        payload = json.loads(body)
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
        )
    )
    return 0


def cmd_user_comments(base_url: str, user_agent: str, args: list[str]) -> int:
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
        payload = json.loads(body)
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
        )
    )
    return 0


# ---------- main ----------


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(USAGE)
        return 0 if argv and argv[0] in {"-h", "--help"} else 2

    load_env()
    base_url = os.environ.get("REDDIT_BASE_URL", "https://www.reddit.com").rstrip("/")
    user_agent = os.environ.get("REDDIT_USER_AGENT", "agents-reddit/1.0")
    cmd, args = argv[0], argv[1:]

    if cmd == "browse":
        return cmd_browse(base_url, user_agent, args)
    if cmd == "search":
        return cmd_search(base_url, user_agent, args)
    if cmd == "post":
        return cmd_post(base_url, user_agent, args)
    if cmd == "post-url":
        return cmd_post_url(base_url, user_agent, args)
    if cmd == "user":
        return cmd_user(base_url, user_agent, args)
    if cmd == "user-posts":
        return cmd_user_posts(base_url, user_agent, args)
    if cmd == "user-comments":
        return cmd_user_comments(base_url, user_agent, args)
    if cmd == "user-analysis":
        if not args:
            return usage_error(
                "usage: reddit user-analysis <username> "
                "[posts_limit=<n>] [comments_limit=<n>] "
                "[time_range=<day|week|month|year|all>] "
                "[top_subreddits_limit=<n>]"
            )
        return user_analysis(base_url, user_agent, args[0], args[1:])
    if cmd == "explain":
        if not args:
            return usage_error("usage: reddit explain <term>")
        return explain(args[0])

    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
