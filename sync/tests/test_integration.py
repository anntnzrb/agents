# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Integration tests for the agents-sync CLI, wrappers, and reconciliation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml

from sync.core.cliproxy_deployment import CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER
from sync.runtime.lock import release_sync_lock, try_acquire_sync_lock
from tests.conftest import (
    PRISTINE_PATH,
    SYNC_ROOT,
    seed_runtime_release,
    shared_tool_cache_env,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

EXIT_SYNTAX_ERROR = 2
EXIT_RUNTIME_MISSING = 127
FAKED_RUNTIME_EXIT_CODE = 42
CLIPROXY_PORT = 8317
CONFIG_FILE_MODE = 0o600
PERMISSION_MASK = 0o777

OFFLINE_NPM_ENV: dict[str, str] = {
    "npm_config_fetch_retries": "0",
    "npm_config_fetch_retry_mintimeout": "100",
    "npm_config_fetch_retry_maxtimeout": "100",
    "npm_config_fetch_timeout": "100",
    "npm_config_registry": "http://127.0.0.1:1/",
    "NPM_CONFIG_FETCH_RETRIES": "0",
    "NPM_CONFIG_FETCH_RETRY_MINTIMEOUT": "100",
    "NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT": "100",
    "NPM_CONFIG_FETCH_TIMEOUT": "100",
    "NPM_CONFIG_REGISTRY": "http://127.0.0.1:1/",
}


@dataclass(frozen=True, slots=True)
class RunResult:
    """Subprocess execution output and exit code."""

    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    """Captured filesystem state entry for directory trees."""

    path: str
    kind: str
    content: str | None = None


def run_sync_process(
    home: Path,
    args: Sequence[str] = (),
    *,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = 30.0,
) -> RunResult:
    """Execute the sync CLI as a subprocess within the given home sandbox."""
    cmd = [sys.executable, "-m", "sync.cli", *args]
    run_env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "PATH": PRISTINE_PATH,
        **shared_tool_cache_env,
        **(env or {}),
    }
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=str(SYNC_ROOT),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=run_env,
            timeout=timeout_seconds,
            check=False,
        )
        return RunResult(proc.returncode, proc.stdout, proc.stderr)
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout
            if isinstance(exc.stdout, str)
            else (exc.stdout.decode() if exc.stdout else "")
        )
        stderr = (
            exc.stderr
            if isinstance(exc.stderr, str)
            else (exc.stderr.decode() if exc.stderr else "")
        )
        return RunResult(124, stdout, stderr)


def run_wrapper(
    wrapper_path: Path,
    args: Sequence[str] = (),
    *,
    home: Path,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = 30.0,
) -> RunResult:
    """Execute a generated wrapper script within the given home sandbox."""
    cmd = [str(wrapper_path), *args]
    run_env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "PATH": PRISTINE_PATH,
        **shared_tool_cache_env,
        **(env or {}),
    }
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=str(home),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=run_env,
            timeout=timeout_seconds,
            check=False,
        )
        return RunResult(proc.returncode, proc.stdout, proc.stderr)
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout
            if isinstance(exc.stdout, str)
            else (exc.stdout.decode() if exc.stdout else "")
        )
        stderr = (
            exc.stderr
            if isinstance(exc.stderr, str)
            else (exc.stderr.decode() if exc.stderr else "")
        )
        return RunResult(124, stdout, stderr)


def write_deployment(
    home: Path,
    server_hostname: str | None = None,
    client_base_url: str = "http://127.0.0.1:1/v1",
) -> None:
    """Write a minimal CLIProxyAPI deployment.json configuration."""
    tools = home / ".config" / "agents" / "tools" / "cliproxyapi"
    tools.mkdir(parents=True, exist_ok=True)
    deployment = {
        "server": {"hostname": server_hostname or socket.gethostname()},
        "listen": {"host": "100.64.0.42", "port": 8317},
        "client": {"baseUrl": client_base_url},
    }
    (tools / "deployment.json").write_text(
        f"{json.dumps(deployment)}\n",
        encoding="utf-8",
    )


