# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for package manifest decoding, settings patching, and bootstrap."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from sync.packages.index import (
    PackageBootstrapTarget,
    bootstrap_package_target,
    package_cache_dir,
    patch_runtime_settings,
    read_package_manifest,
)

if TYPE_CHECKING:
    from pathlib import Path

_EXPECTED_MODE = 0o644


def test_read_package_manifest_returns_empty_manifest_when_missing(
    tmp_path: Path,
) -> None:
    """read_package_manifest returns empty packages list when file does not exist."""
    manifest_path = tmp_path / "packages.json"
    manifest = read_package_manifest(str(manifest_path))
    assert manifest.packages == []


def test_read_package_manifest_trims_and_deduplicates_package_sources(
    tmp_path: Path,
) -> None:
    """read_package_manifest trims whitespace and deduplicates package sources."""
    manifest_path = tmp_path / "packages.json"
    content = """{
      // Comment in JSONC
      "packages": [
        "  https://github.com/owner/repo1  ",
        "https://github.com/owner/repo2",
        "https://github.com/owner/repo1"
      ]
    }
    """
    manifest_path.write_text(content, encoding="utf-8")
    manifest = read_package_manifest(str(manifest_path))
    assert manifest.packages == [
        "https://github.com/owner/repo1",
        "https://github.com/owner/repo2",
    ]


def test_read_package_manifest_raises_on_invalid_json(
    tmp_path: Path,
) -> None:
    """read_package_manifest raises ValueError when parsing invalid JSON."""
    manifest_path = tmp_path / "packages.json"
    manifest_path.write_text("invalid json content {", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        read_package_manifest(str(manifest_path))


def test_read_package_manifest_rejects_missing_packages_key(
    tmp_path: Path,
) -> None:
    """read_package_manifest raises ValueError when packages key is missing."""
    manifest_path = tmp_path / "packages.json"
    manifest_path.write_text('{"theme": "dark"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="packages"):
        read_package_manifest(str(manifest_path))


def test_read_package_manifest_rejects_empty_string_entries(
    tmp_path: Path,
) -> None:
    """read_package_manifest raises ValueError on empty or whitespace entries."""
    manifest_path = tmp_path / "packages.json"
    manifest_path.write_text(
        '{"packages": ["https://github.com/owner/repo", ""]}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="package source must not be empty"):
        read_package_manifest(str(manifest_path))

    manifest_path.write_text(
        '{"packages": ["   "]}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="package source must not be empty"):
        read_package_manifest(str(manifest_path))


def test_bootstrap_package_target_fails_and_leaves_settings_untouched(
    tmp_path: Path,
) -> None:
    """bootstrap_package_target fails without modifying runtime settings."""
    manifest_path = tmp_path / "packages.json"
    manifest_path.write_text('{"packages": [""]}\n', encoding="utf-8")
    settings_path = tmp_path / "settings.json"
    original_settings = '{"theme": "nord"}\n'
    settings_path.write_text(original_settings, encoding="utf-8")

    target = PackageBootstrapTarget(
        manifest_path=str(manifest_path),
        runtime_settings_path=str(settings_path),
        cache_root=str(tmp_path / "cache"),
        timeout_ms=5000,
    )
    success = asyncio.run(bootstrap_package_target(target))
    assert success is False
    assert settings_path.read_text(encoding="utf-8") == original_settings


def test_patch_runtime_settings_replaces_symlink_with_regular_file(
    tmp_path: Path,
) -> None:
    """patch_runtime_settings replaces symlink with regular file preserving target."""
    cache_root = tmp_path / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    source = "https://github.com/owner/repo"
    expected = package_cache_dir(str(cache_root), source)

    external = tmp_path / "external-settings.json"
    original = '{"theme":"dark","packages":[]}\n'
    external.write_text(original, encoding="utf-8")

    settings_path = tmp_path / "settings.json"
    settings_path.symlink_to(external)

    patch_runtime_settings(str(settings_path), [expected])

    assert settings_path.is_file()
    assert not settings_path.is_symlink()
    assert external.read_text(encoding="utf-8") == original

    parsed = json.loads(settings_path.read_text(encoding="utf-8"))
    assert parsed["packages"] == [expected]
    assert parsed["theme"] == "dark"


def test_patch_runtime_settings_preserves_mode_of_existing_regular_file(
    tmp_path: Path,
) -> None:
    """patch_runtime_settings preserves unix permission mode on regular files."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{}", encoding="utf-8")
    settings_path.chmod(_EXPECTED_MODE)

    patch_runtime_settings(str(settings_path), [])

    assert settings_path.is_file()
    assert settings_path.stat().st_mode & 0o777 == _EXPECTED_MODE
