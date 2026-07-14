from __future__ import annotations

import sys

import cli
import make_blueprint
import pytest


def test_dispatcher_preserves_argv_and_propagates_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    original_argv = sys.argv[:]
    observed: dict[str, object] = {}

    def fake_run_path(path: str, run_name: str) -> None:
        observed["path"] = path
        observed["run_name"] = run_name
        observed["argv"] = sys.argv[:]
        raise SystemExit(7)

    monkeypatch.setattr(cli.runpy, "run_path", fake_run_path)
    assert cli.main(["search", "--flag"]) == 7
    assert observed == {
        "path": str(cli.COMMANDS["search"]),
        "run_name": "__main__",
        "argv": [str(cli.COMMANDS["search"]), "--flag"],
    }
    assert sys.argv == original_argv


def test_dispatcher_maps_string_exit_to_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_with_message(path: str, run_name: str) -> None:
        del path, run_name
        raise SystemExit("bad")

    monkeypatch.setattr(cli.runpy, "run_path", fail_with_message)
    assert cli.main(["search"]) == 1
    assert capsys.readouterr().err == "bad\n"


def test_dispatcher_help_and_blueprint_contract(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--help"]) == 0
    assert "uv run --script" in capsys.readouterr().out

    args: make_blueprint.BlueprintArgs = {
        "goal": "Capture note",
        "devices": "iPhone, Mac",
        "trigger": "Share Sheet",
        "inputs": "text",
        "outputs": "note",
        "automation_type": "manual",
        "constraint": ["offline"],
        "failure_mode": ["permission denied"],
    }
    blueprint = make_blueprint.build_blueprint(args)
    assert blueprint["target_devices"] == ["iPhone", "Mac"]
    assert blueprint["action_graph"][0] == "Receive Input from Share Sheet"
    rendered = make_blueprint.render_markdown(blueprint)
    assert "## Validation Matrix" in rendered
    assert "permission denied" in rendered


def test_blueprint_variants_cover_trigger_and_empty_contracts() -> None:
    siri: make_blueprint.BlueprintArgs = {
        "goal": "x",
        "devices": "",
        "trigger": "Siri",
        "inputs": "",
        "outputs": "",
        "automation_type": "manual",
        "constraint": None,
        "failure_mode": None,
    }
    home: make_blueprint.BlueprintArgs = {
        "goal": "x",
        "devices": "",
        "trigger": "Timer",
        "inputs": "",
        "outputs": "",
        "automation_type": "home",
        "constraint": None,
        "failure_mode": None,
    }
    assert make_blueprint.build_blueprint(siri)["action_graph"][0] == "Capture/resolve spoken parameters"
    assert make_blueprint.build_blueprint(home)["action_graph"][0] == "Evaluate automation trigger payload"
