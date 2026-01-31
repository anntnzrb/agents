#!/usr/bin/env -S uv run python
"""Sync agent config files and tool assets into user tool homes."""

from __future__ import annotations

import functools
import itertools
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator


AGENTS_HOME = Path.home() / ".config" / "agents"
ASSETS_HOME = AGENTS_HOME / "assets"
TOOLS_HOME = AGENTS_HOME / "tools"

MCPORTER_HOME = Path.home() / ".mcporter"

DEFAULT_AGENT_FILE = "AGENTS.md"

INSTALL_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class ToolConfig:
    """Config for a target tool home and related sync rules."""

    home: Path
    agent_file: str = DEFAULT_AGENT_FILE
    asset_renames: dict[str, str] = field(default_factory=dict)
    tool_subdir: Path | None = None


TOOL_CONFIG: dict[str, ToolConfig] = {
    "claude": ToolConfig(Path.home() / ".claude", agent_file="CLAUDE.md"),
    "codex": ToolConfig(Path.home() / ".codex"),
    "opencode": ToolConfig(Path.home() / ".config" / "opencode"),
    "pi": ToolConfig(
        Path.home() / ".pi",
        asset_renames={"commands": "prompts"},
        tool_subdir=Path("agent"),
    ),
}


JobKind = Literal["file", "dir"]


@dataclass(frozen=True)
class Job:
    """Single sync job mapping a source to a destination."""

    src: Path
    dst: Path
    kind: JobKind


def guard(func: Callable[..., bool]) -> Callable[..., bool]:
    """Wrap a sync handler with error reporting."""

    @functools.wraps(func)
    def wrapper(*args: object, **kwargs: object) -> bool:
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            # Defensive: keep sync from crashing on unexpected errors.
            err(f"unexpected error in {func.__name__}: {exc}")
            return False

    return wrapper


def err(message: str) -> None:
    """Print a sync error to stderr."""
    print(f"sync: {message}", file=sys.stderr)


def ensure_dir(path: Path) -> None:
    """Ensure a directory exists."""
    path.mkdir(parents=True, exist_ok=True)


def rm_entry(path: Path) -> None:
    """Remove a file, symlink, or directory if present."""
    if path.is_symlink():
        try:
            path.unlink()
        except FileNotFoundError:
            return
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return


def tool_root(tool: ToolConfig) -> Path:
    """Resolve the destination root for a tool."""
    if tool.tool_subdir is None:
        return tool.home
    return tool.home / tool.tool_subdir


def tool_dirs() -> list[Job]:
    """Build jobs to sync tool configs."""
    jobs: list[Job] = []
    for tool_name, tool in TOOL_CONFIG.items():
        src = TOOLS_HOME / tool_name
        dst = tool_root(tool)
        if tool.tool_subdir is not None:
            src = src / tool.tool_subdir
        jobs.append(Job(src, dst, "dir"))
    return jobs


def asset_copies() -> list[Job]:
    """Build jobs to sync assets into tool homes."""
    if not ASSETS_HOME.is_dir():
        return []
    jobs: list[Job] = []
    for asset_path in (path for path in ASSETS_HOME.iterdir() if path.is_dir()):
        asset_name = asset_path.name
        for tool in TOOL_CONFIG.values():
            dest_root = tool_root(tool)
            dest_name = tool.asset_renames.get(asset_name, asset_name)
            jobs.append(Job(asset_path, dest_root / dest_name, "dir"))
    return jobs


def agent_files() -> list[Job]:
    """Build jobs to sync agent instruction files."""
    return [
        Job(ASSETS_HOME / DEFAULT_AGENT_FILE, tool_root(tool) / tool.agent_file, "file")
        for tool in TOOL_CONFIG.values()
    ]


def config_files() -> list[Job]:
    """Build jobs to sync global config files."""
    return [
        Job(ASSETS_HOME / "mcporter.jsonc", MCPORTER_HOME / "mcporter.json", "file"),
    ]


@guard
def copy_item(src: Path, dst: Path) -> bool:
    """Copy a file or directory to a destination."""
    if not src.exists() and not src.is_symlink():
        err(f"missing source: {src}")
        return True
    ensure_dir(dst.parent)
    rm_entry(dst)
    try:
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=False)
        else:
            shutil.copy2(src, dst)
    except OSError as exc:
        err(f"copy failed: {src} -> {dst} ({exc})")
        return False
    return True


@guard
def copy_dir_into(src_dir: Path, dst_dir: Path) -> bool:
    """Copy a directory into an existing destination directory."""
    if not src_dir.is_dir():
        err(f"missing directory: {src_dir}")
        return True
    ensure_dir(dst_dir)
    try:
        shutil.copytree(
            src_dir,
            dst_dir,
            symlinks=False,
            dirs_exist_ok=True,
            copy_function=shutil.copy2,
        )
    except OSError as exc:
        err(f"copy failed: {src_dir} -> {dst_dir} ({exc})")
        return False
    return True


HANDLERS: dict[JobKind, Callable[[Path, Path], bool]] = {
    "dir": copy_dir_into,
    "file": copy_item,
}


def iter_jobs(builders: Iterable[Callable[[], Iterable[Job]]]) -> Iterator[Job]:
    """Iterate over all jobs from job builders."""
    return itertools.chain.from_iterable(builder() for builder in builders)


def run_jobs(jobs: Iterable[Job]) -> bool:
    """Run all jobs and return success."""
    return all(HANDLERS[job.kind](job.src, job.dst) for job in jobs)


def iter_extension_packages(root: Path) -> Iterator[Path]:
    """Yield extension package roots below a given root."""
    if not root.is_dir():
        return
    for current, dirnames, filenames in os.walk(root):
        if "node_modules" in dirnames:
            dirnames.remove("node_modules")
        if "package.json" in filenames:
            yield Path(current)


def needs_node_install(package_dir: Path) -> bool:
    """Return True if node dependencies should be installed."""
    if not (package_dir / "package.json").is_file():
        return False
    return not (package_dir / "node_modules").exists()


def choose_installer(package_dir: Path) -> list[str] | None:
    """Pick a package manager based on lockfiles and availability."""
    if (package_dir / "bun.lockb").exists() and shutil.which("bun"):
        return ["bun", "install"]
    if shutil.which("npm"):
        return ["npm", "install"]
    if shutil.which("bun"):
        return ["bun", "install"]
    return None


def run_install(command: list[str], package_dir: Path) -> bool:
    """Run a dependency install for a package directory."""
    try:
        result = subprocess.run(  # noqa: S603
            command,
            cwd=package_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=INSTALL_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        err(f"missing installer: {command[0]}")
        return False
    except subprocess.TimeoutExpired:
        err(f"deps install timed out in {package_dir}: {command[0]}")
        return False
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "unknown error"
        err(f"deps install failed in {package_dir}: {command[0]} ({detail})")
        return False
    return True


def install_extension_deps(root: Path) -> bool:
    """Install node dependencies for extensions if needed."""
    ok = True
    for package_dir in iter_extension_packages(root):
        if not needs_node_install(package_dir):
            continue
        command = choose_installer(package_dir)
        if command is None:
            err(f"no package manager available for {package_dir}")
            ok = False
            continue
        if not run_install(command, package_dir):
            ok = False
            continue
    return ok


def main() -> int:
    """Run the sync and return an exit code."""
    builders = (tool_dirs, asset_copies, agent_files, config_files)
    success = run_jobs(iter_jobs(builders))
    if success and "pi" in TOOL_CONFIG:
        success = install_extension_deps(tool_root(TOOL_CONFIG["pi"]) / "extensions")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
