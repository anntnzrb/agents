# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for CLIProxyAPI configuration rendering and sync."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypeGuard

import pytest
import yaml

from sync.core.cliproxy_config import (
    render_cliproxy_config,
    sync_cliproxy_config,
)
from sync.core.cliproxy_deployment import (
    ClientConfig,
    CliProxyDeployment,
    ListenConfig,
    ServerConfig,
)

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXPECTED_PORT: Final[int] = 9443
PRIVATE_FILE_MODE: Final[int] = 0o600

DEPLOYMENT: Final[CliProxyDeployment] = CliProxyDeployment(
    server=ServerConfig(hostname="test-gateway"),
    listen=ListenConfig(host="100.64.0.42", port=EXPECTED_PORT),
    client=ClientConfig(baseUrl="https://gateway.example.test:9443/v1"),
)


def _is_obj_dict(val: object) -> TypeGuard[dict[str, object]]:
    return isinstance(val, dict)


def test_cliproxy_render_config_expands_native_and_compatibility_credential_pools() -> (
    None
):
    """Test expansion of native and compatibility pools in template."""
    template = """host: ${CLIPROXY_LISTEN_HOST}
port: ${CLIPROXY_LISTEN_PORT}
remote-management:
  allow-remote: true
  secret-key: test-secret
codex-api-key:
  - x-credential-pool: codex-pool
    prefix: codex-custom
openai-compatibility:
  - name: custom-provider
    prefix: custom
    x-credential-pool: compat-pool
"""
    secrets = {
        "CLIPROXY_CREDENTIAL_POOLS": {
            "codex-pool": [
                {"apiKey": "codex-key-1", "weight": 2},
                {
                    "apiKey": "codex-key-2",
                    "weight": 3,
                    "proxyUrl": "http://proxy.test:8080",
                },
            ],
            "compat-pool": [
                {"apiKey": "compat-key-1", "weight": 1},
                {"apiKey": "compat-key-2"},
            ],
        },
    }

    rendered = render_cliproxy_config(template, secrets, DEPLOYMENT)
    parsed: object = yaml.safe_load(rendered)  # pyright: ignore[reportAny]
    assert isinstance(parsed, dict)
    assert parsed["host"] == "100.64.0.42"
    assert parsed["port"] == EXPECTED_PORT
    assert parsed["remote-management"] == {
        "allow-remote": True,
        "secret-key": "test-secret",
    }
    assert parsed["codex-api-key"] == [
        {"api-key": "codex-key-1", "weight": 2, "prefix": "codex-custom"},
        {
            "api-key": "codex-key-2",
            "weight": 3,
            "proxy-url": "http://proxy.test:8080",
            "prefix": "codex-custom",
        },
    ]
    assert parsed["openai-compatibility"] == [
        {
            "name": "custom-provider",
            "prefix": "custom",
            "api-key-entries": [
                {"api-key": "compat-key-1", "weight": 1},
                {"api-key": "compat-key-2"},
            ],
        },
    ]


def test_cliproxy_render_config_rejects_unreferenced_credential_pools() -> None:
    """Test error when a credential pool is in secrets but unused in template."""
    template = """host: ${CLIPROXY_LISTEN_HOST}
port: ${CLIPROXY_LISTEN_PORT}
codex-api-key:
  - x-credential-pool: used-pool
"""
    secrets = {
        "CLIPROXY_CREDENTIAL_POOLS": {
            "used-pool": [{"apiKey": "k1"}],
            "unused-pool": [{"apiKey": "k2"}],
        },
    }

    with pytest.raises(
        ValueError,
        match="unreferenced CLIProxyAPI credential pool: unused-pool",
    ):
        _ = render_cliproxy_config(template, secrets, DEPLOYMENT)


def test_cliproxy_render_config_rejects_x_model_sources() -> None:
    """Test error when template contains deprecated x-model-sources field."""
    template = """host: ${CLIPROXY_LISTEN_HOST}
port: ${CLIPROXY_LISTEN_PORT}
x-model-sources:
  - id: example
"""
    secrets: dict[str, object] = {"CLIPROXY_CREDENTIAL_POOLS": {}}
    with pytest.raises(
        ValueError,
        match="unsupported CLIProxyAPI template field: x-model-sources",
    ):
        _ = render_cliproxy_config(template, secrets, DEPLOYMENT)


