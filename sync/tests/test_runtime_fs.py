# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for sync runtime filesystem primitives."""

from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from sync.core.secret_template import (
    render_secret_template,
    strip_jsonc,
    sync_secret_template,
)
from sync.runtime.fs import (
    copy_tree,
    is_identical_file,
    is_ignored_sync_entry,
    is_symlink,
    rm_entry,
    sync_managed_children,
    sync_managed_tree,
)

IS_ROOT = hasattr(os, "getuid") and os.getuid() == 0
PRIVATE_FILE_MODE: int = 0o600


def test_is_symlink(tmp_path: Path) -> None:
    """is_symlink returns True for symlinks, False for files, swallows ENOENT."""
    file = tmp_path / "file.txt"
    link = tmp_path / "link"
    missing = tmp_path / "missing"

    file.write_text("hello", encoding="utf-8")
    link.symlink_to(file)

    assert is_symlink(link) is True
    assert is_symlink(file) is False
    assert is_symlink(missing) is False

    if not IS_ROOT:
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0o000)
        try:
            with pytest.raises(PermissionError):
                is_symlink(locked / "x")
        finally:
            locked.chmod(0o755)


def test_rm_entry(tmp_path: Path) -> None:
    """rm_entry removes files, directories, symlinks, and ignores missing."""
    file = tmp_path / "file.txt"
    sub = tmp_path / "sub"
    link = tmp_path / "link"
    missing = tmp_path / "missing"

    file.write_text("hello", encoding="utf-8")
    (sub / "nested").mkdir(parents=True)
    (sub / "nested" / "child.txt").write_text("child", encoding="utf-8")
    link.symlink_to(file)

    rm_entry(link)
    assert not link.exists()
    assert file.exists()

    rm_entry(file)
    assert not file.exists()

    rm_entry(sub)
    assert not sub.exists()

    rm_entry(missing)
    assert not missing.exists()


def test_copy_tree(tmp_path: Path) -> None:
    """copy_tree mirrors files and rejects source directory symlinks."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    cyclic = tmp_path / "cyclic"

    (src / "sub").mkdir(parents=True)
    (src / "file1.txt").write_text("hello", encoding="utf-8")
    (src / "sub" / "file2.txt").write_text("world", encoding="utf-8")

    copy_tree(src, dst)
    assert (dst / "file1.txt").read_text(encoding="utf-8") == "hello"
    assert (dst / "sub" / "file2.txt").read_text(encoding="utf-8") == "world"

    # Copying a single file is allowed
    single_dst = tmp_path / "single.txt"
    copy_tree(src / "file1.txt", single_dst)
    assert single_dst.read_text(encoding="utf-8") == "hello"

    # A source directory symlink is rejected
    cyclic.mkdir()
    (cyclic / "self").symlink_to(cyclic, target_is_directory=True)
    with pytest.raises(RuntimeError, match="refusing source directory symlink:"):
        copy_tree(cyclic, tmp_path / "dst2")


def test_sync_managed_children(tmp_path: Path) -> None:
    """sync_managed_children copies only children."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"

    src.mkdir()
    (src / "child.txt").write_text("child", encoding="utf-8")

    sync_managed_children(src, dst)
    assert (dst / "child.txt").read_text(encoding="utf-8") == "child"


