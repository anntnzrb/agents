"""Opt-in live transport smoke test; offline CI skips this module."""
# ruff: noqa: CPY001, INP001, S101, S603, PLR2004

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import _path  # noqa: F401
import pytest


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_SMOKE") != "1",
    reason="set RUN_LIVE_SMOKE=1 to run the dedicated network smoke test",
)
def test_known_version_live_fetch_is_metrics_only(tmp_path: Path) -> None:
    """Fetch one explicit release into temporary paths without count assertions."""
    skill_dir = Path(__file__).parents[1]
    script = skill_dir / "scripts" / "cli.py"
    command = [
        sys.executable,
        str(script),
        "fetch",
        "--version",
        "v1.1",
        "--cache-dir",
        str(tmp_path / "cache"),
        "--output-dir",
        str(tmp_path / "output"),
    ]
    result = subprocess.run(
        command,
        cwd=skill_dir,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "DEEPSWE_DEFAULT_VERSION": "v1.1"},
    )
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) == 1
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    assert envelope["schema_version"] == 1
    data = envelope["data"]
    assert data["scope"]["benchmark"] == "DeepSWE"
    assert data["scope"]["benchmark_version"] == "v1.1"
    assert data["scope"]["value_status"] == "published"
    provenance = data["provenance"]
    assert provenance["url"].endswith("/v1.1/leaderboard-live.json")
    assert provenance["fetched_at"]
    artifact = data["artifacts"]["leaderboard-live.json"]
    assert artifact["benchmark_version"] == "v1.1"
    assert len(artifact["sha256"]) == 64
    assert artifact["length"] > 0
    encoded = json.dumps(envelope).lower()
    assert "task-body" not in encoded
    assert "exercise-body" not in encoded
    assert "trajectory-body" not in encoded
