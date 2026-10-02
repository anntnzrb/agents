#!/usr/bin/env -S uv run --script
# Copyright (c) 2026
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "httpx2>=2.13.1",
# ]
# ///
"""Share text and binary files through verified anonymous links."""

import argparse
import gzip
import hashlib
import http
import json
import mimetypes
import re
import sys
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypeIs, TypedDict
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Callable

import httpx2

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
    provider: str = "pastes"
    filename: str = "upload.txt"
    mime_type: str = "text/plain"
    verify: bool = True
    ascii_check: bool = False


class UploadResponse(TypedDict):
    """Wire shape of the bytebin upload response."""

    key: str


def _is_str_dict(val: object) -> TypeIs[dict[str, object]]:
    return isinstance(val, dict)


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


def sniff_content(content: bytes, path: Path | None) -> tuple[bool, str]:
    """Classify UTF-8 text and common binary signatures without changing bytes."""
    for signature, mime in (
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"GIF8", "image/gif"),
        (b"%PDF-", "application/pdf"),
        (b"PK\x03\x04", "application/zip"),
        (b"\x1f\x8b", "application/gzip"),
    ):
        if content.startswith(signature):
            return False, mime
    mime = mimetypes.MimeTypes().guess_type(str(path))[0] if path else None
    try:
        _ = content.decode("utf-8")
    except UnicodeDecodeError:
        return False, mime or "application/octet-stream"
    if b"\0" in content or (
        mime
        and (
            mime.startswith(("image/", "audio/", "video/", "font/"))
            or mime
            in {
                "application/pdf",
                "application/zip",
                "application/gzip",
                "application/octet-stream",
            }
        )
    ):
        return False, mime or "application/octet-stream"
    return True, mime if mime and (
        mime.startswith("text/")
        or mime in {"application/json", "application/xml", "application/javascript"}
        or mime.endswith(("+json", "+xml"))
    ) else "text/plain"


def resolve_fetch_url(base_url: str, value: str) -> str:
    """Resolve supported viewer links to raw URLs, preserving custom API URLs."""
    parsed = urlsplit(value)
    if parsed.scheme:
        base = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError("expected an HTTP URL without credentials")
        if parsed.hostname == "pastes.dev":
            return f"{DEFAULT_BASE_URL}{parsed.path.strip('/')}"
        if parsed.netloc not in {
            "api.pastes.dev",
            "files.catbox.moe",
            "litter.catbox.moe",
            base.netloc,
        }:
            raise ValueError("unsupported provider URL")
        return value
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("expected a paste key or supported URL")
    return f"{base_url.rstrip('/')}/{value}"


def ascii_diagnostic(content: bytes) -> str | None:
    """List non-ASCII codepoints and their Windows-1252 misdecoding."""
    text = content.decode("utf-8")
    characters = sorted({char for char in text if not char.isascii()}, key=ord)
    if not characters:
        return None
    displays = (
        char.encode("utf-8").decode("cp1252", errors="replace") for char in characters
    )
    details = "; ".join(
        f"U+{ord(char):04X} {char!r} displays as {display!r}"
        for char, display in zip(characters, displays, strict=True)
    )
    return f"non-ASCII text without charset=utf-8: {details}"


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
        description="Share text and binaries with verified anonymous direct links.",
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
        help="Output URLs, SHA-256, verification, MIME, and retention as JSON",
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
        metavar="KEY_OR_URL",
        help="Fetch exact bytes from a paste key or supported provider URL",
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
    _ = parser.add_argument("--provider", choices=("pastes", "catbox", "litterbox"))
    _ = parser.add_argument("--filename", help="Override the uploaded filename")
    _ = parser.add_argument(
        "--no-verify", action="store_true", help="Skip download verification"
    )
    _ = parser.add_argument(
        "--ascii-check",
        action="store_true",
        help="Fail on non-ASCII text without a UTF-8 charset",
    )
    _ = parser.add_argument("--sha256", help="Expected SHA-256 for --get")
    return parser


def read_input(
    file_arg: str | None, *, is_atty: bool
) -> Result[tuple[bytes, Path | None], AppError]:
    """Read content from file or stdin as a Railway Result."""
    if file_arg and file_arg != "-":
        input_path = Path(file_arg)
        if not input_path.exists() or not input_path.is_file():
            return Err(AppError(f"file not found: {file_arg}", EXIT_USAGE_ERROR))
        try:
            return Ok((input_path.read_bytes(), input_path))
        except OSError as exc:
            return Err(AppError(f"cannot read file: {exc}", EXIT_USAGE_ERROR))

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
    base_url: str,
    raw_key: str,
    user_agent: str,
    timeout: float,
    expected_sha256: str | None = None,
) -> Result[bytes, AppError]:
    """Fetch exact bytes from a key or supported provider URL."""
    try:
        url = resolve_fetch_url(base_url, raw_key)
    except ValueError as exc:
        return Err(AppError(str(exc), EXIT_USAGE_ERROR))
    headers = {"User-Agent": user_agent}
    try:
        with httpx2.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == http.HTTPStatus.NOT_FOUND:
                return Err(AppError(f"content not found: {url}", EXIT_NETWORK_ERROR))
            _ = resp.raise_for_status()
            if (
                expected_sha256
                and hashlib.sha256(resp.content).hexdigest() != expected_sha256.lower()
            ):
                return Err(AppError("SHA-256 mismatch", EXIT_NETWORK_ERROR))
            return Ok(resp.content)
    except httpx2.HTTPStatusError as exc:
        return Err(
            AppError(
                f"HTTP error {exc.response.status_code}: {exc.response.text}",
                EXIT_NETWORK_ERROR,
            )
        )
    except httpx2.RequestError as exc:
        return Err(AppError(f"Network error: {exc}", EXIT_NETWORK_ERROR))


