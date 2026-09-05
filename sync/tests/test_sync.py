# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Comprehensive unit and integration tests for sync engine and lifecycle."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import platform
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypeGuard

import yaml

from sync.core.cliproxy_deployment import (
    ClientConfig,
    CliProxyDeployment,
    ListenConfig,
    ServerConfig,
)
from sync.core.harness import (
    SyncEnv,
    harness_instruction_target,
    harness_source_root,
)
from sync.core.hook_state import fingerprint_tree
from sync.core.index import (
    main,
    parse_timeout_seconds,
    run_sync,
    try_acquire_sync_lock,
)
from sync.core.jobs import run_jobs_with_preserve
from sync.core.managed_state import (
    load_recorded_entry_names,
    plan_managed_entries,
    write_recorded_entry_names,
)
from sync.core.managed_tools import supported_arch
from sync.core.plan import (
    CliProxyConfigJob,
    DirJob,
    ExtensionDepsHookPlan,
    FileJob,
    Job,
    PackageBootstrapHookPlan,
    SecretTemplateJob,
    build_sync_plan,
)
from sync.extensions.install import iter_extension_packages, run_install
from sync.packages.index import (
    extract_import_specifiers,
    missing_package_roots,
    package_cache_dir,
    package_has_build_script,
    package_is_healthy,
    patch_runtime_settings,
    read_package_manifest,
)
from sync.packages.source import clone_package_with_runner
from sync.runtime.lock import release_sync_lock
from sync.runtime.process import (
    RunProcessOptions,
    Success,
    TimedOut,
    run_command_outcome,
    run_process,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pytest

MODE_EXECUTABLE: Final[int] = 0o755
MODE_SECRET: Final[int] = 0o600
PERMISSION_MASK: Final[int] = 0o777

EXPECTED_PACKAGES_COUNT: Final[int] = 2
EXPECTED_ATTEMPTS_COUNT: Final[int] = 2
EXIT_WATCHDOG_TIMEOUT: Final[int] = 124

TIMEOUT_ONE_SECOND_MS: Final[float] = 1000.0
TIMEOUT_TWO_SECONDS_MS: Final[float] = 2000.0
TIMEOUT_THREE_SECONDS_MS: Final[float] = 3000.0

DEFAULT_TIMEOUT_SEVEN: Final[int] = 7
PARSED_TIMEOUT_NINE: Final[int] = 9


def _is_dict(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _test_cliproxy_deployment() -> CliProxyDeployment:
    """Create standard CLI proxy deployment for test runs."""
    return CliProxyDeployment(
        server=ServerConfig(hostname=socket.gethostname()),
        listen=ListenConfig(host="100.64.0.42", port=9443),
        client=ClientConfig(baseUrl="https://gateway.example.test:9443/v1"),
    )


def _write_file(path: Path, content: str) -> None:
    """Write text content to path, creating parent directories if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _is_gone(pid: int) -> bool:
    """Return True if process pid has terminated (ESRCH), False otherwise."""
    try:
        os.kill(pid, 0)
    except OSError as err:
        return err.errno == errno.ESRCH
    else:
        return False


def _init_git_repo(path: Path) -> None:
    """Initialize a mock git repository with one commit."""
    git_bin = shutil.which("git") or "git"
    asyncio.run(run_process([git_bin, "init"], cwd=path))
    asyncio.run(
        run_process(
            [git_bin, "config", "user.name", "Test User"],
            cwd=path,
        )
    )
    asyncio.run(
        run_process(
            [git_bin, "config", "user.email", "test@example.com"],
            cwd=path,
        )
    )
    asyncio.run(run_process([git_bin, "add", "."], cwd=path))
    asyncio.run(run_process([git_bin, "commit", "-m", "init"], cwd=path))


def _make_sync_env(
    root: Path,
    install_timeout_ms: int = 10_000,
) -> SyncEnv:
    """Build a test SyncEnv backed by directory layout under root."""
    agents_root = root / ".config" / "agents"
    sync_source = agents_root / "sync"
    sync_source.mkdir(parents=True, exist_ok=True)

    repo_sync = Path(__file__).resolve().parent.parent
    src_dst = sync_source / "src"
    if not src_dst.exists():
        shutil.copytree(repo_sync / "src", src_dst)
    for filename in ("pyproject.toml", "uv.lock", "README.md"):
        src_file = repo_sync / filename
        dst_file = sync_source / filename
        if src_file.exists() and not dst_file.exists():
            shutil.copyfile(src_file, dst_file)

    deployment_file = agents_root / "tools" / "cliproxyapi" / "deployment.json"
    deployment_file.parent.mkdir(parents=True, exist_ok=True)
    deployment_file.write_text(
        f"{
            json.dumps(
                {
                    'server': {'hostname': socket.gethostname()},
                    'listen': {'host': '100.64.0.42', 'port': 9443},
                    'client': {'baseUrl': 'https://gateway.example.test:9443/v1'},
                }
            )
        }\n",
        encoding="utf-8",
    )

    for harness_id in ("codex", "opencode", "pi", "omp"):
        (agents_root / "harnesses" / harness_id).mkdir(parents=True, exist_ok=True)

    return SyncEnv.from_home(str(root), install_timeout_ms)


def test_run_jobs_with_preserve_renders_secret_template_idempotently(
    tmp_path: Path,
) -> None:
    """Verify secret template job renders idempotently with preserved mode."""
    src = str(tmp_path / "config.yaml.tmpl")
    dst = str(tmp_path / "runtime" / "config.yaml")
    secrets_path = str(tmp_path / "secrets.local.json")
    _write_file(Path(src), "api-key: ${API_KEY}\n")
    _write_file(
        Path(secrets_path),
        f"{json.dumps({'API_KEY': 'quoted"value'})}\n",
    )

    jobs: list[Job] = [SecretTemplateJob(src=src, dst=dst, secrets_path=secrets_path)]
    assert run_jobs_with_preserve(jobs) is True
    assert (
        Path(dst).read_text(encoding="utf-8")
        == f"api-key: {json.dumps('quoted"value')}\n"
    )
    assert (Path(dst).lstat().st_mode & PERMISSION_MASK) == MODE_SECRET

    first = Path(dst).lstat()
    assert run_jobs_with_preserve(jobs) is True
    second = Path(dst).lstat()
    assert second.st_ino == first.st_ino
    assert second.st_mtime_ns == first.st_mtime_ns


def test_run_jobs_with_preserve_skips_secret_template_without_local_secrets(
    tmp_path: Path,
) -> None:
    """Verify secret template job skips execution when secrets are absent."""
    src = str(tmp_path / "config.yaml.tmpl")
    dst = str(tmp_path / "config.yaml")
    _write_file(Path(src), "api-key: ${API_KEY}\n")
    _write_file(Path(dst), "keep\n")

    jobs: list[Job] = [
        SecretTemplateJob(
            src=src,
            dst=dst,
            secrets_path=str(tmp_path / "missing-secrets.json"),
        )
    ]
    assert run_jobs_with_preserve(jobs) is True
    assert Path(dst).read_text(encoding="utf-8") == "keep\n"


def test_run_jobs_with_preserve_rejects_missing_template_secret(
    tmp_path: Path,
) -> None:
    """Verify secret template job fails when template references missing key."""
    src = str(tmp_path / "config.yaml.tmpl")
    dst = str(tmp_path / "config.yaml")
    secrets_path = str(tmp_path / "secrets.local.json")
    _write_file(Path(src), "api-key: ${API_KEY}\n")
    _write_file(Path(dst), "keep\n")
    _write_file(Path(secrets_path), "{}\n")

    jobs: list[Job] = [SecretTemplateJob(src=src, dst=dst, secrets_path=secrets_path)]
    assert run_jobs_with_preserve(jobs) is False
    assert Path(dst).read_text(encoding="utf-8") == "keep\n"


def test_run_jobs_with_preserve_expands_cliproxy_credential_pools_idempotently(
    tmp_path: Path,
) -> None:
    """Verify credential pool expansion in CLI proxy config is idempotent."""
    src = str(tmp_path / "config.yaml.tmpl")
    dst = str(tmp_path / "config.yaml")
    secrets_path = str(tmp_path / "secrets.local.json")
    _write_file(
        Path(src),
        "remote-management:\n"
        "  allow-remote: true\n"
        "  secret-key: tailnet\n"
        "codex-api-key:\n"
        "  - x-credential-pool: opencode-go\n"
        "    prefix: go\n"
        "    base-url: https://example.test/v1\n"
        "openai-compatibility:\n"
        "  - x-credential-pool: deepseek\n"
        "    name: deepseek\n"
        "    base-url: https://deepseek.example/v1\n",
    )
    _write_file(
        Path(secrets_path),
        f"{
            json.dumps(
                {
                    'CLIPROXY_CREDENTIAL_POOLS': {
                        'opencode-go': [
                            {'apiKey': 'go-one', 'weight': 1},
                            {'apiKey': 'go-two', 'weight': 2},
                        ],
                        'deepseek': [{'apiKey': 'router-one', 'weight': 1}],
                    },
                }
            )
        }\n",
    )

    deployment = _test_cliproxy_deployment()
    jobs: list[Job] = [
        CliProxyConfigJob(
            src=src,
            dst=dst,
            secrets_path=secrets_path,
            deployment=deployment,
            gateway_host=True,
        )
    ]
    assert run_jobs_with_preserve(jobs) is True
    config_raw = yaml.safe_load(Path(dst).read_text(encoding="utf-8"))
    assert _is_dict(config_raw)
    remote_mgmt = config_raw.get("remote-management")
    assert _is_dict(remote_mgmt)
    assert remote_mgmt.get("secret-key") == "tailnet"
    assert "api-keys" not in config_raw
    codex_keys = config_raw.get("codex-api-key")
    assert _is_list(codex_keys)
    extracted_codex: list[dict[str, object]] = [
        {
            "apiKey": raw_entry.get("api-key"),
            "weight": raw_entry.get("weight"),
            "poolMarker": raw_entry.get("x-credential-pool"),
        }
        for raw_entry in codex_keys
        if _is_dict(raw_entry)
    ]
    assert extracted_codex == [
        {"apiKey": "go-one", "weight": 1, "poolMarker": None},
        {"apiKey": "go-two", "weight": 2, "poolMarker": None},
    ]
    openai_compat = config_raw.get("openai-compatibility")
    assert _is_list(openai_compat)
    first_compat = openai_compat[0]
    assert _is_dict(first_compat)
    assert first_compat.get("api-key-entries") == [
        {"api-key": "router-one", "weight": 1}
    ]
    assert (Path(dst).lstat().st_mode & PERMISSION_MASK) == MODE_SECRET

    first = Path(dst).lstat()
    assert run_jobs_with_preserve(jobs) is True
    second = Path(dst).lstat()
    assert second.st_ino == first.st_ino
    assert second.st_mtime_ns == first.st_mtime_ns


def test_run_jobs_with_preserve_rejects_duplicate_cliproxy_credentials(
    tmp_path: Path,
) -> None:
    """Verify duplicate credential in pool causes job failure."""
    src = str(tmp_path / "config.yaml.tmpl")
    dst = str(tmp_path / "config.yaml")
    secrets_path = str(tmp_path / "secrets.local.json")
    _write_file(
        Path(src),
        "codex-api-key:\n  - x-credential-pool: opencode-go\n",
    )
    _write_file(Path(dst), "keep\n")
    _write_file(
        Path(secrets_path),
        f"{
            json.dumps(
                {
                    'CLIPROXY_CREDENTIAL_POOLS': {
                        'opencode-go': [
                            {'apiKey': 'duplicate'},
                            {'apiKey': 'duplicate'},
                        ],
                    },
                }
            )
        }\n",
    )

    deployment = _test_cliproxy_deployment()
    jobs: list[Job] = [
        CliProxyConfigJob(
            src=src,
            dst=dst,
            secrets_path=secrets_path,
            deployment=deployment,
            gateway_host=True,
        )
    ]
    assert run_jobs_with_preserve(jobs) is False
    assert Path(dst).read_text(encoding="utf-8") == "keep\n"


def test_run_jobs_with_preserve_keeps_generated_extension_entries(
    tmp_path: Path,
) -> None:
    """Verify generated extension directory entries are preserved."""
    src = str(tmp_path / "src")
    dst = str(tmp_path / "dst")

    _write_file(
        tmp_path / "src" / "extensions" / "context" / "index.ts",
        "export const live = true;\n",
    )
    _write_file(tmp_path / "dst" / "extensions" / "stale.ts", "stale\n")
    _write_file(
        tmp_path / "dst" / "extensions" / "package.json",
        '{"name":"generated"}\n',
    )
    _write_file(
        tmp_path / "dst" / "extensions" / "node_modules" / "dep" / "index.js",
        "module.exports = 1;\n",
    )

    jobs: list[Job] = [DirJob(src=src, dst=dst)]
    result = run_jobs_with_preserve(
        jobs,
        {dst: ["extensions/package.json", "extensions/node_modules"]},
    )
    assert result is True
    assert (tmp_path / "dst" / "extensions" / "context" / "index.ts").exists()
    assert not (tmp_path / "dst" / "extensions" / "stale.ts").exists()
    assert (tmp_path / "dst" / "extensions" / "package.json").exists()
    assert (
        tmp_path / "dst" / "extensions" / "node_modules" / "dep" / "index.js"
    ).exists()


def test_run_jobs_with_preserve_invalidates_cache_after_source_rewrite(
    tmp_path: Path,
) -> None:
    """Verify source content cache invalidates after rewriting source tree."""
    source_one = str(tmp_path / "source-one")
    first_destination = str(tmp_path / "first-destination")
    source_two = str(tmp_path / "source-two")
    final_destination = str(tmp_path / "final-destination")

    _write_file(tmp_path / "source-one" / "shared.txt", "old\n")
    _write_file(tmp_path / "first-destination" / "shared.txt", "xxx\n")
    _write_file(tmp_path / "source-two" / "shared.txt", "new\n")

    jobs: list[Job] = [
        DirJob(src=source_one, dst=first_destination, scope="Tree"),
        DirJob(src=source_two, dst=source_one, scope="Children"),
        DirJob(src=source_one, dst=final_destination, scope="Tree"),
    ]
    result = run_jobs_with_preserve(jobs)
    assert result is True
    assert (tmp_path / "final-destination" / "shared.txt").read_text(
        encoding="utf-8"
    ) == "new\n"


def test_iter_extension_packages_skips_node_modules(
    tmp_path: Path,
) -> None:
    """Verify package walk discovers extension packages and ignores node_modules."""
    _write_file(tmp_path / "a" / "package.json", "{}")
    _write_file(tmp_path / "a" / "nested" / "package.json", "{}")
    _write_file(tmp_path / "a" / "node_modules" / "skip" / "package.json", "{}")

    packages = sorted(asyncio.run(iter_extension_packages(str(tmp_path))))
    assert len(packages) == EXPECTED_PACKAGES_COUNT


def test_run_install_handles_success_failure_and_timeout(
    tmp_path: Path,
) -> None:
    """Verify run_install detects success, non-zero exit, and timeout."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    ok = bin_dir / "ok"
    _write_file(ok, "#!/bin/sh\nexit 0\n")
    ok.chmod(MODE_EXECUTABLE)
    assert asyncio.run(run_install([str(ok)], str(tmp_path), 1000)) is True

    fail = bin_dir / "fail"
    _write_file(fail, "#!/bin/sh\necho bad >&2\nexit 3\n")
    fail.chmod(MODE_EXECUTABLE)
    assert asyncio.run(run_install([str(fail)], str(tmp_path), 1000)) is False

    sleepy = bin_dir / "sleepy"
    _write_file(sleepy, "#!/bin/sh\nsleep 2\n")
    sleepy.chmod(MODE_EXECUTABLE)
    assert asyncio.run(run_install([str(sleepy)], str(tmp_path), 100)) is False


def test_run_command_outcome_resolves_relative_executable_from_command_cwd(
    tmp_path: Path,
) -> None:
    """Verify relative command path resolves relative to execution cwd."""
    script_dir = tmp_path / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)

    ok_script = script_dir / "ok"
    _write_file(ok_script, "#!/bin/sh\nexit 0\n")
    ok_script.chmod(MODE_EXECUTABLE)

    outcome = asyncio.run(
        run_command_outcome(
            ["./scripts/ok"],
            cwd=str(tmp_path),
            timeout_ms=5000,
        )
    )
    assert outcome == Success()


def test_run_command_outcome_times_out_cross_platform(
    tmp_path: Path,
) -> None:
    """Verify long-running subprocess outcome correctly reports TimedOut."""
    started_at = time.perf_counter()
    outcome = asyncio.run(
        run_command_outcome(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            cwd=str(tmp_path),
            timeout_ms=100,
        )
    )
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0

    assert outcome == TimedOut()
    assert elapsed_ms < TIMEOUT_ONE_SECOND_MS


def test_process_timeout_sleeping_fake_uv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify run_process handles timeout when invoked tool hangs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake_uv = bin_dir / "uv"
    _write_file(
        fake_uv,
        "#!/bin/sh\necho 'fake uv $1 $2' >&2\nsleep 30\n",
    )
    fake_uv.chmod(MODE_EXECUTABLE)

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    started_at = time.perf_counter()
    result = asyncio.run(
        run_process(
            ["uv", "python", "install"],
            RunProcessOptions(timeout_ms=100),
        )
    )
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    assert result.timed_out is True
    assert elapsed_ms < TIMEOUT_ONE_SECOND_MS


def test_process_inherit_preserves_terminal_stdin() -> None:
    """Verify process with inherited stdio retains terminal standard input."""
    if not sys.stdin.isatty():
        return

    result = asyncio.run(
        run_process(
            ["sh", "-c", "test -t 0"],
            RunProcessOptions(stdio="inherit"),
        )
    )
    assert result.exit_code == 0


def test_process_timeout_kills_descendant_holding_stdout(
    tmp_path: Path,
) -> None:
    """Verify timeout terminates entire process tree holding standard output."""
    pids_file = tmp_path / "pids.txt"
    fixture = tmp_path / "descendant.py"
    fixture.write_text(
        f"""import os, subprocess, time
pids_file = {str(pids_file)!r}
parent_pid = os.getpid()
child = subprocess.Popen(
    ['sh', '-c', 'while :; do sleep 1; done'],
    stdin=subprocess.DEVNULL,
)
with open(pids_file, 'w', encoding='utf-8') as f:
    f.write(f'{{parent_pid}} {{child.pid}}')
time.sleep(10)
""",
        encoding="utf-8",
    )

    started_at = time.perf_counter()
    result = asyncio.run(
        run_process(
            [sys.executable, "-u", str(fixture)],
            RunProcessOptions(timeout_ms=500, stdio="pipe"),
        )
    )
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0

    assert result.timed_out is True
    assert elapsed_ms < TIMEOUT_TWO_SECONDS_MS

    assert pids_file.exists()
    pids = pids_file.read_text(encoding="utf-8").split()
    parent_pid = int(pids[0])
    child_pid = int(pids[1])

    time.sleep(0.1)
    assert _is_gone(parent_pid), f"parent {parent_pid} still alive"
    assert _is_gone(child_pid), f"child {child_pid} still alive"


def test_run_install_force_kills_term_trapping_process(
    tmp_path: Path,
) -> None:
    """Verify install runner escalates to SIGKILL for processes trapping SIGTERM."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    trapped = bin_dir / "trapped"
    _write_file(
        trapped,
        "#!/bin/sh\ntrap '' TERM\nwhile :; do sleep 1; done\n",
    )
    trapped.chmod(MODE_EXECUTABLE)

    result = asyncio.run(run_install([str(trapped)], str(tmp_path), 100))
    assert result is False


def test_python_bootstrap_times_out_sleeping_fake_uv(
    seeded_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify python bootstrap logs warning on timeout without aborting sync."""
    bin_dir = seeded_home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    fake_uv = bin_dir / "uv"
    _write_file(fake_uv, "#!/bin/sh\nsleep 30\n")
    fake_uv.chmod(MODE_EXECUTABLE)

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    sync_env = _make_sync_env(seeded_home, 100)
    started_at = time.perf_counter()
    success = asyncio.run(run_sync(sync_env))
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0

    assert elapsed_ms < TIMEOUT_TWO_SECONDS_MS
    stderr = capsys.readouterr().err
    assert "uv python install failed" in stderr
    assert success is True


def test_main_reports_lock_contention_and_skips(
    home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify concurrent sync invocation skips execution and returns zero."""
    sync_env = _make_sync_env(home)
    lock = try_acquire_sync_lock(sync_env)
    assert lock is not None
    try:
        exit_code = main()
        assert exit_code == 0
        stderr = capsys.readouterr().err
        assert "another sync is already running; skipping" in stderr
    finally:
        release_sync_lock(lock)


def test_watchdog_exits_124_on_global_timeout(tmp_path: Path) -> None:
    """Verify watchdog timer terminates process with exit code 124 on expiry."""
    helper = tmp_path / "watchdog_helper.py"
    helper.write_text(
        """import time
from sync.core.index import start_sync_watchdog
start_sync_watchdog(1)
while True:
    time.sleep(1)
""",
        encoding="utf-8",
    )
    result = asyncio.run(
        run_process(
            [sys.executable, str(helper)],
            RunProcessOptions(timeout_ms=10_000),
        )
    )
    assert result.exit_code == EXIT_WATCHDOG_TIMEOUT
    assert "timed out after 1s" in result.stderr


def test_watchdog_can_be_cancelled_so_host_outlives_short_timeout(
    tmp_path: Path,
) -> None:
    """Verify cancelling watchdog prevents premature process termination."""
    helper = tmp_path / "watchdog_cancel.py"
    helper.write_text(
        """import time
from sync.core.index import start_sync_watchdog
stop = start_sync_watchdog(1)
time.sleep(0.5)
stop()
time.sleep(1.5)
print('ok')
""",
        encoding="utf-8",
    )
    result = asyncio.run(
        run_process(
            [sys.executable, str(helper)],
            RunProcessOptions(timeout_ms=10_000),
        )
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == "ok"


def test_parse_timeout_seconds_uses_default_for_invalid_values() -> None:
    """Verify parse_timeout_seconds falls back to default on invalid inputs."""
    assert parse_timeout_seconds(None, DEFAULT_TIMEOUT_SEVEN) == DEFAULT_TIMEOUT_SEVEN
    assert parse_timeout_seconds("0", DEFAULT_TIMEOUT_SEVEN) == DEFAULT_TIMEOUT_SEVEN
    assert parse_timeout_seconds("nope", DEFAULT_TIMEOUT_SEVEN) == DEFAULT_TIMEOUT_SEVEN
    assert parse_timeout_seconds("9", DEFAULT_TIMEOUT_SEVEN) == PARSED_TIMEOUT_NINE


def test_sync_env_harness_lookup_is_typed(home: Path) -> None:
    """Verify typed harness resolution and instruction targets in SyncEnv."""
    sync_env = _make_sync_env(home)
    pi = sync_env.harness("pi")
    assert pi is not None
    assert harness_source_root(pi, sync_env.harnesses_home) == str(
        home / ".config" / "agents" / "harnesses" / "pi" / "agent"
    )
    assert harness_instruction_target(pi) == str(home / ".pi" / "agent" / "AGENTS.md")


def test_sync_plan_resolves_hook_targets_from_harness_specs(
    home: Path,
) -> None:
    """Verify hook plans are correctly derived from harness specifications."""
    sync_env = _make_sync_env(home)
    sync_plan = build_sync_plan(sync_env)

    package_hook = next(
        (h for h in sync_plan.hooks if isinstance(h, PackageBootstrapHookPlan)),
        None,
    )
    extension_hooks = [
        h for h in sync_plan.hooks if isinstance(h, ExtensionDepsHookPlan)
    ]

    assert package_hook is not None
    assert package_hook.manifest_path == str(
        home / ".config" / "agents" / "harnesses" / "pi" / "agent" / "packages.json"
    )
    assert package_hook.runtime_settings_path == str(
        home / ".pi" / "agent" / "settings.json"
    )
    assert package_hook.cache_root == str(
        home / ".local" / "share" / "agents" / "pi-packages"
    )

    assert [(h.harness.id, h.root) for h in extension_hooks] == [
        ("opencode", str(home / ".config" / "opencode")),
        ("pi", str(home / ".pi" / "agent" / "extensions")),
        ("omp", str(home / ".omp" / "agent")),
    ]


def test_sync_plan_deploys_cliproxy_panel_asset_only_on_gateway_host(
    home: Path,
) -> None:
    """Verify CLI proxy panel asset is included in jobs only on gateway host."""
    sync_env = _make_sync_env(home)
    panel_src = home / ".config" / "agents" / "tools" / "cliproxyapi" / "panel.html"
    _write_file(panel_src, "<html>panel</html>\n")
    panel_dst = str(Path(".cli-proxy-api") / "static" / "management.html")

    gateway_plan = build_sync_plan(sync_env)
    panel_job = next(
        (
            j
            for j in gateway_plan.jobs
            if isinstance(j, FileJob) and j.dst.endswith(panel_dst)
        ),
        None,
    )
    assert panel_job is not None
    assert panel_job.src == str(panel_src)

    deployment_path = (
        home / ".config" / "agents" / "tools" / "cliproxyapi" / "deployment.json"
    )
    deployment_path.write_text(
        f"{
            json.dumps(
                {
                    'server': {'hostname': 'not-the-gateway.example.test'},
                    'listen': {'host': '100.64.0.42', 'port': 9443},
                    'client': {'baseUrl': 'https://gateway.example.test:9443/v1'},
                }
            )
        }\n",
        encoding="utf-8",
    )
    client_sync_env = SyncEnv.from_home(str(home), 10_000)
    client_plan = build_sync_plan(client_sync_env)
    assert not any(
        isinstance(j, FileJob) and j.dst.endswith(panel_dst) for j in client_plan.jobs
    )


def test_run_sync_happy_path(seeded_home: Path) -> None:
    """Verify full happy-path sync execution reconciles all harness assets."""
    sync_env = _make_sync_env(seeded_home)

    _write_file(
        seeded_home / ".config" / "agents" / "HARNESS.md",
        "agent-instructions",
    )
    _write_file(
        seeded_home / ".config" / "agents" / "tools" / "mcporter" / "mcporter.jsonc",
        '{"x":1}',
    )
    _write_file(
        seeded_home / ".config" / "agents" / "tools" / "summarize" / "config.json",
        '{"model":"fast"}',
    )
    _write_file(
        seeded_home / ".config" / "agents" / "skills" / "current" / "skill.txt",
        "skill-content",
    )
    _write_file(
        seeded_home / ".config" / "agents" / "harnesses" / "codex" / "config.toml",
        "codex = true",
    )
    _write_file(
        seeded_home
        / ".config"
        / "agents"
        / "harnesses"
        / "omp"
        / "agent"
        / "config.yml",
        "theme:\n  dark: graphite\n",
    )
    _write_file(
        seeded_home
        / ".config"
        / "agents"
        / "harnesses"
        / "pi"
        / "agent"
        / "extensions"
        / "answer"
        / "package.json",
        "{}",
    )
    (
        seeded_home
        / ".config"
        / "agents"
        / "harnesses"
        / "pi"
        / "agent"
        / "extensions"
        / "answer"
        / "node_modules"
    ).mkdir(parents=True, exist_ok=True)
    _write_file(seeded_home / ".pi" / "agent" / "auth.json", '{"token":1}')
    _write_file(
        seeded_home / ".pi" / "agent" / "extensions" / "stale.ts",
        "stale",
    )
    _write_file(
        seeded_home / ".omp" / "agent" / "skills" / "stale.txt",
        "stale-skill",
    )
    _write_file(
        seeded_home / ".omp" / "agent" / "logs" / "keep.txt",
        "keep-me",
    )

    assert asyncio.run(run_sync(sync_env)) is True
    assert (seeded_home / ".codex" / "AGENTS.md").exists()
    assert (seeded_home / ".config" / "opencode" / "AGENTS.md").exists()
    assert (seeded_home / ".pi" / "agent" / "AGENTS.md").exists()
    assert (seeded_home / ".omp" / "agent" / "AGENTS.md").exists()
    assert (seeded_home / ".omp" / "agent" / "config.yml").exists()
    assert (seeded_home / ".omp" / "agent" / "skills" / "skill.txt").exists()
    assert (seeded_home / ".mcporter" / "mcporter.json").exists()
    assert (seeded_home / ".summarize" / "config.json").exists()
    assert (seeded_home / ".pi" / "agent" / "auth.json").exists()
    assert not (seeded_home / ".pi" / "agent" / "extensions" / "stale.ts").exists()
    assert not (seeded_home / ".omp" / "agent" / "skills" / "stale.txt").exists()
    assert (seeded_home / ".omp" / "agent" / "logs" / "keep.txt").exists()


def test_run_sync_missing_sources_is_non_fatal(
    seeded_home: Path,
) -> None:
    """Verify sync succeeds gracefully when optional SSOT sources are missing."""
    sync_env = _make_sync_env(seeded_home)
    assert asyncio.run(run_sync(sync_env)) is True


def test_run_sync_cleans_managed_entries_for_multiple_harnesses(
    seeded_home: Path,
) -> None:
    """Verify stale managed entries are removed across multiple harnesses."""
    sync_env = _make_sync_env(seeded_home)
    agents_root = seeded_home / ".config" / "agents"

    _write_file(agents_root / "HARNESS.md", "agent-instructions")
    _write_file(
        agents_root / "skills" / "current" / "skill.txt",
        "fresh-skill",
    )
    _write_file(
        agents_root / "harnesses" / "codex" / "config.toml",
        "fresh = true\n",
    )
    _write_file(
        agents_root / "harnesses" / "omp" / "agent" / "config.yml",
        "theme:\n  light: graphite\n",
    )

    _write_file(seeded_home / ".codex" / "config.toml", "stale = true\n")
    _write_file(seeded_home / ".codex" / "skills" / "stale.txt", "stale-skill")
    _write_file(seeded_home / ".codex" / "logs" / "keep.txt", "keep-me")
    _write_file(seeded_home / ".omp" / "agent" / "config.yml", "stale-config\n")
    _write_file(
        seeded_home / ".omp" / "agent" / "skills" / "stale.txt",
        "stale-skill",
    )
    _write_file(seeded_home / ".omp" / "agent" / "logs" / "keep.txt", "keep-me")

    assert asyncio.run(run_sync(sync_env)) is True
    assert (seeded_home / ".codex" / "config.toml").read_text(
        encoding="utf-8"
    ) == "fresh = true\n"
    assert (seeded_home / ".omp" / "agent" / "config.yml").read_text(
        encoding="utf-8"
    ) == "theme:\n  light: graphite\n"
    assert (seeded_home / ".codex" / "skills" / "skill.txt").exists()
    assert (seeded_home / ".omp" / "agent" / "skills" / "skill.txt").exists()
    assert not (seeded_home / ".codex" / "skills" / "stale.txt").exists()
    assert not (seeded_home / ".omp" / "agent" / "skills" / "stale.txt").exists()
    assert (seeded_home / ".codex" / "logs" / "keep.txt").exists()
    assert (seeded_home / ".omp" / "agent" / "logs" / "keep.txt").exists()


def test_run_sync_omp_cleans_managed_entries_but_preserves_local_files(
    seeded_home: Path,
) -> None:
    """Verify OMP sync cleans managed entries while preserving unmanaged files."""
    sync_env = _make_sync_env(seeded_home)
    agents_root = seeded_home / ".config" / "agents"

    _write_file(agents_root / "HARNESS.md", "agent-instructions")
    _write_file(
        agents_root / "skills" / "current" / "skill.txt",
        "fresh-skill",
    )
    _write_file(
        agents_root / "harnesses" / "omp" / "agent" / "config.yml",
        "theme:\n  light: graphite\n",
    )

    _write_file(seeded_home / ".omp" / "agent" / "config.yml", "stale-config\n")
    _write_file(
        seeded_home / ".omp" / "agent" / "skills" / "stale.txt",
        "stale-skill",
    )
    _write_file(seeded_home / ".omp" / "agent" / "logs" / "keep.txt", "keep-me")

    assert asyncio.run(run_sync(sync_env)) is True
    assert (seeded_home / ".omp" / "agent" / "config.yml").read_text(
        encoding="utf-8"
    ) == "theme:\n  light: graphite\n"
    assert (seeded_home / ".omp" / "agent" / "skills" / "skill.txt").exists()
    assert not (seeded_home / ".omp" / "agent" / "skills" / "stale.txt").exists()
    assert (seeded_home / ".omp" / "agent" / "logs" / "keep.txt").exists()


def test_run_sync_cleans_legacy_pi_entries_without_prior_state(
    seeded_home: Path,
) -> None:
    """Verify legacy pi entries are purged during initial sync without prior state."""
    sync_env = _make_sync_env(seeded_home)
    agents_root = seeded_home / ".config" / "agents"

    _write_file(agents_root / "HARNESS.md", "agent-instructions")
    _write_file(seeded_home / ".pi" / "agent" / "legacy" / "old.txt", "stale")
    _write_file(seeded_home / ".pi" / "agent" / "auth.json", '{"token":1}')

    assert asyncio.run(run_sync(sync_env)) is True
    assert not (seeded_home / ".pi" / "agent" / "legacy").exists()
    assert (seeded_home / ".pi" / "agent" / "auth.json").exists()


def test_run_sync_removes_entries_removed_from_ssot_after_prior_sync(
    seeded_home: Path,
) -> None:
    """Verify deleted SSOT items are removed on subsequent sync run."""
    sync_env = _make_sync_env(seeded_home)
    agents_root = seeded_home / ".config" / "agents"
    codex_config = agents_root / "harnesses" / "codex" / "config.toml"
    skills_root = agents_root / "skills" / "current"

    _write_file(agents_root / "HARNESS.md", "agent-instructions")
    _write_file(skills_root / "skill.txt", "fresh-skill")
    _write_file(codex_config, "fresh = true\n")

    assert asyncio.run(run_sync(sync_env)) is True
    assert (seeded_home / ".codex" / "config.toml").exists()
    assert (seeded_home / ".codex" / "skills" / "skill.txt").exists()
    assert (
        seeded_home / ".local" / "share" / "agents" / "sync-managed" / "codex.json"
    ).exists()

    codex_config.unlink(missing_ok=True)
    if skills_root.exists():
        shutil.rmtree(skills_root)
    _write_file(seeded_home / ".codex" / "logs" / "keep.txt", "keep-me")

    sync_env2 = SyncEnv.from_home(str(seeded_home), 10_000)
    assert asyncio.run(run_sync(sync_env2)) is True
    assert not (seeded_home / ".codex" / "config.toml").exists()
    assert not (seeded_home / ".codex" / "skills").exists()
    assert (seeded_home / ".codex" / "logs" / "keep.txt").exists()


def test_run_sync_removes_cli_proxy_api_wrapper_after_gateway_to_client_transition(
    seeded_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify cli-proxy-api wrapper is deleted when host ceases to be gateway."""
    sync_env = _make_sync_env(seeded_home)
    agents_root = seeded_home / ".config" / "agents"

    arch = supported_arch(platform.machine())
    platform_key = f"{sync_env.platform}-{arch}"
    version = "7.2.132"
    repository = "router-for-me/CLIProxyAPI"
    asset_name = "CLIProxyAPI_fixture.tar.gz"
    checksum = hashlib.sha256(b"fixture archive").hexdigest()
    install_dir = (
        seeded_home
        / "cache"
        / "github-tools"
        / "cliproxyapi"
        / "versions"
        / version
        / platform_key
    )
    wrapper_path = seeded_home / ".local" / "bin" / "cli-proxy-api"
    wrappers_state_path = (
        seeded_home / ".local" / "share" / "agents" / "sync-managed" / "wrappers.json"
    )

    _write_file(
        agents_root / "tools" / "cliproxyapi" / "release.json",
        f"{
            json.dumps(
                {
                    'repository': repository,
                    'version': version,
                    'binary': 'cli-proxy-api',
                    'assets': {platform_key: {'name': asset_name, 'sha256': checksum}},
                },
                indent=2,
            )
        }\n",
    )
    _write_file(install_dir / "cli-proxy-api", "#!/bin/sh\nexit 0\n")
    (install_dir / "cli-proxy-api").chmod(MODE_EXECUTABLE)
    _write_file(
        install_dir / "receipt.json",
        f"{
            json.dumps(
                {
                    'repository': repository,
                    'version': version,
                    'asset': asset_name,
                    'sha256': checksum,
                },
                indent=2,
            )
        }\n",
    )
    _write_file(agents_root / "HARNESS.md", "agent-instructions")
    _write_file(agents_root / "skills" / "current" / "skill.txt", "fresh-skill")
    _write_file(
        agents_root / "harnesses" / "codex" / "config.toml",
        "fresh = true\n",
    )

    monkeypatch.setenv("XDG_CACHE_HOME", str(seeded_home / "cache"))
    assert asyncio.run(run_sync(sync_env)) is True
    assert wrapper_path.exists()
    assert str(wrapper_path) in wrappers_state_path.read_text(encoding="utf-8")

    _write_file(
        agents_root / "tools" / "cliproxyapi" / "deployment.json",
        f"{
            json.dumps(
                {
                    'server': {'hostname': 'different-gateway.example.test'},
                    'listen': {'host': '100.64.0.42', 'port': 9443},
                    'client': {'baseUrl': 'https://gateway.example.test:9443/v1'},
                }
            )
        }\n",
    )

    sync_env2 = SyncEnv.from_home(str(seeded_home), 10_000)
    assert asyncio.run(run_sync(sync_env2)) is True
    assert not wrapper_path.exists()
    assert str(wrapper_path) not in wrappers_state_path.read_text(encoding="utf-8")


