# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for CLIProxyAPI deployment parsing, template preservation, and publication."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypeGuard

if TYPE_CHECKING:
    from collections.abc import Callable
import httpx
import pytest
import yaml

from sync.core.cliproxy_deployment import (
    CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER,
    ClientConfig,
    CliProxyDeployment,
    CliProxyEndpointSyncOptions,
    CliProxyEndpointTarget,
    ListenConfig,
    ServerConfig,
    append_preserved_sections,
    extract_preserved_top_levels,
    is_cliproxy_target_ready,
    parse_cliproxy_deployment,
    publish_cliproxy_endpoint_templates,
    render_cliproxy_endpoint_template,
    sync_cliproxy_endpoint_template,
)

REPOSITORY_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MODE_640: Final[int] = 0o640
MODE_600: Final[int] = 0o600
DEPLOYMENT: Final[CliProxyDeployment] = CliProxyDeployment(
    server=ServerConfig(hostname=socket.gethostname()),
    listen=ListenConfig(host="100.64.0.42", port=9443),
    client=ClientConfig(baseUrl="https://gateway.example.test:9443/v1"),
)


def _is_obj_dict(val: object) -> TypeGuard[dict[str, object]]:
    return isinstance(val, dict)


def _is_obj_list(val: object) -> TypeGuard[list[object]]:
    return isinstance(val, list)


def _make_fake_fetch(response: httpx.Response) -> Callable[..., httpx.Response]:
    def fake_fetch(_url: str, **_kw: object) -> httpx.Response:
        return response

    return fake_fetch


def _fetch_ready(_url: str, **_kw: object) -> httpx.Response:
    return httpx.Response(200, json={"data": [{"id": "ready"}]})


def test_cliproxy_deployment_parses_and_normalizes_the_endpoint_boundary() -> None:
    """Test parsing and strict validation of deployment configuration."""
    parsed = parse_cliproxy_deployment(
        {
            "server": {"hostname": socket.gethostname()},
            "listen": {"host": "100.64.0.42", "port": 9443},
            "client": {"baseUrl": "https://gateway.example.test:9443/v1/"},
        }
    )
    assert parsed.server.hostname == DEPLOYMENT.server.hostname
    assert parsed.listen.host == DEPLOYMENT.listen.host
    assert parsed.listen.port == DEPLOYMENT.listen.port
    assert parsed.client.base_url == DEPLOYMENT.client.base_url

    invalid_hosts = [
        "0.0.0.0",  # noqa: S104
        "000.000.000.000",
        "0.0.0",
        "0",
        "0x0",
        "0000000000",
        "::",
        "::0",
        "0::",
        "0:0:0:0:0:0:0:0",
        "0:0::0",
    ]
    for host in invalid_hosts:
        with pytest.raises(
            ValueError,
            match="specific host or interface address",
        ):
            parse_cliproxy_deployment(
                {
                    "server": {"hostname": "test-gateway"},
                    "listen": {"host": host, "port": 9443},
                    "client": {"baseUrl": "https://gateway.example.test:9443/v1"},
                }
            )

    with pytest.raises(
        ValueError,
        match=r"HTTP\(S\) /v1 endpoint",
    ):
        parse_cliproxy_deployment(
            {
                "server": {"hostname": "test-gateway"},
                "listen": {"host": "100.64.0.42", "port": 9443},
                "client": {"baseUrl": "https://gateway.example.test:9443/api"},
            }
        )

    with pytest.raises(
        ValueError,
        match=r"HTTP\(S\) /v1 endpoint",
    ):
        parse_cliproxy_deployment(
            {
                "server": {"hostname": "test-gateway"},
                "listen": {"host": "100.64.0.42", "port": 9443},
                "client": {"baseUrl": " https://gateway.example.test:9443/v1"},
            }
        )

    for base_url in [
        "https://gateway.example.test:9443/v1?migrate=true",
        "https://gateway.example.test:9443/v1#fragment",
    ]:
        with pytest.raises(
            ValueError,
            match=r"HTTP\(S\) /v1 endpoint",
        ):
            parse_cliproxy_deployment(
                {
                    "server": {"hostname": "test-gateway"},
                    "listen": {"host": "100.64.0.42", "port": 9443},
                    "client": {"baseUrl": base_url},
                }
            )

    with pytest.raises(
        ValueError,
        match="unknown field typo",
    ):
        parse_cliproxy_deployment(
            {
                "server": {"hostname": "test-gateway"},
                "listen": {"host": "100.64.0.42", "port": 9443, "typo": True},
                "client": {"baseUrl": "https://gateway.example.test:9443/v1"},
            }
        )