def test_sync_managed_tree_preserves_paths(tmp_path: Path) -> None:
    """sync_managed_tree keeps nested preserved files and removes stale entries."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"

    (src / "sub").mkdir(parents=True)
    (src / "file1.txt").write_text("hello", encoding="utf-8")
    (src / "sub" / "file3.txt").write_text("world", encoding="utf-8")

    (dst / "preserved").mkdir(parents=True)
    (dst / "preserved" / "nested.txt").write_text("keep", encoding="utf-8")
    (dst / "preserved" / "stale.txt").write_text("delete", encoding="utf-8")
    (dst / "other.txt").write_text("delete", encoding="utf-8")

    sync_managed_tree(src, dst, ["preserved/nested.txt"])

    assert (dst / "file1.txt").read_text(encoding="utf-8") == "hello"
    assert (dst / "sub" / "file3.txt").read_text(encoding="utf-8") == "world"
    assert (dst / "preserved" / "nested.txt").read_text(encoding="utf-8") == "keep"
    assert not (dst / "preserved" / "stale.txt").exists()
    assert not (dst / "other.txt").exists()


def test_sync_managed_tree_removes_destination_symlinks(tmp_path: Path) -> None:
    """sync_managed_tree removes destination symlinks without following them."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    external = tmp_path / "external"

    src.mkdir()
    (src / "file1.txt").write_text("hello", encoding="utf-8")

    external.mkdir()
    (external / "untouched.txt").write_text("untouched", encoding="utf-8")

    dst.mkdir()
    (dst / "link").symlink_to(external, target_is_directory=True)

    sync_managed_tree(src, dst)

    assert (dst / "file1.txt").read_text(encoding="utf-8") == "hello"
    assert not (dst / "link").exists()
    assert (external / "untouched.txt").read_text(encoding="utf-8") == "untouched"
    assert not (external / "file1.txt").exists()


def test_sync_managed_tree_throws_inaccessible_source(tmp_path: Path) -> None:
    """sync_managed_tree throws on inaccessible source directory."""
    if IS_ROOT:
        return
    src = tmp_path / "src"
    dst = tmp_path / "dst"

    src.mkdir()
    (src / "file1.txt").write_text("hello", encoding="utf-8")
    src.chmod(0o000)
    try:
        with pytest.raises(PermissionError):
            sync_managed_tree(src, dst)
    finally:
        src.chmod(0o755)


def test_sync_managed_tree_throws_self_referential_symlink(tmp_path: Path) -> None:
    """sync_managed_tree throws on self-referential source directory symlink."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"

    src.mkdir()
    (src / "self").symlink_to(src, target_is_directory=True)

    with pytest.raises(RuntimeError, match="refusing source directory symlink:"):
        sync_managed_tree(src, dst)

    assert dst.exists()
    assert list(dst.iterdir()) == []


def test_sync_managed_tree_ignores_artifacts(tmp_path: Path) -> None:
    """sync_managed_tree ignores transient artifacts and prunes from dst."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"

    (src / ".venv" / "bin").mkdir(parents=True)
    (src / ".venv" / "bin" / "python").write_text("bin", encoding="utf-8")
    (src / "node_modules" / "pkg").mkdir(parents=True)
    (src / "node_modules" / "pkg" / "index.js").write_text("mod", encoding="utf-8")
    (src / "__pycache__").mkdir(parents=True)
    (src / "__pycache__" / "mod.cpython-314.pyc").write_text("pyc", encoding="utf-8")
    (src / ".pytest_cache" / "v").mkdir(parents=True)
    (src / ".pytest_cache" / "v" / "cache").write_text("c", encoding="utf-8")
    (src / ".ruff_cache" / "cached").mkdir(parents=True)
    (src / ".ruff_cache" / "cached" / "c").write_text("c", encoding="utf-8")
    (src / ".hypothesis" / "data").mkdir(parents=True)
    (src / ".hypothesis" / "data" / "h").write_text("h", encoding="utf-8")
    (src / ".DS_Store").write_text("ds_store", encoding="utf-8")
    (src / "module.pyc").write_text("compiled", encoding="utf-8")
    (src / "module.pyo").write_text("optimized", encoding="utf-8")
    (src / "native.pyd").write_text("windows native binary", encoding="utf-8")
    (src / "real_file.txt").write_text("valid content", encoding="utf-8")

    # Seed destination with stale junk
    (dst / ".venv").mkdir(parents=True)
    (dst / ".venv" / "old").write_text("stale", encoding="utf-8")
    (dst / "node_modules").mkdir(parents=True)
    (dst / "node_modules" / "old").write_text("stale", encoding="utf-8")

    sync_managed_tree(src, dst)

    assert (dst / "real_file.txt").read_text(encoding="utf-8") == "valid content"
    assert (dst / "native.pyd").read_text(encoding="utf-8") == "windows native binary"
    assert not (dst / ".venv").exists()
    assert not (dst / "node_modules").exists()
    assert not (dst / "__pycache__").exists()
    assert not (dst / ".pytest_cache").exists()
    assert not (dst / ".ruff_cache").exists()
    assert not (dst / ".hypothesis").exists()
    assert not (dst / ".DS_Store").exists()
    assert not (dst / "module.pyc").exists()
    assert not (dst / "module.pyo").exists()


