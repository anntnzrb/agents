# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for release download, verification, extraction, and platform helpers."""

from __future__ import annotations

import hashlib
import re
import tarfile
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from sync.core.managed_tools import (
    download_release,
    extract_archive,
    extract_release,
    supported_arch,
    sys_platform,
    verify_checksum,
)

ARCHIVE_CONTENT = b"fixture archive"
EXPECTED_CHECKSUM = hashlib.sha256(ARCHIVE_CONTENT).hexdigest()
INVALID_CHECKSUM = "0" * 64


def test_supported_arch_normalizes_and_validates() -> None:
    """supported_arch normalizes known architectures and rejects unknown ones."""
    assert supported_arch("arm64") == "arm64"
    assert supported_arch("aarch64") == "arm64"
    assert supported_arch("x64") == "x64"
    assert supported_arch("x86_64") == "x64"
    assert supported_arch("amd64") == "x64"
    with pytest.raises(RuntimeError, match=r"unsupported architecture: riscv64"):
        _ = supported_arch("riscv64")


def test_sys_platform_returns_darwin_or_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    """sys_platform returns darwin on macOS and linux on other systems."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    assert sys_platform() == "darwin"
    monkeypatch.setattr("platform.system", lambda: "Linux")
    assert sys_platform() == "linux"


def test_extract_release_enforces_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """extract_release raises TimeoutError when extraction exceeds deadline."""
    archive_path = tmp_path / "test.tar.gz"
    entry_file = tmp_path / "dummy.txt"
    _ = entry_file.write_text("dummy", encoding="utf-8")
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(entry_file, arcname="dummy.txt")

    def slow_extract(
        _archive_path: Path,
        _dest_path: Path,
        _entry_name: str | None,
    ) -> None:
        time.sleep(0.1)

    monkeypatch.setattr("sync.core.managed_tools._do_extract_tar", slow_extract)

    dest = tmp_path / "dest"
    dest.mkdir(parents=True, exist_ok=True)
    with pytest.raises(TimeoutError, match=r"archive extraction timed out"):
        extract_release(archive_path, dest, "dummy.txt", timeout_ms=10)


def test_extract_archive_extracts_all_entries(tmp_path: Path) -> None:
    """extract_archive unpacks full archive contents into target directory."""
    archive_path = tmp_path / "test.tar.gz"
    f1 = tmp_path / "f1.txt"
    f2 = tmp_path / "f2.txt"
    _ = f1.write_text("file 1", encoding="utf-8")
    _ = f2.write_text("file 2", encoding="utf-8")
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(f1, arcname="f1.txt")
        tar.add(f2, arcname="f2.txt")

    dest = tmp_path / "extracted"
    dest.mkdir(parents=True, exist_ok=True)
    extract_archive(archive_path, dest, timeout_ms=5000)
    assert (dest / "f1.txt").read_text(encoding="utf-8") == "file 1"
    assert (dest / "f2.txt").read_text(encoding="utf-8") == "file 2"


def test_verify_checksum_validates_archive_sha256(tmp_path: Path) -> None:
    """verify_checksum passes on valid sha256 and raises RuntimeError on mismatch."""
    archive_path = tmp_path / "test.bin"
    _ = archive_path.write_bytes(ARCHIVE_CONTENT)

    verify_checksum(archive_path, EXPECTED_CHECKSUM)
    verify_checksum(archive_path, EXPECTED_CHECKSUM.upper())

    with pytest.raises(RuntimeError, match=r"checksum mismatch for test\.bin"):
        verify_checksum(archive_path, INVALID_CHECKSUM)


@dataclass(frozen=True, slots=True)
class _FakeHttpResponse:
    status_code: int
    content: bytes

    def raise_for_status(self) -> None:
        pass


def test_download_release_writes_body_and_converts_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 200 response body lands at the destination; timeout is in seconds."""
    calls: list[tuple[str, float]] = []

    def mock_get(url: str, *, timeout: float, **_kwargs: object) -> _FakeHttpResponse:
        calls.append((url, timeout))
        return _FakeHttpResponse(200, ARCHIVE_CONTENT)

    monkeypatch.setattr("sync.runtime.http.httpx.get", mock_get)

    destination = tmp_path / "downloaded.tar.gz"
    download_release("https://example.test/a.tar.gz", destination, 1500)

    assert destination.read_bytes() == ARCHIVE_CONTENT
    assert calls == [("https://example.test/a.tar.gz", 1.5)]


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (_FakeHttpResponse(404, b"missing"), "HTTP 404"),
        (OSError("connection refused"), "connection refused"),
    ],
    ids=["http-404", "transport-error"],
)
def test_download_release_reports_http_and_transport_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: _FakeHttpResponse | Exception,
    message: str,
) -> None:
    """HTTP errors and transport exceptions surface as download failed errors."""

    def mock_get(_url: str, *, timeout: float, **_kwargs: object) -> _FakeHttpResponse:
        _ = timeout
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("sync.runtime.http.httpx.get", mock_get)

    destination = tmp_path / "failed.tar.gz"
    with pytest.raises(RuntimeError, match=re.escape(message)):
        download_release("https://example.test/a.tar.gz", destination, 1500)
    assert not destination.exists()
