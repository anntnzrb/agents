# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Package health validation, manifest inspection, and JS/TS import extraction."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import cast

from sync.core.secret_template import strip_jsonc

RESOURCE_KEYS: tuple[str, ...] = ("extensions", "skills", "prompts", "themes")

BUILTIN_PACKAGE_ROOTS: frozenset[str] = frozenset(
    {
        "assert",
        "buffer",
        "child_process",
        "cluster",
        "console",
        "constants",
        "crypto",
        "dgram",
        "diagnostics_channel",
        "dns",
        "domain",
        "events",
        "fs",
        "http",
        "http2",
        "https",
        "inspector",
        "module",
        "net",
        "os",
        "path",
        "perf_hooks",
        "process",
        "punycode",
        "querystring",
        "readline",
        "repl",
        "stream",
        "string_decoder",
        "timers",
        "tls",
        "tty",
        "url",
        "util",
        "v8",
        "vm",
        "worker_threads",
        "zlib",
    }
)

VALID_PACKAGE_ROOT_PATTERN: re.Pattern[str] = re.compile(
    r"^(@[a-z0-9_.-]+/)?[a-z0-9_.-]+$",
    re.IGNORECASE,
)

_SOURCE_EXTENSIONS: tuple[str, ...] = (
    ".ts",
    ".js",
    ".mts",
    ".cts",
    ".mjs",
    ".cjs",
)
_MIN_SCOPED_PARTS = 2


def package_is_healthy(target_dir: str) -> bool:
    """Return True if package dir contains valid resources and no missing imports."""
    if not _is_directory(target_dir):
        return False
    if missing_package_roots(target_dir):
        return False

    package_json_path = str(Path(target_dir) / "package.json")
    if _is_file(package_json_path):
        try:
            package_json = _read_json_file(package_json_path)
            if isinstance(package_json, dict):
                raw_pkg = cast("dict[str, object]", package_json)
                pi = raw_pkg.get("pi")
                if isinstance(pi, dict):
                    raw_pi = cast("dict[str, object]", pi)
                    validated = _validate_pi_manifest(target_dir, raw_pi)
                    if validated is not None:
                        return validated
        except (ValueError, OSError):
            return False

    return any(_exists(str(Path(target_dir) / key)) for key in RESOURCE_KEYS)


def package_has_build_script(target_dir: str) -> bool:
    """Return True if package.json contains a build script entry."""
    package_json_path = str(Path(target_dir) / "package.json")
    if not _is_file(package_json_path):
        return False

    try:
        package_json = _read_json_file(package_json_path)
    except (ValueError, OSError):
        return False

    if not isinstance(package_json, dict):
        return False
    raw_pkg = cast("dict[str, object]", package_json)
    scripts = raw_pkg.get("scripts")
    return isinstance(scripts, dict) and "build" in scripts


def missing_package_roots(target_dir: str) -> list[str]:
    """Scan JS/TS source files and return names of missing node_modules dependencies."""
    missing: set[str] = set()
    for file_path in _package_source_files(target_dir):
        try:
            content = _read_file(file_path)
        except ValueError:
            continue
        for specifier in extract_import_specifiers(content):
            package_root = _package_root_from_specifier(specifier)
            if not package_root or _package_root_is_builtin(package_root):
                continue
            if not _exists(str(Path(target_dir) / "node_modules" / package_root)):
                missing.add(package_root)
    return sorted(missing)


def _handle_import_token(
    tokens: list[tuple[str, str]],
    idx: int,
    prev_tok: tuple[str | None, str | None],
) -> tuple[str | None, int]:
    num_tokens = len(tokens)
    if (
        idx + 2 < num_tokens
        and tokens[idx + 1] == ("PUNCT", "(")
        and prev_tok != ("PUNCT", ".")
        and tokens[idx + 2][0] == "STRING"
    ):
        return (tokens[idx + 2][1], idx + 3)

    if prev_tok == ("PUNCT", "."):
        return (None, idx + 1)

    is_type_only = (
        idx + 1 < num_tokens
        and tokens[idx + 1] == ("IDENT", "type")
        and idx + 2 < num_tokens
        and tokens[idx + 2] not in (("IDENT", "from"), ("PUNCT", ","))
    )

    if idx + 1 < num_tokens and tokens[idx + 1][0] == "STRING":
        return (tokens[idx + 1][1], idx + 2)

    fwd = idx + 1
    while (
        fwd < num_tokens
        and tokens[fwd] != ("PUNCT", ";")
        and tokens[fwd][1] != "import"
    ):
        if tokens[fwd] == ("IDENT", "from"):
            if fwd + 1 < num_tokens and tokens[fwd + 1][0] == "STRING":
                specifier = None if is_type_only else tokens[fwd + 1][1]
                return (specifier, fwd + 2)
            break
        fwd += 1
    return (None, idx + 1)


