"""Explicitly gated live smoke for rotated process credentials only."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from artificial_analysis.contracts import as_dict, parse_json
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
    payload = as_dict(parse_json(lines[0]))
    assert payload
    return payload


def test_live_fetch_and_stats_smoke_are_shape_only(tmp_path: Path) -> None:
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
    data = as_dict(fetch["data"])
    assert data
    freshness = as_dict(data["freshness"])
    assert freshness["mode"] in {"fresh", "cache-revalidated"}
    assert freshness["stale"] is False

    stats = _run_cli(["stats", "--snapshot", str(snapshot)], env=env)
    assert stats["ok"] is True
    stats_data = as_dict(stats["data"])
    assert stats_data
    counts = as_dict(stats_data["counts"])
    assert counts

    sources = as_dict(data["sources"])
    evidence: dict[str, object] = {
        "fetch": {
            "freshness": data["freshness"],
            "sources": {
                name: {
                    "url": redact_query(str(as_dict(source).get("url", ""))),
                    "status_code": as_dict(source).get("status_code"),
                    "etag_present": bool(as_dict(source).get("etag_received")),
                    "last_modified_present": bool(
                        as_dict(source).get("last_modified_received")
                    ),
                    "sha256": as_dict(source).get("sha256"),
                    "byte_length": as_dict(source).get("byte_length"),
                }
                for name, source in sources.items()
            },
        },
        "stats_shape": sorted(counts),
    }
    evidence_path = tmp_path / "live-smoke-evidence.json"
    _ = evidence_path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
    serialized = evidence_path.read_text(encoding="utf-8")
    assert process_key not in serialized
    assert "authorization" not in serialized.casefold()
    assert "cookie" not in serialized.casefold()
