"""Recovery export before an idle stop."""

import subprocess
from typing import TYPE_CHECKING

import cli

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def fake_upstream(
    monkeypatch: pytest.MonkeyPatch, export_codes: list[int]
) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    codes = iter(export_codes)

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        code = next(codes) if args[0] == "export" else 0
        return subprocess.CompletedProcess(args, code, "", "EEXIST")

    monkeypatch.setattr(cli, "upstream", run)
    return calls


def test_transient_export_failure_still_exports_and_stops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    calls = fake_upstream(monkeypatch, [1, 0])
    assert cli.export_and_stop(cli.Paths(root=tmp_path), elements=3)
    assert [call[0] for call in calls] == ["export", "export", "stop"]


def test_persistent_export_failure_keeps_the_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    calls = fake_upstream(monkeypatch, [1, 1])
    assert not cli.export_and_stop(cli.Paths(root=tmp_path), elements=3)
    assert "stop" not in [call[0] for call in calls]
