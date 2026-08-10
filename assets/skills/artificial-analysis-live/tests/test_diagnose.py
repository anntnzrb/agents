"""Offline diagnose command tests."""

# ruff: noqa: CPY001, INP001, S101, D103, TC003, PLR2004
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import _path  # noqa: F401
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
    snapshot.write_text(
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
    (cache / "providers-cache.json").write_text(
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
    envelope = json.loads(lines[0])
    assert envelope["ok"] is True
    assert envelope["version"] == "1"
    data = envelope["data"]
    assert data["schema"]["version"] == 2
    assert data["parser"]["version"] == "1"
    assert data["freshness"]["mode"] == "cache-revalidated"
    assert data["snapshot"]["counts"]["models"] == 1
    assert "should-not-appear" not in stdout
    assert "secret-value" not in stdout


def test_diagnose_missing_snapshot_is_structured_error_health(tmp_path: Path) -> None:
    code, stdout, stderr = _capture_main(
        ["diagnose", "--snapshot", str(tmp_path / "missing.json")],
    )

    assert code == 0
    assert stderr == ""
    envelope = json.loads(stdout)
    assert envelope["ok"] is True
    assert envelope["data"]["health"]["status"] == "error"
    assert envelope["data"]["diagnostics"][0]["code"] == "SNAPSHOT_MISSING"


def test_diagnose_rpc_never_fetches_and_returns_one_response(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
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
    cli.run_rpc(stdin=io.StringIO(request + "\n"), stdout=output)
    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    response = json.loads(lines[0])
    assert response["id"] == "diagnose-1"
    assert response["success"] is True
    assert response["data"]["schema"]["version"] == 2
