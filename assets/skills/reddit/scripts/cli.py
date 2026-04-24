#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

USAGE = "usage: reddit <browse|search|post|post-url|user|user-posts|user-comments|user-analysis|explain> ..."
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
        candidates.append(Path(os.environ["SKILLS_DIR"]).expanduser() / "reddit" / ".env")
    candidates.append(ancestor_env("reddit"))
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


def alias_pair(pair: str) -> str:
    aliases = {
        "time=": "t=",
        "comment_limit=": "limit=",
        "comment_sort=": "sort=",
        "comment_depth=": "depth=",
    }
    for old, new in aliases.items():
        if pair.startswith(old):
            return f"{new}{pair[len(old):]}"
    return pair


def request_get(url: str, params: list[tuple[str, str]], user_agent: str, emit: bool = True) -> tuple[int, bytes]:
    if params:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read()
        if emit:
            sys.stdout.buffer.write(body)
        return 0, body
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace") or f"HTTP {exc.code}"
        print(text, file=sys.stderr)
        return 22, b""
    except urllib.error.URLError as exc:
        print(f"Reddit network error: {exc.reason}", file=sys.stderr)
        return 1, b""


def split_limit_extra(args: list[str], default_limit: str) -> tuple[str, list[tuple[str, str]]]:
    limit = default_limit
    extra: list[tuple[str, str]] = []
    for raw in args:
        aliased = alias_pair(raw)
        if aliased.startswith("limit="):
            limit = aliased.removeprefix("limit=")
        else:
            extra.extend(pairs([aliased]))
    return limit, extra


def json_print(payload: Any) -> None:
    print(json.dumps(payload, separators=(",", ":")))


def explain(term: str) -> int:
    normalized = term.lower()
    json_print({"term": normalized, "definition": GLOSSARY.get(normalized, "Unknown term in the built-in glossary. Search Reddit or the web for current community usage.")})
    return 0


def listing_data(payload: Any, limit: int, cutoff: float) -> list[dict[str, Any]]:
    children = payload.get("data", {}).get("children", []) if isinstance(payload, dict) else []
    rows: list[dict[str, Any]] = []
    for child in children:
        data = child.get("data", {}) if isinstance(child, dict) else {}
        if isinstance(data, dict) and float(data.get("created_utc") or 0) >= cutoff:
            rows.append(data)
    return rows[:limit]


def cutoff_for(range_name: str, now: float) -> float:
    return {
        "day": now - 86_400,
        "week": now - 604_800,
        "month": now - 2_592_000,
        "year": now - 31_536_000,
        "all": 0,
    }.get(range_name, 0)


