# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Sync-owned catalog persistence with a fake network edge and real files."""

import json
from pathlib import Path

import httpx
import pytest

from sync.core.cliproxy_config import models_dev_lookup


def test_catalog_is_private_atomic_and_strips_xhigh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish privately by replacement and normalize the xhigh qualifier."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    directory = tmp_path / "agents"
    directory.mkdir()
    shared = directory / "models-dev.json"
    _ = shared.write_text("untouched", encoding="utf-8")
    owned = directory / "models-dev-sync.json"
    _ = owned.write_text("{}", encoding="utf-8")
    inode = owned.stat().st_ino

    def fetch(*_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "provider": {
                    "models": {
                        "example-xhigh": {
                            "name": "Example",
                            "limit": {"context": 123456},
                        },
                    }
                }
            },
        )

    monkeypatch.setattr(httpx, "get", fetch)
    assert models_dev_lookup()("example") == {
        "name": "Example",
        "context_length": 123456,
    }
    assert shared.read_text(encoding="utf-8") == "untouched"
    assert owned.stat().st_ino != inode
    assert json.loads(owned.read_text(encoding="utf-8"))["stripped"]["example"]
    assert sorted(p.name for p in directory.iterdir()) == [
        "models-dev-sync.json",
        "models-dev.json",
    ]


def test_catalog_rejects_unknown_cache_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an incompatible snapshot rather than trusting its freshness."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    directory = tmp_path / "agents"
    directory.mkdir()
    record = {"name": "Untrusted"}
    path = directory / "models-dev-sync.json"
    incompatible = json.dumps(
        {
            "version": 999,
            "fetchedAt": 9999999999999,
            "models": {"example": record},
            "suffixes": {},
            "stripped": {},
        }
    )
    _ = path.write_text(incompatible, encoding="utf-8")
    _ = (directory / "models-dev.json").write_text(incompatible, encoding="utf-8")

    def fetch(*_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            json={"provider": {"models": {"example": {"name": "Fetched"}}}},
        )

    monkeypatch.setattr(httpx, "get", fetch)
    assert models_dev_lookup()("example") == {"name": "Fetched"}
