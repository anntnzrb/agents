#!/usr/bin/env -S uv run --script
# Copyright (c) 2026
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "httpx>=0.27.0",
# ]
# ///
"""Upload code, diffs, and text to pastes.dev."""

from __future__ import annotations

import argparse
import gzip
import http
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, assert_never

if TYPE_CHECKING:
    from collections.abc import Callable

import httpx

DEFAULT_BASE_URL: Final[str] = "https://api.pastes.dev/"
DEFAULT_USER_AGENT: Final[str] = "webpaste-cli/0.1.0"
DEFAULT_TIMEOUT: Final[float] = 15.0

EXIT_SUCCESS: Final[int] = 0
EXIT_NETWORK_ERROR: Final[int] = 1
EXIT_USAGE_ERROR: Final[int] = 2


@dataclass(frozen=True, slots=True)
class Ok[T]:
    """Successful computation result."""

    value: T

    def map[U](self, fn: Callable[[T], U]) -> Ok[U]:
        """Apply a transform function to the success value."""
        return Ok(fn(self.value))

    def and_then[U, E](self, fn: Callable[[T], Result[U, E]]) -> Result[U, E]:
        """Chain a function returning another Result."""
        return fn(self.value)


@dataclass(frozen=True, slots=True)
class Err[E]:
    """Failed computation result."""

    error: E

    def map[U](self, _fn: Callable[[object], U]) -> Err[E]:
        """Pass error through unchanged on map."""
        return self

    def and_then[U](self, _fn: Callable[[object], Result[U, E]]) -> Err[E]:
        """Pass error through unchanged on and_then."""
        return self


type Result[T, E] = Ok[T] | Err[E]


@dataclass(frozen=True, slots=True)
class AppError:
    """Domain error carrying user message and process exit code."""

    message: str
    exit_code: int


@dataclass(frozen=True, slots=True)
class UploadPayload:
    """Prepared upload payload ready for network dispatch."""

    content: bytes
    language: str
    base_url: str
    user_agent: str
    timeout: float
    use_gzip: bool
    output_json: bool
    output_raw: bool
    output_raw_url: bool


# Canonical language IDs recognized by lucko/paste Monaco editor
CANONICAL_LANGUAGES: Final[frozenset[str]] = frozenset(
    {
        "plain",
        "log",
        "yaml",
        "json",
        "xml",
        "ini",
        "java",
        "javascript",
        "typescript",
        "python",
        "kotlin",
        "scala",
        "cpp",
        "csharp",
        "shell",
        "ruby",
        "rust",
        "sql",
        "go",
        "lua",
        "swift",
        "c",
        "html",
        "css",
        "scss",
        "php",
        "graphql",
        "diff",
        "dockerfile",
        "markdown",
        "proto",
    }
)

# Common aliases mapped to canonical IDs
LANGUAGE_ALIASES: Final[dict[str, str]] = {
    "py": "python",
    "js": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "jsx": "javascript",
    "ts": "typescript",
    "mts": "typescript",
    "cts": "typescript",
    "tsx": "typescript",
    "rs": "rust",
    "c++": "cpp",
    "cxx": "cpp",
    "cc": "cpp",
    "h": "c",
    "hpp": "cpp",
    "hxx": "cpp",
    "cs": "csharp",
    "kt": "kotlin",
    "kts": "kotlin",
    "sc": "scala",
    "rb": "ruby",
    "sh": "shell",
    "bash": "shell",
    "zsh": "shell",
    "fish": "shell",
    "yml": "yaml",
    "md": "markdown",
    "mdown": "markdown",
    "htm": "html",
    "sass": "scss",
    "gql": "graphql",
    "patch": "diff",
    "docker": "dockerfile",
    "containerfile": "dockerfile",
    "toml": "ini",
    "cfg": "ini",
    "conf": "ini",
    "properties": "ini",
    "txt": "plain",
    "text": "plain",
}

EXTENSION_TO_LANGUAGE: Final[dict[str, str]] = {
    ".py": "python",
    ".pyi": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cxx": "cpp",
    ".hxx": "cpp",
    ".cc": "cpp",
    ".hh": "cpp",
    ".cs": "csharp",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".sc": "scala",
    ".rb": "ruby",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".fish": "shell",
    ".ksh": "shell",
    ".sql": "sql",
    ".lua": "lua",
    ".swift": "swift",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "scss",
    ".php": "php",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".diff": "diff",
    ".patch": "diff",
    ".md": "markdown",
    ".markdown": "markdown",
    ".mdown": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
    ".svg": "xml",
    ".plist": "xml",
    ".ini": "ini",
    ".toml": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".dockerfile": "dockerfile",
    ".proto": "proto",
    ".log": "log",
    ".txt": "plain",
}