def test_is_ignored_sync_entry() -> None:
    """is_ignored_sync_entry matches expected ignore set and suffixes."""
    assert is_ignored_sync_entry(".venv") is True
    assert is_ignored_sync_entry("node_modules") is True
    assert is_ignored_sync_entry("__pycache__") is True
    assert is_ignored_sync_entry(".pytest_cache") is True
    assert is_ignored_sync_entry(".ruff_cache") is True
    assert is_ignored_sync_entry(".hypothesis") is True
    assert is_ignored_sync_entry(".DS_Store") is True
    assert is_ignored_sync_entry(".git") is True
    assert is_ignored_sync_entry("foo.pyc") is True
    assert is_ignored_sync_entry("bar.pyo") is True
    assert is_ignored_sync_entry("foo.py") is False
    assert is_ignored_sync_entry("native.pyd") is False


def test_is_identical_file(tmp_path: Path) -> None:
    """is_identical_file compares size, mode, and byte content."""
    f1 = tmp_path / "f1.txt"
    f2 = tmp_path / "f2.txt"
    f3 = tmp_path / "f3.txt"

    f1.write_text("hello", encoding="utf-8")
    f2.write_text("hello", encoding="utf-8")
    f3.write_text("world", encoding="utf-8")

    stat1 = f1.stat()
    assert is_identical_file(f1, stat1, f2) is True
    assert is_identical_file(f1, stat1, f3) is False

    # Mode difference
    f2.chmod(0o777)
    assert is_identical_file(f1, stat1, f2) is False


def test_strip_jsonc() -> None:
    """strip_jsonc handles line comments, block comments, and trailing commas."""
    input_text = """{
        // line comment
        "key": "value", /* block comment */
        "url": "http://example.com//test",
        "nested": [
            1,
            2,
            /* multi
               line
               comment */
        ],
    }"""
    cleaned = strip_jsonc(input_text)
    assert "// line comment" not in cleaned
    assert "/* block comment */" not in cleaned
    assert '"url": "http://example.com//test"' in cleaned
    # Line count preserved
    assert cleaned.count("\n") == input_text.count("\n")


def test_secret_template_rendering_and_sync(tmp_path: Path) -> None:
    """render_secret_template and sync_secret_template perform atomic private sync."""
    template = '{"api_key": ${SECRET_KEY}, "other": "plain"}'
    rendered = render_secret_template(template, {"SECRET_KEY": "super_secret"})
    assert rendered == '{"api_key": "super_secret", "other": "plain"}'

    # Invalid placeholder format
    with pytest.raises(ValueError, match="invalid secret placeholder:"):
        render_secret_template("${invalid-name}", {"invalid-name": "val"})

    # Missing secret
    with pytest.raises(ValueError, match="missing secret:"):
        render_secret_template("${MISSING_KEY}", {})

    # sync_secret_template end to end
    tmpl_file = tmp_path / "tmpl.json"
    secrets_file = tmp_path / "secrets.jsonc"
    dst_file = tmp_path / "out.json"

    tmpl_file.write_text(template, encoding="utf-8")
    secrets_file.write_text(
        '{\n  // secrets\n  "SECRET_KEY": "val",\n}\n',
        encoding="utf-8",
    )

    sync_secret_template(tmpl_file, dst_file, secrets_file)
    assert dst_file.read_text(encoding="utf-8") == (
        '{"api_key": "val", "other": "plain"}'
    )
    assert stat.S_IMODE(dst_file.stat().st_mode) == PRIVATE_FILE_MODE

    # Idempotent write (no change)
    mtime_before = dst_file.stat().st_mtime_ns
    sync_secret_template(tmpl_file, dst_file, secrets_file)
    mtime_after = dst_file.stat().st_mtime_ns
    assert mtime_before == mtime_after