def test_cliproxy_endpoint_template_renders_idempotently(tmp_path: Path) -> None:
    """Test template rendering idempotency, mode preservation, and errors."""
    src = tmp_path / "source.toml"
    dst = tmp_path / "generated" / "config.toml"
    src.write_text(
        f'base_url = "{CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n',
        encoding="utf-8",
    )
    src.chmod(0o640)

    sync_cliproxy_endpoint_template(src, dst, DEPLOYMENT)
    assert dst.read_text(encoding="utf-8") == (
        f'base_url = "{DEPLOYMENT.client.base_url}"\n'
    )
    assert dst.stat().st_mode & 0o777 == MODE_640
    first_ino = dst.stat().st_ino

    sync_cliproxy_endpoint_template(src, dst, DEPLOYMENT)
    assert dst.stat().st_ino == first_ino

    with pytest.raises(
        ValueError,
        match="missing CLIProxyAPI endpoint placeholder",
    ):
        render_cliproxy_endpoint_template("base_url = local\n", DEPLOYMENT)


def test_cliproxy_target_readiness_requires_a_nonempty_models_payload() -> None:
    """Test target readiness check requires HTTP 200 with non-empty data array."""
    test_cases = [
        (httpx.Response(204), False),
        (httpx.Response(200, json={"status": "ok"}), False),
        (httpx.Response(200, json={"data": []}), False),
        (httpx.Response(200, json={"data": [{"id": "ready"}]}), True),
    ]

    for response, expected in test_cases:
        ready = is_cliproxy_target_ready(
            DEPLOYMENT,
            CliProxyEndpointSyncOptions(fetch=_make_fake_fetch(response)),
        )
        assert ready is expected


def test_cliproxy_endpoint_publication_requires_a_keyless_ready_target(
    tmp_path: Path,
) -> None:
    """Test endpoint publication skips unready targets without mutating destination."""
    src = tmp_path / "source.toml"
    dst = tmp_path / "generated" / "config.toml"
    src.write_text(
        f'base_url = "{CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n',
        encoding="utf-8",
    )
    (tmp_path / "generated").mkdir(parents=True, exist_ok=True)
    dst.write_text('base_url = "old"\n', encoding="utf-8")
    dst.chmod(0o600)

    recorded_headers: dict[str, str] = {}

    def fetch_503(
        _url: str,
        headers: dict[str, str] | None = None,
        **_kwargs: object,
    ) -> httpx.Response:
        if headers:
            recorded_headers.update(headers)
        return httpx.Response(503)

    result = publish_cliproxy_endpoint_templates(
        [CliProxyEndpointTarget(src=str(src), dst=str(dst))],
        DEPLOYMENT,
        CliProxyEndpointSyncOptions(fetch=fetch_503),
    )
    assert result == "skipped"
    assert dst.read_text(encoding="utf-8") == 'base_url = "old"\n'
    assert dst.stat().st_mode & 0o777 == MODE_600
    assert "authorization" not in recorded_headers
    assert "Authorization" not in recorded_headers
    assert recorded_headers.get("Cache-Control") == "no-cache"


def test_cliproxy_endpoint_publication_rolls_back_all_targets_after_a_write_failure(
    tmp_path: Path,
) -> None:
    """Test transactional rollback restores original state on any target failure."""
    src_one = tmp_path / "source-one.toml"
    src_two = tmp_path / "source-two.toml"
    dst_one = tmp_path / "generated" / "one.toml"
    dst_two = tmp_path / "generated" / "two.toml"

    src_one.write_text(
        f'base_url = "{CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n',
        encoding="utf-8",
    )
    src_two.write_text(
        f'base_url = "{CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n',
        encoding="utf-8",
    )
    (tmp_path / "generated").mkdir(parents=True, exist_ok=True)
    dst_one.write_text("old\n", encoding="utf-8")
    dst_one.chmod(0o600)
    dst_two.mkdir()  # Directory causes write failure

    with pytest.raises(RuntimeError):
        publish_cliproxy_endpoint_templates(
            [
                CliProxyEndpointTarget(src=str(src_one), dst=str(dst_one)),
                CliProxyEndpointTarget(src=str(src_two), dst=str(dst_two)),
            ],
            DEPLOYMENT,
            CliProxyEndpointSyncOptions(fetch=_fetch_ready),
        )
    assert dst_one.read_text(encoding="utf-8") == "old\n"
    assert dst_one.stat().st_mode & 0o777 == MODE_600
    assert dst_two.is_dir()


