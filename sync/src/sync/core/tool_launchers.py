# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""npm-installed tool launcher specifications and default argument helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sync.core.harness import SyncEnv

__all__ = [
    "TOOL_LAUNCHERS",
    "ToolLauncherSpec",
    "tool_launcher",
    "tool_launcher_default_args",
]


@dataclass(frozen=True, slots=True)
class ToolLauncherSpec:
    """Specification for an external npm-installed tool launcher."""

    id: str
    package: str
    bin: str
    dist_tag: str | None = None
    smoke_check: str | None = None
    default_args: tuple[str, ...] = ()
    config_home_segments: tuple[str, ...] = ()


TOOL_LAUNCHERS: tuple[ToolLauncherSpec, ...] = (
    ToolLauncherSpec(
        id="mcporter",
        package="mcporter",
        bin="mcporter",
        config_home_segments=(".mcporter", "mcporter.json"),
    ),
    ToolLauncherSpec(
        id="summarize",
        package="@steipete/summarize",
        bin="summarize",
        default_args=(
            "--force-summary",
            "--timestamps",
            "--format",
            "md",
            "--retries",
            "2",
            "--metrics",
            "detailed",
        ),
    ),
)


def tool_launcher(tool_id: str) -> ToolLauncherSpec | None:
    """Find a registered tool launcher spec by id."""
    for tool in TOOL_LAUNCHERS:
        if tool.id == tool_id:
            return tool
    return None


def tool_launcher_default_args(
    sync_env: SyncEnv,
    tool: ToolLauncherSpec,
) -> list[str]:
    """Compute default launcher CLI arguments including config path if configured."""
    config_args: list[str] = []
    if tool.config_home_segments:
        config_path = str(Path(sync_env.home).joinpath(*tool.config_home_segments))
        config_args = ["--config", config_path]
    return [*config_args, *tool.default_args]