def test_run_sync_copies_current_skills_but_not_legacy_skills(
    seeded_home: Path,
) -> None:
    """Verify only skills under current/ are deployed to harness skill directories."""
    sync_env = _make_sync_env(seeded_home)
    agents_root = seeded_home / ".config" / "agents"

    _write_file(agents_root / "HARNESS.md", "agent-instructions")
    _write_file(
        agents_root / "skills" / "current" / "skill.txt",
        "fresh-skill",
    )
    _write_file(
        agents_root / "skills" / "legacy" / "old-skill.txt",
        "legacy-skill",
    )

    assert asyncio.run(run_sync(sync_env)) is True
    assert (seeded_home / ".codex" / "skills" / "skill.txt").exists()
    assert not (seeded_home / ".codex" / "skills" / "legacy").exists()
    assert (seeded_home / ".omp" / "agent" / "skills" / "skill.txt").exists()
    assert not (seeded_home / ".omp" / "agent" / "skills" / "legacy").exists()


def test_run_sync_preserves_generated_extension_runtime_when_hook_inputs_match(
    seeded_home: Path,
) -> None:
    """Verify extension dependencies are not deleted when fingerprint is unchanged."""
    sync_env = _make_sync_env(seeded_home)

    _write_file(
        seeded_home / ".config" / "agents" / "HARNESS.md",
        "agent-instructions",
    )
    ext_src = (
        seeded_home / ".config" / "agents" / "harnesses" / "pi" / "agent" / "extensions"
    )
    _write_file(ext_src / "context" / "index.ts", "export const live = true;\n")
    _write_file(seeded_home / ".pi" / "agent" / "auth.json", '{"token":1}')
    _write_file(
        seeded_home / ".pi" / "agent" / "extensions" / "package.json",
        '{"name":"generated"}\n',
    )
    _write_file(
        seeded_home
        / ".pi"
        / "agent"
        / "extensions"
        / "node_modules"
        / "dep"
        / "index.js",
        "module.exports = 1;\n",
    )
    _write_file(
        seeded_home
        / ".local"
        / "share"
        / "agents"
        / "sync-managed"
        / "pi.extension-deps.json",
        f"{
            json.dumps(
                {
                    'fingerprint': fingerprint_tree(ext_src),
                    'generatedEntries': ['package.json', 'node_modules'],
                },
                indent=2,
            )
        }\n",
    )

    assert asyncio.run(run_sync(sync_env)) is True
    assert (seeded_home / ".pi" / "agent" / "extensions" / "package.json").exists()
    assert (
        seeded_home
        / ".pi"
        / "agent"
        / "extensions"
        / "node_modules"
        / "dep"
        / "index.js"
    ).exists()


