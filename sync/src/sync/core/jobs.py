# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Sync job execution, runtime release installation, and release lifecycle."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import secrets
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

from sync.core.cliproxy_config import sync_cliproxy_config
from sync.core.cliproxy_deployment import (
    CliProxyEndpointPublication,
    CliProxyEndpointSyncOptions,
    is_cliproxy_target_ready,
    publish_cliproxy_endpoint_templates,
)
from sync.core.plan import (
    CliProxyConfigJob,
    CliProxyEndpointTemplatesJob,
    CliProxyReadinessJob,
    DirJob,
    FileJob,
    Job,
    SecretTemplateJob,
    SyncRuntimeInstallJob,
)
from sync.core.secret_template import sync_secret_template
from sync.runtime.errors import assert_never, err, panic_message, warn
from sync.runtime.fs import (
    SourceContentCache,
    is_symlink,
    rm_entry,
    sync_managed_children,
    sync_managed_tree,
)

SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
STAGE_DIR_PATTERN = re.compile(r"^\.stage-(\d+)-([0-9a-f]+)$", re.IGNORECASE)
DEFAULT_PRUNE_TIMEOUT_MS = 120_000
MIN_INSTALL_TIMEOUT_MS = 1000


@dataclass(slots=True)
class JobRunState:
    """Internal mutable run state shared across jobs in a sync run."""

    cli_proxy_target_ready: bool | None = None


class Hasher(Protocol):
    """Protocol for hash objects supporting incremental update."""

    def update(self, data: bytes, /) -> None:
        """Update the hash with bytes data."""
        ...


@dataclass(frozen=True, slots=True)
class RequiredPaths:
    """Validated source paths required for runtime installation."""

    src_dir: str
    pyproject_toml: str
    uv_lock: str


def run_jobs_with_preserve(
    jobs: Sequence[Job],
    preserve_paths_by_dst: Mapping[str, Sequence[str]] | None = None,
) -> bool:
    """Run a sequence of jobs in order, failing fast on the first failure."""
    if preserve_paths_by_dst is None:
        preserve_paths_by_dst = {}
    source_content_cache: SourceContentCache = {}
    state = JobRunState()
    for job in jobs:
        if not _run_job(job, preserve_paths_by_dst, source_content_cache, state):
            return False
    return True


def _run_dir_job(
    job: DirJob,
    preserve_paths_by_dst: Mapping[str, Sequence[str]],
    source_content_cache: SourceContentCache,
) -> bool:
    preserve_paths = [
        *preserve_paths_by_dst.get(job.dst, ()),
        *job.preserve_paths,
    ]
    if job.scope == "Children":
        return _sync_dir_into(job.src, job.dst, preserve_paths, source_content_cache)
    return _sync_managed_dir(job.src, job.dst, preserve_paths, source_content_cache)


def _run_secret_template_job(job: SecretTemplateJob) -> bool:
    if not Path(job.src).exists():
        err(f"missing source: {job.src}")
        return True
    if not Path(job.secrets_path).exists():
        warn(f"missing local secrets {job.secrets_path}; skipping {job.dst}")
        return True
    sync_secret_template(job.src, job.dst, job.secrets_path)
    return True


def _run_cliproxy_readiness_job(job: CliProxyReadinessJob, state: JobRunState) -> bool:
    if job.gateway_host:
        return True
    state.cli_proxy_target_ready = is_cliproxy_target_ready(job.deployment)
    if not state.cli_proxy_target_ready:
        warn("CLIProxyAPI endpoint is not ready; preserving existing client artifacts")
    return True


def _run_cliproxy_endpoint_templates_job(
    job: CliProxyEndpointTemplatesJob, state: JobRunState
) -> bool:
    if state.cli_proxy_target_ready is False:
        return True
    options = CliProxyEndpointSyncOptions(
        skip_readiness=state.cli_proxy_target_ready is True
    )
    publication: CliProxyEndpointPublication = publish_cliproxy_endpoint_templates(
        job.targets,
        job.deployment,
        options=options,
    )
    if publication == "skipped" and len(job.targets) > 0:
        warn("CLIProxyAPI endpoint is not ready; preserving existing harness endpoints")
    return True


