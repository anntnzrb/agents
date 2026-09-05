# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for extension hook state management and tree fingerprinting."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Final, TypeGuard

import pytest

if TYPE_CHECKING:
    from pathlib import Path
from sync.core.harness import HarnessSpec, build_harness
from sync.core.harness_adapters import HARNESS_ADAPTERS
from sync.core.hook_state import (
    clear_extension_hook_state,
    fingerprint_tree,
    load_extension_hook_state,
    prepare_extension_hook_state,
    record_extension_hook_state,
)
from sync.core.managed_state import (
    load_recorded_entry_names,
    top_level_entry_names,
)
from sync.core.plan import ExtensionDepsHookPlan
from sync.core.secret_template import render_secret_template
from sync.runtime.fs import sync_text_file
from sync.runtime.jsonc import strip_jsonc

_MISSING_SHA256: Final[str] = (
    "ffa63583dfa6706b87d284b86b0d693a161e4840aad2c5cf6b5d27c3b9621f7d"
)
SHA256_HEX_LENGTH: Final[int] = 64
EXPECTED_PRIVATE_MODE: Final[int] = 0o600


def _is_obj_dict(val: object) -> TypeGuard[dict[str, object]]:
    return isinstance(val, dict)


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
    _ = (tmp_path / "src" / "a.ts").write_text("a", encoding="utf-8")
    _ = (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    first = fingerprint_tree(tmp_path)
    second = fingerprint_tree(tmp_path)
    assert first == second


def test_fingerprint_tree_changes_when_file_content_changes(
    tmp_path: Path,
) -> None:
    """Modifying a file inside tree changes the fingerprint."""
    (tmp_path / "src").mkdir(parents=True)
    _ = (tmp_path / "src" / "a.ts").write_text("a", encoding="utf-8")

    first = fingerprint_tree(tmp_path)
    _ = (tmp_path / "src" / "a.ts").write_text("b", encoding="utf-8")
    second = fingerprint_tree(tmp_path)

    assert first != second


def test_fingerprint_tree_ignores_python_cache_directories_and_compiled_files(
    tmp_path: Path,
) -> None:
    """Python cache dirs and bytecode files are ignored in tree fingerprinting."""
    (tmp_path / "src" / "__pycache__").mkdir(parents=True)
    _ = (tmp_path / "src" / "a.py").write_text("print(1)", encoding="utf-8")
    _ = (tmp_path / "src" / "__pycache__" / "a.cpython-312.pyc").write_bytes(
        b"bytecode"
    )
    _ = (tmp_path / "src" / "compiled.pyo").write_bytes(b"bytecode")

    baseline = fingerprint_tree(tmp_path)

    _ = (tmp_path / "src" / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"mutated")
    _ = (tmp_path / "src" / "compiled.pyo").write_bytes(b"mutated")

    assert fingerprint_tree(tmp_path) == baseline


def test_fingerprint_tree_refuses_source_directory_symlinks_with_diagnostic_error(
    tmp_path: Path,
) -> None:
    """Directory symlinks are refused with a diagnostic error message."""
    target_dir = tmp_path / "target_dir"
    target_dir.mkdir()
    _ = (target_dir / "file.txt").write_text("hello", encoding="utf-8")
    link_dir = tmp_path / "link_dir"
    link_dir.symlink_to(target_dir)

    expected_pattern = re.escape(f"refusing source directory symlink: {link_dir}")
    with pytest.raises(ValueError, match=expected_pattern):
        _ = fingerprint_tree(tmp_path)


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
        _ = fingerprint_tree(tmp_path)


def test_fingerprint_tree_rejects_symlink_loop_cycles_before_unbounded_recursion(
    tmp_path: Path,
) -> None:
    """Symlink loop cycles (link_a -> link_b -> link_a) raise error."""
    link_a = tmp_path / "link_a"
    link_b = tmp_path / "link_b"
    link_a.symlink_to(link_b)
    link_b.symlink_to(link_a)

    with pytest.raises(OSError, match=r"Too many levels of symbolic links|loop"):
        _ = fingerprint_tree(tmp_path)


def test_fingerprint_tree_records_broken_symlinks_without_failing(
    tmp_path: Path,
) -> None:
    """Broken symlinks are hashed with broken: prefix without raising."""
    (tmp_path / "broken_link").symlink_to(tmp_path / "nonexistent")
    fp1 = fingerprint_tree(tmp_path)
    assert isinstance(fp1, str)
    assert len(fp1) == SHA256_HEX_LENGTH
    assert fingerprint_tree(tmp_path) == fp1

    expected_fp1 = hashlib.sha256(b"broken:broken_link\n").hexdigest()
    assert fp1 == expected_fp1

    (tmp_path / "broken_link_2").symlink_to(tmp_path / "nonexistent2")
    fp2 = fingerprint_tree(tmp_path)
    assert fp2 != fp1

    expected_fp2 = hashlib.sha256(
        b"broken:broken_link\nbroken:broken_link_2\n"
    ).hexdigest()
    assert fp2 == expected_fp2


def test_fingerprint_tree_regular_files_and_normal_subdirs_fingerprint_identically(
    tmp_path: Path,
) -> None:
    """Independent identical trees produce identical fingerprints."""
    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"

    for r in [root1, root2]:
        (r / "src" / "nested").mkdir(parents=True)
        _ = (r / "src" / "index.ts").write_text("export const x = 1;", encoding="utf-8")
        _ = (r / "src" / "nested" / "util.ts").write_text(
            "export const util = true;", encoding="utf-8"
        )
        _ = (r / "package.json").write_text('{"name":"test"}', encoding="utf-8")

    assert fingerprint_tree(root1) == fingerprint_tree(root2)


def test_fingerprint_tree_fingerprints_symlinks_to_regular_files(
    tmp_path: Path,
) -> None:
    """Symlinks to regular files track target content changes."""
    target_file = tmp_path / "target.txt"
    _ = target_file.write_text("target content", encoding="utf-8")
    fp_without_link = fingerprint_tree(tmp_path)

    (tmp_path / "link.txt").symlink_to(target_file)

    fp = fingerprint_tree(tmp_path)
    assert isinstance(fp, str)
    assert len(fp) == SHA256_HEX_LENGTH
    assert fingerprint_tree(tmp_path) == fp
    assert fp != fp_without_link

    _ = target_file.write_text("mutated target content", encoding="utf-8")
    fp_mutated = fingerprint_tree(tmp_path)
    assert fp_mutated != fp
    assert fp_mutated != fp_without_link


def test_fingerprint_tree_sorts_directory_entries_with_mixed_case_and_non_ascii_names(
    tmp_path: Path,
) -> None:
    """Entries are processed in deterministic Unicode code-point order."""
    for name in ["_x", "a", "B", "ä", "z"]:
        _ = (tmp_path / name).write_text(f"content of {name}", encoding="utf-8")

    (tmp_path / "Sub_C").mkdir()
    _ = (tmp_path / "Sub_C" / "file.txt").write_text("sub C", encoding="utf-8")
    (tmp_path / "sub_b").mkdir()
    _ = (tmp_path / "sub_b" / "file.txt").write_text("sub b", encoding="utf-8")
    (tmp_path / "sub_ä").mkdir()
    _ = (tmp_path / "sub_ä" / "file.txt").write_text("sub ä", encoding="utf-8")

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
    _ = (source_root / "src" / "a.ts").write_text("a", encoding="utf-8")
    _ = (source_root / "package.json").write_text("{}", encoding="utf-8")

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
    _ = state_path.write_text(
        json.dumps({"fingerprint": fingerprint, "generatedEntries": generated_entries}),
        encoding="utf-8",
    )
    _ = (home / "package.json").write_text("{}", encoding="utf-8")

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
    _ = (source_root / "src" / "a.ts").write_text("a", encoding="utf-8")
    _ = (source_root / "package.json").write_text("{}", encoding="utf-8")

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
    _ = state_path.write_text(
        json.dumps({"fingerprint": fingerprint, "generatedEntries": ["package.json"]}),
        encoding="utf-8",
    )
    _ = (home / "package.json").write_text("{}", encoding="utf-8")

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
    _ = (source_root / "skill-a" / "package.json").write_text("{}", encoding="utf-8")

    (home / "skill-a" / "node_modules" / "dep").mkdir(parents=True)
    _ = (home / "skill-a" / "package.json").write_text("{}", encoding="utf-8")
    _ = (home / "skill-a" / "bun.lock").write_text("", encoding="utf-8")

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
    _ = state_path.write_text('{"fingerprint":"abc","generatedEntries":[]}')
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
    _ = state_path.write_text("invalid json content!@#$", encoding="utf-8")

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


def test_prepare_extension_hook_state_branches(tmp_path: Path) -> None:
    """Hook state handles invalid shape, stale entries, missing file, and JSONC."""
    source_root = tmp_path / "source"
    home = tmp_path / "home"
    source_root.mkdir(parents=True)
    home.mkdir(parents=True)
    (source_root / "src").mkdir(parents=True)
    _ = (source_root / "src" / "index.ts").write_text(
        "export const x = 1;", encoding="utf-8"
    )
    fp = fingerprint_tree(source_root)

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
    state_path = home / "state.json"
    hook = ExtensionDepsHookPlan(
        harness=harness,
        job_root=str(home),
        root=str(home),
        source_root=str(source_root),
        relative_root="",
        state_path=str(state_path),
        timeout_ms=1000,
    )

    # 1. Missing state file
    missing_state = prepare_extension_hook_state(hook)
    assert missing_state.should_skip is False
    assert missing_state.should_refresh_state is False
    assert missing_state.generated_entries == []

    # 2. Wrong shape (JSON array)
    _ = state_path.write_text("[1, 2, 3]", encoding="utf-8")
    array_state = prepare_extension_hook_state(hook)
    assert array_state.should_skip is False

    # 3. Wrong shape (missing generatedEntries / invalid types)
    _ = state_path.write_text(
        json.dumps({"fingerprint": 123, "generatedEntries": []}), encoding="utf-8"
    )
    bad_type_state = prepare_extension_hook_state(hook)
    assert bad_type_state.should_skip is False

    # 4. JSONC comments in state file
    _ = (home / "package.json").write_text("{}", encoding="utf-8")
    jsonc_payload = f"""// leading comment
    /* block comment */
    {{
      "fingerprint": "{fp}",
      "generatedEntries": [
        "package.json",
      ],
    }}"""
    _ = state_path.write_text(jsonc_payload, encoding="utf-8")
    jsonc_state = prepare_extension_hook_state(hook)
    assert jsonc_state.should_skip is True
    assert jsonc_state.preserve_paths == ["package.json"]

    # 5. Non-generated entries filtered and should_refresh_state set to True
    _ = (home / "custom.txt").write_text("custom", encoding="utf-8")
    mixed_payload = json.dumps(
        {
            "fingerprint": fp,
            "generatedEntries": ["package.json", "custom.txt", "unrelated.ts"],
        }
    )
    _ = state_path.write_text(mixed_payload, encoding="utf-8")
    filtered_state = prepare_extension_hook_state(hook)
    assert filtered_state.should_skip is True
    assert filtered_state.generated_entries == ["package.json"]
    assert filtered_state.preserve_paths == ["package.json"]
    assert filtered_state.should_refresh_state is True


def test_strip_jsonc_trailing_comma_string_aware() -> None:
    """strip_jsonc removes trailing commas without modifying commas in strings."""
    jsonc_input = """{
        // comment before key
        "message": "hello, } world",
        "nested": {
            "key, ] test": "value, }", /* block comment */
        },
        "list": [
            "item, } 1",
            "item, ] 2",
        ],
    }"""
    cleaned = strip_jsonc(jsonc_input)
    parsed: object = json.loads(cleaned)  # pyright: ignore[reportAny]
    assert _is_obj_dict(parsed)
    assert parsed["message"] == "hello, } world"
    nested = parsed["nested"]
    assert _is_obj_dict(nested)
    assert nested["key, ] test"] == "value, }"
    assert parsed["list"] == ["item, } 1", "item, ] 2"]


def test_load_state_ignores_invalid_unicode_decode_error(tmp_path: Path) -> None:
    """load_recorded_entry_names and load_extension_hook_state handle invalid UTF-8."""
    bad_managed_state = tmp_path / "bad_managed.json"
    _ = bad_managed_state.write_bytes(b"\x80\xff\xfe\x00not-utf8")

    entries = load_recorded_entry_names(bad_managed_state)
    assert entries == []

    bad_hook_state = tmp_path / "bad_hook.json"
    _ = bad_hook_state.write_bytes(b"\x80\xff\xfe\x00not-utf8")

    hook_state = load_extension_hook_state(str(bad_hook_state))
    assert hook_state is None


def test_fingerprint_tree_propagates_oserror_when_not_enoent(tmp_path: Path) -> None:
    """fingerprint_tree propagates EACCES/ENOTDIR instead of swallowing them."""
    file_path = tmp_path / "regular_file.txt"
    _ = file_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        _ = fingerprint_tree(file_path)

    unreadable_dir = tmp_path / "unreadable"
    unreadable_dir.mkdir()
    _ = (unreadable_dir / "child.txt").write_text("inner", encoding="utf-8")
    unreadable_dir.chmod(0o000)
    try:
        with pytest.raises(PermissionError):
            _ = fingerprint_tree(unreadable_dir)
    finally:
        unreadable_dir.chmod(0o755)


def test_render_secret_template_preserves_non_ascii_unicode_bytes() -> None:
    """render_secret_template produces unescaped UTF-8 matching JSON.stringify."""
    template = '{"secret": ${SECRET_VAL}, "plain": "ok"}'
    unicode_value = "clé_secrète_🔑_日本語"
    rendered = render_secret_template(template, {"SECRET_VAL": unicode_value})
    assert f'"{unicode_value}"' in rendered
    assert "\\u" not in rendered

    parsed: object = json.loads(rendered)  # pyright: ignore[reportAny]
    assert _is_obj_dict(parsed)
    assert parsed["secret"] == unicode_value
    assert parsed["plain"] == "ok"


def test_top_level_entry_names_reexported_from_plan(tmp_path: Path) -> None:
    """managed_state.top_level_entry_names behaves identically to plan export."""
    (tmp_path / "alpha").mkdir()
    _ = (tmp_path / "beta.txt").write_text("content", encoding="utf-8")
    names = top_level_entry_names(str(tmp_path))
    assert names == ["alpha", "beta.txt"]


def test_sync_text_file_loops_os_write_completely(tmp_path: Path) -> None:
    """sync_text_file writes full content atomically with correct mode."""
    target = tmp_path / "subdir" / "output.txt"
    payload = "long text payload with multi-byte unicode: 🚀 — " * 100
    sync_text_file(target, payload, mode=EXPECTED_PRIVATE_MODE)
    assert target.exists()
    assert (target.stat().st_mode & 0o777) == EXPECTED_PRIVATE_MODE
    assert target.read_text(encoding="utf-8") == payload
