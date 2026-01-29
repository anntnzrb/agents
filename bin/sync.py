#!/usr/bin/env -S uv run python
from __future__ import annotations

import functools
import itertools
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, Literal


AGENTS_HOME = Path.home() / ".config" / "agents"
ASSETS_HOME = AGENTS_HOME / "assets"
TOOLS_HOME = AGENTS_HOME / "tools"

MCPORTER_HOME = Path.home() / ".mcporter"

DEFAULT_AGENT_FILE = "AGENTS.md"


@dataclass(frozen=True)
class ToolConfig:
    home: Path
    agent_file: str = DEFAULT_AGENT_FILE
    asset_renames: dict[str, str] = field(default_factory=dict)
    tool_subdir: Path | None = None


TOOL_CONFIG: dict[str, ToolConfig] = {
    "claude": ToolConfig(Path.home() / ".claude", agent_file="CLAUDE.md"),
    "codex": ToolConfig(Path.home() / ".config" / "codex"),
    "opencode": ToolConfig(Path.home() / ".config" / "opencode"),
    "pi": ToolConfig(
        Path.home() / ".config" / "pi" / "agent",
        asset_renames={"commands": "prompts"},
        tool_subdir=Path("agent"),
    ),
}


JobKind = Literal["file", "dir"]


@dataclass(frozen=True)
class Job:
    src: Path
    dst: Path
    kind: JobKind


def guard(func: Callable[..., bool]) -> Callable[..., bool]:
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> bool:
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # defensive: keep sync from crashing on unexpected errors
            err(f"unexpected error in {func.__name__}: {exc}")
            return False

    return wrapper


def err(message: str) -> None:
    print(f"sync: {message}", file=sys.stderr)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def rm_entry(path: Path) -> None:
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


def tool_dirs() -> list[Job]:
    jobs: list[Job] = []
    for tool_name, tool in TOOL_CONFIG.items():
        src = TOOLS_HOME / tool_name
        if tool.tool_subdir is not None:
            src = src / tool.tool_subdir
        jobs.append(Job(src, tool.home, "dir"))
    return jobs


def asset_copies() -> list[Job]:
    if not ASSETS_HOME.is_dir():
        return []
    jobs: list[Job] = []
    for asset_path in (path for path in ASSETS_HOME.iterdir() if path.is_dir()):
        asset_name = asset_path.name
        for tool in TOOL_CONFIG.values():
            dest_name = tool.asset_renames.get(asset_name, asset_name)
            jobs.append(Job(asset_path, tool.home / dest_name, "dir"))
    return jobs


def agent_files() -> list[Job]:
    return [
        Job(AGENTS_HOME / DEFAULT_AGENT_FILE, tool.home / tool.agent_file, "file")
        for tool in TOOL_CONFIG.values()
    ]


def config_files() -> list[Job]:
    return [Job(ASSETS_HOME / "mcporter.jsonc", MCPORTER_HOME / "mcporter.json", "file")]


@guard
def copy_item(src: Path, dst: Path) -> bool:
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
    if not src_dir.is_dir():
        err(f"missing directory: {src_dir}")
        return True
    ensure_dir(dst_dir)
    try:
        shutil.copytree(src_dir, dst_dir, symlinks=False, dirs_exist_ok=True, copy_function=shutil.copy2)
    except OSError as exc:
        err(f"copy failed: {src_dir} -> {dst_dir} ({exc})")
        return False
    return True


HANDLERS: dict[JobKind, Callable[[Path, Path], bool]] = {
    "dir": copy_dir_into,
    "file": copy_item,
}


def iter_jobs(builders: Iterable[Callable[[], Iterable[Job]]]) -> Iterator[Job]:
    return itertools.chain.from_iterable(builder() for builder in builders)


def run_jobs(jobs: Iterable[Job]) -> bool:
    return all(HANDLERS[job.kind](job.src, job.dst) for job in jobs)


def main() -> int:
    builders = (tool_dirs, asset_copies, agent_files, config_files)
    return 0 if run_jobs(iter_jobs(builders)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