def test_run_sync_drops_legacy_npm_extension_state_entries_without_reinstall(
    seeded_home: Path,
) -> None:
    """Verify legacy package lock entries in state are removed cleanly."""
    sync_env = _make_sync_env(seeded_home)
    source_root = (
        seeded_home / ".config" / "agents" / "harnesses" / "pi" / "agent" / "extensions"
    )
    state_path = (
        seeded_home
        / ".local"
        / "share"
        / "agents"
        / "sync-managed"
        / "pi.extension-deps.json"
    )

    _write_file(
        seeded_home / ".config" / "agents" / "HARNESS.md",
        "agent-instructions",
    )
    _write_file(
        source_root / "context" / "index.ts",
        "export const live = true;\n",
    )
    _write_file(seeded_home / ".pi" / "agent" / "auth.json", '{"token":1}')
    _write_file(
        seeded_home / ".pi" / "agent" / "extensions" / "package.json",
        '{"name":"generated"}\n',
    )
    _write_file(
        seeded_home
        / ".pi"
        / "agent"
        / "extensions"
        / "node_modules"
        / "dep"
        / "index.js",
        "module.exports = 1;\n",
    )
    _write_file(
        seeded_home / ".pi" / "agent" / "extensions" / "package-lock.json",
        '{"lockfileVersion":3}\n',
    )
    _write_file(
        seeded_home / ".pi" / "agent" / "extensions" / "npm-shrinkwrap.json",
        '{"lockfileVersion":3}\n',
    )
    _write_file(
        state_path,
        f"{
            json.dumps(
                {
                    'fingerprint': fingerprint_tree(source_root),
                    'generatedEntries': [
                        'package.json',
                        'node_modules',
                        'package-lock.json',
                        'npm-shrinkwrap.json',
                    ],
                },
                indent=2,
            )
        }\n",
    )

    assert asyncio.run(run_sync(sync_env)) is True
    assert (seeded_home / ".pi" / "agent" / "extensions" / "package.json").exists()
    assert (
        seeded_home
        / ".pi"
        / "agent"
        / "extensions"
        / "node_modules"
        / "dep"
        / "index.js"
    ).exists()
    assert not (
        seeded_home / ".pi" / "agent" / "extensions" / "package-lock.json"
    ).exists()
    assert not (
        seeded_home / ".pi" / "agent" / "extensions" / "npm-shrinkwrap.json"
    ).exists()

    state_raw = json.loads(state_path.read_text(encoding="utf-8"))
    assert _is_dict(state_raw)
    assert state_raw.get("generatedEntries") == ["package.json", "node_modules"]


