# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for SyncRuntimeInstall job and release lifecycle management."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
from pathlib import Path

from sync.core.harness import SyncEnv
from sync.core.index import run_sync
from sync.core.jobs import (
    prune_unreferenced_releases,
    remove_legacy_runtime_install,
    run_jobs_with_preserve,
)
from sync.core.plan import SyncRuntimeInstallJob, build_sync_plan

TEST_TIMEOUT_MS = 60_000
EXPECTED_TWO_RELEASES_COUNT = 2


def make_home(tmp_path: Path, *, gateway_host: bool = True) -> str:
    """Create a temporary test home directory with required SSOT layout."""
    home = str(tmp_path)
    tools = Path(home) / ".config" / "agents" / "tools"
    (tools / "cliproxyapi").mkdir(parents=True, exist_ok=True)
    (tools / "mcporter").mkdir(parents=True, exist_ok=True)
    (tools / "summarize").mkdir(parents=True, exist_ok=True)

    hostname = socket.gethostname() if gateway_host else "test-gateway"
    deployment = {
        "server": {"hostname": hostname},
        "listen": {"host": "127.0.0.1", "port": 9443},
        "client": {"baseUrl": "http://127.0.0.1:9443/v1"},
    }
    (tools / "cliproxyapi" / "deployment.json").write_text(
        f"{json.dumps(deployment)}\n", encoding="utf-8"
    )
    (tools / "mcporter" / "mcporter.jsonc").write_text("{}\n", encoding="utf-8")
    (tools / "summarize" / "config.json").write_text("{}\n", encoding="utf-8")

    return home


def seed_source_root(home: str, cli_content: str = 'print("ok")\n') -> str:
    """Seed the sync source directory with src/, pyproject.toml, and uv.lock."""
    repo_sync = Path(__file__).resolve().parent.parent
    source_root = Path(home) / ".config" / "agents" / "sync"
    source_root.mkdir(parents=True, exist_ok=True)

    src_dst = source_root / "src"
    if src_dst.exists():
        shutil.rmtree(src_dst)
    shutil.copytree(repo_sync / "src", src_dst)

    for filename in ("pyproject.toml", "uv.lock", "README.md"):
        src_file = repo_sync / filename
        if src_file.exists():
            shutil.copyfile(
                src_file,
                source_root / filename,
            )

    cli_path = source_root / "src" / "sync" / "cli.py"
    if not cli_path.parent.exists():
        cli_path = source_root / "src" / "cli.py"
    cli_path.write_text(cli_content, encoding="utf-8")

    return str(source_root)


def get_runtime_install_job(
    home: str,
) -> tuple[SyncEnv, SyncRuntimeInstallJob]:
    """Build a sync plan for home and extract the SyncRuntimeInstallJob."""
    sync_env = SyncEnv.from_home(home, TEST_TIMEOUT_MS, platform="linux")
    plan = build_sync_plan(sync_env)
    job = next(
        (j for j in plan.jobs if isinstance(j, SyncRuntimeInstallJob)),
        None,
    )
    assert job is not None
    return sync_env, job


def read_dir_names(root: str) -> list[str]:
    """Return sorted entry names in root excluding hidden entries."""
    root_path = Path(root)
    if not root_path.exists():
        return []
    return sorted(
        entry.name for entry in root_path.iterdir() if not entry.name.startswith(".")
    )


def test_plan_includes_the_job_with_new_runtime_paths(tmp_path: Path) -> None:
    """Test that buildSyncPlan emits a SyncRuntimeInstallJob with correct paths."""
    home = make_home(tmp_path)
    seed_source_root(home)
    sync_env, job = get_runtime_install_job(home)

    assert job.source_root == str(Path(sync_env.ssot_home) / "sync")
    assert job.releases_root == str(Path(sync_env.runtime_home) / "sync-releases")
    assert job.current_link == str(Path(sync_env.runtime_home) / "sync-current")
    assert job.timeout_ms > 0


