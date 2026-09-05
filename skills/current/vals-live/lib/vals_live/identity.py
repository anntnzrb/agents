# Copyright 2026 Vals-live contributors.
"""Conservative source identity and URL canonicalization."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from hashlib import sha256
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "fbclid",
}
_NONWORD = re.compile(r"[^a-z0-9]+")


def canonical_url(value: str) -> str:
    """Canonicalize an official URL without dropping meaningful query fields."""
    value = value.strip()
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return value.rstrip("/")
    query = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), "")
    )


def token(value: str) -> str:
    """Normalize an identity label into a stable token."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    result = _NONWORD.sub("-", normalized).strip("-")
    return result or "unknown"


def stable_id(
    source: str,
    *,
    source_id: object = None,
    url: object = None,
    label: object = None,
    kind: str = "item",
) -> tuple[str, str]:
    """Build a source-scoped identity and record its evidence basis."""
    basis = ""
    identity_basis = "label"
    if isinstance(source_id, str) and source_id.strip():
        basis = source_id.strip()
        identity_basis = "source_id"
    elif isinstance(url, str) and url.strip():
        basis = canonical_url(url)
        identity_basis = "url"
    elif isinstance(label, str) and label.strip():
        basis = label.strip()
    else:
        basis = "unknown"
    stable_basis = basis if identity_basis == "source_id" else token(basis)
    return f"{source}:{kind}:{stable_basis}", identity_basis


def model_id(
    model: object, *, source_id: object = None, url: object = None
) -> tuple[str, str]:
    """Build a stable model identity."""
    return stable_id("vals", source_id=source_id, url=url, label=model, kind="model")


def variant_id(
    base: str, provider: object = None, variant: object = None, harness: object = None
) -> str:
    """Build a model-variant identity from provider, variant, and harness."""
    fields = [
        token(str(value)) if isinstance(value, str) and value else "unknown"
        for value in (provider, variant, harness)
    ]
    return f"{base}:variant:{'-'.join(fields)}"


def snapshot_identity(raw: bytes) -> str:
    """Hash raw bytes into a snapshot identity."""
    return f"snapshot:sha256:{sha256(raw).hexdigest()}"


def release_identity(root: object, raw: bytes) -> tuple[str | None, str]:
    """Return source-defined release/version and always-available snapshot identity."""
    candidates: list[object] = []
    if isinstance(root, Mapping):
        root_map = cast("Mapping[str, object]", root)
        candidates.extend(
            root_map[key]
            for key in (
                "release",
                "release_id",
                "source_release",
                "benchmark_version",
                "version",
            )
            if key in root_map
        )
        metadata = root_map.get("metadata")
        if isinstance(metadata, Mapping):
            meta_map = cast("Mapping[str, object]", metadata)
            candidates.extend(
                meta_map[key]
                for key in (
                    "release",
                    "release_id",
                    "source_release",
                    "benchmark_version",
                    "version",
                )
                if key in meta_map
            )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip(), snapshot_identity(raw)
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            return str(candidate), snapshot_identity(raw)
    return None, snapshot_identity(raw)
