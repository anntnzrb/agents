# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for merging managed JSON configuration over local machine state."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sync.core.json_config import merge_json_objects, sync_merged_json_config

if TYPE_CHECKING:
    from pathlib import Path


def test_merge_json_objects_overlays_nested_keys_and_preserves_local_keys() -> None:
    """Verify nested overlay wins while destination-only keys are preserved."""
    base = {
        "version": 1,
        "devin": {"org_id": "org-1"},
        "agent": {"model": "local", "preferred_family_models": {"swe-2": "swe-2-max"}},
    }
    overlay = {"auto_update": False, "agent": {"model": "managed"}}

    assert merge_json_objects(base, overlay) == {
        "version": 1,
        "devin": {"org_id": "org-1"},
        "agent": {
            "model": "managed",
            "preferred_family_models": {"swe-2": "swe-2-max"},
        },
        "auto_update": False,
    }


def test_merge_json_objects_replaces_arrays_and_scalars() -> None:
    """Verify overlay arrays and scalars replace destination values outright."""
    base = {"permissions": {"allow": ["Read(**)"]}, "theme_mode": "dark"}
    overlay = {"permissions": {"allow": ["Exec(git)"]}, "theme_mode": "light"}

    assert merge_json_objects(base, overlay) == {
        "permissions": {"allow": ["Exec(git)"]},
        "theme_mode": "light",
    }


def test_sync_merged_json_config_writes_overlay_and_preserves_local_keys(
    tmp_path: Path,
) -> None:
    """Verify managed keys publish while destination-only keys survive."""
    src = tmp_path / "config.json"
    dst = tmp_path / "devin" / "config.json"
    dst.parent.mkdir()
    _ = src.write_text('{"version": 1, "auto_update": false}\n', encoding="utf-8")
    _ = dst.write_text(
        '{"version": 1, "devin": {"org_id": "org-1"}}\n', encoding="utf-8"
    )

    sync_merged_json_config(str(src), str(dst))

    assert json.loads(dst.read_text(encoding="utf-8")) == {
        "version": 1,
        "devin": {"org_id": "org-1"},
        "auto_update": False,
    }


def test_sync_merged_json_config_creates_destination_from_source(
    tmp_path: Path,
) -> None:
    """Verify a missing destination is created from the managed source."""
    src = tmp_path / "config.json"
    dst = tmp_path / "devin" / "config.json"
    _ = src.write_text('{"version": 1, "auto_update": false}\n', encoding="utf-8")

    sync_merged_json_config(str(src), str(dst))

    assert json.loads(dst.read_text(encoding="utf-8")) == {
        "version": 1,
        "auto_update": False,
    }