def user_analysis(base_url: str, user_agent: str, username: str, args: list[str]) -> int:
    posts_limit = 10
    comments_limit = 10
    time_range = "month"
    top_limit = 10
    fetch_limit = 100
    for pair in args:
        if pair.startswith("posts_limit="):
            posts_limit = int(pair.removeprefix("posts_limit="))
        elif pair.startswith("comments_limit="):
            comments_limit = int(pair.removeprefix("comments_limit="))
        elif pair.startswith("time_range="):
            time_range = pair.removeprefix("time_range=")
        elif pair.startswith("top_subreddits_limit="):
            top_limit = int(pair.removeprefix("top_subreddits_limit="))

    fetched: list[Any] = []
    for path, params in [
        (f"/user/{username}/about.json", []),
        (f"/user/{username}/submitted.json", [("limit", str(fetch_limit))]),
        (f"/user/{username}/comments.json", [("limit", str(fetch_limit))]),
    ]:
        code, body = request_get(f"{base_url}{path}", params, user_agent, emit=False)
        if code != 0:
            return code
        try:
            fetched.append(json.loads(body))
        except json.JSONDecodeError as exc:
            print(f"Reddit returned invalid JSON: {exc}", file=sys.stderr)
            return 1

    about, posts, comments = fetched
    about_data = about.get("data", {}) if isinstance(about, dict) else {}
    now = time.time()
    cutoff = cutoff_for(time_range, now)
    recent_posts = listing_data(posts, posts_limit, cutoff)
    recent_comments = listing_data(comments, comments_limit, cutoff)
    top_source = listing_data(posts, 100, cutoff) + listing_data(comments, 100, cutoff)
    counts = Counter(str(item.get("subreddit")) for item in top_source if item.get("subreddit") is not None)
    top_subreddits = [{"subreddit": name, "count": count} for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_limit]]
    json_print(
        {
            "user": {
                "name": about_data.get("name"),
                "created_utc": about_data.get("created_utc"),
                "link_karma": about_data.get("link_karma"),
                "comment_karma": about_data.get("comment_karma"),
                "total_karma": int(about_data.get("link_karma") or 0) + int(about_data.get("comment_karma") or 0),
                "is_gold": about_data.get("is_gold"),
                "is_mod": about_data.get("is_mod"),
                "verified": about_data.get("verified"),
            },
            "posts": recent_posts,
            "comments": recent_comments,
            "top_subreddits": top_subreddits,
        }
    )
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(USAGE)
        return 0 if argv and argv[0] in {"-h", "--help"} else 2

    load_env()
    base_url = os.environ.get("REDDIT_BASE_URL", "https://www.reddit.com").rstrip("/")
    user_agent = os.environ.get("REDDIT_USER_AGENT", "agents-reddit/1.0")
    cmd, args = argv[0], argv[1:]

    if cmd == "browse":
        if not args:
            print("usage: reddit browse <subreddit> [sort] [key=value ...]", file=sys.stderr)
            return 2
        subreddit = args[0]
        sort = args[1] if len(args) > 1 and "=" not in args[1] else "hot"
        rest = args[2:] if len(args) > 1 and "=" not in args[1] else args[1:]
        limit, extra = split_limit_extra(rest, "10")
        return request_get(f"{base_url}/r/{subreddit}/{sort}.json", [("limit", limit), *extra], user_agent)[0]

    if cmd == "search":
        if not args:
            print("usage: reddit search <query> [key=value ...]", file=sys.stderr)
            return 2
        query = args[0]
        sort = "relevance"
        t = "all"
        limit = "10"
        author = ""
        flair = ""
        subreddits: list[str] = []
        extra: list[tuple[str, str]] = []
        for pair in args[1:]:
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
                try:
                    parsed = json.loads(pair.removeprefix("subreddits="))
                    if isinstance(parsed, list):
                        subreddits.extend(str(item) for item in parsed if item)
                except json.JSONDecodeError:
                    pass
            else:
                extra.extend(pairs([pair]))
        full_query = query
        for subreddit in subreddits:
            full_query += f" subreddit:{subreddit}"
        if author:
            full_query += f" author:{author}"
        if flair:
            full_query += f' flair:"{flair}"'
        return request_get(f"{base_url}/search.json", [("q", full_query), ("sort", sort), ("t", t), ("limit", limit), *extra], user_agent)[0]

    if cmd == "post":
        if len(args) < 2:
            print("usage: reddit post <subreddit> <post_id> [key=value ...]", file=sys.stderr)
            return 2
        limit, extra = split_limit_extra(args[2:], "20")
        return request_get(f"{base_url}/r/{args[0]}/comments/{args[1]}/.json", [("limit", limit), *extra], user_agent)[0]

    if cmd == "post-url":
        if not args:
            print("usage: reddit post-url <url> [key=value ...]", file=sys.stderr)
            return 2
        clean_url = args[0].split("?", 1)[0]
        clean_url = clean_url.removesuffix(".json") + ".json"
        limit, extra = split_limit_extra(args[1:], "20")
        return request_get(clean_url, [("limit", limit), *extra], user_agent)[0]

    if cmd == "user":
        if not args:
            print("usage: reddit user <username>", file=sys.stderr)
            return 2
        return request_get(f"{base_url}/user/{args[0]}/about.json", [], user_agent)[0]

    if cmd == "user-posts":
        if not args:
            print("usage: reddit user-posts <username> [key=value ...]", file=sys.stderr)
            return 2
        limit, extra = split_limit_extra(args[1:], "10")
        return request_get(f"{base_url}/user/{args[0]}/submitted.json", [("limit", limit), *extra], user_agent)[0]

    if cmd == "user-comments":
        if not args:
            print("usage: reddit user-comments <username> [key=value ...]", file=sys.stderr)
            return 2
        limit, extra = split_limit_extra(args[1:], "10")
        return request_get(f"{base_url}/user/{args[0]}/comments.json", [("limit", limit), *extra], user_agent)[0]

    if cmd == "user-analysis":
        if not args:
            print("usage: reddit user-analysis <username> [posts_limit=<n>] [comments_limit=<n>] [time_range=<day|week|month|year|all>] [top_subreddits_limit=<n>]", file=sys.stderr)
            return 2
        try:
            return user_analysis(base_url, user_agent, args[0], args[1:])
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    if cmd == "explain":
        if not args:
            print("usage: reddit explain <term>", file=sys.stderr)
            return 2
        return explain(args[0])

    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