def write_fixture_files(home: Path) -> None:
    """Populate home directory with standard SSOT configurations and targets."""
    write_deployment(home)
    (home / ".config" / "agents" / "HARNESS.md").write_text(
        "agent-instructions",
        encoding="utf-8",
    )
    (home / ".config" / "agents" / "tools" / "mcporter" / "mcporter.jsonc").write_text(
        '{"x":1}', encoding="utf-8"
    )
    (home / ".config" / "agents" / "tools" / "summarize" / "config.json").write_text(
        '{"x":1}', encoding="utf-8"
    )
    (
        home / ".config" / "agents" / "tools" / "cliproxyapi" / "config.yaml.tmpl"
    ).write_text(
        "host: ${CLIPROXY_LISTEN_HOST}\n"
        "port: ${CLIPROXY_LISTEN_PORT}\n"
        "remote-management:\n"
        "  allow-remote: true\n"
        "  secret-key: tailnet\n"
        "codex-api-key:\n"
        "  - x-credential-pool: fixture\n"
        "    prefix: fixture\n",
        encoding="utf-8",
    )
    (home / ".config" / "agents" / "secrets.local.json").write_text(
        json.dumps(
            {
                "CLIPROXY_CREDENTIAL_POOLS": {
                    "fixture": [{"apiKey": "upstream-secret", "weight": 1}],
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    skills_current = home / ".config" / "agents" / "skills" / "current"
    skills_current.mkdir(parents=True, exist_ok=True)
    (skills_current / "skill.txt").write_text("skill-content", encoding="utf-8")

    skills_legacy = home / ".config" / "agents" / "skills" / "legacy"
    skills_legacy.mkdir(parents=True, exist_ok=True)
    (skills_legacy / "old.txt").write_text("legacy-content", encoding="utf-8")

    (home / ".config" / "agents" / "harnesses" / "codex" / "config.toml").write_text(
        f'base_url = "{CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n',
        encoding="utf-8",
    )
    (
        home / ".config" / "agents" / "harnesses" / "opencode" / "opencode.jsonc"
    ).write_text(
        f'"baseURL": "{CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}"\n',
        encoding="utf-8",
    )
    (home / ".codex" / "config.toml").write_text(
        'base_url = "http://old-gateway.example.test/v1"\n',
        encoding="utf-8",
    )
    (home / ".config" / "opencode" / "opencode.jsonc").write_text(
        '"baseURL": "http://old-gateway.example.test/v1"\n',
        encoding="utf-8",
    )
    (
        home / ".config" / "agents" / "harnesses" / "deepseek" / "cordis.patch.yml"
    ).write_text("[]\n", encoding="utf-8")
    (
        home / ".config" / "agents" / "harnesses" / "omp" / "agent" / "config.yml"
    ).write_text("theme:\n  dark: graphite\n", encoding="utf-8")
    (
        home / ".config" / "agents" / "harnesses" / "omp" / "agent" / "models.yml"
    ).write_text(
        f"baseUrl: {CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}\n",
        encoding="utf-8",
    )
    (home / ".omp" / "agent" / "models.yml").write_text(
        "baseUrl: http://old-gateway.example.test/v1\n",
        encoding="utf-8",
    )
    (home / ".pi" / "agent" / "auth.json").write_text('{"token":1}', encoding="utf-8")
    (home / ".pi" / "agent" / "settings.json").write_text("{}\n", encoding="utf-8")
    (home / ".omp" / "agent" / "logs" / "keep.txt").write_text(
        "keep-me", encoding="utf-8"
    )


def make_fixture(root: Path) -> Path:
    """Create complete SSOT layout fixture inside root and return home directory."""
    home = root / "fixture-home"
    for p in (
        home / ".config" / "agents" / "harnesses" / "codex",
        home / ".config" / "agents" / "harnesses" / "deepseek",
        home / ".config" / "agents" / "harnesses" / "opencode",
        home / ".config" / "agents" / "harnesses" / "omp" / "agent",
        home / ".config" / "agents" / "harnesses" / "pi" / "agent",
        home / ".config" / "agents" / "tools" / "mcporter",
        home / ".config" / "agents" / "tools" / "summarize",
        home / ".config" / "agents" / "tools" / "cliproxyapi",
        home / ".pi" / "agent",
        home / ".omp" / "agent" / "logs",
        home / ".codex",
        home / ".config" / "opencode",
        home / ".mcporter",
        home / ".summarize",
        home / ".dsh",
        home / ".local" / "bin",
        home / ".local" / "share" / "agents" / "sync-managed",
        home / ".local" / "share" / "agents" / "sync-releases",
    ):
        p.mkdir(parents=True, exist_ok=True)

    sync_source = home / ".config" / "agents" / "sync"
    sync_source.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SYNC_ROOT / "src", sync_source / "src")
    for filename in ("pyproject.toml", "uv.lock", "README.md"):
        f = SYNC_ROOT / filename
        if f.is_file():
            shutil.copyfile(f, sync_source / filename)

    seed_runtime_release(home)
    write_fixture_files(home)
    return home


def seed_cached_npm_package(
    home: Path,
    spec: Mapping[str, str],
    version: str,
    script_content: str,
) -> None:
    """Seed npm cache with an executable for offline launcher fallback testing."""
    cache_home = home / ".cache"
    tool = spec["tool"]
    pkg_name = spec["package"]
    bin_name = spec["bin"]
    tool_cache = cache_home / "npm-tools" / tool
    pkg_key = hashlib.sha256(pkg_name.encode()).hexdigest()[:16]
    pkg_cache = tool_cache / "packages" / pkg_key
    version_dir = pkg_cache / "versions" / version
    bin_dir = version_dir / "node_modules" / ".bin"
    pkg_dir = version_dir / "node_modules" / Path(pkg_name)
    bin_dir.mkdir(parents=True, exist_ok=True)
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "package.json").write_text(
        json.dumps({"name": pkg_name, "version": version}),
        encoding="utf-8",
    )
    executable = bin_dir / bin_name
    executable.write_text(script_content, encoding="utf-8")
    executable.chmod(0o755)
    current_link = pkg_cache / "current"
    if current_link.is_symlink() or current_link.exists():
        current_link.unlink()
    current_link.symlink_to(Path("versions") / version)


def init_git_repo(repo_path: Path) -> None:
    """Initialize a git repository with an initial commit."""
    commands = [
        ["git", "init"],
        ["git", "config", "user.name", "Test User"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "add", "."],
        ["git", "commit", "-m", "init"],
    ]
    for cmd in commands:
        res = subprocess.run(  # noqa: S603
            cmd,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, res.stderr or res.stdout


def setup_package_repos(source_repo: Path, build_repo: Path) -> None:
    """Initialize test package repositories for pi package bootstrapping."""
    (source_repo / "src").mkdir(parents=True, exist_ok=True)
    (build_repo / "src").mkdir(parents=True, exist_ok=True)
    (source_repo / "package.json").write_text(
        json.dumps({"pi": {"extensions": ["./src/index.ts"]}}, indent=2) + "\n",
        encoding="utf-8",
    )
    (source_repo / "src" / "index.ts").write_text(
        "export default {}\n",
        encoding="utf-8",
    )
    (build_repo / "package.json").write_text(
        json.dumps(
            {
                "scripts": {"build": "bun run build.ts"},
                "pi": {"extensions": ["./dist/index.js"]},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (build_repo / "build.ts").write_text(
        'import { mkdirSync, writeFileSync } from "node:fs";\n'
        'mkdirSync("dist", { recursive: true });\n'
        'writeFileSync("dist/index.js", "export default {}\\n");\n',
        encoding="utf-8",
    )
    init_git_repo(source_repo)
    init_git_repo(build_repo)


def snapshot_home(home: Path) -> list[SnapshotEntry]:
    """Capture snapshot of managed directories in home sandbox."""
    roots = [
        ".codex",
        ".dsh",
        ".config/opencode",
        ".pi",
        ".omp",
        ".mcporter",
        ".summarize",
        ".cli-proxy-api",
        ".local/share/agents/sync-managed",
        ".local/share/agents/pi-packages",
        ".local/bin",
    ]
    entries: list[SnapshotEntry] = []
    for root in roots:
        abs_path = home / root
        if abs_path.exists():
            _walk(abs_path, root, entries)
    return [e for e in entries if not e.path.endswith("/sync.lock")]


def snapshot_selected(root: Path) -> list[SnapshotEntry]:
    """Capture snapshot of a specific directory tree excluding git and modules."""
    entries: list[SnapshotEntry] = []
    if root.exists():
        _walk(root, "", entries)
    return [
        e for e in entries if "/.git" not in e.path and "/node_modules" not in e.path
    ]


def _walk(abs_path: Path, rel_path: str, out: list[SnapshotEntry]) -> None:
    normalized = rel_path.replace(os.sep, "/")
    if abs_path.is_symlink():
        out.append(SnapshotEntry(path=normalized, kind="symlink"))
        return
    if abs_path.is_dir():
        out.append(SnapshotEntry(path=normalized, kind="dir"))
        for child in sorted(abs_path.iterdir(), key=lambda c: c.name):
            child_rel = f"{rel_path}/{child.name}" if rel_path else child.name
            _walk(child, child_rel, out)
        return
    try:
        content = abs_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = None
    out.append(SnapshotEntry(path=normalized, kind="file", content=content))


def test_integration_cli_help_flags_exit_0(tmp_path: Path) -> None:
    """Test CLI help flags produce exit code 0 and match golden text."""
    home = make_fixture(tmp_path)
    golden_help = (SYNC_ROOT / "tests" / "golden" / "help.txt").read_text(
        encoding="utf-8"
    )
    golden_launch_help = (SYNC_ROOT / "tests" / "golden" / "launch-help.txt").read_text(
        encoding="utf-8"
    )

    general_flags = [
        ["--help"],
        ["-h"],
        ["help"],
        ["sync", "--help"],
        ["sync", "-h"],
        ["sync", "help"],
    ]
    for args in general_flags:
        result = run_sync_process(home, args)
        assert result.exit_code == 0, f"args {args} failed: {result.stderr}"
        assert result.stdout.strip() == golden_help.strip()

    launch_flags = [["launch", "--help"], ["launch", "-h"], ["launch", "help"]]
    for args in launch_flags:
        result = run_sync_process(home, args)
        assert result.exit_code == 0, f"args {args} failed: {result.stderr}"
        assert result.stdout.strip() == golden_launch_help.strip()


def test_integration_cli_syntax_errors_exit_2(tmp_path: Path) -> None:
    """Test invalid subcommands and bad syntax return exit code 2."""
    home = make_fixture(tmp_path)
    bad_cmd = run_sync_process(home, ["invalid-subcommand"])
    assert bad_cmd.exit_code == EXIT_SYNTAX_ERROR
    assert "sync: usage: sync" in bad_cmd.stderr

    bad_launch_no_name = run_sync_process(home, ["launch"])
    assert bad_launch_no_name.exit_code == EXIT_SYNTAX_ERROR
    assert "sync: usage: launch NAME -- [ARGS...]" in bad_launch_no_name.stderr

    bad_launch_no_sep = run_sync_process(home, ["launch", "codex", "no-separator"])
    assert bad_launch_no_sep.exit_code == EXIT_SYNTAX_ERROR
    assert "sync: usage: launch NAME -- [ARGS...]" in bad_launch_no_sep.stderr


def test_integration_missing_runtime_sources_fails_sync_exit_1(
    tmp_path: Path,
) -> None:
    """Test sync fails with exit code 1 when runtime sources are missing."""
    home = tmp_path / "home"
    (home / ".config" / "agents").mkdir(parents=True, exist_ok=True)
    write_deployment(home)

    result = run_sync_process(home)
    assert result.exit_code == 1, result.stderr or result.stdout
    assert "missing or unreadable runtime source" in result.stderr


def test_integration_malformed_config_fails_sync_exit_1(
    tmp_path: Path,
) -> None:
    """Test sync fails with exit code 1 on malformed JSON deployment config."""
    home = make_fixture(tmp_path)
    (
        home / ".config" / "agents" / "tools" / "cliproxyapi" / "deployment.json"
    ).write_text("{ invalid json syntax\n", encoding="utf-8")

    result = run_sync_process(home)
    assert result.exit_code == 1, result.stderr or result.stdout
    assert (
        "parse CLIProxyAPI deployment" in result.stderr
        or "deployment.json" in result.stderr
    )


def test_integration_happy_path_matches_expected_outputs(
    tmp_path: Path,
) -> None:
    """Test standard end-to-end sync reconciles files, configs, and wrappers."""
    home = make_fixture(tmp_path)
    result = run_sync_process(home)
    assert result.exit_code == 0, result.stderr or result.stdout

    assert (home / ".codex" / "AGENTS.md").is_file()
    assert (home / ".dsh" / "AGENTS.md").is_file()
    assert (home / ".dsh" / "cordis.patch.yml").is_file()
    assert (home / ".dsh" / "skills" / "skill.txt").is_file()
    assert (home / ".config" / "opencode" / "AGENTS.md").is_file()
    assert (home / ".pi" / "agent" / "AGENTS.md").is_file()
    assert (home / ".omp" / "agent" / "AGENTS.md").is_file()
    assert (home / ".omp" / "agent" / "config.yml").is_file()
    assert (home / ".omp" / "agent" / "skills" / "skill.txt").is_file()
    assert not (home / ".omp" / "agent" / "skills" / "legacy").exists()
    assert (home / ".mcporter" / "mcporter.json").is_file()
    assert (home / ".summarize" / "config.json").is_file()

    raw_config: object = yaml.safe_load(
        (home / ".cli-proxy-api" / "config.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(raw_config, dict)
    config = cast("dict[str, object]", raw_config)
    assert config["host"] == "100.64.0.42"
    assert config["port"] == CLIPROXY_PORT
    remote_mgmt = cast("dict[str, object]", config["remote-management"])
    assert remote_mgmt["secret-key"] == "tailnet"
    assert "api-keys" not in config
    codex_keys = cast("list[dict[str, object]]", config["codex-api-key"])
    assert codex_keys[0]["api-key"] == "upstream-secret"
    assert "x-credential-pool" not in codex_keys[0]
    assert (
        home / ".cli-proxy-api" / "config.yaml"
    ).stat().st_mode & PERMISSION_MASK == CONFIG_FILE_MODE
    assert not (
        home / ".local" / "share" / "agents" / "cliproxyapi" / "client-api-key"
    ).exists()

    for path in (
        home / ".codex" / "config.toml",
        home / ".config" / "opencode" / "opencode.jsonc",
        home / ".omp" / "agent" / "models.yml",
    ):
        content = path.read_text(encoding="utf-8")
        assert "http://old-gateway.example.test/v1" in content, str(path)
        assert CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER not in content, str(path)

    installed_cli = (
        home
        / ".local"
        / "share"
        / "agents"
        / "sync-current"
        / "src"
        / "sync"
        / "cli.py"
    )
    assert installed_cli.is_file(), str(installed_cli)
    assert len(installed_cli.read_text(encoding="utf-8")) > 0

    assert (home / ".pi" / "agent" / "auth.json").is_file()

    for command in ("codex", "dsh", "opencode", "pi", "omp"):
        wrapper = home / ".local" / "bin" / command
        assert wrapper.is_file(), str(wrapper)
        text = wrapper.read_text(encoding="utf-8")
        assert "agents-managed-wrapper:v1" in text
        assert ".local/share/agents/sync-current" in text
        assert str(SYNC_ROOT) not in text
        assert ".config/agents/sync" not in text


def test_integration_repeated_runs_remain_idempotent(tmp_path: Path) -> None:
    """Test repeated sync runs are idempotent and preserve inodes/mtimes."""
    home = make_fixture(tmp_path)
    first = run_sync_process(home)
    assert first.exit_code == 0, first.stderr or first.stdout
    endpoint_first = (home / ".codex" / "config.toml").stat()
    snapshot_first = snapshot_home(home)

    second = run_sync_process(home)
    assert second.exit_code == 0, second.stderr or second.stdout
    endpoint_second = (home / ".codex" / "config.toml").stat()
    snapshot_second = snapshot_home(home)

    assert endpoint_second.st_ino == endpoint_first.st_ino
    assert endpoint_second.st_mtime_ns == endpoint_first.st_mtime_ns
    assert snapshot_first == snapshot_second


def test_integration_owned_entry_cleanup_and_unmanaged_file_preservation(
    tmp_path: Path,
) -> None:
    """Test unmanaged user files are preserved while deleted SSOT entries are pruned."""
    home = make_fixture(tmp_path)

    unmanaged_log = home / ".omp" / "agent" / "logs" / "custom-user.log"
    unmanaged_log.write_text("user-log-content\n", encoding="utf-8")

    unmanaged_bin = home / ".local" / "bin" / "user-tool"
    unmanaged_bin.parent.mkdir(parents=True, exist_ok=True)
    unmanaged_bin.write_text("#!/bin/sh\necho 'user-tool'\n", encoding="utf-8")
    unmanaged_bin.chmod(0o755)

    first_result = run_sync_process(home)
    assert first_result.exit_code == 0, first_result.stderr or first_result.stdout

    skill_path = home / ".omp" / "agent" / "skills" / "skill.txt"
    assert skill_path.is_file()
    assert unmanaged_log.is_file()
    assert unmanaged_log.read_text(encoding="utf-8") == "user-log-content\n"
    assert unmanaged_bin.is_file()

    shutil.rmtree(home / ".config" / "agents" / "skills" / "legacy", ignore_errors=True)

    second_result = run_sync_process(home)
    assert second_result.exit_code == 0, second_result.stderr or second_result.stdout

    assert skill_path.is_file()
    assert unmanaged_log.is_file()
    assert unmanaged_log.read_text(encoding="utf-8") == "user-log-content\n"
    assert unmanaged_bin.is_file()

    unmanaged_codex = home / ".local" / "bin" / "codex"
    unmanaged_codex.write_text("#!/bin/sh\necho 'custom-codex'\n", encoding="utf-8")
    unmanaged_codex.chmod(0o755)

    third_result = run_sync_process(home)
    assert third_result.exit_code == 0, third_result.stderr or third_result.stdout
    assert "preserving unmanaged wrapper conflict" in third_result.stderr
    assert (
        unmanaged_codex.read_text(encoding="utf-8")
        == "#!/bin/sh\necho 'custom-codex'\n"
    )


def test_integration_failed_publication_clean_recovery(
    tmp_path: Path,
) -> None:
    """Test skipped endpoints on unreachable proxy recover on subsequent healthy run."""
    home = make_fixture(tmp_path)
    write_deployment(home, "different-host", "http://127.0.0.1:1/v1")

    endpoint_paths = [
        home / ".codex" / "config.toml",
        home / ".config" / "opencode" / "opencode.jsonc",
        home / ".omp" / "agent" / "models.yml",
    ]
    original_contents = [p.read_text(encoding="utf-8") for p in endpoint_paths]

    skipped_result = run_sync_process(home)
    assert skipped_result.exit_code == 0, skipped_result.stderr or skipped_result.stdout
    for i, path in enumerate(endpoint_paths):
        assert path.read_text(encoding="utf-8") == original_contents[i]

    write_deployment(home, socket.gethostname(), "http://100.64.0.42:8317/v1")
    recovery_result = run_sync_process(home)
    assert recovery_result.exit_code == 0, (
        recovery_result.stderr or recovery_result.stdout
    )
    for path in endpoint_paths:
        content = path.read_text(encoding="utf-8")
        assert CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER not in content

    assert (home / ".codex" / "AGENTS.md").is_file()


def test_integration_process_lock_contention_and_release_on_exit(
    tmp_path: Path,
) -> None:
    """Test active sync lock skips execution with message and releases cleanly."""
    home = make_fixture(tmp_path)
    state_dir = str(home / ".local" / "share" / "agents" / "sync-managed")
    lock_path = str(home / ".local" / "share" / "agents" / "sync-managed" / "sync.lock")

    lock = try_acquire_sync_lock(state_dir, lock_path)
    assert lock is not None

    contended_result = run_sync_process(home)
    assert contended_result.exit_code == 0, (
        contended_result.stderr or contended_result.stdout
    )
    assert "another sync is already running; skipping" in contended_result.stderr

    release_sync_lock(lock)

    after_release_result = run_sync_process(home)
    assert after_release_result.exit_code == 0, (
        after_release_result.stderr or after_release_result.stdout
    )
    assert (home / ".codex" / "AGENTS.md").is_file()


def test_integration_cached_launch_fallback_when_offline(
    tmp_path: Path,
) -> None:
    """Test launch command falls back to cached npm package when offline."""
    home = make_fixture(tmp_path)
    sync_result = run_sync_process(home)
    assert sync_result.exit_code == 0, sync_result.stderr or sync_result.stdout

    seed_cached_npm_package(
        home,
        {"tool": "codex", "package": "@openai/codex", "bin": "codex"},
        "0.1.0",
        '#!/bin/sh\necho "mock-codex-0.1.0:mode=cached args=$*"\nexit 0\n',
    )

    launch_result = run_sync_process(
        home,
        ["launch", "codex", "--", "--hello", "world"],
        env=OFFLINE_NPM_ENV,
    )
    assert launch_result.exit_code == 0, launch_result.stderr or launch_result.stdout
    assert "using cached codex@0.1.0" in launch_result.stderr
    assert "mock-codex-0.1.0:mode=cached args=--hello world" in launch_result.stdout


def test_integration_missing_runtime_wrapper_returns_127_with_hint(
    tmp_path: Path,
) -> None:
    """Test wrapper script returns 127 and hint when sync runtime is absent."""
    home = make_fixture(tmp_path)
    sync_result = run_sync_process(home)
    assert sync_result.exit_code == 0, sync_result.stderr or sync_result.stdout

    wrapper = home / ".local" / "bin" / "codex"
    assert wrapper.is_file(), str(wrapper)

    runtime_dir = home / ".local" / "share" / "agents" / "sync-current"
    if runtime_dir.is_symlink():
        runtime_dir.unlink()
    else:
        shutil.rmtree(runtime_dir, ignore_errors=True)

    result = run_wrapper(wrapper, ["--version"], home=home)
    assert result.exit_code == EXIT_RUNTIME_MISSING, result.stderr or result.stdout
    assert (
        "agents: sync runtime is missing; run sync from the agents repository"
        in result.stderr
    )


def test_integration_environment_variable_precedence_dot_env_vs_parent(
    tmp_path: Path,
) -> None:
    """Test parent environment variables override values defined in .env file."""
    home = make_fixture(tmp_path)
    (home / ".config" / "agents" / ".env").write_text(
        "BASE_FROM_DOTENV=dotenv_val\nOVERRIDE_VAR=dotenv_val\n",
        encoding="utf-8",
    )

    sync_result = run_sync_process(home)
    assert sync_result.exit_code == 0, sync_result.stderr or sync_result.stdout

    seed_cached_npm_package(
        home,
        {"tool": "codex", "package": "@openai/codex", "bin": "codex"},
        "0.1.0",
        "#!/bin/sh\n"
        'echo "BASE_FROM_DOTENV=$BASE_FROM_DOTENV"\n'
        'echo "OVERRIDE_VAR=$OVERRIDE_VAR"\n'
        'echo "PARENT_ONLY_VAR=$PARENT_ONLY_VAR"\n'
        "exit 0\n",
    )

    launch_result = run_sync_process(
        home,
        ["launch", "codex"],
        env={
            **OFFLINE_NPM_ENV,
            "OVERRIDE_VAR": "parent_val",
            "PARENT_ONLY_VAR": "parent_val",
        },
    )

    assert launch_result.exit_code == 0, launch_result.stderr or launch_result.stdout
    assert "BASE_FROM_DOTENV=dotenv_val" in launch_result.stdout
    assert "OVERRIDE_VAR=parent_val" in launch_result.stdout
    assert "PARENT_ONLY_VAR=parent_val" in launch_result.stdout


def test_integration_unavailable_client_preserves_all_cliproxy_artifacts(
    tmp_path: Path,
) -> None:
    """Test unavailable client preserves server config and all harness endpoints."""
    home = make_fixture(tmp_path)
    write_deployment(home, "different-host", "http://127.0.0.1:1/v1")

    config_path = home / ".cli-proxy-api" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("existing-server-config\n", encoding="utf-8")
    config_path.chmod(0o600)

    endpoint_paths = [
        home / ".codex" / "config.toml",
        home / ".config" / "opencode" / "opencode.jsonc",
        home / ".omp" / "agent" / "models.yml",
    ]
    active_paths = [config_path, *endpoint_paths]
    before = [
        {
            "content": p.read_text(encoding="utf-8"),
            "mode": p.stat().st_mode & PERMISSION_MASK,
        }
        for p in active_paths
    ]

    result = run_sync_process(home)
    assert result.exit_code == 0, result.stderr or result.stdout
    after = [
        {
            "content": p.read_text(encoding="utf-8"),
            "mode": p.stat().st_mode & PERMISSION_MASK,
        }
        for p in active_paths
    ]
    assert after == before


def test_integration_package_bootstrap_patches_settings_and_cache_paths(
    tmp_path: Path,
) -> None:
    """Test package bootstrap updates pi settings and builds package caches."""
    home = make_fixture(tmp_path)
    source_repo = tmp_path / "repos" / "source-pkg"
    build_repo = tmp_path / "repos" / "build-pkg"
    setup_package_repos(source_repo, build_repo)

    pkgs_json = (
        home / ".config" / "agents" / "harnesses" / "pi" / "agent" / "packages.json"
    )
    pkgs_json.parent.mkdir(parents=True, exist_ok=True)
    pkgs_json.write_text(
        json.dumps({"packages": [str(source_repo), str(build_repo)]}, indent=2) + "\n",
        encoding="utf-8",
    )

    result = run_sync_process(home)
    assert result.exit_code == 0, result.stderr or result.stdout

    settings = (home / ".pi" / "agent" / "settings.json").read_text(encoding="utf-8")
    assert "source-pkg" in settings
    assert "build-pkg" in settings

    cache_snapshot = snapshot_selected(
        home / ".local" / "share" / "agents" / "pi-packages"
    )
    assert any("source-pkg" in entry.path for entry in cache_snapshot)
    assert any("build-pkg" in entry.path for entry in cache_snapshot)


def test_integration_invalid_package_json_fails_package_bootstrap(
    tmp_path: Path,
) -> None:
    """Test invalid package.json in bootstrap packages causes sync failure."""
    home = make_fixture(tmp_path)
    bad_repo = tmp_path / "repos" / "bad-pkg"
    bad_repo.mkdir(parents=True, exist_ok=True)
    (bad_repo / "package.json").write_text("{not valid json", encoding="utf-8")
    init_git_repo(bad_repo)

    pkgs_json = (
        home / ".config" / "agents" / "harnesses" / "pi" / "agent" / "packages.json"
    )
    pkgs_json.parent.mkdir(parents=True, exist_ok=True)
    pkgs_json.write_text(
        json.dumps({"packages": [str(bad_repo)]}, indent=2) + "\n",
        encoding="utf-8",
    )

    result = run_sync_process(home)
    assert result.exit_code != 0
    assert "package bootstrap failed for" in result.stderr


def test_integration_wrapper_forwards_arguments_to_faked_runtime(
    tmp_path: Path,
) -> None:
    """Test wrapper script forwards CLI arguments to installed runtime."""
    home = make_fixture(tmp_path)
    sync_result = run_sync_process(home)
    assert sync_result.exit_code == 0, sync_result.stderr or sync_result.stdout

    wrapper = home / ".local" / "bin" / "codex"
    release_dir = (home / ".local" / "share" / "agents" / "sync-current").resolve()
    venv_python = release_dir / ".venv" / "bin" / "python"
    assert wrapper.is_file(), str(wrapper)
    assert venv_python.exists(), str(venv_python)

    wrapper_text = wrapper.read_text(encoding="utf-8")
    assert "agents-managed-wrapper:v1" in wrapper_text
    assert ".local/share/agents/sync-current" in wrapper_text
    assert ".venv/bin/python" in wrapper_text
    assert "-m sync.cli" in wrapper_text
    assert str(SYNC_ROOT) not in wrapper_text
    assert ".config/agents/sync" not in wrapper_text

    # Replace the seeded venv symlink with a fake venv python that echoes the
    # module invocation, isolating this test from the shared release venv.
    venv_dir = release_dir / ".venv"
    if venv_dir.is_symlink() or venv_dir.exists():
        if venv_dir.is_symlink():
            venv_dir.unlink()
        else:
            shutil.rmtree(venv_dir, ignore_errors=True)
    fake_bin = venv_dir / "bin"
    fake_bin.mkdir(parents=True, exist_ok=True)
    fake_python = fake_bin / "python"
    fake_python.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-m" ]; then shift 2; fi\n'
        'echo "mode=$1"\n'
        'echo "sourceName=$2"\n'
        'echo "separator=$3"\n'
        "shift 3\n"
        "i=0\n"
        'for arg in "$@"; do\n'
        '  echo "arg[$i]=$arg"\n'
        "  i=$((i + 1))\n"
        "done\n"
        "exit 42\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    result = run_wrapper(
        wrapper,
        ["--sentinel", "one", "two three"],
        home=home,
    )
    assert result.exit_code == FAKED_RUNTIME_EXIT_CODE, result.stderr or result.stdout
    assert "mode=launch" in result.stdout
    assert "sourceName=codex" in result.stdout
    assert "separator=--" in result.stdout
    assert "arg[0]=--sentinel" in result.stdout
    assert "arg[1]=one" in result.stdout
    assert "arg[2]=two three" in result.stdout