def test_run_sync_removes_generated_extension_runtime_when_hook_inputs_change(
    seeded_home: Path,
) -> None:
    """Verify stale extension runtime entries are removed on fingerprint mismatch."""
    sync_env = _make_sync_env(seeded_home)

    _write_file(
        seeded_home / ".config" / "agents" / "HARNESS.md",
        "agent-instructions",
    )
    _write_file(
        seeded_home
        / ".config"
        / "agents"
        / "harnesses"
        / "pi"
        / "agent"
        / "extensions"
        / "context"
        / "index.ts",
        "export const live = true;\n",
    )
    _write_file(seeded_home / ".pi" / "agent" / "auth.json", '{"token":1}')
    _write_file(
        seeded_home / ".pi" / "agent" / "extensions" / "package.json",
        '{"name":"generated"}\n',
    )
    _write_file(
        seeded_home
        / ".pi"
        / "agent"
        / "extensions"
        / "node_modules"
        / "dep"
        / "index.js",
        "module.exports = 1;\n",
    )
    _write_file(
        seeded_home
        / ".local"
        / "share"
        / "agents"
        / "sync-managed"
        / "pi.extension-deps.json",
        f"{
            json.dumps(
                {
                    'fingerprint': 'stale',
                    'generatedEntries': ['package.json', 'node_modules'],
                },
                indent=2,
            )
        }\n",
    )

    assert asyncio.run(run_sync(sync_env)) is True
    assert not (seeded_home / ".pi" / "agent" / "extensions" / "package.json").exists()
    assert not (seeded_home / ".pi" / "agent" / "extensions" / "node_modules").exists()