SHEBANG_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^#!\s*(?:/usr/bin/env\s+|/bin/|/usr/bin/)?([a-zA-Z0-9_\-]+)"
)

SHEBANG_INTERPRETER_MAP: Final[dict[str, str]] = {
    "python": "python",
    "python3": "python",
    "py": "python",
    "bash": "shell",
    "sh": "shell",
    "zsh": "shell",
    "fish": "shell",
    "ksh": "shell",
    "node": "javascript",
    "nodejs": "javascript",
    "bun": "javascript",
    "deno": "javascript",
    "ruby": "ruby",
    "rb": "ruby",
}

SPECIAL_FILENAMES: Final[dict[str, str]] = {
    "dockerfile": "dockerfile",
    "containerfile": "dockerfile",
    ".env": "shell",
    ".env.example": "shell",
    ".env.local": "shell",
}


def normalize_language(lang: str) -> str:
    """Normalize language identifier to canonical Monaco language ID."""
    clean = lang.lower().strip()
    if clean in CANONICAL_LANGUAGES:
        return clean
    return LANGUAGE_ALIASES.get(clean, clean)


def detect_from_path(path: Path) -> str | None:
    """Infer language from filename or extension."""
    name = path.name.lower()
    if name in SPECIAL_FILENAMES:
        return SPECIAL_FILENAMES[name]
    ext = path.suffix.lower()
    if ext in EXTENSION_TO_LANGUAGE:
        return EXTENSION_TO_LANGUAGE[ext]
    return None


def detect_from_shebang(content: bytes) -> str | None:
    """Infer language from initial shebang line."""
    first_line = (
        content[:200].decode("utf-8", errors="ignore").split("\n", 1)[0].strip()
    )
    match = SHEBANG_PATTERN.match(first_line)
    if not match:
        return None
    interpreter = match.group(1).lower()
    return SHEBANG_INTERPRETER_MAP.get(interpreter)


def detect_language(
    path: Path | None, content: bytes, explicit_lang: str | None
) -> str:
    """Determine language identifier from explicit option, extension, or shebang."""
    if explicit_lang:
        return normalize_language(explicit_lang)

    if path is not None:
        path_res = detect_from_path(path)
        if path_res:
            return path_res

    shebang_res = detect_from_shebang(content)
    if shebang_res:
        return shebang_res

    return "plain"


def get_content_type(language: str) -> str:
    """Return appropriate MIME Content-Type header."""
    canonical = normalize_language(language)
    if canonical == "json":
        return "application/json"
    return f"text/{canonical}"


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Upload code or text to pastes.dev / bytebin.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="Path to file to upload (reads from stdin if omitted or '-')",
    )
    parser.add_argument(
        "-l",
        "--lang",
        help="Explicit language identifier or alias (e.g. python, py, ts, diff, json)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON payload (key, url, and raw_url)",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Output only the paste key",
    )
    parser.add_argument(
        "--raw-url",
        action="store_true",
        help="Output direct raw content URL",
    )
    parser.add_argument(
        "--get",
        metavar="KEY",
        help="Fetch content of an existing paste by key",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base API URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help=f"User-Agent header string (default: {DEFAULT_USER_AGENT})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--no-gzip",
        action="store_true",
        help="Disable gzip payload compression",
    )
    return parser


def read_input(
    file_arg: str | None, *, is_atty: bool
) -> Result[tuple[bytes, Path | None], AppError]:
    """Read content from file or stdin as a Railway Result."""
    if file_arg and file_arg != "-":
        input_path = Path(file_arg)
        if not input_path.exists() or not input_path.is_file():
            return Err(AppError(f"file not found: {file_arg}", EXIT_USAGE_ERROR))
        return Ok((input_path.read_bytes(), input_path))

    if is_atty:
        return Err(
            AppError(
                "no input provided (pass a file path or pipe stdin)",
                EXIT_USAGE_ERROR,
            )
        )

    stdin_bytes = sys.stdin.buffer.read()
    if not stdin_bytes:
        return Err(AppError("cannot upload empty content", EXIT_USAGE_ERROR))

    return Ok((stdin_bytes, None))