def test_cliproxy_endpoint_replacement_preserves_codex_owned_tail(
    tmp_path: Path,
) -> None:
    """Test preservation of user-owned tables across repeated publish calls."""
    src = tmp_path / "source.toml"
    dst = tmp_path / "generated" / "config.toml"
    src.write_text(
        f'base_url = "{CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n',
        encoding="utf-8",
    )
    (tmp_path / "generated").mkdir(parents=True, exist_ok=True)

    owned_tail = (
        '\n[hooks.state."orchestrator"]\nspawn_count = 3\n\n'
        '[projects."~/work/example"]\nmodel = "gpt-5.6-sol"\n'
    )
    rendered = render_cliproxy_endpoint_template(
        src.read_text(encoding="utf-8"),
        DEPLOYMENT,
    )
    dst.write_text(f"{rendered}{owned_tail}", encoding="utf-8")
    dst.chmod(0o600)

    targets = [
        CliProxyEndpointTarget(
            src=str(src),
            dst=str(dst),
            preserve_top_levels=["hooks.state", "projects"],
        )
    ]

    def fetch_ready(_url: str, **_kw: object) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "ready"}]})

    result = publish_cliproxy_endpoint_templates(
        targets,
        DEPLOYMENT,
        CliProxyEndpointSyncOptions(fetch=fetch_ready),
    )
    assert result == "published"
    assert dst.read_text(encoding="utf-8") == f"{rendered}{owned_tail}"
    assert dst.stat().st_mode & 0o777 == MODE_600
    first_stat = dst.stat()

    publish_cliproxy_endpoint_templates(
        targets,
        DEPLOYMENT,
        CliProxyEndpointSyncOptions(fetch=fetch_ready),
    )
    assert dst.read_text(encoding="utf-8") == f"{rendered}{owned_tail}"
    assert dst.stat().st_ino == first_stat.st_ino
    assert dst.stat().st_mtime_ns == first_stat.st_mtime_ns


def test_cliproxy_endpoint_preserves_owned_tables_without_stale_managed_tails(
    tmp_path: Path,
) -> None:
    """Test owned tables are preserved cleanly without keeping outdated managed keys."""
    src = tmp_path / "source.toml"
    dst = tmp_path / "generated" / "config.toml"
    (tmp_path / "generated").mkdir(parents=True, exist_ok=True)

    src.write_text(
        f'base_url = "{CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n\n'
        '[general]\nmode = "new_fast"\n\n[model]\nname = "gpt-5.6-luna"\n',
        encoding="utf-8",
    )
    dst.write_text(
        'base_url = "https://old.gateway.test:9443/v1"\n\n'
        '[general]\nmode = "old_fast"\nlegacy_flag = true\n\n'
        '[hooks.state."orchestrator"]\nspawn_count = 3\n\n'
        '[model]\nname = "old-model-name"\ntemperature = 0.2\n\n'
        '[projects."~/work/example"]\nmodel = "gpt-5.6-sol"\n',
        encoding="utf-8",
    )
    dst.chmod(0o600)

    targets = [
        CliProxyEndpointTarget(
            src=str(src),
            dst=str(dst),
            preserve_top_levels=["hooks.state", "projects"],
        )
    ]

    def fetch_ready(_url: str, **_kw: object) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "ready"}]})

    result = publish_cliproxy_endpoint_templates(
        targets,
        DEPLOYMENT,
        CliProxyEndpointSyncOptions(fetch=fetch_ready),
    )
    assert result == "published"

    expected = (
        'base_url = "https://gateway.example.test:9443/v1"\n\n'
        '[general]\nmode = "new_fast"\n\n'
        '[model]\nname = "gpt-5.6-luna"\n\n'
        '[hooks.state."orchestrator"]\nspawn_count = 3\n\n'
        '[projects."~/work/example"]\nmodel = "gpt-5.6-sol"\n'
    )
    assert dst.read_text(encoding="utf-8") == expected
    assert dst.stat().st_mode & 0o777 == MODE_600
    first_stat = dst.stat()

    publish_cliproxy_endpoint_templates(
        targets,
        DEPLOYMENT,
        CliProxyEndpointSyncOptions(fetch=fetch_ready),
    )
    assert dst.read_text(encoding="utf-8") == expected
    assert dst.stat().st_ino == first_stat.st_ino
    assert dst.stat().st_mtime_ns == first_stat.st_mtime_ns


def test_extract_preserved_top_levels_extracts_matching_subtables_and_arrays() -> None:
    """Test TOML section extraction filters precisely on top-level key paths."""
    toml_doc = """
# top-level comments
base_url = "http://localhost:8080"

[general]
mode = "fast"

[hooks.state."orchestrator"]
spawn_count = 3
last_id = "abc\\"def"

[hooks.state.sub]
nested = true

[hooks.statement]
unrelated = true

[[projects.items]]
name = "p1"

[[projects.items]]
name = "p2"

[project]
other = 1

[model]
name = "gpt"
"""

    assert extract_preserved_top_levels(toml_doc, []) == ""
    assert extract_preserved_top_levels(toml_doc, ["nonexistent"]) == ""

    preserved = extract_preserved_top_levels(toml_doc, ["hooks.state", "projects"])
    expected = (
        '[hooks.state."orchestrator"]\n'
        "spawn_count = 3\n"
        'last_id = "abc\\"def"\n\n'
        "[hooks.state.sub]\n"
        "nested = true\n\n"
        "[[projects.items]]\n"
        'name = "p1"\n\n'
        "[[projects.items]]\n"
        'name = "p2"\n'
    )
    assert preserved == expected