def test_run_sync_omp_does_not_bootstrap_packages(
    seeded_home: Path,
) -> None:
    """Verify OMP harness skips package bootstrap step."""
    sync_env = _make_sync_env(seeded_home)
    agents_root = seeded_home / ".config" / "agents"

    _write_file(agents_root / "HARNESS.md", "agent-instructions")
    _write_file(
        agents_root / "harnesses" / "omp" / "agent" / "config.yml",
        "interruptMode: immediate\n",
    )
    _write_file(
        agents_root / "harnesses" / "omp" / "agent" / "packages.json",
        "this is not valid json\n",
    )

    assert asyncio.run(run_sync(sync_env)) is True
    assert (seeded_home / ".omp" / "agent" / "packages.json").read_text(
        encoding="utf-8"
    ) == "this is not valid json\n"
    assert (seeded_home / ".omp" / "agent" / "config.yml").exists()


def test_run_sync_omp_ignores_runtime_session_sources_when_inferring_dependencies(
    seeded_home: Path,
) -> None:
    """Verify session script imports are ignored during OMP dependency scan."""
    sync_env = _make_sync_env(seeded_home)
    agents_root = seeded_home / ".config" / "agents"

    _write_file(agents_root / "HARNESS.md", "agent-instructions")
    _write_file(
        agents_root / "harnesses" / "omp" / "agent" / "config.yml",
        "interruptMode: immediate\n",
    )
    _write_file(
        seeded_home / ".omp" / "agent" / "sessions" / "poison.ts",
        'import "#sqlite";\n',
    )

    assert asyncio.run(run_sync(sync_env)) is True
    assert not (seeded_home / ".omp" / "agent" / "package.json").exists()


