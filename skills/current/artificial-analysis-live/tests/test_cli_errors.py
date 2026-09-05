"""Staged compact CLI and RPC error protocol tests."""

# ruff: noqa: TC003, S105
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

from artificial_analysis import cli

if TYPE_CHECKING:
    import pytest


def _capture_main(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli.main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def test_json_errors_emit_exactly_one_compact_redacted_object(tmp_path: Path) -> None:
    secret = "super-secret-api-key"
    code, stdout, stderr = _capture_main(
        ["stats", str(tmp_path / secret), "--json-errors"],
    )

    assert code == 2
    assert len(stdout.splitlines()) == 1
    payload = cast("dict[str, object]", json.loads(stdout))
    assert payload["ok"] is False
    assert payload["version"] == "1"
    assert payload["command"] == "stats"
    err = cast("dict[str, object]", payload["error"])
    assert err["code"] == "extraction_error"
    assert secret not in stdout
    assert secret not in stderr


def test_legacy_errors_remain_stderr_only(tmp_path: Path) -> None:
    code, stdout, stderr = _capture_main(
        ["stats", str(tmp_path / "missing.json"), "--legacy-errors"],
    )

    assert code == 2
    assert stdout == ""
    assert stderr.startswith("error: ")


def test_rpc_keeps_one_response_per_line_and_stable_codes() -> None:
    requests = "\n".join(
        [
            "not-json",
            json.dumps({"id": 1, "type": "diff", "args": {}}),
            json.dumps({"id": 2, "type": "unknown-command", "args": {}}),
        ],
    )
    output = io.StringIO()
    _ = cli.run_rpc(stdin=io.StringIO(requests + "\n"), stdout=output)

    responses = [
        cast("dict[str, object]", json.loads(line))
        for line in output.getvalue().splitlines()
    ]
    assert len(responses) == 3
    assert [
        cast("dict[str, object]", response["error"])["code"] for response in responses
    ] == [
        "invalid_json",
        "usage_error",
        "unknown_command",
    ]
    assert all(response["type"] == "response" for response in responses)


def test_rpc_catches_type_and_value_errors_without_secret_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_args: object) -> dict[str, object]:
        raise TypeError("api_key=do-not-leak")

    monkeypatch.setattr(cli, "_stats_payload", fail)
    output = io.StringIO()
    _ = cli.run_rpc(
        stdin=io.StringIO(json.dumps({"id": "x", "type": "stats", "args": {}}) + "\n"),
        stdout=output,
    )
    response = cast("dict[str, object]", json.loads(output.getvalue()))
    err = cast("dict[str, object]", response["error"])
    assert err["code"] == "invalid_args"
    assert "do-not-leak" not in output.getvalue()


def test_rpc_serialization_failures_keep_one_response_and_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _bad_payload(_args: object) -> dict[str, object]:
        return {"bad": float("inf")}

    monkeypatch.setattr(cli, "_stats_payload", _bad_payload)
    output = io.StringIO()
    _ = cli.run_rpc(
        stdin=io.StringIO(
            json.dumps({"id": "serialization-1", "type": "stats", "args": {}}) + "\n"
        ),
        stdout=output,
    )
    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    response = cast("dict[str, object]", json.loads(lines[0]))
    assert response["id"] == "serialization-1"
    err = cast("dict[str, object]", response["error"])
    assert err["code"] == "internal_error"
    assert "inf" not in lines[0]
