"""Subprocess tests for scripts/cli.py driven by fixture injection."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypeIs, runtime_checkable

import pytest

if TYPE_CHECKING:
    from types import ModuleType

_json_loads: Callable[[str | bytes | bytearray], object] = json.loads

CLI = Path(__file__).parent.parent / "scripts" / "cli.py"
FIXTURES = Path(__file__).parent / "fixtures"


@runtime_checkable
class _ValCli(Protocol):
    def parse_stat(self, cell: str) -> tuple[float, float]: ...
    def agent_display_name(self, cell: str) -> str: ...


def _is_mapping(val: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(val, Mapping)


def _is_object_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


def _load_cli() -> ModuleType:
    spec = importlib.util.spec_from_file_location("val_cli_under_test", CLI)
    assert spec is not None, f"cannot load {CLI}"
    assert spec.loader is not None, f"cannot load {CLI}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def val_cli() -> _ValCli:
    module = _load_cli()
    if not isinstance(module, _ValCli):
        raise TypeError(f"{module} does not implement _ValCli")
    return module


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    """Copy the captured real-world fixtures into a per-test directory."""
    for source in FIXTURES.iterdir():
        if source.is_file():
            _ = shutil.copy(source, tmp_path / source.name)
    return tmp_path


def run_cli(
    *argv: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the CLI as a subprocess with an overlaid environment."""
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, str(CLI), *argv],
        capture_output=True,
        text=True,
        env=full_env,
        timeout=60,
        check=False,
    )


def fixture_env(fixture_dir: Path, tmp_path: Path) -> dict[str, str]:
    """Environment overlay activating fixture injection and a scratch state."""
    return {
        "VALORANT_META_FIXTURE_DIR": str(fixture_dir),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }


def emit_json(proc: subprocess.CompletedProcess[str]) -> Mapping[str, object]:
    """Decode the single JSON object the CLI prints."""
    raw = _json_loads(proc.stdout)
    assert _is_mapping(raw), proc.stdout
    return raw


def test_help_runs() -> None:
    proc = run_cli("--help")
    assert proc.returncode == 0


def test_agents_parse_count_and_first_row(fixture_dir: Path, tmp_path: Path) -> None:
    proc = run_cli("agents", env=fixture_env(fixture_dir, tmp_path))
    assert proc.returncode == 0, proc.stdout
    raw = emit_json(proc)
    assert raw["ok"] is True
    agents = raw["agents"]
    assert _is_object_list(agents)
    assert len(agents) == 30
    first = agents[0]
    assert _is_mapping(first)
    assert first["name"] == "Killjoy"
    assert first["winrate"] == 52.9
    assert first["tier"] == "S"
    assert first["wr_delta_7d"] == 1.2
    assert first["role"] == "Sentinel"
    assert raw["patch"] == "13.10"


def test_agents_display_name_beats_alt_text(fixture_dir: Path, tmp_path: Path) -> None:
    proc = run_cli("agents", env=fixture_env(fixture_dir, tmp_path))
    raw = emit_json(proc)
    agents = raw["agents"]
    assert _is_object_list(agents)
    names = [agent["name"] for agent in agents if _is_mapping(agent)]
    assert "Killjoy" in names  # display name, not the KillJoy alt text
    assert "KillJoy" not in names
    assert "KAY/O" in names  # slash survives despite the kay/o image path


def test_patch_version_and_changes(fixture_dir: Path, tmp_path: Path) -> None:
    proc = run_cli("patch", env=fixture_env(fixture_dir, tmp_path))
    assert proc.returncode == 0, proc.stdout
    raw = emit_json(proc)
    assert raw["version"] == "13.10"
    assert raw["release_date"] == "Nov 10, 2026"
    changes = raw["changes"]
    assert _is_object_list(changes)
    assert len(changes) == 7
    first = changes[0]
    assert _is_mapping(first)
    assert first["tag"] == "NEUTRAL"
    assert first["target"] == "Cypher"
    detail = raw["detail"]
    assert _is_mapping(detail)
    assert detail["official_url"] == (
        "https://playvalorant.com/en-us/news/game-updates/valorant-patch-notes-13-10"
    )
    counts = detail["counts"]
    assert _is_mapping(counts)
    assert counts["BUFF"] == 3
    assert counts["NEW"] == 2
    movers = detail["movers"]
    assert _is_object_list(movers)
    assert len(movers) == 6
    top = movers[0]
    assert _is_mapping(top)
    assert top["name"] == "Deadlock"
    assert top["direction"] == "climbing"


