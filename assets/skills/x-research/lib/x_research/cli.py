"""Command-line interface for deterministic public X research via FxTwitter."""
# ruff: noqa: BLE001, CPY001, D107, EM101, EM102, PLR2004, TRY003

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from typing import TextIO
from urllib.parse import urlsplit

from .contracts import (
    ContractError,
    normalize_conversation_payload,
    normalize_page_payload,
    normalize_status_payload,
)
from .provider import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT,
    FetchResult,
    FxTwitterClient,
    ProviderError,
)

SCHEMA_VERSION = 1
_PROVIDER_NAME = "fxtwitter"
_COMMANDS = frozenset({"fetch", "user-posts", "search", "conversation"})
_SAFE_HANDLE_RE = re.compile(r"^[A-Za-z0-9_]+$")
_NUMERIC_ID_RE = re.compile(r"^[0-9]+$")
_STATUS_PATH_RE = re.compile(r"^/[A-Za-z0-9_]+/status/([0-9]+)/?$")


class CliError(RuntimeError):
    """An expected CLI failure rendered as the JSON error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        details: object | None = None,
        *,
        exit_code: int = 2,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = {} if details is None else details
        self.exit_code = exit_code


class _ArgumentParser(argparse.ArgumentParser):
    """Raise a structured error instead of printing argparse diagnostics."""

    def error(self, message: str) -> None:
        raise CliError("usage", message, exit_code=2)


def _nonempty(raw: str) -> str:
    if not raw or not raw.strip():
        raise argparse.ArgumentTypeError("value must not be empty")
    return raw


def _cursor(raw: str) -> str:
    return _nonempty(raw)


def _count(raw: str) -> int:
    if not _NUMERIC_ID_RE.fullmatch(raw):
        raise argparse.ArgumentTypeError("count must be an integer from 1 to 100")
    value = int(raw)
    if not 1 <= value <= 100:
        raise argparse.ArgumentTypeError("count must be an integer from 1 to 100")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the public command grammar."""
    parser = _ArgumentParser(
        prog="x-research",
        description="Read public X/Twitter posts through the FxTwitter v2 API.",
        epilog=(
            "Every command accepts --summary for a deterministic citation-safe "
            "projection and --pretty for valid indented JSON."
        ),
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    fetch = commands.add_parser("fetch", help="fetch one exact public post")
    fetch.add_argument(
        "target", help="numeric post ID or an x.com/twitter.com status URL"
    )
    fetch.add_argument(
        "--provider",
        choices=(_PROVIDER_NAME,),
        default=_PROVIDER_NAME,
        help="read-only provider (only fxtwitter is supported)",
    )
    fetch.add_argument("--lang", type=_nonempty, help="optional translation language")
    fetch.add_argument(
        "--summary",
        action="store_true",
        help="project output to citation-safe fields without metrics or media",
    )
    fetch.add_argument(
        "--pretty",
        action="store_true",
        help="emit valid JSON with two-space indentation",
    )

    user_posts = commands.add_parser(
        "user-posts", help="fetch one bounded user timeline page"
    )
    user_posts.add_argument("handle", help="X handle without the @ prefix")
    user_posts.add_argument("--count", type=_count, default=20)
    user_posts.add_argument("--cursor", type=_cursor)
    user_posts.add_argument(
        "--include-replies",
        action="store_true",
        help="include replies in the timeline request",
    )
    user_posts.add_argument(
        "--summary",
        action="store_true",
        help="project output to citation-safe fields without metrics or media",
    )
    user_posts.add_argument(
        "--pretty",
        action="store_true",
        help="emit valid JSON with two-space indentation",
    )

    search = commands.add_parser("search", help="fetch one bounded search page")
    search.add_argument("query", help="search query; whitespace is normalized")
    search.add_argument("--count", type=_count, default=30)
    search.add_argument("--feed", choices=("latest", "top", "media"), default="latest")
    search.add_argument("--cursor", type=_cursor)
    search.add_argument(
        "--summary",
        action="store_true",
        help="project output to citation-safe fields without metrics or media",
    )
    search.add_argument(
        "--pretty",
        action="store_true",
        help="emit valid JSON with two-space indentation",
    )

    conversation = commands.add_parser(
        "conversation", help="fetch one conversation page"
    )
    conversation.add_argument("id", help="numeric post ID")
    conversation.add_argument(
        "--ranking-mode",
        choices=("likes", "recency"),
        default="likes",
    )
    conversation.add_argument("--cursor", type=_cursor)
    conversation.add_argument(
        "--summary",
        action="store_true",
        help="project output to citation-safe fields without metrics or media",
    )
    conversation.add_argument(
        "--pretty",
        action="store_true",
        help="emit valid JSON with two-space indentation",
    )
    return parser


def _validate_handle(raw: str) -> str:
    if not raw or _SAFE_HANDLE_RE.fullmatch(raw) is None:
        raise CliError(
            "invalid_handle",
            "handle must contain only letters, digits, and underscores",
            {"handle": raw},
        )
    return raw


def _validate_numeric_id(raw: str, *, field: str = "id") -> str:
    if not raw or _NUMERIC_ID_RE.fullmatch(raw) is None:
        raise CliError(
            f"invalid_{field}",
            f"{field} must be a numeric ID",
            {field: raw},
        )
    return raw


def _status_id_from_target(raw: str) -> str:
    """Validate a numeric ID or exact supported X status URL and return its ID."""
    if not raw or raw != raw.strip():
        raise CliError(
            "invalid_target",
            "target must be a numeric ID or an https x.com/twitter.com status URL",
            {"target": raw},
        )
    if _NUMERIC_ID_RE.fullmatch(raw) is not None:
        return raw

    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname.lower() if parsed.hostname is not None else None
        port = parsed.port
    except ValueError:
        hostname = None
        port = None
        parsed = None

    if (
        parsed is None
        or parsed.scheme.lower() != "https"
        or hostname not in {"x.com", "twitter.com"}
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "?" in raw
        or "#" in raw
    ):
        raise CliError(
            "invalid_target",
            "target must be a numeric ID or an https x.com/twitter.com status URL",
            {"target": raw},
        )

    match = _STATUS_PATH_RE.fullmatch(parsed.path)
    if match is None:
        raise CliError(
            "invalid_target",
            "target must be a numeric ID or an https x.com/twitter.com status URL",
            {"target": raw},
        )
    return match.group(1)


def _normalize_query(raw: str) -> str:
    query = " ".join(raw.split())
    if not query:
        raise CliError(
            "invalid_query", "query must contain non-whitespace text", {"query": raw}
        )
    return query


def _details_mapping(details: object) -> dict[str, object]:
    if isinstance(details, Mapping):
        return dict(details)
    return {"details": details}


def _provider_status(result: FetchResult) -> int:
    status = result.provider_status
    return status if isinstance(status, int) else result.http_status


def _provenance(result: FetchResult) -> dict[str, object]:
    return {
        "provider": _PROVIDER_NAME,
        "official": False,
        "auth_mode": "none",
        "source_url": result.source_url,
        "endpoint": result.endpoint,
        "fetched_at": result.fetched_at,
        "provider_status": _provider_status(result),
    }


def _payload_error(error: ContractError, result: FetchResult) -> CliError:
    details = _details_mapping(error.details)
    details.setdefault("provider_status", _provider_status(result))
    details.setdefault("http_status", result.http_status)
    details.setdefault("source_url", result.source_url)
    details.setdefault("endpoint", result.endpoint)
    return CliError(error.code, error.message, details, exit_code=1)


def _normalize_status(result: FetchResult) -> dict[str, object]:
    try:
        normalized = normalize_status_payload(result.payload)
    except ContractError as error:
        raise _payload_error(error, result) from error
    if not isinstance(normalized, Mapping):
        raise CliError(
            "invalid_provider_payload",
            "provider status normalization did not return an object",
            {
                "provider_status": _provider_status(result),
                "http_status": result.http_status,
                "source_url": result.source_url,
                "endpoint": result.endpoint,
            },
            exit_code=1,
        )
    post = normalized.get("post")
    if isinstance(post, Mapping):
        return dict(post)
    if "post" in normalized:
        raise CliError(
            "invalid_provider_payload",
            "provider status normalization returned an invalid post object",
            {
                "provider_status": _provider_status(result),
                "http_status": result.http_status,
                "source_url": result.source_url,
                "endpoint": result.endpoint,
            },
            exit_code=1,
        )
    return dict(normalized)


def _normalize_page(result: FetchResult, requested_count: int) -> dict[str, object]:
    try:
        normalized = normalize_page_payload(result.payload, requested_count)
    except ContractError as error:
        raise _payload_error(error, result) from error
    if not isinstance(normalized, Mapping):
        raise CliError(
            "invalid_provider_payload",
            "provider page normalization did not return an object",
            {
                "provider_status": _provider_status(result),
                "http_status": result.http_status,
                "source_url": result.source_url,
                "endpoint": result.endpoint,
            },
            exit_code=1,
        )
    page = dict(normalized)
    page.setdefault("requested_count", requested_count)
    posts = page.get("posts")
    if "returned_count" not in page and isinstance(posts, list):
        page["returned_count"] = len(posts)
    return page


def _normalize_conversation(result: FetchResult) -> dict[str, object]:
    try:
        normalized = normalize_conversation_payload(result.payload)
    except ContractError as error:
        raise _payload_error(error, result) from error
    if not isinstance(normalized, Mapping):
        raise CliError(
            "invalid_provider_payload",
            "provider conversation normalization did not return an object",
            {
                "provider_status": _provider_status(result),
                "http_status": result.http_status,
                "source_url": result.source_url,
                "endpoint": result.endpoint,
            },
            exit_code=1,
        )
    return dict(normalized)


def _with_provenance(
    data: Mapping[str, object], result: FetchResult
) -> dict[str, object]:
    enriched = dict(data)
    enriched.update(_provenance(result))
    return enriched


def _client() -> FxTwitterClient:
    base_url = os.environ.get("X_RESEARCH_BASE_URL", DEFAULT_BASE_URL)
    try:
        return FxTwitterClient(base_url=base_url, timeout=DEFAULT_TIMEOUT)
    except ProviderError as error:
        details = _details_mapping(error.details)
        raise CliError(error.code, error.message, details, exit_code=2) from error
    except (TypeError, ValueError) as error:
        raise CliError("invalid_base_url", str(error), exit_code=2) from error


def _ensure_http_success(result: FetchResult) -> None:
    if 200 <= result.http_status < 300:
        return
    raise CliError(
        "provider_http_error",
        f"provider returned HTTP status {result.http_status}",
        {
            "http_status": result.http_status,
            "provider_status": _provider_status(result),
            "source_url": result.source_url,
            "endpoint": result.endpoint,
        },
        exit_code=1,
    )


def _fetch(args: argparse.Namespace, client: FxTwitterClient) -> dict[str, object]:
    target = args.target
    post_id = _status_id_from_target(target)
    params: list[tuple[str, str]] = []
    if args.lang is not None:
        params.append(("lang", args.lang))
    result = client.request_json(f"/2/status/{post_id}", params)
    _ensure_http_success(result)
    data: dict[str, object] = {"post": _normalize_status(result)}
    if _NUMERIC_ID_RE.fullmatch(target) is not None:
        data["requested_id"] = target
    else:
        data["requested_url"] = target
    data.update(_provenance(result))
    return data


def _user_posts(args: argparse.Namespace, client: FxTwitterClient) -> dict[str, object]:
    handle = _validate_handle(args.handle)
    params: list[tuple[str, str]] = [("count", str(args.count))]
    if args.cursor is not None:
        params.append(("cursor", args.cursor))
    params.append(("groupthreads", "0"))
    if args.include_replies:
        params.append(("with_replies", "1"))
    result = client.request_json(f"/2/profile/{handle}/statuses", params)
    _ensure_http_success(result)
    data = _normalize_page(result, args.count)
    data["handle"] = handle
    return _with_provenance(data, result)


def _search(args: argparse.Namespace, client: FxTwitterClient) -> dict[str, object]:
    query = _normalize_query(args.query)
    params: list[tuple[str, str]] = [
        ("q", query),
        ("count", str(args.count)),
        ("feed", args.feed),
    ]
    if args.cursor is not None:
        params.append(("cursor", args.cursor))
    result = client.request_json("/2/search", params)
    _ensure_http_success(result)
    data = _normalize_page(result, args.count)
    data["query"] = query
    data["feed"] = args.feed
    return _with_provenance(data, result)


def _conversation(
    args: argparse.Namespace, client: FxTwitterClient
) -> dict[str, object]:
    post_id = _validate_numeric_id(args.id)
    params: list[tuple[str, str]] = [("ranking_mode", args.ranking_mode)]
    if args.cursor is not None:
        params.append(("cursor", args.cursor))
    result = client.request_json(f"/2/conversation/{post_id}", params)
    _ensure_http_success(result)
    data = _normalize_conversation(result)
    data["requested_id"] = post_id
    data["ranking_mode"] = args.ranking_mode
    thread = data.get("thread")
    replies = data.get("replies")
    if isinstance(thread, list) and isinstance(replies, list):
        data["returned_count"] = 1 + len(thread) + len(replies)
    return _with_provenance(data, result)


def _dispatch(args: argparse.Namespace) -> dict[str, object]:
    # Validate command-local values before constructing a client or touching the wire.
    command = args.command
    if command == "fetch":
        _status_id_from_target(args.target)
    elif command == "user-posts":
        _validate_handle(args.handle)
    elif command == "search":
        _normalize_query(args.query)
    elif command == "conversation":
        _validate_numeric_id(args.id)
    else:
        raise CliError("usage", "a command is required", exit_code=2)

    client = _client()
    if command == "fetch":
        return _fetch(args, client)
    if command == "user-posts":
        return _user_posts(args, client)
    if command == "search":
        return _search(args, client)
    if command == "conversation":
        return _conversation(args, client)
    raise CliError("usage", f"unknown command: {command}", exit_code=2)


def _command_hint(argv: Sequence[str]) -> str:
    for value in argv:
        if value in _COMMANDS:
            return value
    return "unknown"


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


_SUMMARY_ROOT_FIELDS = (
    "requested_id",
    "requested_url",
    "handle",
    "query",
    "feed",
    "ranking_mode",
    "requested_count",
    "returned_count",
    "cursor",
    "has_more",
    "complete",
    "complete_reason",
    "provider",
    "official",
    "auth_mode",
    "source_url",
    "endpoint",
    "fetched_at",
    "provider_status",
)
_SUMMARY_POST_FIELDS = (
    "id",
    "url",
    "text",
    "created_at",
    "author",
    "lang",
    "quote_id",
    "reply_to_id",
)


def _summary_author(author: Mapping[str, object]) -> dict[str, object]:
    """Project a normalized author to citation-safe identity fields."""
    return {
        key: author[key]
        for key in ("id", "handle", "name", "url", "verified")
        if key in author
    }


def _summary_post(post: Mapping[str, object]) -> dict[str, object]:
    """Project a normalized post while retaining its complete text."""
    summary: dict[str, object] = {}
    for key in _SUMMARY_POST_FIELDS:
        if key == "author":
            author = post.get(key)
            if isinstance(author, Mapping):
                summary[key] = _summary_author(author)
            continue
        if key in post:
            summary[key] = post[key]
    return summary


def _summary_post_value(value: object) -> object | None:
    if isinstance(value, Mapping):
        return _summary_post(value)
    if isinstance(value, list):
        return [_summary_post(item) for item in value if isinstance(item, Mapping)]
    return None


def _summary_data(command: str, data: Mapping[str, object]) -> dict[str, object]:
    """Project normalized command data without changing its request semantics."""
    del command
    summary: dict[str, object] = {
        key: data[key] for key in _SUMMARY_ROOT_FIELDS if key in data
    }
    for key in ("post", "posts", "target", "thread", "replies"):
        if key not in data:
            continue
        projected = _summary_post_value(data[key])
        if projected is not None:
            summary[key] = projected
    profile = data.get("profile")
    if isinstance(profile, Mapping):
        summary["profile"] = _summary_author(profile)
    return summary


def _emit(value: object, *, stream: TextIO, pretty: bool = False) -> None:
    if pretty:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
    else:
        serialized = _compact_json(value)
    print(serialized, file=stream)


def _success(command: str, data: Mapping[str, object]) -> dict[str, object]:
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "data": dict(data),
    }