def test_publishes_current_link_and_installs_dependencies(
    tmp_path: Path,
) -> None:
    """Test that SyncRuntimeInstall creates release and publishes symlink."""
    home = make_home(tmp_path)
    seed_source_root(home)
    _, job = get_runtime_install_job(home)

    ok = run_jobs_with_preserve([job])
    assert ok is True

    current_link = Path(home) / ".local" / "share" / "agents" / "sync-current"
    assert current_link.exists()
    release_dir = current_link.resolve()
    cli_py = release_dir / "src" / "sync" / "cli.py"
    cli_root_py = release_dir / "src" / "cli.py"
    assert cli_py.exists() or cli_root_py.exists()
    marker = release_dir / ".release-complete"
    venv_dir = release_dir / ".venv"
    assert marker.exists() or venv_dir.exists()


def test_fails_and_leaves_current_link_untouched_when_lockfile_is_missing(
    tmp_path: Path,
) -> None:
    """Test that installation fails when uv.lock is absent."""
    home = make_home(tmp_path)
    seed_source_root(home)
    (Path(home) / ".config" / "agents" / "sync" / "uv.lock").unlink()
    _, job = get_runtime_install_job(home)

    ok = run_jobs_with_preserve([job])
    assert ok is False
    assert not Path(job.current_link).exists()


def test_fails_and_removes_stage_on_broken_pyproject_toml(
    tmp_path: Path,
) -> None:
    """Test that installation fails and cleans up stage on broken pyproject.toml."""
    home = make_home(tmp_path)
    seed_source_root(home)
    (Path(home) / ".config" / "agents" / "sync" / "pyproject.toml").write_text(
        "{ broken toml\n", encoding="utf-8"
    )
    _, job = get_runtime_install_job(home)

    ok = run_jobs_with_preserve([job])
    assert ok is False
    assert not Path(job.current_link).exists()

    releases_path = Path(job.releases_root)
    all_entries = (
        [entry.name for entry in releases_path.iterdir()]
        if releases_path.exists()
        else []
    )
    assert not any(name.startswith(".stage-") for name in all_entries)


def test_installs_new_release_and_updates_current_link_without_pruning_previous_release(
    tmp_path: Path,
) -> None:
    """Test updating runtime release creates a second release and preserves first."""
    home = make_home(tmp_path)
    source_root = seed_source_root(home)
    _, job = get_runtime_install_job(home)

    ok = run_jobs_with_preserve([job])
    assert ok is True
    first_releases = read_dir_names(job.releases_root)
    assert len(first_releases) == 1

    source_path = Path(source_root)
    cli_path = source_path / "src" / "sync" / "cli.py"
    if not cli_path.exists():
        cli_path = source_path / "src" / "cli.py"
    cli_path.write_text('print("updated")\n', encoding="utf-8")

    _, job2 = get_runtime_install_job(home)
    ok2 = run_jobs_with_preserve([job2])
    assert ok2 is True
    second_releases = read_dir_names(job2.releases_root)
    assert len(second_releases) == EXPECTED_TWO_RELEASES_COUNT
    assert first_releases[0] in second_releases


def test_runtime_installation_cleans_up_temporary_stage_on_install_failure(
    tmp_path: Path,
) -> None:
    """Test that failed uv sync cleans up the temporary .stage directory."""
    home = make_home(tmp_path)
    source_root = seed_source_root(home)

    with (Path(source_root) / "pyproject.toml").open("a", encoding="utf-8") as f:
        f.write('\n[project.dependencies]\nnonexistent-pkg-xyz = "99.99.99"\n')

    _, job = get_runtime_install_job(home)
    success = run_jobs_with_preserve([job])
    assert success is False

    releases_path = Path(job.releases_root)
    if releases_path.exists():
        entries = [entry.name for entry in releases_path.iterdir()]
        stages = [name for name in entries if name.startswith(".stage-")]
        assert stages == []


