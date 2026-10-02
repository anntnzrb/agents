# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Isolated tests for facade configuration publication, not its HTTP behavior."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path

from sync.core.cliproxy_config import (
    Credential,
    read_cliproxy_secrets,
    sync_cliproxy_config,
)
from sync.core.cliproxy_deployment import parse_cliproxy_deployment

PRIVATE_FILE_MODE = 0o600


def _inputs(tmp_path: Path, *, key: str | None = "test-key") -> tuple[Path, Path, Path]:
    template = tmp_path / "config.yaml.tmpl"
    _ = template.write_text("host: ignored\nport: 1\n", encoding="utf-8")
    profile = {
        "systemOne": {
            "baseUrl": "https://openrouter.example.test/api/v1",
            "models": ["typesafe/jev-1.13"],
        }
    }
    _ = (tmp_path / "gateway.json").write_text(json.dumps(profile), encoding="utf-8")
    secrets: dict[str, object] = {
        "CLIPROXY_CREDENTIAL_POOLS": {},
        "CLIPROXY_FUNNEL_TOKEN": "test-funnel-" + "0" * 32,
    }
    if key is not None:
        secrets["CLIPROXY_CREDENTIAL_POOLS"] = {
            "openrouter": [{"apiKey": key, "weight": 1}]
        }
    secrets_path = tmp_path / "secrets.json"
    _ = secrets_path.write_text(json.dumps(secrets), encoding="utf-8")
    return template, tmp_path / "installed" / "config.yaml", secrets_path


def _deployment(*, enabled: bool = True) -> dict[str, object]:
    result: dict[str, object] = {
        "server": {"hostname": "test-host"},
        "listen": {"host": "127.0.0.1", "port": 18317},
        "client": {"baseUrl": "http://127.0.0.1:18319/v1"},
    }
    if enabled:
        result["gateway"] = {"host": "127.0.0.1", "port": 18319}
    return result


def test_facade_config_is_private_and_funnel_uses_the_facade(tmp_path: Path) -> None:
    """Publish the exact standalone runtime contract without exposing its key."""
    src, dst, secrets = _inputs(tmp_path)
    deployment = parse_cliproxy_deployment(_deployment())
    sync_cliproxy_config(src, dst, secrets, deployment)
    runtime = dst.parent / "gateway.json"
    assert json.loads(runtime.read_text(encoding="utf-8")) == {
        "listen": {"host": "127.0.0.1", "port": 18319},
        "upstream": "http://127.0.0.1:18317",
        "systemOne": {
            "baseUrl": "https://openrouter.example.test/api/v1",
            "models": ["typesafe/jev-1.13"],
            "apiKeyEntries": [{"apiKey": "test-key", "weight": 1}],
        },
    }
    assert runtime.stat().st_mode & 0o777 == PRIVATE_FILE_MODE
    assert yaml.safe_load(dst.read_text(encoding="utf-8"))["openai-compatibility"] == [
        {
            "name": "openrouter",
            "base-url": "https://openrouter.example.test/api/v1",
            "models": [],
            "api-key-entries": [{"api-key": "test-key", "weight": 1}],
        }
    ]
    assert dst.stat().st_mode & 0o777 == PRIVATE_FILE_MODE
    assert "CLIPROXY_UPSTREAM=http://127.0.0.1:18319\n" in (
        dst.parent / "auth-gateway.env"
    ).read_text(encoding="utf-8")
    inode = runtime.stat().st_ino
    sync_cliproxy_config(src, dst, secrets, deployment)
    assert runtime.stat().st_ino == inode


def test_disabling_facade_removes_runtime_key_and_restores_funnel(
    tmp_path: Path,
) -> None:
    """No stale facade configuration survives disabling its listener."""
    src, dst, secrets = _inputs(tmp_path)
    sync_cliproxy_config(src, dst, secrets, parse_cliproxy_deployment(_deployment()))
    sync_cliproxy_config(
        src, dst, secrets, parse_cliproxy_deployment(_deployment(enabled=False))
    )
    assert not (dst.parent / "gateway.json").exists()
    assert "CLIPROXY_UPSTREAM=http://127.0.0.1:18317\n" in (
        dst.parent / "auth-gateway.env"
    ).read_text(encoding="utf-8")