def _failure(command: str, error: CliError) -> dict[str, object]:
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and emit exactly one JSON envelope on success/failure."""
    values = list(sys.argv[1:] if argv is None else argv)
    command = _command_hint(values)
    pretty = "--pretty" in values
    try:
        args = build_parser().parse_args(values)
        command = args.command or command
        pretty = bool(getattr(args, "pretty", pretty))
        data = _dispatch(args)
        if args.summary:
            data = _summary_data(command, data)
    except CliError as error:
        _emit(_failure(command, error), stream=sys.stderr, pretty=pretty)
        return error.exit_code
    except ProviderError as error:
        _emit(
            _failure(
                command,
                CliError(
                    error.code,
                    error.message,
                    _details_mapping(error.details),
                    exit_code=1,
                ),
            ),
            stream=sys.stderr,
            pretty=pretty,
        )
        return 1
    except ContractError as error:
        _emit(
            _failure(
                command,
                CliError(
                    error.code,
                    error.message,
                    _details_mapping(error.details),
                    exit_code=1,
                ),
            ),
            stream=sys.stderr,
            pretty=pretty,
        )
        return 1
    except (
        Exception
    ) as error:  # Process boundary: never leak a traceback into machine output.
        internal = CliError("internal_error", str(error), exit_code=1)
        _emit(_failure(command, internal), stream=sys.stderr, pretty=pretty)
        return 1

    _emit(_success(command, data), stream=sys.stdout, pretty=pretty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
