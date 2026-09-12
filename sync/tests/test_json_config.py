# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for managed JSON configuration copy preserving declared keys."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sync.core.json_config import sync_json_config

if TYPE_CHECKING:
    from pathlib import Path


def test_sync_json_config_copies_source_verbatim(tmp_path: Path) -> None:
    """Verify an empty preserve list produces a byte-identical copy."""
    src = tmp_path / "config.json"
    dst = tmp_path / "devin" / "config.json"
    raw = '{"version": 1,"auto_update":false,  "theme_mode":"dark"}\n'
    _ = src.write_text(raw, encoding="utf-8")

    sync_json_config(str(src), str(dst), ())

    assert dst.read_text(encoding="utf-8") == raw


def test_sync_json_config_reinjects_declared_destination_paths(
    tmp_path: Path,
) -> None:
    """Verify declared dot-paths from the destination survive the copy."""
    src = tmp_path / "config.json"
    dst = tmp_path / "devin" / "config.json"
    dst.parent.mkdir()
    _ = src.write_text(
        '{"version": 1, "auto_update": false, "agent": {"model": "managed"}}\n',
        encoding="utf-8",
    )
    _ = dst.write_text(
        json.dumps(
            {
                "version": 1,
                "devin": {"org_id": "org-1"},
                "shell": {"setup_complete": True},
                "agent": {"preferred_family_models": {"swe-2": "swe-2-max"}},
            }
        ),
        encoding="utf-8",
    )

    sync_json_config(
        str(src),
        str(dst),
        ("devin", "shell", "agent.preferred_family_models"),
    )

    assert json.loads(dst.read_text(encoding="utf-8")) == {
        "version": 1,
        "auto_update": False,
        "agent": {
            "model": "managed",
            "preferred_family_models": {"swe-2": "swe-2-max"},
        },
        "devin": {"org_id": "org-1"},
        "shell": {"setup_complete": True},
    }


def test_sync_json_config_source_wins_declared_collisions(tmp_path: Path) -> None:
    """Verify a declared path defined by the source keeps the source value."""
    src = tmp_path / "config.json"
    dst = tmp_path / "devin" / "config.json"
    dst.parent.mkdir()
    _ = src.write_text('{"devin": {"org_id": "managed-org"}}\n', encoding="utf-8")
    _ = dst.write_text(
        '{"devin": {"org_id": "org-1", "extra": true}}\n', encoding="utf-8"
    )

    sync_json_config(str(src), str(dst), ("devin",))

    assert json.loads(dst.read_text(encoding="utf-8")) == {
        "devin": {"org_id": "managed-org"}
    }


def test_sync_json_config_skips_paths_absent_in_destination(tmp_path: Path) -> None:
    """Verify a declared path missing from the destination is not added."""
    src = tmp_path / "config.json"
    dst = tmp_path / "devin" / "config.json"
    dst.parent.mkdir()
    _ = src.write_text('{"version": 1}\n', encoding="utf-8")
    _ = dst.write_text('{"devin": {"org_id": "org-1"}}\n', encoding="utf-8")

    sync_json_config(str(src), str(dst), ("devin", "shell"))

    assert json.loads(dst.read_text(encoding="utf-8")) == {
        "version": 1,
        "devin": {"org_id": "org-1"},
    }


def test_sync_json_config_removes_undeclared_destination_keys(
    tmp_path: Path,
) -> None:
    """Verify destination keys outside the declared paths are removed."""
    src = tmp_path / "config.json"
    dst = tmp_path / "devin" / "config.json"
    dst.parent.mkdir()
    _ = src.write_text('{"version": 1}\n', encoding="utf-8")
    _ = dst.write_text(
        '{"stale": true, "devin": {"org_id": "org-1"}}\n', encoding="utf-8"
    )

    sync_json_config(str(src), str(dst), ("devin",))

    assert json.loads(dst.read_text(encoding="utf-8")) == {
        "version": 1,
        "devin": {"org_id": "org-1"},
    }


def test_sync_json_config_source_wins_non_object_ancestor(tmp_path: Path) -> None:
    """Verify a declared path under a source-defined scalar is not injected."""
    src = tmp_path / "config.json"
    dst = tmp_path / "devin" / "config.json"
    dst.parent.mkdir()
    _ = src.write_text('{"agent": "managed-scalar"}\n', encoding="utf-8")
    _ = dst.write_text(
        '{"agent": {"preferred_family_models": {"swe-2": "swe-2-max"}}}\n',
        encoding="utf-8",
    )

    sync_json_config(str(src), str(dst), ("agent.preferred_family_models",))

    assert json.loads(dst.read_text(encoding="utf-8")) == {"agent": "managed-scalar"}


def test_sync_json_config_verbatim_copy_when_nothing_survives(
    tmp_path: Path,
) -> None:
    """Verify a byte-identical copy when no declared path exists in dst."""
    src = tmp_path / "config.json"
    dst = tmp_path / "devin" / "config.json"
    dst.parent.mkdir()
    raw = '{"version": 1,"auto_update":false}\n'
    _ = src.write_text(raw, encoding="utf-8")
    _ = dst.write_text('{"stale": true}\n', encoding="utf-8")

    sync_json_config(str(src), str(dst), ("devin", "shell"))

    assert dst.read_text(encoding="utf-8") == raw


def test_sync_json_config_creates_missing_destination(tmp_path: Path) -> None:
    """Verify a missing destination is created from the managed source."""
    src = tmp_path / "config.json"
    dst = tmp_path / "devin" / "config.json"
    _ = src.write_text('{"version": 1, "auto_update": false}\n', encoding="utf-8")

    sync_json_config(str(src), str(dst), ("devin",))

    assert json.loads(dst.read_text(encoding="utf-8")) == {
        "version": 1,
        "auto_update": False,
    }


def test_sync_json_config_missing_source_raises(tmp_path: Path) -> None:
    """Verify a missing source file is an error."""
    src = tmp_path / "config.json"
    dst = tmp_path / "devin" / "config.json"

    with pytest.raises(RuntimeError, match="missing source"):
        sync_json_config(str(src), str(dst), ())