def _handle_export_token(
    tokens: list[tuple[str, str]],
    idx: int,
    prev_tok: tuple[str | None, str | None],
) -> tuple[str | None, int]:
    if prev_tok == ("PUNCT", "."):
        return (None, idx + 1)
    num_tokens = len(tokens)
    is_type_only = idx + 1 < num_tokens and tokens[idx + 1] == ("IDENT", "type")
    fwd = idx + 1
    while (
        fwd < num_tokens
        and tokens[fwd] != ("PUNCT", ";")
        and tokens[fwd][1] != "export"
    ):
        if tokens[fwd] == ("IDENT", "from"):
            if fwd + 1 < num_tokens and tokens[fwd + 1][0] == "STRING":
                specifier = None if is_type_only else tokens[fwd + 1][1]
                return (specifier, fwd + 2)
            break
        fwd += 1
    return (None, idx + 1)


def _handle_require_token(
    tokens: list[tuple[str, str]],
    idx: int,
    prev_tok: tuple[str | None, str | None],
) -> tuple[str | None, int]:
    num_tokens = len(tokens)
    if (
        prev_tok != ("PUNCT", ".")
        and idx + 2 < num_tokens
        and tokens[idx + 1] == ("PUNCT", "(")
        and tokens[idx + 2][0] == "STRING"
    ):
        return (tokens[idx + 2][1], idx + 3)
    return (None, idx + 1)


def extract_import_specifiers(content: str) -> list[str]:
    """Extract runtime ESM/CJS import specifiers from JS/TS source code."""
    tokens = _tokenize_source(content)
    specifiers: list[str] = []
    num_tokens = len(tokens)

    idx = 0
    while idx < num_tokens:
        tok_type, tok_val = tokens[idx]
        prev_tok = tokens[idx - 1] if idx > 0 else (None, None)

        if tok_type == "IDENT":
            if tok_val == "import":
                spec, next_idx = _handle_import_token(tokens, idx, prev_tok)
                if spec is not None:
                    specifiers.append(spec)
                idx = next_idx
                continue
            if tok_val == "export":
                spec, next_idx = _handle_export_token(tokens, idx, prev_tok)
                if spec is not None:
                    specifiers.append(spec)
                idx = next_idx
                continue
            if tok_val == "require":
                spec, next_idx = _handle_require_token(tokens, idx, prev_tok)
                if spec is not None:
                    specifiers.append(spec)
                idx = next_idx
                continue
        idx += 1

    return specifiers


def _skip_comment(content: str, idx: int) -> int:
    length = len(content)
    if idx + 1 < length and content[idx + 1] == "/":
        idx += 2
        while idx < length and content[idx] != "\n":
            idx += 1
        return idx
    if idx + 1 < length and content[idx + 1] == "*":
        idx += 2
        while idx + 1 < length and not (
            content[idx] == "*" and content[idx + 1] == "/"
        ):
            idx += 1
        return idx + 2
    return idx


def _scan_string(content: str, idx: int) -> tuple[str, int]:
    quote = content[idx]
    idx += 1
    length = len(content)
    chars: list[str] = []
    while idx < length and content[idx] != quote:
        if content[idx] == "\\" and idx + 1 < length:
            idx += 1
            chars.append(content[idx])
        else:
            chars.append(content[idx])
        idx += 1
    if idx < length:
        idx += 1
    return ("".join(chars), idx)


def _scan_template_tail(
    content: str,
    idx: int,
    template_stack: list[int],
) -> int:
    length = len(content)
    while idx < length:
        if content[idx] == "`":
            return idx + 1
        if content[idx] == "$" and idx + 1 < length and content[idx + 1] == "{":
            template_stack.append(0)
            return idx + 2
        if content[idx] == "\\" and idx + 1 < length:
            idx += 2
        else:
            idx += 1
    return idx


