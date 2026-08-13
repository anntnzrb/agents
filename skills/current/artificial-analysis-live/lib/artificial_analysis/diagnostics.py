# Copyright (c) 2026 anntnzrb
"""Stable diagnostics and credential-safe projections for Artificial Analysis."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Final
from urllib.parse import quote, unquote_plus, urlsplit, urlunsplit

from .contracts import (
    DIAGNOSTIC_CODES,
    DIAGNOSTIC_SEVERITIES,
    Diagnostic,
    compact_json,
)

# Public aliases keep the catalog discoverable without coupling callers to the
# contracts implementation details.
CODES = DIAGNOSTIC_CODES
SEVERITIES = DIAGNOSTIC_SEVERITIES

REDACTED: Final[str] = "[REDACTED]"

# Metrics contain the word token legitimately.  Only credential-shaped token
# keys are sensitive; these metric forms stay observable in diagnostics.
_SAFE_TOKEN_KEY_PARTS: Final[frozenset[str]] = frozenset(
    {
        "answer",
        "cache",
        "count",
        "input",
        "output",
        "reasoning",
        "task",
        "total",
        "cost",
        "latency",
        "rate",
        "per",
        "tokens",
    }
)

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----", re.IGNORECASE
)
_BEARER_RE = re.compile(r"(\bbearer\s+)([^\s,;]+)", re.IGNORECASE)
_BASIC_RE = re.compile(r"(\bbasic\s+)([^\s,;]+)", re.IGNORECASE)
_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(\b(?:api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|auth[-_ ]?token|"
    r"password|secret|bearer|token|private[-_ ]?key)\s*[=:]\s*)([^\s&;,]+)",
    re.IGNORECASE,
)


def _key_parts(key: object) -> tuple[str, ...]:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
    return tuple(part for part in normalized.split("_") if part)


def _sensitive_key(key: object) -> bool:
    parts = _key_parts(key)
    sensitive = False
    if parts:
        joined = "_".join(parts)
        sensitive = any(
            marker in joined
            for marker in (
                "private_key",
                "privatekey",
                "password",
                "passwd",
                "secret",
                "credential",
            )
        )
        if not sensitive:
            sensitive = any(
                marker in parts
                for marker in (
                    "authorization",
                    "proxy_authorization",
                    "cookie",
                    "set_cookie",
                    "bearer",
                )
            )
        if not sensitive and "api" in parts:
            sensitive = any(part in parts for part in ("key", "keys"))
        if not sensitive:
            sensitive = joined in {
                "token",
                "access_token",
                "refresh_token",
                "id_token",
                "auth_token",
                "session_token",
                "csrf_token",
                "oauth_token",
            }
        if not sensitive and ("token" in parts or "tokens" in parts):
            # A metric key such as output_tokens or token_count is not a secret.
            sensitive = not set(parts) & _SAFE_TOKEN_KEY_PARTS
    return sensitive


def _redact_query_text(query: str) -> str:
    """Redact sensitive query values while preserving safe query text."""
    if not query:
        return query
    pieces: list[str] = []
    changed = False
    for piece in query.split("&"):
        key, separator, _ = piece.partition("=")
        if _sensitive_key(unquote_plus(key)):
            replacement = quote(REDACTED, safe="[]") if separator else REDACTED
            pieces.append(f"{key}{separator}{replacement}")
            changed = True
        else:
            pieces.append(piece)
    return "&".join(pieces) if changed else query


def redact_query(value: str) -> str:
    """Redact credential-bearing query parameters in a URL or query string."""
    if not isinstance(value, str):
        return value
    if "://" in value or value.startswith(("/", "?", "#")):
        parsed = urlsplit(value)
        redacted_query = _redact_query_text(parsed.query)
        redacted_fragment = _redact_query_text(parsed.fragment)
        if redacted_query == parsed.query and redacted_fragment == parsed.fragment:
            return value
        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                redacted_query,
                redacted_fragment,
            )
        )
    # A bare query is useful in diagnostics too, but do not reinterpret prose
    # containing a question mark as a query unless it has key=value syntax.
    if "=" not in value:
        return value
    return _redact_query_text(value)


def _redact_string(value: str) -> str:
    value = redact_query(value)
    if _PRIVATE_KEY_RE.search(value):
        return REDACTED
    value = _BEARER_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", value)
    value = _BASIC_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", value)
    return _CREDENTIAL_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{REDACTED}",
        value,
    )


def redact(value: object, *, _sensitive: bool = False) -> object:
    """Recursively redact credential keys and values without hiding metrics."""
    if _sensitive:
        value = REDACTED
    elif isinstance(value, Mapping):
        value = {
            key: redact(item, _sensitive=_sensitive_key(key))
            for key, item in value.items()
        }
    elif isinstance(value, list):
        value = [redact(item) for item in value]
    elif isinstance(value, tuple):
        value = tuple(redact(item) for item in value)
    elif isinstance(value, set):
        value = {redact(item) for item in value}
    elif isinstance(value, frozenset):
        value = frozenset(redact(item) for item in value)
    elif isinstance(value, str):
        value = _redact_string(value)
    return value


def _as_diagnostic(value: Diagnostic | Mapping[object, object]) -> Diagnostic:
    if isinstance(value, Diagnostic):
        return value
    # Accepting a plain mapping keeps merge useful at a JSON boundary while
    # retaining one canonical Diagnostic shape.
    return Diagnostic(
        code=str(value.get("code", "")),
        severity=str(value.get("severity", "")),
        stage=str(value.get("stage", "")),
        message=str(value.get("message", "")),
        source_path=(
            str(value["source_path"]) if value.get("source_path") is not None else None
        ),
        artifact_id=(
            str(value["artifact_id"]) if value.get("artifact_id") is not None else None
        ),
        details=value.get("details"),
    )


def merge_diagnostics(
    *groups: Iterable[Diagnostic | Mapping[object, object]]
    | Diagnostic
    | Mapping[object, object],
) -> list[Diagnostic]:
    """Merge diagnostics in first-seen order, dropping exact duplicates."""
    merged: list[Diagnostic] = []
    seen: set[str] = set()
    for group in groups:
        if isinstance(group, (Diagnostic, Mapping)):
            items: Iterable[Diagnostic | Mapping[object, object]] = (group,)
        else:
            items = group
        for item in items:
            diagnostic = _as_diagnostic(item)
            key = compact_json(diagnostic.to_dict())
            if key in seen:
                continue
            seen.add(key)
            merged.append(diagnostic)
    return merged


__all__ = ["REDACTED", "Diagnostic", "merge_diagnostics", "redact", "redact_query"]
