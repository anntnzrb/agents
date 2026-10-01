# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Boundary parsing for static CDN release manifests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from sync.runtime.errors import panic_message
from sync.runtime.http import get_ok
from sync.runtime.jsonc import is_obj_dict

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "ChecksumAlgorithm",
    "StaticReleaseAsset",
    "StaticReleaseManifest",
    "fetch_static_release_manifest",
]

COMPONENT_PATTERN = r"^[A-Za-z0-9._-]+$"
SHA256_PATTERN = r"^[a-f0-9]{64}$"
SHA512_PATTERN = r"^[a-f0-9]{128}$"

type ChecksumAlgorithm = Literal["sha256", "sha512"]


class StaticReleaseAsset(BaseModel):
    """Platform bundle URL and checksum from a static release manifest."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    url: str
    sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    sha512: str | None = Field(default=None, pattern=SHA512_PATTERN)

    @model_validator(mode="after")
    def _require_checksum(self) -> Self:
        if self.sha256 is None and self.sha512 is None:
            message = "asset requires a sha256 or sha512 checksum"
            raise ValueError(message)
        return self

    @property
    def checksum(self) -> tuple[ChecksumAlgorithm, str]:
        """Return the strongest declared digest with its algorithm."""
        if self.sha512 is not None:
            return ("sha512", self.sha512)
        if self.sha256 is not None:
            return ("sha256", self.sha256)
        message = "asset has no checksum"
        raise RuntimeError(message)


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
    target: str | None = None,
) -> StaticReleaseManifest:
    """Fetch and validate a static release manifest from a URL.

    With ``target``, the URL serves one platform's ``{version, url, <digest>}``
    document, which is returned as a manifest whose only platform is ``target``.
    """
    if fetch is not None:
        return fetch(url, timeout_ms)
    response = get_ok(url, timeout_ms, "release manifest fetch failed")
    try:
        parsed: object = json.loads(response.text)  # pyright: ignore[reportAny]
    except (ValueError, TypeError) as exc:
        message = f"release manifest parse failed ({panic_message(exc)})"
        raise RuntimeError(message) from exc

    if target is not None and is_obj_dict(parsed):
        parsed = {"version": parsed.get("version"), "platforms": {target: parsed}}
    try:
        return StaticReleaseManifest.model_validate(parsed)
    except ValidationError as exc:
        message = f"invalid release manifest ({panic_message(exc)})"
        raise RuntimeError(message) from exc
