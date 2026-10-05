# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Sync's native MCP publication boundary for Pi."""

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from sync.core.harness import SyncEnv
from sync.core.jobs import run_jobs_with_preserve
from sync.core.pi_mcp import render_pi_mcp
from sync.core.plan import DirJob, FileJob, build_sync_plan
from sync.runtime.jsonc import is_obj_dict, is_obj_list
from tests.test_integration import make_fixture, run_sync_process


def test_pi_mcp_publication_and_removal(tmp_path: Path) -> None:
    """Publish native servers and exact exclusions without changing other homes."""
    home = make_fixture(tmp_path)
    source = home / "src" / "agents"
    registry = source / "tools/mcporter/mcporter.jsonc"
    settings = source / "harnesses/pi/agent/settings.json"
    _ = settings.write_text('{"skills": ["+extra"], "theme": "test"}', encoding="utf-8")
    content = json.dumps(
        {
            "mcpServers": {
                "docs": {
                    "serverUrl": "https://example.test/mcp",
                    "description": "Docs",
                    "piSkill": "context7",
                    "protocolVersion": "legacy",
                },
                "public": {"serverUrl": "https://public.test/mcp"},
            }
        }
    )
    _ = registry.write_text(content, encoding="utf-8")
    result = run_sync_process(home)
    assert result.exit_code == 0, result.stderr
    target = home / ".pi/agent/mcp.json"
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "mcpServers": {
            "docs": {"url": "https://example.test/mcp", "description": "Docs"},
            "public": {"url": "https://public.test/mcp"},
        }
    }
    generated = home / ".pi/agent/settings.json"
    assert json.loads(generated.read_text(encoding="utf-8")) == {
        "skills": ["+extra", f"-{home}/.pi/agent/skills/context7"],
        "theme": "test",
        "packages": [],
    }
    assert (home / ".mcporter/mcporter.json").read_text(encoding="utf-8") == content
    assert not (home / ".omp/agent/mcp.json").exists()
    _ = registry.write_text('{"mcpServers": {}}', encoding="utf-8")
    result = run_sync_process(home)
    assert result.exit_code == 0, result.stderr
    assert json.loads(target.read_text(encoding="utf-8")) == {"mcpServers": {}}
    assert json.loads(generated.read_text(encoding="utf-8"))["skills"] == ["+extra"]


def test_pi_mcp_environment_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep secrets as references, omit unset optional headers, and retain defaults."""
    home = make_fixture(tmp_path)
    source = home / "src" / "agents" / "tools" / "mcporter" / "mcporter.jsonc"
    monkeypatch.setenv("MCP_TEST_KEY", "do-not-publish")
    monkeypatch.delenv("MCP_TEST_MISSING", raising=False)
    monkeypatch.setenv("MCP_TEST_EMPTY", "")
    _ = source.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "test": {
                        "serverUrl": "https://example.test/mcp",
                        "headers": {
                            "Key": "${MCP_TEST_KEY:-}",
                            "Missing": "${MCP_TEST_MISSING:-}",
                            "Empty": "${MCP_TEST_EMPTY:-}",
                            "Default": "${MCP_TEST_MISSING:-public}",
                        },
                        "env": {
                            "KEY": "${MCP_TEST_KEY:-}",
                            "MODE": "${MCP_TEST_MISSING:-public}",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    plan = build_sync_plan(SyncEnv.from_home(str(home)))
    jobs = [
        job
        for job in plan.jobs
        if not isinstance(job, (DirJob, FileJob))
        and getattr(job, "kind", "") == "PiMcp"
    ]
    assert asyncio.run(run_jobs_with_preserve(jobs))
    text = (home / ".pi/agent/mcp.json").read_text(encoding="utf-8")
    assert "do-not-publish" not in text
    assert json.loads(text)["mcpServers"]["test"] == {
        "url": "https://example.test/mcp",
        "headers": {"Key": "${MCP_TEST_KEY}", "Default": "public"},
        "env": {"KEY": "${MCP_TEST_KEY}", "MODE": "public"},
    }


def test_pi_stdio_arguments_expand_only_at_launch(tmp_path: Path) -> None:
    """Expand arguments at runtime without shell injection or publishing secrets."""
    output = tmp_path / "arguments.json"
    config, _ = render_pi_mcp(
        {
            "mcpServers": {
                "local": {
                    "command": "printf",
                    "args": [
                        "%s\\n",
                        "${MCP_TEST_TOKEN:-fallback}",
                        "${MCP_TEST_MISSING:-public}",
                    ],
                }
            }
        },
        str(tmp_path),
        {},
    )
    # Exercise the serialized process boundary, not Pi implementation internals.
    serialized = json.dumps(config)
    assert "MCP_TEST_TOKEN" in serialized
    parsed: object = json.loads(serialized)  # pyright: ignore[reportAny]
    assert is_obj_dict(parsed)
    servers = parsed["mcpServers"]
    assert is_obj_dict(servers)
    server = servers["local"]
    assert is_obj_dict(server)
    command, args = server["command"], server["args"]
    assert isinstance(command, str)
    assert is_obj_list(args)
    assert all(isinstance(arg, str) for arg in args)
    value = 'secret with spaces; $(touch should-not-exist) "quoted"'
    result = subprocess.run(  # noqa: S603 - generated command from a fixed test fixture
        [command, *(arg for arg in args if isinstance(arg, str))],
        env={**os.environ, "MCP_TEST_TOKEN": value, "MCP_TEST_MISSING": ""},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    _ = output.write_text(result.stdout, encoding="utf-8")
    assert output.read_text(encoding="utf-8") == f"{value}\npublic\n"
    assert not (tmp_path / "should-not-exist").exists()