def test_extract_import_specifiers_ignores_prose_and_string_literals() -> None:
    """Verify import parser extracts genuine imports while ignoring prose/strings."""
    sample = (
        '\nimport fs from "node:fs";\n'
        'import { createCommitTools } from "@oh-my-pi/pi-coding-agent";\n'
        'export { helper } from "external-lib";\n'
        "const code = 'file.content.includes(\"rename from \")';\n"
        'const prose = "from lodash";\n'
        'const dynamic = await import("dynamic-pkg");\n'
        'const required = require("req-pkg");\n'
    )
    extracted = extract_import_specifiers(sample)
    assert extracted == [
        "node:fs",
        "@oh-my-pi/pi-coding-agent",
        "external-lib",
        "dynamic-pkg",
        "req-pkg",
    ]


def test_missing_package_roots_ignores_invalid_package_names_in_source(
    tmp_path: Path,
) -> None:
    """Verify invalid package name patterns in comments/strings are ignored."""
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "index.ts").write_text(
        '\nimport { test } from "@oh-my-pi/pi-coding-agent";\n'
        'const check = file.content.includes("\\nrename from ") || '
        'file.content.startsWith("rename from ");\n',
        encoding="utf-8",
    )
    missing = missing_package_roots(str(tmp_path))
    assert missing == ["@oh-my-pi/pi-coding-agent"]


