# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Read public X/Twitter posts through the FxTwitter v2 API."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

# Add lib directory to sys.path for internal imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from commands import run_command
from models import SCHEMA_VERSION, UNDEFINED, CliError, ContractError, ProviderError
from provider import FxTwitterClient, live_client
from summary import summary_data

KNOWN_COMMANDS = frozenset({"fetch", "user-posts", "search", "conversation"})


class _UsageError(Exception):
    """Argparse validation failure; emitted as a ``usage`` JSON error."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)


def get_command_hint(args: Sequence[str]) -> str:
    for arg in args:
        if arg in KNOWN_COMMANDS:
            return arg
    return "unknown"


def _sanitize(value: Any) -> Any:
    """Mirror JSON.stringify: drop ``undefined`` object values, null array slots."""
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items() if v is not UNDEFINED}
    if isinstance(value, list):
        return [None if item is UNDEFINED else _sanitize(item) for item in value]
    return value


def _write_envelope(stream: Any, envelope: dict[str, Any], pretty: bool) -> None:
    sanitized = _sanitize(envelope)
    if pretty:
        serialized = json.dumps(sanitized, ensure_ascii=False, indent=2)
    else:
        serialized = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
    stream.write(serialized + "\n")


def emit_success(command: str, data: dict[str, Any], pretty: bool) -> None:
    envelope = {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "data": data,
    }
    _write_envelope(sys.stdout, envelope, pretty)


def emit_failure(command: str, error: Any, pretty: bool) -> None:
    if isinstance(error, dict):
        code = error["code"]
        message = error["message"]
        details = error["details"]
    else:
        code = error.code
        message = error.message
        details = error.details
    envelope = {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "error": {"code": code, "message": message, "details": details},
    }
    _write_envelope(sys.stderr, envelope, pretty)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="x-research",
        description="Read public X/Twitter posts through the FxTwitter v2 API.",
    )
    parser.add_argument("--version", action="version", version="1.0.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch", help="fetch one exact public post")
    fetch.add_argument(
        "target", help="numeric Post ID or an x.com/twitter.com status URL"
    )
    fetch.add_argument(
        "--provider",
        default="fxtwitter",
        help="read-only provider (only fxtwitter is supported)",
    )
    fetch.add_argument("--lang", default=None, help="optional translation language")
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

    user_posts = subparsers.add_parser(
        "user-posts", help="fetch one bounded user timeline page"
    )
    user_posts.add_argument("handle", help="X handle without the @ prefix")
    user_posts.add_argument(
        "--count",
        type=int,
        default=20,
        help="requested number of posts (1..100)",
    )
    user_posts.add_argument("--cursor", default=None, help="optional pagination cursor")
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

    search = subparsers.add_parser("search", help="fetch one bounded search page")
    search.add_argument("query", help="search query; whitespace is normalized")
    search.add_argument(
        "--count",
        type=int,
        default=30,
        help="requested number of posts (1..100)",
    )
    search.add_argument(
        "--feed",
        choices=["latest", "top", "media"],
        default="latest",
        help="search feed",
    )
    search.add_argument("--cursor", default=None, help="optional pagination cursor")
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

    conversation = subparsers.add_parser(
        "conversation", help="fetch one conversation page"
    )
    conversation.add_argument("id", help="numeric post ID")
    conversation.add_argument(
        "--ranking-mode",
        choices=["likes", "recency"],
        default="likes",
        help="reply ranking mode",
    )
    conversation.add_argument(
        "--cursor", default=None, help="optional pagination cursor"
    )
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


def _dispatch(args: argparse.Namespace, client: FxTwitterClient) -> dict[str, Any]:
    if args.command == "fetch":
        return run_command(
            {
                "command": "fetch",
                "target": args.target,
                "provider": args.provider,
                "lang": args.lang,
                "summary": args.summary,
                "pretty": args.pretty,
            },
            client,
        )
    if args.command == "user-posts":
        return run_command(
            {
                "command": "user-posts",
                "handle": args.handle,
                "count": args.count,
                "cursor": args.cursor,
                "includeReplies": args.include_replies,
                "summary": args.summary,
                "pretty": args.pretty,
            },
            client,
        )
    if args.command == "search":
        return run_command(
            {
                "command": "search",
                "query": args.query,
                "count": args.count,
                "feed": args.feed,
                "cursor": args.cursor,
                "summary": args.summary,
                "pretty": args.pretty,
            },
            client,
        )
    if args.command == "conversation":
        return run_command(
            {
                "command": "conversation",
                "id": args.id,
                "rankingMode": args.ranking_mode,
                "cursor": args.cursor,
                "summary": args.summary,
                "pretty": args.pretty,
            },
            client,
        )
    raise CliError(
        code="usage",
        message=f"unknown command: {args.command}",
        details={},
    )


def run_cli(raw_args: Sequence[str]) -> int:
    is_help = "--help" in raw_args or "-h" in raw_args
    is_pretty = "--pretty" in raw_args
    hint = get_command_hint(raw_args)

    try:
        args = build_parser().parse_args(list(raw_args))
    except _UsageError as err:
        if is_help:
            return 0
        emit_failure(
            hint,
            {"code": "usage", "message": str(err), "details": {}},
            is_pretty,
        )
        return 2
    except SystemExit as exc:
        if is_help:
            return 0
        return exc.code if isinstance(exc.code, int) else 0

    try:
        client = live_client()
        data = _dispatch(args, client)
        final_data = summary_data(args.command, data) if args.summary else data
        emit_success(args.command, final_data, args.pretty)
    except CliError as err:
        if is_help:
            return 0
        emit_failure(hint, err, is_pretty)
        return 2
    except (ProviderError, ContractError) as err:
        if is_help:
            return 0
        emit_failure(hint, err, is_pretty)
        return 1
    except Exception as err:
        if is_help:
            return 0
        emit_failure(
            hint,
            {"code": "internal_error", "message": str(err), "details": {}},
            is_pretty,
        )
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    return run_cli(raw_args)


if __name__ == "__main__":
    sys.exit(main())
