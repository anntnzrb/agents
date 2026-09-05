# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for extension hook state management and tree fingerprinting."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Final

import pytest

if TYPE_CHECKING:
    from pathlib import Path
from sync.core.harness import HarnessSpec, build_harness
from sync.core.harness_adapters import HARNESS_ADAPTERS
from sync.core.hook_state import (
    clear_extension_hook_state,
    fingerprint_tree,
    prepare_extension_hook_state,
    record_extension_hook_state,
)
from sync.core.plan import ExtensionDepsHookPlan

_MISSING_SHA256: Final[str] = (
    "ffa63583dfa6706b87d284b86b0d693a161e4840aad2c5cf6b5d27c3b9621f7d"
)
SHA256_HEX_LENGTH: Final[int] = 64


def test_fingerprint_tree_missing_source_root_matches_golden(
    tmp_path: Path,
) -> None:
    """Missing source root produces exact sha256('missing') digest."""
    missing_dir = tmp_path / "nonexistent"
    result = fingerprint_tree(missing_dir)
    assert result == _MISSING_SHA256


def test_fingerprint_tree_empty_directory(tmp_path: Path) -> None:
    """Empty directory produces a deterministic sha256 digest."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    first = fingerprint_tree(empty_dir)
    second = fingerprint_tree(empty_dir)
    assert first == second
    assert len(first) == SHA256_HEX_LENGTH


def test_fingerprint_tree_is_stable_for_unchanged_source_tree(
    tmp_path: Path,
) -> None:
    """Unchanged tree returns identical fingerprint across invocations."""
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "a.ts").write_text("a", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    first = fingerprint_tree(tmp_path)
    second = fingerprint_tree(tmp_path)
    assert first == second


def test_fingerprint_tree_changes_when_file_content_changes(
    tmp_path: Path,
) -> None:
    """Modifying a file inside tree changes the fingerprint."""
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "a.ts").write_text("a", encoding="utf-8")

    first = fingerprint_tree(tmp_path)
    (tmp_path / "src" / "a.ts").write_text("b", encoding="utf-8")
    second = fingerprint_tree(tmp_path)

    assert first != second


def test_fingerprint_tree_ignores_python_cache_directories_and_compiled_files(
    tmp_path: Path,
) -> None:
    """Python cache dirs and bytecode files are ignored in tree fingerprinting."""
    (tmp_path / "src" / "__pycache__").mkdir(parents=True)
    (tmp_path / "src" / "a.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / "src" / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"bytecode")
    (tmp_path / "src" / "compiled.pyo").write_bytes(b"bytecode")

    baseline = fingerprint_tree(tmp_path)

    (tmp_path / "src" / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"mutated")
    (tmp_path / "src" / "compiled.pyo").write_bytes(b"mutated")

    assert fingerprint_tree(tmp_path) == baseline


def test_fingerprint_tree_refuses_source_directory_symlinks_with_diagnostic_error(
    tmp_path: Path,
) -> None:
    """Directory symlinks are refused with a diagnostic error message."""
    target_dir = tmp_path / "target_dir"
    target_dir.mkdir()
    (target_dir / "file.txt").write_text("hello", encoding="utf-8")
    link_dir = tmp_path / "link_dir"
    link_dir.symlink_to(target_dir)

    expected_pattern = re.escape(f"refusing source directory symlink: {link_dir}")
    with pytest.raises(ValueError, match=expected_pattern):
        fingerprint_tree(tmp_path)


def test_fingerprint_tree_rejects_recursive_symlink_cycles_before_unbounded_recursion(
    tmp_path: Path,
) -> None:
    """Recursive symlinks pointing to ancestor dirs are refused immediately."""
    sub_dir = tmp_path / "sub"
    sub_dir.mkdir()
    cycle_link = sub_dir / "cycle"
    cycle_link.symlink_to(tmp_path)

    expected_pattern = re.escape(f"refusing source directory symlink: {cycle_link}")
    with pytest.raises(ValueError, match=expected_pattern):
        fingerprint_tree(tmp_path)


def test_fingerprint_tree_rejects_symlink_loop_cycles_before_unbounded_recursion(
    tmp_path: Path,
) -> None:
    """Symlink loop cycles (link_a -> link_b -> link_a) raise error."""
    link_a = tmp_path / "link_a"
    link_b = tmp_path / "link_b"
    link_a.symlink_to(link_b)
    link_b.symlink_to(link_a)

    with pytest.raises(OSError, match=r"Too many levels of symbolic links|loop"):
        fingerprint_tree(tmp_path)


def test_fingerprint_tree_records_broken_symlinks_without_failing(
    tmp_path: Path,
) -> None:
    """Broken symlinks are hashed with broken: prefix without raising."""
    (tmp_path / "broken_link").symlink_to(tmp_path / "nonexistent")
    fp1 = fingerprint_tree(tmp_path)
    assert isinstance(fp1, str)
    assert len(fp1) == SHA256_HEX_LENGTH
    assert fingerprint_tree(tmp_path) == fp1

    (tmp_path / "broken_link_2").symlink_to(tmp_path / "nonexistent2")
    fp2 = fingerprint_tree(tmp_path)
    assert fp2 != fp1


def test_fingerprint_tree_regular_files_and_normal_subdirs_fingerprint_identically(
    tmp_path: Path,
) -> None:
    """Independent identical trees produce identical fingerprints."""
    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"

    for r in [root1, root2]:
        (r / "src" / "nested").mkdir(parents=True)
        (r / "src" / "index.ts").write_text("export const x = 1;", encoding="utf-8")
        (r / "src" / "nested" / "util.ts").write_text(
            "export const util = true;", encoding="utf-8"
        )
        (r / "package.json").write_text('{"name":"test"}', encoding="utf-8")

    assert fingerprint_tree(root1) == fingerprint_tree(root2)


def test_fingerprint_tree_fingerprints_symlinks_to_regular_files(
    tmp_path: Path,
) -> None:
    """Symlinks to regular files are hashed identically to regular files."""
    target_file = tmp_path / "target.txt"
    target_file.write_text("target content", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(target_file)

    fp = fingerprint_tree(tmp_path)
    assert isinstance(fp, str)
    assert len(fp) == SHA256_HEX_LENGTH
    assert fingerprint_tree(tmp_path) == fp


def test_fingerprint_tree_sorts_directory_entries_with_mixed_case_and_non_ascii_names(
    tmp_path: Path,
) -> None:
    """Entries are processed in deterministic Unicode code-point order."""
    for name in ["_x", "a", "B", "ä", "z"]:
        (tmp_path / name).write_text(f"content of {name}", encoding="utf-8")

    (tmp_path / "Sub_C").mkdir()
    (tmp_path / "Sub_C" / "file.txt").write_text("sub C", encoding="utf-8")
    (tmp_path / "sub_b").mkdir()
    (tmp_path / "sub_b" / "file.txt").write_text("sub b", encoding="utf-8")
    (tmp_path / "sub_ä").mkdir()
    (tmp_path / "sub_ä" / "file.txt").write_text("sub ä", encoding="utf-8")

    hasher = hashlib.sha256()
    hasher.update(b"file:B\n")
    hasher.update(b"content of B")
    hasher.update(b"\n")

    hasher.update(b"dir:Sub_C\n")
    hasher.update(b"file:Sub_C/file.txt\n")
    hasher.update(b"sub C")
    hasher.update(b"\n")

    hasher.update(b"file:_x\n")
    hasher.update(b"content of _x")
    hasher.update(b"\n")

    hasher.update(b"file:a\n")
    hasher.update(b"content of a")
    hasher.update(b"\n")

    hasher.update(b"dir:sub_b\n")
    hasher.update(b"file:sub_b/file.txt\n")
    hasher.update(b"sub b")
    hasher.update(b"\n")

    hasher.update(b"dir:sub_\xc3\xa4\n")
    hasher.update(b"file:sub_\xc3\xa4/file.txt\n")
    hasher.update("sub ä".encode())
    hasher.update(b"\n")

    hasher.update(b"file:z\n")
    hasher.update(b"content of z")
    hasher.update(b"\n")

    hasher.update("file:ä\n".encode())
    hasher.update("content of ä".encode())
    hasher.update(b"\n")

    expected = hasher.hexdigest()
    assert fingerprint_tree(tmp_path) == expected


def test_prepare_extension_hook_state_produces_exact_serialized_fingerprint_and_entries(
    tmp_path: Path,
) -> None:
    """Prepare state matches recorded fingerprint and reports skip=True."""
    source_root = tmp_path / "source"
    home = tmp_path / "home"
    (source_root / "src").mkdir(parents=True)
    (source_root / "src" / "a.ts").write_text("a", encoding="utf-8")
    (source_root / "package.json").write_text("{}", encoding="utf-8")

    managed_state_home = home / ".local" / "share" / "agents" / "sync-managed"
    managed_state_home.mkdir(parents=True)

    adapter = next(a for a in HARNESS_ADAPTERS if a.id == "opencode")
    harness = build_harness(
        HarnessSpec(
            id=adapter.id,
            source_name=adapter.id,
            home=str(home),
            launcher=adapter.launcher,
            instruction_file=adapter.instruction_file,
            runtime_subdir=adapter.runtime_subdir,
            compat_managed_entries=adapter.compat_managed_entries,
            hooks=adapter.hooks,
        )
    )
    state_path = managed_state_home / "opencode.extension-deps.json"
    fingerprint = fingerprint_tree(source_root)
    generated_entries = ["package.json"]
    state_path.write_text(
        json.dumps({"fingerprint": fingerprint, "generatedEntries": generated_entries}),
        encoding="utf-8",
    )
    (home / "package.json").write_text("{}", encoding="utf-8")

    hook = ExtensionDepsHookPlan(
        harness=harness,
        job_root=str(home),
        root=str(home),
        source_root=str(source_root),
        relative_root="",
        state_path=str(state_path),
        timeout_ms=1000,
    )
    state = prepare_extension_hook_state(hook)
    assert state.should_skip is True
    assert state.fingerprint == fingerprint
    assert state.generated_entries == generated_entries
    assert state.preserve_paths == ["package.json"]


def test_prepare_extension_hook_state_uses_empty_relative_root_without_dot_slash_prefix(
    tmp_path: Path,
) -> None:
    """Preserve paths do not include './' when relative_root is empty."""
    source_root = tmp_path / "source"
    home = tmp_path / "home"
    (source_root / "src").mkdir(parents=True)
    (source_root / "src" / "a.ts").write_text("a", encoding="utf-8")
    (source_root / "package.json").write_text("{}", encoding="utf-8")

    managed_state_home = home / ".local" / "share" / "agents" / "sync-managed"
    managed_state_home.mkdir(parents=True)

    adapter = next(a for a in HARNESS_ADAPTERS if a.id == "opencode")
    harness = build_harness(
        HarnessSpec(
            id=adapter.id,
            source_name=adapter.id,
            home=str(home),
            launcher=adapter.launcher,
            instruction_file=adapter.instruction_file,
            runtime_subdir=adapter.runtime_subdir,
            compat_managed_entries=adapter.compat_managed_entries,
            hooks=adapter.hooks,
        )
    )
    state_path = managed_state_home / "opencode.extension-deps.json"
    fingerprint = fingerprint_tree(source_root)
    state_path.write_text(
        json.dumps({"fingerprint": fingerprint, "generatedEntries": ["package.json"]}),
        encoding="utf-8",
    )
    (home / "package.json").write_text("{}", encoding="utf-8")

    hook = ExtensionDepsHookPlan(
        harness=harness,
        job_root=str(home),
        root=str(home),
        source_root=str(source_root),
        relative_root="",
        state_path=str(state_path),
        timeout_ms=1000,
    )
    state = prepare_extension_hook_state(hook)
    assert state.should_skip is True
    assert "./package.json" not in state.preserve_paths
    assert "package.json" in state.preserve_paths


def test_prepare_extension_hook_state_records_and_preserves_nested_package_entries(
    tmp_path: Path,
) -> None:
    """Record and prepare cycle accurately captures 1-deep nested generated files."""
    source_root = tmp_path / "source"
    home = tmp_path / "home"
    (source_root / "skill-a").mkdir(parents=True)
    (source_root / "skill-a" / "package.json").write_text("{}", encoding="utf-8")

    (home / "skill-a" / "node_modules" / "dep").mkdir(parents=True)
    (home / "skill-a" / "package.json").write_text("{}", encoding="utf-8")
    (home / "skill-a" / "bun.lock").write_text("", encoding="utf-8")

    managed_state_home = home / ".local" / "share" / "agents" / "sync-managed"
    managed_state_home.mkdir(parents=True)

    adapter = next(a for a in HARNESS_ADAPTERS if a.id == "omp")
    harness = build_harness(
        HarnessSpec(
            id=adapter.id,
            source_name=adapter.id,
            home=str(home),
            launcher=adapter.launcher,
            instruction_file=adapter.instruction_file,
            runtime_subdir=adapter.runtime_subdir,
            compat_managed_entries=adapter.compat_managed_entries,
            hooks=adapter.hooks,
        )
    )
    state_path = managed_state_home / "omp.skills-deps.json"
    hook = ExtensionDepsHookPlan(
        harness=harness,
        job_root=str(home / "skills"),
        root=str(home),
        source_root=str(source_root),
        relative_root="",
        state_path=str(state_path),
        timeout_ms=1000,
    )

    prepared = prepare_extension_hook_state(hook)
    assert prepared.should_skip is False

    record_extension_hook_state(hook, prepared)

    updated_state = prepare_extension_hook_state(hook)
    assert updated_state.should_skip is True
    assert "skill-a/node_modules" in updated_state.preserve_paths
    assert "skill-a/bun.lock" in updated_state.preserve_paths
    assert "skill-a/package.json" in updated_state.preserve_paths


def test_clear_extension_hook_state(tmp_path: Path) -> None:
    """Clear state file removes state file when present, no-op when missing."""
    state_path = tmp_path / "test.state.json"
    state_path.write_text('{"fingerprint":"abc","generatedEntries":[]}')
    assert state_path.exists()

    clear_extension_hook_state(state_path)
    assert not state_path.exists()

    # Repeated clear on nonexistent path does not raise
    clear_extension_hook_state(state_path)


def test_prepare_extension_hook_state_corrupt_state(tmp_path: Path) -> None:
    """Malformed or invalid state file is ignored safely without crashing."""
    source_root = tmp_path / "source"
    home = tmp_path / "home"
    source_root.mkdir(parents=True)
    home.mkdir(parents=True)

    adapter = next(a for a in HARNESS_ADAPTERS if a.id == "opencode")
    harness = build_harness(
        HarnessSpec(
            id=adapter.id,
            source_name=adapter.id,
            home=str(home),
            launcher=adapter.launcher,
            instruction_file=adapter.instruction_file,
            runtime_subdir=adapter.runtime_subdir,
            compat_managed_entries=adapter.compat_managed_entries,
            hooks=adapter.hooks,
        )
    )
    state_path = home / "corrupt.json"
    state_path.write_text("invalid json content!@#$", encoding="utf-8")

    hook = ExtensionDepsHookPlan(
        harness=harness,
        job_root=str(home),
        root=str(home),
        source_root=str(source_root),
        relative_root="",
        state_path=str(state_path),
        timeout_ms=1000,
    )
    state = prepare_extension_hook_state(hook)
    assert state.should_skip is False
    assert state.fingerprint == fingerprint_tree(source_root)