def test_read_package_manifest_dedupes_sources(tmp_path: Path) -> None:
    """Verify read_package_manifest eliminates duplicate package URLs."""
    manifest_path = tmp_path / "packages.json"
    manifest_path.write_text(
        f"{
            json.dumps(
                {
                    'packages': [
                        'https://github.com/tintinweb/pi-supervisor',
                        'https://github.com/tintinweb/pi-supervisor',
                        'https://github.com/joelhooks/pi-tools',
                    ],
                },
                indent=2,
            )
        }\n",
        encoding="utf-8",
    )
    manifest = read_package_manifest(str(manifest_path))
    assert len(manifest.packages) == EXPECTED_PACKAGES_COUNT


def test_patch_runtime_settings_preserves_other_keys(tmp_path: Path) -> None:
    """Verify updating packages array in settings.json preserves existing keys."""
    path = tmp_path / "settings.json"
    path.write_text(
        '{\n  "theme": "dark",\n  "defaultModel": "gpt-5.4"\n}\n',
        encoding="utf-8",
    )
    patch_runtime_settings(str(path), [str(tmp_path / "pkg")])
    settings_raw = json.loads(path.read_text(encoding="utf-8"))
    assert _is_dict(settings_raw)
    assert settings_raw.get("theme") == "dark"
    assert settings_raw.get("packages") == [str(tmp_path / "pkg")]


def test_package_cache_dir_is_stable(tmp_path: Path) -> None:
    """Verify package cache directory generation is deterministic."""
    root = str(tmp_path / "cache-root")
    left = package_cache_dir(root, "https://github.com/tintinweb/pi-supervisor")
    right = package_cache_dir(root, "https://github.com/tintinweb/pi-supervisor")
    assert left == right


def test_package_cache_dir_uses_basename_for_local_paths(
    tmp_path: Path,
) -> None:
    """Verify local directory sources use directory basename in slug."""
    root = str(tmp_path / "cache-root")
    sources = [
        str(tmp_path / "opt" / "packages" / "foo"),
        str(tmp_path / "var" / "tmp" / "foo") + "/",
    ]

    for source in sources:
        cache_dir = package_cache_dir(root, source)
        assert Path(cache_dir).name.startswith("foo-"), source


def test_github_clone_command_prefers_gh_when_available(
    tmp_path: Path,
) -> None:
    """Verify gh CLI is tried first when available."""
    target = str(tmp_path / "out")
    attempts: list[list[str]] = []

    async def fake_runner(command: Sequence[str]) -> bool:
        attempts.append(list(command))
        return True

    asyncio.run(
        clone_package_with_runner(
            "https://github.com/tintinweb/pi-supervisor",
            target,
            gh_available=True,
            runner=fake_runner,
        )
    )
    assert len(attempts) == 1
    assert attempts[0][0] == "gh"
    assert attempts[0][3] == "tintinweb/pi-supervisor"


def test_github_clone_falls_back_to_git_after_gh_failure(
    tmp_path: Path,
) -> None:
    """Verify clone runner falls back to git clone if gh fails."""
    target = str(tmp_path / "out")
    attempts: list[list[str]] = []
    outcomes = [False, True]
    index = 0

    async def fake_runner(command: Sequence[str]) -> bool:
        nonlocal index
        attempts.append(list(command))
        outcome = outcomes[index] if index < len(outcomes) else False
        index += 1
        return outcome

    success = asyncio.run(
        clone_package_with_runner(
            "https://github.com/tintinweb/pi-supervisor",
            target,
            gh_available=True,
            runner=fake_runner,
        )
    )

    assert success is True
    assert len(attempts) == EXPECTED_ATTEMPTS_COUNT
    assert attempts[0][0] == "gh"
    assert attempts[1][0] == "git"
    assert attempts[1][3] == "https://github.com/tintinweb/pi-supervisor"


def test_validate_package_dir_accepts_manifest_and_conventional_dirs(
    tmp_path: Path,
) -> None:
    """Verify package health checks accept manifest and conventional extension dirs."""
    manifest_pkg = tmp_path / "manifest-pkg"
    _write_file(
        manifest_pkg / "package.json",
        f"{json.dumps({'pi': {'extensions': ['./src/index.ts']}})}\n",
    )
    _write_file(manifest_pkg / "src" / "index.ts", "export default {}\n")
    assert package_is_healthy(str(manifest_pkg)) is True

    conventional_pkg = tmp_path / "conventional-pkg"
    _write_file(conventional_pkg / "extensions" / "index.ts", "export default {}\n")
    assert package_is_healthy(str(conventional_pkg)) is True


def test_validate_package_dir_detects_missing_import_packages(
    tmp_path: Path,
) -> None:
    """Verify missing imported dependencies cause package health check to fail."""
    pkg = tmp_path / "import-pkg"
    _write_file(
        pkg / "package.json",
        f"{json.dumps({'pi': {'extensions': ['./index.ts']}})}\n",
    )
    _write_file(
        pkg / "index.ts",
        'import { Text } from "@earendil-works/pi-tui";\nexport default Text;\n',
    )
    assert package_is_healthy(str(pkg)) is False

    _write_file(
        pkg / "node_modules" / "@earendil-works" / "pi-tui" / "package.json",
        "{}\n",
    )
    assert package_is_healthy(str(pkg)) is True