def test_append_preserved_sections_handles_various_newline_layouts() -> None:
    """Test whitespace layout preservation in append_preserved_sections."""
    assert (
        append_preserved_sections("rendered\n\n", "[table]\nk = 1\n")
        == "rendered\n\n[table]\nk = 1\n"
    )
    assert (
        append_preserved_sections("rendered\n", "[table]\nk = 1\n")
        == "rendered\n\n[table]\nk = 1\n"
    )
    assert (
        append_preserved_sections("rendered", "[table]\nk = 1\n")
        == "rendered\n\n[table]\nk = 1\n"
    )
    assert append_preserved_sections("rendered\n", "") == "rendered\n"
    assert append_preserved_sections("", "[table]\nk = 1\n") == "[table]\nk = 1\n"


def test_cliproxy_custom_aliases_use_provider_native_model_and_payload_shapes() -> None:
    """Test committed cliproxy config template contains expected provider profiles."""
    source = (REPOSITORY_ROOT / "tools" / "cliproxyapi" / "config.yaml.tmpl").read_text(
        encoding="utf-8"
    )
    config: object = yaml.safe_load(source)
    assert _is_obj_dict(config)

    profiles = config.get("openai-compatibility")
    assert _is_obj_list(profiles)

    cline = next(
        (
            p
            for p in profiles
            if _is_obj_dict(p) and p.get("name") == "cline-pass-custom"
        ),
        None,
    )
    assert _is_obj_dict(cline)
    cline_models_raw = cline.get("models")
    assert _is_obj_list(cline_models_raw)
    cline_models = [m.get("name") for m in cline_models_raw if _is_obj_dict(m)]
    assert cline_models == [
        "cline-pass/deepseek-v4-flash",
        "cline-pass/deepseek-v4-pro",
        "cline-pass/glm-5.3",
        "cline-pass/kimi-k3",
        "cline-pass/qwen3.8-max",
    ]

    command_code = next(
        (
            p
            for p in profiles
            if _is_obj_dict(p) and p.get("name") == "command-code-custom"
        ),
        None,
    )
    assert _is_obj_dict(command_code)
    cmd_models_raw = command_code.get("models")
    assert _is_obj_list(cmd_models_raw)
    cmd_models = [m.get("name") for m in cmd_models_raw if _is_obj_dict(m)]
    assert cmd_models == [
        "deepseek/deepseek-v4-flash",
        "deepseek/deepseek-v4-pro",
        "zai-org/GLM-5.3",
        "moonshotai/Kimi-K3",
    ]

    payload_val = config.get("payload")
    assert _is_obj_dict(payload_val)
    override_val = payload_val.get("override")
    assert _is_obj_list(override_val)
    antigravity = next(
        (
            r
            for r in override_val
            if _is_obj_dict(r)
            and (models := r.get("models")) is not None
            and _is_obj_list(models)
            and any(
                _is_obj_dict(m) and m.get("protocol") == "antigravity" for m in models
            )
        ),
        None,
    )
    assert _is_obj_dict(antigravity)
    assert antigravity.get("params") == {
        "generationConfig.thinkingConfig.thinkingLevel": "medium",
    }


def test_cliproxy_opencode_endpoint_removes_placeholder_and_injects_base_url(
    tmp_path: Path,
) -> None:
    """Test endpoint template rendering for opencode jsonc and ts configs."""
    dst_dir = tmp_path / ".config" / "opencode"
    dst_dir.mkdir(parents=True, exist_ok=True)
    jsonc_src = tmp_path / "opencode.jsonc.tmpl"
    ts_src = tmp_path / "cliproxy.ts.tmpl"
    jsonc_src.write_text(
        f'const x = "{CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}";\n',
        encoding="utf-8",
    )
    ts_src.write_text(
        f'const x = "{CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}";\n',
        encoding="utf-8",
    )

    sync_cliproxy_endpoint_template(jsonc_src, dst_dir / "opencode.jsonc", DEPLOYMENT)
    sync_cliproxy_endpoint_template(
        ts_src, dst_dir / "plugins" / "cliproxy.ts", DEPLOYMENT
    )

    assert (dst_dir / "opencode.jsonc").read_text(encoding="utf-8") == (
        f'const x = "{DEPLOYMENT.client.base_url}";\n'
    )
    assert (dst_dir / "plugins" / "cliproxy.ts").read_text(encoding="utf-8") == (
        f'const x = "{DEPLOYMENT.client.base_url}";\n'
    )
