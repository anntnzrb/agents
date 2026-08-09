# Copyright (c) 2026
"""Deterministic, source-namespaced identities for dynamic LiveBench rows."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
    }
)
_NON_WORD = re.compile(r"[^a-z0-9]+")


def canonical_token(value: object) -> str:
    """Canonical token for the LiveBench adapter."""
    text = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    text = _NON_WORD.sub("-", text).strip("-")
    return text or "unknown"


def canonical_url(value: str) -> str:
    """Canonical url for the LiveBench adapter."""
    parts = urlsplit(value.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.casefold() not in _TRACKING
    ]
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(
        (parts.scheme.casefold(), parts.netloc.casefold(), path, urlencode(query), "")
    )


def release_id(value: object) -> str:
    """Release id for the LiveBench adapter."""
    return f"livebench:release:{canonical_token(value)}"


def category_id(label: object) -> str:
    """Category id for the LiveBench adapter."""
    return f"livebench:category:{canonical_token(label)}"


def subtask_id(key: object) -> str:
    """Subtask id for the LiveBench adapter."""
    return f"livebench:subtask:{canonical_token(key)}"


def model_id(slug: object) -> str:
    """Model id for the LiveBench adapter."""
    return f"livebench:model:{canonical_token(slug)}"


def variant_id(slug: object, provider: object = None, variant: object = None) -> str:
    """Variant id for the LiveBench adapter."""
    model_part = canonical_token(slug)
    provider_part = canonical_token(provider) if provider not in (None, "") else "none"
    variant_part = canonical_token(variant) if variant not in (None, "") else "base"
    return (
        f"livebench:model:{model_part}:provider:{provider_part}:variant:{variant_part}"
    )


def identity_tuple(row: dict[str, object]) -> tuple[str, str | None, str | None]:
    """Identity tuple for the LiveBench adapter."""
    model = str(row.get("model_slug") or row.get("model") or "")
    provider = row.get("provider")
    variant = row.get("variant")
    return (
        model,
        str(provider) if provider not in (None, "") else None,
        str(variant) if variant not in (None, "") else None,
    )