def execute_fetch(
    base_url: str, key: str, user_agent: str, timeout: float
) -> Result[str, AppError]:
    """Fetch existing paste content from bytebin."""
    url = f"{base_url.rstrip('/')}/{key.strip()}"
    headers = {"User-Agent": user_agent}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == http.HTTPStatus.NOT_FOUND:
                return Err(
                    AppError(f"paste not found for key: {key}", EXIT_NETWORK_ERROR)
                )
            resp.raise_for_status()
            text = resp.text
            return Ok(text if text.endswith("\n") else text + "\n")
    except httpx.HTTPStatusError as exc:
        return Err(
            AppError(
                f"HTTP error {exc.response.status_code}: {exc.response.text}",
                EXIT_NETWORK_ERROR,
            )
        )
    except httpx.RequestError as exc:
        return Err(AppError(f"Network error: {exc}", EXIT_NETWORK_ERROR))


def format_upload_response(key: str, payload: UploadPayload) -> str:
    """Format final output string based on CLI presentation flags."""
    raw_url = f"{payload.base_url.rstrip('/')}/{key}"
    view_url = (
        f"https://pastes.dev/{key}" if "pastes.dev" in payload.base_url else raw_url
    )

    if payload.output_json:
        res_obj = {
            "key": key,
            "url": view_url,
            "raw_url": raw_url,
            "language": payload.language,
        }
        return json.dumps(res_obj) + "\n"
    if payload.output_raw:
        return f"{key}\n"
    if payload.output_raw_url:
        return f"{raw_url}\n"
    return f"{view_url}\n"


def execute_upload(payload: UploadPayload) -> Result[str, AppError]:
    """Post prepared payload to bytebin endpoint."""
    if not payload.content:
        return Err(AppError("cannot upload empty content", EXIT_USAGE_ERROR))

    post_url = f"{payload.base_url.rstrip('/')}/post"
    content_type = get_content_type(payload.language)

    headers = {
        "User-Agent": payload.user_agent,
        "Content-Type": content_type,
        "Accept": "application/json",
    }

    body = payload.content
    if payload.use_gzip:
        body = gzip.compress(payload.content)
        headers["Content-Encoding"] = "gzip"

    try:
        with httpx.Client(timeout=payload.timeout) as client:
            resp = client.post(post_url, headers=headers, content=body)
            resp.raise_for_status()
            data = resp.json()
            key = data.get("key")
            if not key:
                return Err(
                    AppError("missing key in server response", EXIT_NETWORK_ERROR)
                )

            return Ok(format_upload_response(key, payload))
    except httpx.HTTPStatusError as exc:
        return Err(
            AppError(
                f"HTTP error {exc.response.status_code}: {exc.response.text}",
                EXIT_NETWORK_ERROR,
            )
        )
    except httpx.RequestError as exc:
        return Err(AppError(f"Network error: {exc}", EXIT_NETWORK_ERROR))


def run_pipeline(args: argparse.Namespace, *, is_atty: bool) -> Result[str, AppError]:
    """Execute upload or fetch workflow."""
    if args.get:
        return execute_fetch(args.base_url, args.get, args.user_agent, args.timeout)

    input_res = read_input(args.file, is_atty=is_atty)

    def to_payload(pair: tuple[bytes, Path | None]) -> UploadPayload:
        content, path = pair
        language = detect_language(path, content, args.lang)
        return UploadPayload(
            content=content,
            language=language,
            base_url=args.base_url,
            user_agent=args.user_agent,
            timeout=args.timeout,
            use_gzip=not args.no_gzip,
            output_json=args.json,
            output_raw=args.raw,
            output_raw_url=args.raw_url,
        )

    return input_res.map(to_payload).and_then(execute_upload)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    is_atty = sys.stdin.isatty()
    res = run_pipeline(args, is_atty=is_atty)

    match res:
        case Ok(out):
            sys.stdout.write(out)
            return EXIT_SUCCESS
        case Err(err):
            sys.stderr.write(f"Error: {err.message}\n")
            return err.exit_code
        case _ as unreachable:
            assert_never(unreachable)


if __name__ == "__main__":
    raise SystemExit(main())