def test_prune_unreferenced_releases_cleans_complete_unreferenced_and_stale_stages(
    tmp_path: Path,
) -> None:
    """Test pruning unreferenced complete releases and dead process stages."""
    home = make_home(tmp_path)
    source_root = seed_source_root(home)
    _, job = get_runtime_install_job(home)
    run_jobs_with_preserve([job])

    first_release_name = read_dir_names(job.releases_root)[0]

    source_path = Path(source_root)
    cli_path = source_path / "src" / "sync" / "cli.py"
    if not cli_path.exists():
        cli_path = source_path / "src" / "cli.py"
    cli_path.write_text('print("updated")\n', encoding="utf-8")

    _, job2 = get_runtime_install_job(home)
    run_jobs_with_preserve([job2])

    releases_path = Path(job.releases_root)
    unrecognized_dir = releases_path / "custom-unrecognized-dir"
    unrecognized_dir.mkdir(parents=True, exist_ok=True)
    (unrecognized_dir / "data.txt").write_text("preserve-me", encoding="utf-8")

    stage_dotfile = releases_path / ".stage-test-keep"
    stage_dotfile.mkdir(parents=True, exist_ok=True)
    (stage_dotfile / "tmp.txt").write_text("stage-temp", encoding="utf-8")

    incomplete_sha_dir = releases_path / ("a" * 64)
    incomplete_sha_dir.mkdir(parents=True, exist_ok=True)
    (incomplete_sha_dir / "incomplete.txt").write_text("incomplete", encoding="utf-8")

    dead_pid_stage = releases_path / ".stage-99999999-deadbeef12345678"
    dead_pid_stage.mkdir(parents=True, exist_ok=True)
    (dead_pid_stage / "pyproject.toml").write_text("{}", encoding="utf-8")

    live_pid_stage = releases_path / f".stage-{os.getpid()}-livebeef12345678"
    live_pid_stage.mkdir(parents=True, exist_ok=True)
    (live_pid_stage / "pyproject.toml").write_text("{}", encoding="utf-8")

    prune_unreferenced_releases(job2.releases_root, job2.current_link)

    remaining = [entry.name for entry in Path(job2.releases_root).iterdir()]
    assert ".stage-test-keep" in remaining
    assert "custom-unrecognized-dir" in remaining
    assert "a" * 64 in remaining
    assert f".stage-{os.getpid()}-livebeef12345678" in remaining

    current_release_name = next(
        name
        for name in read_dir_names(job2.releases_root)
        if name not in ("custom-unrecognized-dir", "a" * 64)
    )
    assert current_release_name in remaining
    assert first_release_name not in remaining
    assert ".stage-99999999-deadbeef12345678" not in remaining


def test_remove_legacy_runtime_install_removes_legacy_directory(
    tmp_path: Path,
) -> None:
    """Test that remove_legacy_runtime_install removes legacy mutable sync dir."""
    home = make_home(tmp_path, gateway_host=False)
    runtime_home = str(Path(home) / ".local" / "share" / "agents")
    legacy = Path(runtime_home) / "sync"
    (legacy / "src").mkdir(parents=True, exist_ok=True)
    (legacy / "src" / "cli.py").write_text('print("legacy")\n', encoding="utf-8")

    ok = remove_legacy_runtime_install(runtime_home)
    assert ok is True
    assert not legacy.exists()


def test_run_sync_removes_the_legacy_mutable_runtime_after_current_link_and_wrappers(
    tmp_path: Path,
) -> None:
    """run_sync removes legacy mutable runtime directory e2e."""
    home = make_home(tmp_path, gateway_host=False)
    legacy = Path(home) / ".local" / "share" / "agents" / "sync"
    (legacy / "src").mkdir(parents=True, exist_ok=True)
    (legacy / "src" / "cli.py").write_text('print("legacy")\n', encoding="utf-8")
    seed_source_root(home)

    sync_env = SyncEnv.from_home(home, TEST_TIMEOUT_MS, platform="linux")
    ok = asyncio.run(run_sync(sync_env))
    assert ok is True
    assert not legacy.exists()
    current_link = Path(home) / ".local" / "share" / "agents" / "sync-current"
    assert current_link.exists()


def test_runtime_install_fails_loudly_when_source_subdir_is_unreadable(
    tmp_path: Path,
) -> None:
    """Test that runtime installation fails when source directory is unreadable."""
    home = make_home(tmp_path)
    source_root = seed_source_root(home)
    unreadable_dir = Path(source_root) / "src" / "unreadable"
    unreadable_dir.mkdir(parents=True, exist_ok=True)
    (unreadable_dir / "file.py").write_text("content\n", encoding="utf-8")
    unreadable_dir.chmod(0o000)
    try:
        _, job = get_runtime_install_job(home)
        ok = run_jobs_with_preserve([job])
        assert ok is False
        assert not Path(job.current_link).exists()
    finally:
        unreadable_dir.chmod(0o755)