def _run_cliproxy_config_job(job: CliProxyConfigJob, state: JobRunState) -> bool:
    if state.cli_proxy_target_ready is False or not job.gateway_host:
        return True
    if not Path(job.src).exists():
        err(f"missing source: {job.src}")
        return True
    if not Path(job.secrets_path).exists():
        warn(f"missing local secrets {job.secrets_path}; skipping {job.dst}")
        return True
    sync_cliproxy_config(job.src, job.dst, job.secrets_path, job.deployment)
    return True


def _run_job(
    job: Job,
    preserve_paths_by_dst: Mapping[str, Sequence[str]],
    source_content_cache: SourceContentCache,
    state: JobRunState,
) -> bool:
    try:
        match job:
            case DirJob():
                success = _run_dir_job(job, preserve_paths_by_dst, source_content_cache)
            case FileJob():
                success = _sync_item(job.src, job.dst)
            case SecretTemplateJob():
                success = _run_secret_template_job(job)
            case CliProxyReadinessJob():
                success = _run_cliproxy_readiness_job(job, state)
            case CliProxyEndpointTemplatesJob():
                success = _run_cliproxy_endpoint_templates_job(job, state)
            case CliProxyConfigJob():
                success = _run_cliproxy_config_job(job, state)
            case SyncRuntimeInstallJob():
                success = _run_sync_runtime_install_job(job)
            case _:
                assert_never(job)
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        err(f"unexpected error in {job.kind}: {panic_message(error)}")
        return False
    else:
        return success


