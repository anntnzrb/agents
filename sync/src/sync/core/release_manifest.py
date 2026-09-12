# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Boundary parsing for static CDN release manifests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, ClassVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sync.runtime.errors import panic_message

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "StaticReleaseAsset",
    "StaticReleaseManifest",
    "fetch_static_release_manifest",
]

COMPONENT_PATTERN = r"^[A-Za-z0-9._-]+$"
SHA256_PATTERN = r"^[a-f0-9]{64}$"
HTTP_OK = 200
MS_PER_SECOND = 1000.0


class StaticReleaseAsset(BaseModel):
    """Platform bundle URL and checksum from a static release manifest."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    url: str
    sha256: str = Field(pattern=SHA256_PATTERN)


class StaticReleaseManifest(BaseModel):
    """Static release manifest describing the current version and platforms."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    version: str = Field(pattern=COMPONENT_PATTERN)
    platforms: dict[str, StaticReleaseAsset]


type FetchManifestFn = Callable[[str, int], StaticReleaseManifest]


def fetch_static_release_manifest(
    url: str,
    timeout_ms: int,
    fetch: FetchManifestFn | None = None,
) -> StaticReleaseManifest:
    """Fetch and validate a static release manifest from a URL."""
    if fetch is not None:
        return fetch(url, timeout_ms)
    timeout_sec = timeout_ms / MS_PER_SECOND
    try:
        response = httpx.get(url, timeout=timeout_sec, follow_redirects=True)
    except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
        message = f"release manifest fetch failed ({panic_message(exc)})"
        raise RuntimeError(message) from exc

    if response.status_code != HTTP_OK:
        message = f"release manifest fetch failed with HTTP {response.status_code}"
        raise RuntimeError(message)

    try:
        parsed: object = json.loads(response.text)  # pyright: ignore[reportAny]
    except (ValueError, TypeError) as exc:
        message = f"release manifest parse failed ({panic_message(exc)})"
        raise RuntimeError(message) from exc

    try:
        return StaticReleaseManifest.model_validate(parsed)
    except ValidationError as exc:
        message = f"invalid release manifest ({panic_message(exc)})"
        raise RuntimeError(message) from exc
