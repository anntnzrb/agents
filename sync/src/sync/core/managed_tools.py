# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Release archive download, verification, extraction, and platform helpers."""

from __future__ import annotations

import concurrent.futures
import hashlib
import platform
import tarfile
from pathlib import Path

from sync.runtime.errors import panic_message
from sync.runtime.http import get_ok

MS_PER_SECOND = 1000.0


def supported_arch(arch: str) -> str:
    """Normalize and validate target machine architecture.

    Returns 'arm64' or 'x64', or raises RuntimeError for unsupported architectures.
    """
    normalized = arch.strip().lower()
    if normalized in ("arm64", "aarch64"):
        return "arm64"
    if normalized in ("x64", "x86_64", "amd64"):
        return "x64"
    message = f"unsupported architecture: {arch}"
    raise RuntimeError(message)


def download_release(url: str, destination: str | Path, timeout_ms: int) -> None:
    """Download a remote release archive to a local file destination."""
    dest_path = Path(destination)
    response = get_ok(url, timeout_ms, "download failed")
    try:
        _ = dest_path.write_bytes(response.content)
    except OSError as exc:
        message = f"download failed ({panic_message(exc)})"
        raise RuntimeError(message) from exc


def _do_extract_tar(
    archive_path: Path,
    dest_path: Path,
    entry_name: str | None,
) -> None:
    with tarfile.open(archive_path, mode="r:*") as tar:
        if entry_name is None:
            tar.extractall(path=dest_path, filter="data")
        else:
            member = tar.getmember(entry_name)
            tar.extract(member, path=dest_path, filter="data")


def _extract_with_timeout(
    archive_path: Path,
    dest_path: Path,
    entry_name: str | None,
    timeout_ms: int,
) -> None:
    timeout_sec = max(0.0, timeout_ms / MS_PER_SECOND)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            _do_extract_tar,
            archive_path,
            dest_path,
            entry_name,
        )
        future.result(timeout=timeout_sec)
    except (TimeoutError, concurrent.futures.TimeoutError) as exc:
        message = "archive extraction timed out"
        raise TimeoutError(message) from exc
    except KeyError as exc:
        message = f"archive extraction failed: missing entry {entry_name}"
        raise RuntimeError(message) from exc
    except (OSError, tarfile.TarError) as exc:
        message = f"archive extraction failed: {panic_message(exc)}"
        raise RuntimeError(message) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def extract_release(
    archive: str | Path,
    destination: str | Path,
    entry_name: str,
    timeout_ms: int,
) -> None:
    """Extract a single entry from a tarball archive to destination directory."""
    _extract_with_timeout(Path(archive), Path(destination), entry_name, timeout_ms)


def extract_archive(
    archive: str | Path,
    destination: str | Path,
    timeout_ms: int,
) -> None:
    """Extract every entry from a tarball archive into a destination directory."""
    _extract_with_timeout(Path(archive), Path(destination), None, timeout_ms)


def verify_checksum(archive: str | Path, expected: str) -> None:
    """Verify SHA-256 checksum of an archive file against expected lowerhex."""
    archive_path = Path(archive)
    content = archive_path.read_bytes()
    actual = hashlib.sha256(content).hexdigest().lower()
    if actual != expected.lower():
        message = f"checksum mismatch for {archive_path.name}"
        raise RuntimeError(message)


def sys_platform() -> str:
    """Return system platform identifier matching host platform."""
    if platform.system().lower() == "darwin":
        return "darwin"
    return "linux"
