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
from typing import TYPE_CHECKING, Final, TypedDict, cast

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

    def map[U](self, _fn: Callable[..., U]) -> Err[E]:
        """Pass error through unchanged on map."""
        return self

    def and_then[U](self, _fn: Callable[..., Result[U, E]]) -> Err[E]:
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


class UploadResponse(TypedDict):
    """Wire shape of the bytebin upload response."""

    key: str


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


EPILOG_EXAMPLES: Final[str] = """
examples:
  # Upload a local file (auto-detects language from extension)
  webpaste src/main.rs

  # Pipe generated code or logs via stdin with language override
  git diff | webpaste -l diff
  cat query.sql | webpaste -l sql

  # Structured JSON output for agents and automation
  webpaste --json src/config.json

  # Retrieve existing paste content by key
  webpaste --get <KEY>

  # Output direct raw content URL
  webpaste --raw-url src/app.py

supported languages:
  plain, log, yaml, json, xml, ini, java, javascript, typescript,
  python, kotlin, scala, cpp, csharp, shell, ruby, rust, sql, go,
  lua, swift, c, html, css, scss, php, graphql, diff, dockerfile,
  markdown, proto
"""


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Upload code or text to pastes.dev.",
        epilog=EPILOG_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _ = parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="Path to file to upload (reads from stdin if omitted or '-')",
    )
    _ = parser.add_argument(
        "-l",
        "--lang",
        help="Explicit language identifier or alias (e.g. python, py, ts, diff, json)",
    )
    _ = parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON payload (key, url, and raw_url)",
    )
    _ = parser.add_argument(
        "--raw",
        action="store_true",
        help="Output only the paste key",
    )
    _ = parser.add_argument(
        "--raw-url",
        action="store_true",
        help="Output direct raw content URL",
    )
    _ = parser.add_argument(
        "--get",
        metavar="KEY",
        help="Fetch content of an existing paste by key",
    )
    _ = parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base API URL (default: {DEFAULT_BASE_URL})",
    )
    _ = parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help=f"User-Agent header string (default: {DEFAULT_USER_AGENT})",
    )
    _ = parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    _ = parser.add_argument(
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

    no_input_guide = (
        "no input provided. Pass a file path or pipe content via stdin.\n"
        "Run with --help for options and examples:\n"
        "  webpaste src/server.ts\n"
        "  git diff | webpaste -l diff\n"
        "  webpaste --get <KEY>"
    )

    if is_atty:
        return Err(AppError(no_input_guide, EXIT_USAGE_ERROR))

    stdin_bytes = sys.stdin.buffer.read()
    if not stdin_bytes:
        return Err(AppError(no_input_guide, EXIT_USAGE_ERROR))

    return Ok((stdin_bytes, None))


def execute_fetch(
    base_url: str, raw_key: str, user_agent: str, timeout: float
) -> Result[str, AppError]:
    """Fetch existing paste content from bytebin."""
    key = raw_key.strip().rstrip("/").split("/")[-1]
    url = f"{base_url.rstrip('/')}/{key}"
    headers = {"User-Agent": user_agent}
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == http.HTTPStatus.NOT_FOUND:
                return Err(
                    AppError(f"paste not found for key: {key}", EXIT_NETWORK_ERROR)
                )
            _ = resp.raise_for_status()
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
            _ = resp.raise_for_status()
            data = cast("UploadResponse", resp.json())
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


def _config_str(args: argparse.Namespace, field: str) -> str:
    """Extract a required str option from parsed args."""
    return cast("str", getattr(args, field))


def _optional_str(args: argparse.Namespace, field: str) -> str | None:
    """Extract an optional str option from parsed args."""
    return cast("str | None", getattr(args, field))


def _config_float(args: argparse.Namespace, field: str) -> float:
    """Extract a required float option from parsed args."""
    return cast("float", getattr(args, field))


def _config_bool(args: argparse.Namespace, field: str) -> bool:
    """Extract a required bool flag from parsed args."""
    return cast("bool", getattr(args, field))


def run_pipeline(args: argparse.Namespace, *, is_atty: bool) -> Result[str, AppError]:
    """Execute upload or fetch workflow."""
    get_key = _optional_str(args, "get")
    if get_key:
        return execute_fetch(
            _config_str(args, "base_url"),
            get_key,
            _config_str(args, "user_agent"),
            _config_float(args, "timeout"),
        )

    file_arg = _optional_str(args, "file")
    lang = _optional_str(args, "lang")
    base_url = _config_str(args, "base_url")
    user_agent = _config_str(args, "user_agent")
    timeout = _config_float(args, "timeout")
    use_gzip = not _config_bool(args, "no_gzip")
    output_json = _config_bool(args, "json")
    output_raw = _config_bool(args, "raw")
    output_raw_url = _config_bool(args, "raw_url")

    input_res = read_input(file_arg, is_atty=is_atty)

    def to_payload(pair: tuple[bytes, Path | None]) -> UploadPayload:
        content, path = pair
        language = detect_language(path, content, lang)
        return UploadPayload(
            content=content,
            language=language,
            base_url=base_url,
            user_agent=user_agent,
            timeout=timeout,
            use_gzip=use_gzip,
            output_json=output_json,
            output_raw=output_raw,
            output_raw_url=output_raw_url,
        )

    return input_res.map(to_payload).and_then(execute_upload)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    is_atty = sys.stdin.isatty()
    res = run_pipeline(args, is_atty=is_atty)

    if isinstance(res, Ok):
        _ = sys.stdout.write(res.value)
        return EXIT_SUCCESS
    _ = sys.stderr.write(f"Error: {res.error.message}\n")
    return res.error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