def _scan_ident(content: str, idx: int) -> tuple[str, int]:
    start = idx
    length = len(content)
    while idx < length and (content[idx].isalnum() or content[idx] in "_$"):
        idx += 1
    return (content[start:idx], idx)


def _handle_template_brace(
    content: str,
    idx: int,
    template_stack: list[int],
    tokens: list[tuple[str, str]],
) -> int:
    ch = content[idx]
    if ch == "{":
        template_stack[-1] += 1
        tokens.append(("PUNCT", "{"))
        return idx + 1
    if ch == "}":
        if template_stack[-1] == 0:
            template_stack.pop()
            return _scan_template_tail(content, idx + 1, template_stack)
        template_stack[-1] -= 1
        tokens.append(("PUNCT", "}"))
        return idx + 1
    return idx


def _tokenize_source(content: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    idx = 0
    length = len(content)
    template_stack: list[int] = []

    while idx < length:
        ch = content[idx]

        if ch == "/" and idx + 1 < length and content[idx + 1] in ("/", "*"):
            idx = _skip_comment(content, idx)
            continue

        if ch in ("'", '"'):
            s, idx = _scan_string(content, idx)
            tokens.append(("STRING", s))
            continue

        if ch == "`":
            idx = _scan_template_tail(content, idx + 1, template_stack)
            continue

        if template_stack and ch in ("{", "}"):
            idx = _handle_template_brace(content, idx, template_stack, tokens)
            continue

        if ch.isspace():
            idx += 1
            continue

        if ch in "(){}[];,.*:":
            tokens.append(("PUNCT", ch))
            idx += 1
            continue

        if ch.isalpha() or ch in "_$":
            ident, idx = _scan_ident(content, idx)
            tokens.append(("IDENT", ident))
            continue

        idx += 1

    return tokens


def _package_root_from_specifier(specifier: str) -> str | None:
    trimmed = specifier.strip()
    if (
        not trimmed
        or trimmed.startswith((".", "/", "node:", "bun:", "data:"))
        or trimmed == "bun"
    ):
        return None
    if trimmed.startswith("@"):
        parts = trimmed[1:].split("/")
        if len(parts) < _MIN_SCOPED_PARTS or not parts[0] or not parts[1]:
            return None
        root = f"@{parts[0]}/{parts[1]}"
    else:
        root = trimmed.split("/")[0]

    if not VALID_PACKAGE_ROOT_PATTERN.match(root):
        return None
    return root


def _package_root_is_builtin(package_root: str) -> bool:
    return package_root in BUILTIN_PACKAGE_ROOTS


def _validate_pi_manifest(target_dir: str, pi: dict[str, object]) -> bool | None:
    has_entries = False
    for key in RESOURCE_KEYS:
        entries = pi.get(key)
        if not isinstance(entries, list):
            continue
        raw_entries = cast("list[object]", entries)
        for entry in raw_entries:
            if not isinstance(entry, str):
                continue
            if _is_pattern_entry(entry):
                continue
            has_entries = True
            if not _exists(str(Path(target_dir) / entry)):
                return False
    return True if has_entries else None


def _is_pattern_entry(value: str) -> bool:
    return value.startswith(("!", "+", "-")) or "*" in value or "?" in value


def _read_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as error:
        message = f"read {path} ({error})"
        raise ValueError(message) from error


def _read_json_file(path: str) -> object:
    content = _read_file(path)
    try:
        return json.loads(strip_jsonc(content))
    except (ValueError, TypeError) as error:
        message = f"parse {path} ({error})"
        raise ValueError(message) from error


def _package_source_files(root: str) -> list[str]:
    if not _is_directory(root):
        return []
    files: list[str] = []
    try:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
            dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git")]
            files.extend(
                str(Path(dirpath) / filename)
                for filename in filenames
                if filename.endswith(_SOURCE_EXTENSIONS)
            )
    except OSError:
        return []
    return files


def _is_directory(path: str) -> bool:
    try:
        return Path(path).is_dir()
    except OSError:
        return False


def _is_file(path: str) -> bool:
    try:
        return Path(path).is_file()
    except OSError:
        return False


def _exists(path: str) -> bool:
    try:
        return Path(path).exists()
    except OSError:
        return False