def test_validate_package_dir_rejects_malformed_package_json(
    tmp_path: Path,
) -> None:
    """Verify malformed package.json safely fails health and build script checks."""
    pkg = tmp_path / "bad-pkg"
    _write_file(pkg / "package.json", "{not valid json")

    assert package_is_healthy(str(pkg)) is False
    assert package_has_build_script(str(pkg)) is False


def test_run_sync_bootstraps_packages_and_patches_runtime_settings(
    seeded_home: Path,
) -> None:
    """Verify bootstrap hook builds and registers packages in settings.json."""
    sync_env = _make_sync_env(seeded_home)
    _write_file(
        seeded_home / ".config" / "agents" / "HARNESS.md",
        "agent-instructions",
    )
    _write_file(seeded_home / ".pi" / "agent" / "settings.json", "{}\n")

    repos = seeded_home / "repos"
    source_repo = repos / "source-pkg"
    _write_file(
        source_repo / "package.json",
        '{\n  "pi": {\n    "extensions": ["./src/index.ts"]\n  }\n}\n',
    )
    _write_file(source_repo / "src" / "index.ts", "export default {}\n")
    _init_git_repo(source_repo)

    build_repo = repos / "build-pkg"
    _write_file(
        build_repo / "package.json",
        '{\n  "scripts": {\n    "build": "mkdir -p dist && '
        "printf 'export default {}\\n' > dist/index.js\"\n  },\n"
        '  "pi": {\n    "extensions": ["./dist/index.js"]\n  }\n}\n',
    )
    _init_git_repo(build_repo)

    _write_file(
        seeded_home
        / ".config"
        / "agents"
        / "harnesses"
        / "pi"
        / "agent"
        / "packages.json",
        f"{json.dumps({'packages': [str(source_repo), str(build_repo)]}, indent=2)}\n",
    )

    success = asyncio.run(run_sync(sync_env))
    assert success is True
    settings = (seeded_home / ".pi" / "agent" / "settings.json").read_text(
        encoding="utf-8"
    )
    assert "source-pkg" in settings
    assert "build-pkg" in settings
    assert (seeded_home / ".local" / "share" / "agents" / "pi-packages").exists()


def test_managed_state_helpers_match_safe_entry_rules(home: Path) -> None:
    """Verify safe entry filter rejects directory traversals and absolute paths."""
    sync_env = _make_sync_env(home)
    harness = sync_env.harness("codex")
    assert harness is not None

    state_file = home / ".local" / "share" / "agents" / "sync-managed" / "codex.json"
    _write_file(
        state_file,
        '[\n  "good.txt",\n  "..",\n  "/tmp/escape",\n  "nested/path",\n  '
        '"../outside",\n  "good.txt"\n]',
    )

    names = load_recorded_entry_names(str(state_file))
    assert names == ["good.txt"]

    plan = plan_managed_entries(sync_env)
    assert len(plan.harnesses) > 0


def test_managed_state_write_persists_expected_json(tmp_path: Path) -> None:
    """Verify write_recorded_entry_names persists formatted JSON array."""
    path = tmp_path / "state" / "codex.json"
    write_recorded_entry_names(str(path), ["alpha", "beta"])
    assert path.read_text(encoding="utf-8") == '[\n  "alpha",\n  "beta"\n]\n'


def test_managed_state_identical_json_skips_replacement(tmp_path: Path) -> None:
    """Verify writing identical state json skips filesystem mutation."""
    path = tmp_path / "state" / "codex.json"
    expected = '[\n  "alpha",\n  "beta"\n]\n'

    write_recorded_entry_names(str(path), ["alpha", "beta"])
    before = path.lstat()
    write_recorded_entry_names(str(path), ["alpha", "beta"])
    after = path.lstat()

    assert path.read_text(encoding="utf-8") == expected
    assert after.st_ino == before.st_ino
    assert after.st_mtime_ns == before.st_mtime_ns


def test_managed_state_replaces_identical_symlink(tmp_path: Path) -> None:
    """Verify symlink state file is replaced with regular file."""
    path = tmp_path / "state" / "codex.json"
    target = tmp_path / "target.json"
    expected = '[\n  "alpha",\n  "beta"\n]\n'

    _write_file(target, expected)
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)

    write_recorded_entry_names(str(path), ["alpha", "beta"])

    assert not path.is_symlink()
    assert path.read_text(encoding="utf-8") == expected
    assert target.read_text(encoding="utf-8") == expected


def test_managed_state_malformed_json_is_recoverable(home: Path) -> None:
    """Verify corrupt managed state file falls back to empty entry list."""
    sync_env = _make_sync_env(home)
    state_path = home / ".local" / "share" / "agents" / "sync-managed" / "codex.json"
    _write_file(state_path, "{not valid json")

    recovered = load_recorded_entry_names(str(state_path))
    assert recovered == []

    plan = plan_managed_entries(sync_env)
    assert len(plan.harnesses) > 0


def test_run_sync_prunes_older_complete_releases(
    seeded_home: Path,
) -> None:
    """Verify older complete releases are pruned while unrecognized dirs remain."""
    sync_env = _make_sync_env(seeded_home)
    releases_root = seeded_home / ".local" / "share" / "agents" / "sync-releases"

    entries = [e.name for e in releases_root.iterdir() if not e.name.startswith(".")]
    assert len(entries) == 1
    current_release_id = entries[0]

    old_complete_release_id = "0" * 64
    old_complete_dir = releases_root / old_complete_release_id
    (old_complete_dir / "src" / "sync").mkdir(parents=True, exist_ok=True)
    (old_complete_dir / "src" / "sync" / "cli.py").write_text(
        "print('old')\n", encoding="utf-8"
    )
    (old_complete_dir / ".release-complete").touch()

    unrecognized_dir = releases_root / "unrecognized-custom-dir"
    unrecognized_dir.mkdir(parents=True, exist_ok=True)
    (unrecognized_dir / "test.txt").write_text("data", encoding="utf-8")

    incomplete_sha_dir = releases_root / ("1" * 64)
    incomplete_sha_dir.mkdir(parents=True, exist_ok=True)
    (incomplete_sha_dir / "incomplete.txt").write_text("no marker", encoding="utf-8")

    assert asyncio.run(run_sync(sync_env)) is True

    remaining = [e.name for e in releases_root.iterdir() if not e.name.startswith(".")]
    assert current_release_id in remaining
    assert "unrecognized-custom-dir" in remaining
    assert ("1" * 64) in remaining
    assert old_complete_release_id not in remaining


def test_run_sync_preserves_previous_releases_if_wrapper_reconciliation_fails(
    seeded_home: Path,
) -> None:
    """Verify previous releases are preserved if wrapper step fails."""
    sync_env = _make_sync_env(seeded_home)
    releases_root = seeded_home / ".local" / "share" / "agents" / "sync-releases"

    entries = [e.name for e in releases_root.iterdir() if not e.name.startswith(".")]
    assert len(entries) == 1
    current_release_id = entries[0]

    old_complete_release_id = "0" * 64
    old_complete_dir = releases_root / old_complete_release_id
    (old_complete_dir / "src" / "sync").mkdir(parents=True, exist_ok=True)
    (old_complete_dir / "src" / "sync" / "cli.py").write_text(
        "print('old')\n", encoding="utf-8"
    )
    (old_complete_dir / ".release-complete").touch()

    local_bin = seeded_home / ".local" / "bin"
    if local_bin.exists():
        if local_bin.is_dir():
            shutil.rmtree(local_bin)
        else:
            local_bin.unlink()
    _write_file(local_bin, "blocking-file-not-dir")

    assert asyncio.run(run_sync(sync_env)) is False

    remaining = [e.name for e in releases_root.iterdir() if not e.name.startswith(".")]
    assert old_complete_release_id in remaining
    assert current_release_id in remaining