def _execute_uv_sync(stage: str, release_id: str, timeout_ms: int) -> None:
    timeout_seconds = max(timeout_ms, MIN_INSTALL_TIMEOUT_MS) / 1000.0
    uv_bin = shutil.which("uv") or "uv"
    try:
        install = subprocess.run(  # noqa: S603
            [uv_bin, "sync", "--frozen", "--no-dev"],
            cwd=stage,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = (
            exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        )
        install = subprocess.CompletedProcess(
            [uv_bin, "sync", "--frozen", "--no-dev"],
            returncode=-1,
            stdout=stdout,
            stderr=stderr,
        )

    if timed_out or install.returncode != 0:
        stderr_text = install.stderr.strip() if install.stderr else ""
        stdout_text = install.stdout.strip() if install.stdout else ""
        detail = stderr_text or stdout_text or "unknown error"
        message = f"runtime dependency install failed: {detail}"
        raise RuntimeError(message)

    marker_path = Path(stage) / ".release-complete"
    with marker_path.open("w", encoding="utf-8") as marker_file:
        marker_file.write(f"{release_id}\n")

    if not _is_complete_release(stage):
        message = "runtime install did not produce a complete release"
        raise RuntimeError(message)


def _run_sync_runtime_install_job(job: SyncRuntimeInstallJob) -> bool:
    required_paths = _validate_required_sources(job.source_root)
    if required_paths is None:
        return False

    Path(job.releases_root).mkdir(parents=True, exist_ok=True)

    release_id = _compute_runtime_release_id(required_paths)
    release_dir = str(Path(job.releases_root) / release_id)
    if _is_complete_release(release_dir):
        return publish_current_link(job.current_link, release_dir)

    stage = _create_stage(job.releases_root)
    try:
        _copy_runtime_inputs(required_paths, stage, {})
        _execute_uv_sync(stage, release_id, job.timeout_ms)
        if Path(release_dir).exists():
            if _is_complete_release(release_dir):
                return publish_current_link(job.current_link, release_dir)
            rm_entry(release_dir)
        Path(stage).rename(release_dir)
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        err(f"runtime install failed: {panic_message(error)}")
        return False
    finally:
        if Path(stage).exists():
            with contextlib.suppress(OSError):
                rm_entry(stage)

    return publish_current_link(job.current_link, release_dir)


def _validate_required_sources(source_root: str) -> RequiredPaths | None:
    source_path = Path(source_root)
    src_dir = str(source_path / "src")
    pyproject_toml = str(source_path / "pyproject.toml")
    uv_lock = str(source_path / "uv.lock")

    if not _is_regular_readable(src_dir, "src/", "directory"):
        return None
    if not _is_regular_readable(pyproject_toml, "pyproject.toml", "file"):
        return None
    if not _is_regular_readable(uv_lock, "uv.lock", "file"):
        return None

    return RequiredPaths(
        src_dir=src_dir,
        pyproject_toml=pyproject_toml,
        uv_lock=uv_lock,
    )


def _is_regular_readable(
    target_path: str, label: str, kind: Literal["directory", "file"]
) -> bool:
    try:
        metadata = Path(target_path).lstat()
        if stat.S_ISLNK(metadata.st_mode):
            err(f"runtime source {label} is a symlink: {target_path}")
            return False
        is_dir = stat.S_ISDIR(metadata.st_mode)
        is_reg = stat.S_ISREG(metadata.st_mode)
        if kind == "directory" and not is_dir:
            err(f"runtime source {label} is not a directory: {target_path}")
            return False
        if kind == "file" and not is_reg:
            err(f"runtime source {label} is not a regular file: {target_path}")
            return False
        required_access = (os.R_OK | os.X_OK) if kind == "directory" else os.R_OK
        if not os.access(target_path, required_access):
            err(f"missing or unreadable runtime source {label}: {target_path}")
            return False
    except OSError as error:
        err(
            f"missing or unreadable runtime source {label}: {target_path} "
            f"({panic_message(error)})"
        )
        return False
    else:
        return True


def _compute_runtime_release_id(paths: RequiredPaths) -> str:
    hasher = hashlib.sha256()
    _hash_directory_into(paths.src_dir, hasher)
    for file_path in (paths.pyproject_toml, paths.uv_lock):
        with Path(file_path).open("rb") as file_handle:
            hasher.update(file_handle.read())
    return hasher.hexdigest()


def _hash_directory_into(root: str, hasher: Hasher, prefix: str = "") -> None:
    try:
        entries = sorted(Path(root).iterdir(), key=lambda entry: entry.name)
    except OSError:
        return

    for entry in entries:
        relative_path = entry.name if len(prefix) == 0 else f"{prefix}/{entry.name}"
        if entry.is_symlink():
            try:
                target_stat = entry.stat()
            except OSError as error:
                message = f"unreadable symlink target: {entry} ({panic_message(error)})"
                raise RuntimeError(message) from error
            if stat.S_ISDIR(target_stat.st_mode):
                message = f"refusing source directory symlink: {entry}"
                raise RuntimeError(message)
            hasher.update(f"file:{relative_path}\n".encode())
            with entry.open("rb") as file_handle:
                hasher.update(file_handle.read())
            hasher.update(b"\n")
        elif entry.is_dir():
            hasher.update(f"dir:{relative_path}\n".encode())
            _hash_directory_into(str(entry), hasher, relative_path)
        elif entry.is_file():
            hasher.update(f"file:{relative_path}\n".encode())
            with entry.open("rb") as file_handle:
                hasher.update(file_handle.read())
            hasher.update(b"\n")


def _copy_runtime_inputs(
    paths: RequiredPaths,
    stage: str,
    source_content_cache: SourceContentCache,
) -> None:
    stage_path = Path(stage)
    stage_src = str(stage_path / "src")
    stage_path.mkdir(parents=True, exist_ok=True)
    sync_managed_tree(paths.src_dir, stage_src, (), source_content_cache)
    stage_pyproject = str(stage_path / "pyproject.toml")
    stage_uv_lock = str(stage_path / "uv.lock")
    shutil.copyfile(paths.pyproject_toml, stage_pyproject)
    shutil.copymode(paths.pyproject_toml, stage_pyproject)
    shutil.copyfile(paths.uv_lock, stage_uv_lock)
    shutil.copymode(paths.uv_lock, stage_uv_lock)
    source_readme = Path(paths.pyproject_toml).parent / "README.md"
    stage_readme = stage_path / "README.md"
    if source_readme.is_file():
        shutil.copyfile(source_readme, stage_readme)
        shutil.copymode(source_readme, stage_readme)
    else:
        stage_readme.write_text("", encoding="utf-8")


def _is_complete_release(release_dir: str) -> bool:
    try:
        release_path = Path(release_dir)
        cli_py = release_path / "src" / "sync" / "cli.py"
        cli_root_py = release_path / "src" / "cli.py"
        if not (cli_py.is_file() or cli_root_py.is_file()):
            return False
        marker = release_path / ".release-complete"
        venv_dir = release_path / ".venv"
        return marker.is_file() or venv_dir.is_dir()
    except OSError:
        return False


def _create_stage(releases_root: str) -> str:
    nonce = secrets.token_hex(4)
    stage_path = Path(releases_root) / f".stage-{os.getpid()}-{nonce}"
    if stage_path.exists():
        message = f"runtime stage collision: {stage_path}"
        raise RuntimeError(message)
    return str(stage_path)


def publish_current_link(current_link: str, release_dir: str) -> bool:
    """Atomically publish release_dir to current_link via temporary symlink."""
    parent = Path(current_link).parent
    parent.mkdir(parents=True, exist_ok=True)
    temp = Path(f"{current_link}.{os.getpid()}.tmp")
    try:
        rm_entry(str(temp))
        target = os.path.relpath(release_dir, str(parent))
        temp.symlink_to(target)
        temp.replace(current_link)
    except (OSError, RuntimeError) as error:
        err(f"failed to publish current link {current_link}: {panic_message(error)}")
        with contextlib.suppress(OSError):
            rm_entry(str(temp))
        return False
    return True


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    else:
        return True


def _prune_stage_dir(
    releases_root: str,
    entry_name: str,
    pid: int,
    now_ms: float,
    timeout_ms: int,
) -> None:
    stage_path = str(Path(releases_root) / entry_name)
    is_stale = not _is_process_alive(pid)
    if not is_stale:
        try:
            entry_stat = Path(stage_path).stat()
            age_ms = now_ms - (entry_stat.st_mtime * 1000.0)
            if age_ms > timeout_ms:
                is_stale = True
        except OSError:
            pass

    if is_stale:
        try:
            rm_entry(stage_path)
        except (OSError, RuntimeError) as error:
            warn(
                f"failed to prune stale stage directory {entry_name}: "
                f"{panic_message(error)}"
            )


def _prune_unreferenced_release(
    releases_root: str,
    entry_name: str,
) -> None:
    release_path = str(Path(releases_root) / entry_name)
    if not _is_complete_release(release_path):
        return

    try:
        rm_entry(release_path)
    except (OSError, RuntimeError) as error:
        warn(
            f"failed to prune unreferenced release {entry_name}: {panic_message(error)}"
        )


def prune_unreferenced_releases(
    releases_root: str,
    current_release_dir_or_link: str,
    timeout_ms: int = DEFAULT_PRUNE_TIMEOUT_MS,
) -> None:
    """Prune unreferenced complete releases and stale stage directories."""
    if (
        not Path(releases_root).exists()
        or not Path(current_release_dir_or_link).exists()
    ):
        return

    try:
        resolved = Path(current_release_dir_or_link).resolve()
        current_base = resolved.name
    except OSError as error:
        warn(
            f"failed to resolve current release link for pruning: "
            f"{panic_message(error)}"
        )
        return

    if not SHA256_HEX_PATTERN.match(current_base):
        return

    try:
        entries = list(Path(releases_root).iterdir())
    except OSError as error:
        warn(f"failed to list releases for pruning: {panic_message(error)}")
        return

    now_ms = time.time() * 1000.0

    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            continue

        stage_match = STAGE_DIR_PATTERN.match(entry.name)
        if stage_match is not None:
            pid = int(stage_match.group(1))
            _prune_stage_dir(releases_root, entry.name, pid, now_ms, timeout_ms)
            continue

        if (
            entry.name.startswith(".")
            or entry.name == current_base
            or not SHA256_HEX_PATTERN.match(entry.name)
        ):
            continue

        _prune_unreferenced_release(releases_root, entry.name)


def remove_legacy_runtime_install(runtime_home: str) -> bool:
    """Remove legacy mutable runtime directory if it exists."""
    legacy = Path(runtime_home) / "sync"
    try:
        if not legacy.exists() and not legacy.is_symlink():
            return True
        metadata = legacy.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            return True
        rm_entry(str(legacy))
    except (OSError, RuntimeError) as error:
        err(f"legacy runtime cleanup failed: {legacy} ({panic_message(error)})")
        return False
    else:
        return True


def _sync_dir_into(
    src_dir: str,
    dst_dir: str,
    preserve_paths: Sequence[str],
    source_content_cache: SourceContentCache,
) -> bool:
    try:
        if not _is_directory_like(src_dir):
            err(f"missing directory: {src_dir}")
            return True

        Path(dst_dir).mkdir(parents=True, exist_ok=True)
        sync_managed_children(src_dir, dst_dir, preserve_paths, source_content_cache)
    except (OSError, RuntimeError) as error:
        err(f"copy failed: {src_dir} -> {dst_dir} ({panic_message(error)})")
        return False
    else:
        return True


def _sync_managed_dir(
    src_dir: str,
    dst_dir: str,
    preserve_paths: Sequence[str],
    source_content_cache: SourceContentCache,
) -> bool:
    try:
        if not _is_directory_like(src_dir):
            err(f"missing directory: {src_dir}")
            return True

        Path(dst_dir).parent.mkdir(parents=True, exist_ok=True)
        sync_managed_tree(src_dir, dst_dir, preserve_paths, source_content_cache)
    except (OSError, RuntimeError) as error:
        err(f"copy failed: {src_dir} -> {dst_dir} ({panic_message(error)})")
        return False
    else:
        return True


def _sync_item(src: str, dst: str) -> bool:
    try:
        if not Path(src).exists() and not is_symlink(src):
            err(f"missing source: {src}")
            return True

        if files_match(src, dst):
            return True

        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        rm_entry(dst)
        shutil.copyfile(src, dst)
        shutil.copymode(src, dst)
    except (OSError, RuntimeError) as error:
        err(f"copy failed: {src} -> {dst} ({panic_message(error)})")
        return False
    else:
        return True


def _is_directory_like(path: str) -> bool:
    try:
        return stat.S_ISDIR(Path(path).stat().st_mode)
    except OSError:
        return False


def files_match(src: str, dst: str) -> bool:
    """Return True if src and dst regular files have identical size, mode, content."""
    try:
        if is_symlink(dst):
            return False
        src_p = Path(src)
        dst_p = Path(dst)
        src_stat = src_p.stat()
        dst_stat = dst_p.stat()
        if not stat.S_ISREG(src_stat.st_mode) or not stat.S_ISREG(dst_stat.st_mode):
            return False
        if src_stat.st_size != dst_stat.st_size or (src_stat.st_mode & 0o777) != (
            dst_stat.st_mode & 0o777
        ):
            return False
        if src_stat.st_size == 0:
            return True
        with src_p.open("rb") as f_src, dst_p.open("rb") as f_dst:
            return f_src.read() == f_dst.read()
    except OSError:
        return False


__all__ = [
    "DEFAULT_PRUNE_TIMEOUT_MS",
    "MIN_INSTALL_TIMEOUT_MS",
    "JobRunState",
    "RequiredPaths",
    "files_match",
    "prune_unreferenced_releases",
    "publish_current_link",
    "remove_legacy_runtime_install",
    "run_jobs_with_preserve",
]
