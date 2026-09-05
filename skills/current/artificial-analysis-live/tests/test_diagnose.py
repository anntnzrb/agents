"""Offline diagnose command tests."""

# ruff: noqa: TC003
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import cast

from artificial_analysis import cli


def _capture_main(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def test_diagnose_is_offline_redacted_and_reports_health(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    cache = tmp_path / "cache"
    cache.mkdir()
    _ = snapshot.write_text(
        json.dumps(
            {
                "meta": {
                    "schema_version": 2,
                    "parser": "fixture-parser",
                    "parser_version": "1",
                    "freshness": {"mode": "cache-revalidated", "stale": False},
                    "api_key": "should-not-appear",
                },
                "models": [{"slug": "model-a", "name": "Model A"}],
                "hosts": [],
                "hosts_models": [],
            },
        ),
    )
    _ = (cache / "providers-cache.json").write_text(
        json.dumps(
            {
                "etag": "fixture-etag",
                "source_url": "https://example.test/?api_key=secret-value",
                "sha256": "a" * 64,
            },
        ),
    )

    code, stdout, stderr = _capture_main(
        ["diagnose", "--snapshot", str(snapshot), "--cache-dir", str(cache)],
    )

    assert code == 0
    assert stderr == ""
    lines = stdout.splitlines()
    assert len(lines) == 1
    envelope = cast("dict[str, object]", json.loads(lines[0]))
    assert envelope["ok"] is True
    assert envelope["version"] == "1"
    data = cast("dict[str, object]", envelope["data"])
    assert cast("dict[str, object]", data["schema"])["version"] == 2
    assert cast("dict[str, object]", data["parser"])["version"] == "1"
    assert cast("dict[str, object]", data["freshness"])["mode"] == "cache-revalidated"
    snapshot_meta = cast("dict[str, object]", data["snapshot"])
    assert cast("dict[str, object]", snapshot_meta["counts"])["models"] == 1
    assert "should-not-appear" not in stdout
    assert "secret-value" not in stdout


def test_diagnose_missing_snapshot_is_structured_error_health(tmp_path: Path) -> None:
    code, stdout, stderr = _capture_main(
        ["diagnose", "--snapshot", str(tmp_path / "missing.json")],
    )

    assert code == 0
    assert stderr == ""
    envelope = cast("dict[str, object]", json.loads(stdout))
    assert envelope["ok"] is True
    env_data = cast("dict[str, object]", envelope["data"])
    assert cast("dict[str, object]", env_data["health"])["status"] == "error"
    diag0 = cast("dict[str, object]", cast("list[object]", env_data["diagnostics"])[0])
    assert diag0["code"] == "SNAPSHOT_MISSING"


def test_diagnose_rpc_never_fetches_and_returns_one_response(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    _ = snapshot.write_text(
        json.dumps(
            {
                "meta": {"schema_version": 2},
                "models": [],
                "hosts": [],
                "hosts_models": [],
            }
        )
    )
    request = json.dumps(
        {"id": "diagnose-1", "type": "diagnose", "args": {"snapshot": str(snapshot)}}
    )
    output = io.StringIO()
    _ = cli.run_rpc(stdin=io.StringIO(request + "\n"), stdout=output)
    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    response = cast("dict[str, object]", json.loads(lines[0]))
    assert response["id"] == "diagnose-1"
    assert response["success"] is True
    resp_data = cast("dict[str, object]", response["data"])
    assert cast("dict[str, object]", resp_data["schema"])["version"] == 2