def test_maps_parse(fixture_dir: Path, tmp_path: Path) -> None:
    proc = run_cli("maps", env=fixture_env(fixture_dir, tmp_path))
    assert proc.returncode == 0, proc.stdout
    raw = emit_json(proc)
    maps = raw["maps"]
    assert _is_object_list(maps)
    assert len(maps) == 1
    first = maps[0]
    assert _is_mapping(first)
    assert first["name"] == "Bind"
    assert first["attack"] == 48.17
    assert first["defense"] == 51.83
    assert isinstance(raw["note"], str)


def test_snapshot_derivation_shape(fixture_dir: Path, tmp_path: Path) -> None:
    proc = run_cli("snapshot", env=fixture_env(fixture_dir, tmp_path))
    assert proc.returncode == 0, proc.stdout
    raw = emit_json(proc)
    assert raw["ok"] is True
    abuse = raw["abuse"]
    assert _is_mapping(abuse)
    meta = abuse["meta"]
    niche = abuse["niche"]
    assert _is_object_list(meta)
    assert _is_object_list(niche)
    meta_names = [row["name"] for row in meta if _is_mapping(row)]
    niche_names = [row["name"] for row in niche if _is_mapping(row)]
    assert "Clove" in meta_names
    assert "Phoenix" in meta_names
    assert "Killjoy" in niche_names
    avoid = raw["avoid"]
    assert _is_object_list(avoid)
    assert len(avoid) == 3
    avoid_names = [row["name"] for row in avoid if _is_mapping(row)]
    assert avoid_names == ["KAY/O", "Harbor", "Omen"]
    movers = raw["movers"]
    assert _is_mapping(movers)
    risers = movers["risers"]
    fallers = movers["fallers"]
    assert _is_object_list(risers)
    assert _is_object_list(fallers)
    assert len(risers) == 3
    assert len(fallers) == 3
    first_riser = risers[0]
    assert _is_mapping(first_riser)
    assert first_riser["name"] == "Harbor"
    thresholds = raw["thresholds"]
    assert _is_mapping(thresholds)
    assert thresholds["abuse_wr_min"] == 51.0
    patch_context = raw["patch_context"]
    assert _is_mapping(patch_context)
    assert patch_context["version"] == "13.10"


def test_missing_fixture_is_clean_json_error(fixture_dir: Path, tmp_path: Path) -> None:
    (fixture_dir / "agents.md").unlink()
    proc = run_cli("agents", env=fixture_env(fixture_dir, tmp_path))
    assert proc.returncode == 1
    raw = emit_json(proc)
    assert raw["ok"] is False
    error = raw["error"]
    assert _is_mapping(error)
    assert error["code"] == "FIXTURE_MISSING"
    assert proc.stderr == "" or "Traceback" not in proc.stderr


def test_corrupt_fixture_is_parse_error(fixture_dir: Path, tmp_path: Path) -> None:
    _ = (fixture_dir / "agents.md").write_text(
        "# totally unrelated page\n\nno table here\n", encoding="utf-8"
    )
    proc = run_cli("agents", env=fixture_env(fixture_dir, tmp_path))
    assert proc.returncode == 1
    raw = emit_json(proc)
    assert raw["ok"] is False
    error = raw["error"]
    assert _is_mapping(error)
    assert error["code"] == "PARSE_FAILED"

@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("52.9%+1.2", (52.9, 1.2)),
        ("0.7%+/-0.0", (0.7, 0.0)),
        ("52.2%-0.1", (52.2, -0.1)),
        ("11.3%-2.6", (11.3, -2.6)),
        ("8.0%+0.6", (8.0, 0.6)),
    ],
)
def test_parse_stat(val_cli: _ValCli, cell: str, expected: tuple[float, float]) -> None:
    value, delta = val_cli.parse_stat(cell)
    assert value == pytest.approx(expected[0])
    assert delta == pytest.approx(expected[1])


def test_agent_display_name_unit(val_cli: _ValCli) -> None:
    cell = (
        "[![KillJoy](https://api.valking.gg/images/agents/killjoy/display_icon.webp)"
        "\\<br>\\<br>Killjoy](https://valking.gg/en/agents/killjoy)"
    )
    assert val_cli.agent_display_name(cell) == "Killjoy"
    kayo = (
        "[![KAY/O](https://api.valking.gg/images/agents/kay/o/display_icon.webp)"
        "\\<br>\\<br>KAY/O](https://valking.gg/en/agents/kayo)"
    )
    assert val_cli.agent_display_name(kayo) == "KAY/O"
