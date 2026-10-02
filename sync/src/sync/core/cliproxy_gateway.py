# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Render the standalone System One facade's private runtime configuration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, ClassVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sync.core.cliproxy_deployment import cliproxy_listen_origin

if TYPE_CHECKING:
    from pathlib import Path

    from sync.core.cliproxy_deployment import CliProxyDeployment

GATEWAY_CONFIG = "gateway.json"
GATEWAY_SCRIPT = "gateway.py"
SYSTEM_ONE_POOL = "openrouter"
SYSTEM_ONE_PROVIDER = "openrouter"


class SystemOneProfile(BaseModel):
    """Non-secret upstream protocol and explicit model allowlist."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid", frozen=True, strict=True, populate_by_name=True
    )
    base_url: str = Field(alias="baseUrl")
    models: list[Annotated[str, Field(min_length=1, pattern=r"^\S+$")]] = Field(
        min_length=1
    )

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            value != value.strip()
            or parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/").split("/")[-1] != "v1"
            or (
                parsed.scheme == "http"
                and parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            )
        ):
            msg = (
                "gateway baseUrl must be an HTTPS /v1 endpoint (HTTP only on loopback)"
            )
            raise ValueError(msg)
        _ = parsed.port
        return value.rstrip("/")

    @field_validator("models")
    @classmethod
    def _validate_models(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            msg = "gateway models must be unique"
            raise ValueError(msg)
        return values


class GatewayProfile(BaseModel):
    """Source-owned configuration; listeners and credentials come from sync."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True)
    system_one: SystemOneProfile = Field(alias="systemOne")


def read_gateway_profile(source: Path) -> GatewayProfile:
    """Read the source profile only when its credential pool is configured."""
    try:
        return GatewayProfile.model_validate_json(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        msg = f"invalid gateway profile {source}"
        raise ValueError(msg) from error


def render_gateway_config(
    profile: GatewayProfile | None,
    deployment: CliProxyDeployment,
    credentials: list[dict[str, object]],
) -> str | None:
    """Validate activation before any files are published; return private JSON."""
    if deployment.gateway is None:
        return None
    if profile is None or not credentials:
        msg = "gateway requires the openrouter credential pool"
        raise ValueError(msg)
    result = {
        "listen": deployment.gateway.model_dump(),
        "upstream": cliproxy_listen_origin(deployment.listen),
        "systemOne": profile.system_one.model_dump(by_alias=True)
        | {"apiKeyEntries": credentials},
    }
    return json.dumps(result, indent=2) + "\n"