def test_committed_template_renders_with_example_secrets() -> None:
    """Test that the committed config template renders with example secrets."""
    template_path = REPOSITORY_ROOT / "tools" / "cliproxyapi" / "config.yaml.tmpl"
    secrets_path = REPOSITORY_ROOT / "secrets.local.example.json"

    template = template_path.read_text(encoding="utf-8")
    secrets_text = secrets_path.read_text(encoding="utf-8")
    secrets: object = json.loads(secrets_text)  # pyright: ignore[reportAny]
    assert _is_obj_dict(secrets)

    rendered = render_cliproxy_config(template, secrets, DEPLOYMENT)
    parsed: object = yaml.safe_load(rendered)  # pyright: ignore[reportAny]
    assert isinstance(parsed, dict)
    assert parsed["host"] == "100.64.0.42"
    assert parsed["port"] == EXPECTED_PORT


def test_cliproxy_render_config_rejects_missing_credential_pools() -> None:
    """Test error when template references a pool missing from secrets."""
    template = """host: ${CLIPROXY_LISTEN_HOST}
port: ${CLIPROXY_LISTEN_PORT}
codex-api-key:
  - x-credential-pool: missing-pool
"""
    secrets = {
        "CLIPROXY_CREDENTIAL_POOLS": {
            "other-pool": [{"apiKey": "k1"}],
        },
    }

    with pytest.raises(
        ValueError,
        match="missing CLIProxyAPI credential pool: missing-pool",
    ):
        _ = render_cliproxy_config(template, secrets, DEPLOYMENT)


def test_cliproxy_sync_writes_private_config_file(tmp_path: Path) -> None:
    """Test that sync_cliproxy_config writes dst with mode 0600."""
    src = tmp_path / "config.yaml.tmpl"
    dst = tmp_path / "runtime" / "config.yaml"
    secrets_path = tmp_path / "secrets.json"
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)

    _ = src.write_text(
        """host: ${CLIPROXY_LISTEN_HOST}
port: ${CLIPROXY_LISTEN_PORT}
remote-management:
  allow-remote: true
codex-api-key:
  - x-credential-pool: fixture
""",
        encoding="utf-8",
    )
    _ = secrets_path.write_text(
        json.dumps(
            {
                "CLIPROXY_CREDENTIAL_POOLS": {
                    "fixture": [{"apiKey": "upstream"}],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    sync_cliproxy_config(src, dst, secrets_path, DEPLOYMENT)

    assert dst.exists()
    assert dst.stat().st_mode & 0o777 == PRIVATE_FILE_MODE
    rendered_text = dst.read_text(encoding="utf-8")
    parsed: object = yaml.safe_load(rendered_text)  # pyright: ignore[reportAny]
    assert isinstance(parsed, dict)
    assert parsed["host"] == "100.64.0.42"
    assert parsed["port"] == EXPECTED_PORT
    assert parsed["codex-api-key"] == [{"api-key": "upstream"}]


def test_cliproxy_render_config_passes_through_static_native_entry() -> None:
    """Test that native credential entries without pool marker pass through."""
    template = """host: ${CLIPROXY_LISTEN_HOST}
port: ${CLIPROXY_LISTEN_PORT}
codex-api-key:
  - api-key: static-upstream-key
    weight: 1
    prefix: static-prefix
"""
    secrets: dict[str, object] = {"CLIPROXY_CREDENTIAL_POOLS": {}}

    rendered = render_cliproxy_config(template, secrets, DEPLOYMENT)
    parsed: object = yaml.safe_load(rendered)  # pyright: ignore[reportAny]
    assert isinstance(parsed, dict)
    assert parsed["codex-api-key"] == [
        {"api-key": "static-upstream-key", "weight": 1, "prefix": "static-prefix"}
    ]


@pytest.mark.parametrize(
    ("section_yaml", "expected_match"),
    [
        (
            "openai-compatibility:\n  - name: c1\n    x-credential-pool: null",
            (
                r"invalid openai-compatibility\[0\]\.x-credential-pool: "
                r"expected non-empty string"
            ),
        ),
        (
            "codex-api-key:\n  - x-credential-pool: null",
            (
                r"invalid codex-api-key\[0\]\.x-credential-pool: "
                r"expected non-empty string"
            ),
        ),
    ],
)
def test_cliproxy_render_config_rejects_null_credential_pool_marker(
    section_yaml: str,
    expected_match: str,
) -> None:
    """Test error when an entry explicitly sets x-credential-pool to null."""
    template = f"""host: ${{CLIPROXY_LISTEN_HOST}}
port: ${{CLIPROXY_LISTEN_PORT}}
{section_yaml}
"""
    secrets: dict[str, object] = {"CLIPROXY_CREDENTIAL_POOLS": {}}

    with pytest.raises(ValueError, match=expected_match):
        _ = render_cliproxy_config(template, secrets, DEPLOYMENT)