def format_upload_response(
    key: str,
    payload: UploadPayload,
    raw_url: str,
    content_type: str | None,
    charset: str | None,
) -> str:
    """Format final output string based on CLI presentation flags."""
    view_url = (
        f"https://pastes.dev/{key}"
        if payload.provider == "pastes"
        and urlsplit(payload.base_url).hostname == "api.pastes.dev"
        else raw_url
    )

    if payload.output_json:
        res_obj = {
            "key": key,
            "url": view_url,
            "raw_url": raw_url,
            "language": payload.language,
            "provider": payload.provider,
            "content_type": content_type,
            "charset": charset,
            "bytes": len(payload.content),
            "sha256": hashlib.sha256(payload.content).hexdigest(),
            "verified": payload.verify or payload.ascii_check,
            "retention": {"pastes": "90d", "catbox": "2y-inactive", "litterbox": "72h"}[
                payload.provider
            ],
        }
        return json.dumps(res_obj) + "\n"
    if payload.output_raw:
        return f"{key}\n"
    if payload.output_raw_url:
        return f"{raw_url}\n"
    return f"{view_url}\n"


def post_pastes(client: httpx2.Client, payload: UploadPayload) -> tuple[str, str]:
    """Post text to a pastes-compatible API and validate its key."""
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
    resp = client.post(post_url, headers=headers, content=body)
    _ = resp.raise_for_status()
    decode_json: Callable[..., object] = resp.json
    raw = decode_json()
    if not _is_str_dict(raw):
        raise ValueError("malformed server response")
    key = raw.get("key")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise ValueError("missing or invalid key in server response")
    return key, f"{payload.base_url.rstrip('/')}/{key}"


def post_catbox(client: httpx2.Client, payload: UploadPayload) -> tuple[str, str]:
    """Post a single anonymous file to Catbox or Litterbox."""
    endpoint = (
        "https://catbox.moe/user/api.php"
        if payload.provider == "catbox"
        else "https://litterbox.catbox.moe/resources/internals/api.php"
    )
    data = {"reqtype": "fileupload"}
    if payload.provider == "litterbox":
        data["time"] = "72h"
    resp = client.post(
        endpoint,
        headers={"User-Agent": payload.user_agent},
        data=data,
        files={"fileToUpload": (payload.filename, payload.content, payload.mime_type)},
    )
    _ = resp.raise_for_status()
    raw_url = resp.text.strip()
    parsed = urlsplit(raw_url)
    host = "files.catbox.moe" if payload.provider == "catbox" else "litter.catbox.moe"
    if parsed.scheme != "https" or parsed.netloc != host or not parsed.path.strip("/"):
        raise ValueError("invalid upload URL in server response")
    return parsed.path.rsplit("/", 1)[-1], raw_url


def verify_upload(
    client: httpx2.Client,
    payload: UploadPayload,
    raw_url: str,
) -> Result[tuple[str | None, str | None], AppError]:
    """Download the published bytes and inspect the served MIME metadata."""
    downloaded = client.get(raw_url, headers={"User-Agent": payload.user_agent})
    if downloaded.status_code == http.HTTPStatus.NOT_FOUND:
        return Err(AppError(f"blank upload: 404 at {raw_url}", EXIT_NETWORK_ERROR))
    _ = downloaded.raise_for_status()
    if (
        not downloaded.content
        or hashlib.sha256(downloaded.content).digest()
        != hashlib.sha256(payload.content).digest()
    ):
        return Err(
            AppError(
                f"blank upload or SHA-256 mismatch at {raw_url}", EXIT_NETWORK_ERROR
            )
        )
    content_type = downloaded.headers.get("content-type")
    message = Message()
    if content_type:
        message["content-type"] = content_type
    charset = message.get_content_charset()
    if payload.ascii_check and charset != "utf-8":
        diagnostic = ascii_diagnostic(payload.content)
        if diagnostic:
            return Err(AppError(diagnostic, EXIT_NETWORK_ERROR))
    if not payload.output_json:
        metadata = f"Served content-type: {content_type or 'unknown'}"
        print(
            f"{metadata}; charset: {charset or 'undeclared'}",
            file=sys.stderr,
        )
    return Ok((content_type, charset))