def test_missing_facade_key_fails_before_configuration_publication(
    tmp_path: Path,
) -> None:
    """Invalid activation leaves the existing files intact."""
    src, dst, secrets = _inputs(tmp_path, key=None)
    dst.parent.mkdir()
    _ = dst.write_text("old-config\n", encoding="utf-8")
    with pytest.raises(ValueError, match="openrouter"):
        sync_cliproxy_config(
            src, dst, secrets, parse_cliproxy_deployment(_deployment())
        )
    assert dst.read_text(encoding="utf-8") == "old-config\n"


@pytest.mark.parametrize(
    "models", [[], [""], ["typesafe/jev-1.13", "typesafe/jev-1.13"]]
)
def test_invalid_allowlist_fails_before_publication(
    tmp_path: Path, models: list[str]
) -> None:
    """An empty or ambiguous allowlist cannot become a runtime configuration."""
    src, dst, secrets = _inputs(tmp_path)
    _ = (tmp_path / "gateway.json").write_text(
        json.dumps(
            {
                "systemOne": {
                    "baseUrl": "https://openrouter.example.test/api/v1",
                    "models": models,
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="gateway"):
        sync_cliproxy_config(
            src, dst, secrets, parse_cliproxy_deployment(_deployment())
        )
    assert not dst.exists()


def test_facade_listener_cannot_conflict_with_backend() -> None:
    """Conflicting listeners are rejected at the deployment boundary."""
    value = _deployment()
    value["gateway"] = value["listen"]
    with pytest.raises(ValueError, match="listener"):
        _ = parse_cliproxy_deployment(value)


def test_multiple_openrouter_keys_are_registered_without_chat_models(
    tmp_path: Path,
) -> None:
    """Every pooled key is available to native quota inspection and classification."""
    src, dst, secrets_path = _inputs(tmp_path)
    value = read_cliproxy_secrets(secrets_path)
    value.cliproxy_credential_pools["openrouter"].append(
        Credential(apiKey="second-key", weight=2)
    )
    _ = secrets_path.write_text(
        json.dumps(value.model_dump(by_alias=True, exclude_none=True)), encoding="utf-8"
    )
    sync_cliproxy_config(
        src, dst, secrets_path, parse_cliproxy_deployment(_deployment())
    )
    assert json.loads((dst.parent / "gateway.json").read_text(encoding="utf-8"))[
        "systemOne"
    ]["apiKeyEntries"] == [
        {"apiKey": "test-key", "weight": 1},
        {"apiKey": "second-key", "weight": 2},
    ]
    assert (
        yaml.safe_load(dst.read_text(encoding="utf-8"))["openai-compatibility"][0][
            "models"
        ]
        == []
    )
    assert yaml.safe_load(dst.read_text(encoding="utf-8"))["openai-compatibility"][0][
        "api-key-entries"
    ] == [
        {"api-key": "test-key", "weight": 1},
        {"api-key": "second-key", "weight": 2},
    ]


def test_quota_keys_registered_when_classifier_listener_disabled(
    tmp_path: Path,
) -> None:
    """Disabling classification preserves per-key quota inspection."""
    src, dst, secrets = _inputs(tmp_path)
    sync_cliproxy_config(
        src, dst, secrets, parse_cliproxy_deployment(_deployment(enabled=False))
    )
    assert not (dst.parent / "gateway.json").exists()
    assert (
        yaml.safe_load(dst.read_text(encoding="utf-8"))["openai-compatibility"][0][
            "api-key-entries"
        ][0]["api-key"]
        == "test-key"
    )


@pytest.mark.parametrize(
    "entry",
    [{"apiKey": "bad key"}, {"apiKey": "key", "proxyUrl": "http://localhost:8080"}],
)
def test_invalid_classifier_credentials_do_not_publish(
    tmp_path: Path, entry: dict[str, object]
) -> None:
    """Reject unsupported proxy settings and unsafe header tokens before writes."""
    src, dst, secrets_path = _inputs(tmp_path)
    value = read_cliproxy_secrets(secrets_path)
    value.cliproxy_credential_pools["openrouter"] = [Credential.model_validate(entry)]
    _ = secrets_path.write_text(
        json.dumps(value.model_dump(by_alias=True, exclude_none=True)), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="openrouter"):
        sync_cliproxy_config(
            src, dst, secrets_path, parse_cliproxy_deployment(_deployment())
        )
    assert not dst.exists()
