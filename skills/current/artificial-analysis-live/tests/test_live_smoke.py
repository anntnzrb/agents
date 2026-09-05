"""Explicitly gated live smoke for rotated process credentials only."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import cast

import pytest

from artificial_analysis.diagnostics import redact_query

SKILL_ROOT = Path(__file__).resolve().parents[1]
CLI = SKILL_ROOT / "scripts" / "cli.py"
RUN_SMOKE = os.environ.get("RUN_LIVE_SMOKE") == "1"
HAS_PROCESS_KEY = bool(os.environ.get("ARTIFICIAL_ANALYSIS_API_KEY"))

pytestmark = pytest.mark.skipif(
    not (RUN_SMOKE and HAS_PROCESS_KEY),
    reason="live smoke requires RUN_LIVE_SMOKE=1 and a process-injected API key",
)


def _run_cli(args: list[str], *, env: dict[str, str]) -> dict[str, object]:
    completed = subprocess.run(
        ["uv", "run", "--script", str(CLI), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    assert completed.returncode == 0
    lines = completed.stdout.splitlines()
    assert len(lines) == 1
    payload = cast("dict[str, object]", json.loads(lines[0]))
    assert isinstance(payload, dict)
    return payload


def test_live_fetch_reader_and_coding_smoke_are_shape_only(tmp_path: Path) -> None:
    process_key = os.environ["ARTIFICIAL_ANALYSIS_API_KEY"]
    env = dict(os.environ)
    env["ARTIFICIAL_ANALYSIS_API_KEY"] = process_key
    _ = env.pop("ARTIFICIAL_ANALYSIS_ENV_FILE", None)
    snapshot = tmp_path / "snapshot.json"
    endpoints = tmp_path / "endpoints.txt"
    source_url = tmp_path / "source-url.txt"
    cache_dir = tmp_path / "cache"
    fetch = _run_cli(
        [
            "fetch",
            "--output-json",
            str(snapshot),
            "--output-endpoints",
            str(endpoints),
            "--output-url",
            str(source_url),
            "--cache-dir",
            str(cache_dir),
            "--min-endpoints",
            "1",
            "--min-providers",
            "1",
        ],
        env=env,
    )
    assert fetch["ok"] is True
    assert fetch["version"] == "1"
    data = cast("dict[str, object]", fetch["data"])
    assert isinstance(data, dict)
    freshness = cast("dict[str, object]", data["freshness"])
    assert freshness["mode"] in {"fresh", "cache-revalidated"}
    assert freshness["stale"] is False

    stats = _run_cli(["stats", "--snapshot", str(snapshot)], env=env)
    assert stats["ok"] is True
    stats_data = cast("dict[str, object]", stats["data"])
    assert isinstance(stats_data, dict)
    counts = cast("dict[str, object]", stats_data["counts"])
    assert isinstance(counts, dict)

    coding = _run_cli(
        ["coding", "--limit", "1", "--output-json", str(tmp_path / "coding.json")],
        env=env,
    )
    assert coding["ok"] is True
    coding_data = cast("dict[str, object]", coding["data"])
    assert isinstance(coding_data, dict)
    rows = cast("list[object]", coding_data["rows"])
    assert isinstance(rows, list)

    sources = cast("dict[str, dict[str, object]]", data["sources"])
    evidence: dict[str, object] = {
        "fetch": {
            "freshness": data["freshness"],
            "sources": {
                name: {
                    "url": redact_query(str(source.get("url", ""))),
                    "status_code": source.get("status_code"),
                    "etag_present": bool(source.get("etag_received")),
                    "last_modified_present": bool(source.get("last_modified_received")),
                    "sha256": source.get("sha256"),
                    "byte_length": source.get("byte_length"),
                }
                for name, source in sources.items()
            },
        },
        "stats_shape": sorted(counts),
        "coding_shape": sorted(coding_data),
    }
    evidence_path = tmp_path / "live-smoke-evidence.json"
    _ = evidence_path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
    serialized = evidence_path.read_text(encoding="utf-8")
    assert process_key not in serialized
    assert "authorization" not in serialized.casefold()
    assert "cookie" not in serialized.casefold()