def execute_upload(payload: UploadPayload) -> Result[str, AppError]:
    """Upload once, then verify the returned direct URL before printing it."""
    if not payload.content:
        return Err(AppError("cannot upload empty content", EXIT_USAGE_ERROR))
    if payload.provider == "pastes" and payload.ascii_check:
        diagnostic = ascii_diagnostic(payload.content)
        if diagnostic:
            return Err(AppError(diagnostic, EXIT_USAGE_ERROR))

    try:
        with httpx2.Client(timeout=payload.timeout, follow_redirects=True) as client:
            if payload.provider == "pastes":
                key, raw_url = post_pastes(client, payload)
            else:
                key, raw_url = post_catbox(client, payload)
            content_type = None
            charset = None
            if payload.verify or payload.ascii_check:
                verified = verify_upload(client, payload, raw_url)
                if isinstance(verified, Err):
                    return verified
                content_type, charset = verified.value
            return Ok(
                format_upload_response(key, payload, raw_url, content_type, charset)
            )
    except ValueError as exc:
        return Err(AppError(f"malformed server response: {exc}", EXIT_NETWORK_ERROR))
    except httpx2.HTTPStatusError as exc:
        return Err(
            AppError(
                f"HTTP error {exc.response.status_code}: {exc.response.text}",
                EXIT_NETWORK_ERROR,
            )
        )
    except httpx2.RequestError as exc:
        return Err(AppError(f"Network error: {exc}", EXIT_NETWORK_ERROR))


def _config_str(args: argparse.Namespace, field: str) -> str:
    """Extract a required str option from parsed args."""
    val = getattr(args, field, None)
    if isinstance(val, str):
        return val
    msg = f"expected string for {field}, got {type(val)}"
    raise TypeError(msg)


def _optional_str(args: argparse.Namespace, field: str) -> str | None:
    """Extract an optional str option from parsed args."""
    val = getattr(args, field, None)
    return val if isinstance(val, str) else None


def _config_float(args: argparse.Namespace, field: str) -> float:
    """Extract a required float option from parsed args."""
    val = getattr(args, field, None)
    if isinstance(val, (int, float)):
        return float(val)
    msg = f"expected float for {field}, got {type(val)}"
    raise TypeError(msg)


def _config_bool(args: argparse.Namespace, field: str) -> bool:
    """Extract a required bool flag from parsed args."""
    val = getattr(args, field, None)
    if isinstance(val, bool):
        return val
    msg = f"expected bool for {field}, got {type(val)}"
    raise TypeError(msg)


def run_pipeline(
    args: argparse.Namespace, *, is_atty: bool
) -> Ok[str] | Ok[bytes] | Err[AppError]:
    """Execute upload or fetch workflow."""
    get_key = _optional_str(args, "get")
    expected_sha256 = _optional_str(args, "sha256")
    if expected_sha256 and (
        not get_key or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256)
    ):
        return Err(
            AppError(
                "--sha256 requires --get and a 64-digit hex hash", EXIT_USAGE_ERROR
            )
        )
    if _config_float(args, "timeout") <= 0:
        return Err(AppError("--timeout must be positive", EXIT_USAGE_ERROR))
    if get_key:
        return execute_fetch(
            _config_str(args, "base_url"),
            get_key,
            _config_str(args, "user_agent"),
            _config_float(args, "timeout"),
            expected_sha256,
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

    def to_payload(pair: tuple[bytes, Path | None]) -> Result[UploadPayload, AppError]:
        content, path = pair
        language = detect_language(path, content, lang)
        is_text, mime = sniff_content(content, path)
        provider = _optional_str(args, "provider") or (
            "pastes" if is_text else "catbox"
        )
        if provider == "pastes" and not is_text:
            return Err(
                AppError(
                    "pastes supports text only; use catbox for binary files",
                    EXIT_USAGE_ERROR,
                )
            )
        if _config_bool(args, "ascii_check") and not is_text:
            return Err(AppError("--ascii-check requires UTF-8 text", EXIT_USAGE_ERROR))
        if provider != "pastes" and base_url != DEFAULT_BASE_URL:
            return Err(AppError("--base-url applies only to pastes", EXIT_USAGE_ERROR))
        filename = _optional_str(args, "filename") or (
            path.name if path else "upload.txt"
        )
        if not filename or any(char in filename for char in "\r\n/\\"):
            return Err(
                AppError("--filename must be a nonempty basename", EXIT_USAGE_ERROR)
            )
        return Ok(
            UploadPayload(
                content=content,
                language=language,
                base_url=base_url,
                user_agent=user_agent,
                timeout=timeout,
                use_gzip=use_gzip,
                output_json=output_json,
                output_raw=output_raw,
                output_raw_url=output_raw_url,
                provider=provider,
                filename=filename,
                mime_type=mime,
                verify=not _config_bool(args, "no_verify"),
                ascii_check=_config_bool(args, "ascii_check"),
            )
        )

    return input_res.and_then(to_payload).and_then(execute_upload)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    is_atty = sys.stdin.isatty()
    res = run_pipeline(args, is_atty=is_atty)

    if isinstance(res, Ok):
        if isinstance(res.value, bytes):
            _ = sys.stdout.buffer.write(res.value)
        else:
            _ = sys.stdout.write(res.value)
        return EXIT_SUCCESS
    _ = sys.stderr.write(f"Error: {res.error.message}\n")
    return res.error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
