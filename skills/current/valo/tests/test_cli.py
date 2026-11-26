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
    def registrable_domain(self, url: str) -> str: ...
    def load_env_fallback(self) -> None: ...

    __file__: str


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
        "VALO_FIXTURE_DIR": str(fixture_dir),
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


def test_failure_increments_consecutive_failures(
    fixture_dir: Path, tmp_path: Path
) -> None:
    env = fixture_env(fixture_dir, tmp_path)
    (fixture_dir / "agents.md").unlink()
    for _ in range(2):
        proc = run_cli("agents", env=env)
        assert proc.returncode == 1
    proc = run_cli("sources", env=env)
    raw = emit_json(proc)
    sources = raw["sources"]
    assert _is_object_list(sources)
    agents_entry = next(
        entry for entry in sources if _is_mapping(entry) and entry["key"] == "agents"
    )
    assert _is_mapping(agents_entry)
    health = agents_entry["health"]
    assert _is_mapping(health)
    assert health["consecutive_failures"] == 2


def test_corrupt_state_is_fresh_start(fixture_dir: Path, tmp_path: Path) -> None:
    state_dir = tmp_path / "state" / "valo"
    state_dir.mkdir(parents=True)
    _ = (state_dir / "state.json").write_text("not json at all", encoding="utf-8")
    proc = run_cli("agents", env=fixture_env(fixture_dir, tmp_path))
    assert proc.returncode == 0, proc.stdout
    raw = emit_json(proc)
    assert raw["ok"] is True
    rewritten = _json_loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert _is_mapping(rewritten)
    sources = rewritten["sources"]
    assert _is_mapping(sources)
    agents_state = sources["agents"]
    assert _is_mapping(agents_state)
    assert agents_state["consecutive_failures"] == 0


def test_doctor_with_fixtures(fixture_dir: Path, tmp_path: Path) -> None:
    proc = run_cli("doctor", env=fixture_env(fixture_dir, tmp_path))
    assert proc.returncode == 0, proc.stdout
    raw = emit_json(proc)
    assert raw["ok"] is True
    assert raw["healthy"] is True
    sources = raw["sources"]
    assert _is_object_list(sources)
    assert len(sources) == 3
    keys = sorted(str(entry["key"]) for entry in sources if _is_mapping(entry))
    assert keys == ["agents", "maps", "patches"]
    for entry in sources:
        assert _is_mapping(entry)
        assert entry["ok"] is True
        assert entry["fingerprint_status"] == "no-baseline"
        assert entry["consecutive_failures"] == 0
        assert isinstance(entry["latency_ms"], int)


def test_doctor_fingerprint_match_on_second_run(
    fixture_dir: Path, tmp_path: Path
) -> None:
    env = fixture_env(fixture_dir, tmp_path)
    first = run_cli("doctor", env=env)
    assert first.returncode == 0
    second = run_cli("doctor", env=env)
    raw = emit_json(second)
    sources = raw["sources"]
    assert _is_object_list(sources)
    for entry in sources:
        assert _is_mapping(entry)
        assert entry["fingerprint_status"] == "match"


def test_doctor_reports_broken_source(fixture_dir: Path, tmp_path: Path) -> None:
    (fixture_dir / "maps.md").unlink()
    proc = run_cli("doctor", env=fixture_env(fixture_dir, tmp_path))
    assert proc.returncode == 0
    raw = emit_json(proc)
    assert raw["healthy"] is False
    sources = raw["sources"]
    assert _is_object_list(sources)
    maps_entry = next(
        entry for entry in sources if _is_mapping(entry) and entry["key"] == "maps"
    )
    assert _is_mapping(maps_entry)
    assert maps_entry["ok"] is False
    assert isinstance(maps_entry["error"], str)


def write_fake_parallel(tmp_path: Path, payload: Mapping[str, object]) -> Path:
    """Write a fake parallel CLI emitting the given JSON payload."""
    fake = tmp_path / "fake_parallel.py"
    script = (
        "import json, sys\n"
        f"sys.stdout.write(json.dumps({json.dumps(payload)}) + '\\n')\n"
    )
    _ = fake.write_text(script, encoding="utf-8")
    return fake


def write_fixture_library(tmp_path: Path) -> dict[str, str]:
    """Write a controlled library fixture and return its env override."""
    entries = [
        {
            "name": "valking.gg",
            "url": "https://valking.gg",
            "category": "stats-site",
            "status": "adopted",
            "machine_readable": "firecrawl-ok",
            "reason": "fixture",
            "vetted_at": "2026-01-01",
        },
        {
            "name": "metabot.gg",
            "url": "https://metabot.gg",
            "category": "stats-site",
            "status": "avoid",
            "machine_readable": "no",
            "reason": "fixture",
            "vetted_at": "2026-01-01",
        },
        {
            "name": "CHARLATAN",
            "url": "https://www.youtube.com/@charlatan",
            "category": "creator",
            "status": "adopted",
            "machine_readable": "n/a",
            "reason": "fixture",
            "vetted_at": "2026-01-01",
        },
        {
            "name": "Konpeki",
            "url": "https://www.youtube.com/@coachkonpeki",
            "category": "creator",
            "status": "avoid",
            "machine_readable": "n/a",
            "reason": "fixture",
            "vetted_at": "2026-01-01",
        },
    ]
    path = tmp_path / "library-fixture.json"
    _ = path.write_text(
        json.dumps({"version": 1, "entries": entries}), encoding="utf-8"
    )
    return {"VALO_LIBRARY_FILE": str(path)}


def test_discover_filters_vetted_domains(fixture_dir: Path, tmp_path: Path) -> None:
    payload = {
        "results": [
            {"url": "https://valking.gg/en/agents", "title": "registry source"},
            {"url": "https://api.valking.gg/images/x", "title": "same entity"},
            {"url": "https://metabot.gg/stats/agents", "title": "library avoid"},
            {"url": "https://www.youtube.com/@someone", "title": "platform"},
            {"url": "https://op.gg/valorant/statistics", "title": "candidate"},
            {"url": "https://www.vstats.xyz/agent-stats", "title": "candidate"},
        ]
    }
    fake = write_fake_parallel(tmp_path, payload)
    env = fixture_env(fixture_dir, tmp_path)
    env["VALO_PARALLEL_CLI"] = str(fake)
    env.update(write_fixture_library(tmp_path))
    proc = run_cli("discover", env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    raw = emit_json(proc)
    assert raw["ok"] is True
    candidates = raw["new_candidates"]
    assert _is_object_list(candidates)
    assert candidates == ["op.gg", "vstats.xyz"]
    # valking.gg and api.valking.gg collapse to one vetted entity, metabot.gg
    # is a library avoid entry, youtube.com is vetted through creator entries
    assert raw["filtered_known"] == 3
    assert "candidates" not in raw


def test_discover_missing_parallel_is_clean_error(tmp_path: Path) -> None:
    env = {
        "VALO_PARALLEL_CLI": str(tmp_path / "does-not-exist.py"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }
    proc = run_cli("discover", env=env)
    assert proc.returncode == 1
    raw = emit_json(proc)
    assert raw["ok"] is False
    error = raw["error"]
    assert _is_mapping(error)
    assert error["code"] == "MISSING_DEPENDENCY"
    message = error["message"]
    assert isinstance(message, str)
    assert "VALO_PARALLEL_CLI" in message


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


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://valking.gg", "valking.gg"),
        ("https://valking.gg/en/agents", "valking.gg"),
        ("https://www.valking.gg/en/agents", "valking.gg"),
        ("https://api.valking.gg/images/x.webp", "valking.gg"),
        ("valking.gg", "valking.gg"),
        ("www.vstats.xyz", "vstats.xyz"),
        ("https://op.gg/valorant/statistics", "op.gg"),
        ("https://www.youtube.com/@CHARLATAN", "youtube.com"),
    ],
)
def test_registrable_domain(val_cli: _ValCli, url: str, expected: str) -> None:
    assert val_cli.registrable_domain(url) == expected


def test_library_schema_valid() -> None:
    path = CLI.parent.parent / "library.json"
    raw = _json_loads(path.read_text(encoding="utf-8"))
    assert _is_mapping(raw)
    assert raw["version"] == 1
    entries = raw["entries"]
    assert _is_object_list(entries)
    assert len(entries) >= 3
    required = {
        "name",
        "url",
        "category",
        "status",
        "machine_readable",
        "reason",
        "vetted_at",
    }
    categories = {
        "stats-site",
        "creator",
        "aim-tool",
        "vod-tool",
        "pro-meta",
        "community",
    }
    statuses = {"adopted", "avoid", "unclear"}
    machine_readable = {
        "firecrawl-ok",
        "server-rendered",
        "api",
        "no",
        "unknown",
        "n/a",
    }
    for entry in entries:
        assert _is_mapping(entry)
        assert required <= set(entry)
        for key in required:
            assert isinstance(entry[key], str)
            assert entry[key]
        assert entry["category"] in categories
        assert entry["status"] in statuses
        assert entry["machine_readable"] in machine_readable


def test_library_command_all_entries(tmp_path: Path) -> None:
    env = {"XDG_STATE_HOME": str(tmp_path / "state"), **write_fixture_library(tmp_path)}
    proc = run_cli("library", env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    raw = emit_json(proc)
    assert raw["ok"] is True
    entries = raw["entries"]
    assert _is_object_list(entries)
    assert len(entries) == 4
    assert raw["total"] == 4
    counts = raw["counts"]
    assert _is_mapping(counts)
    assert counts["adopted"] == 2
    assert counts["avoid"] == 2
    names = [entry["name"] for entry in entries if _is_mapping(entry)]
    assert "valking.gg" in names
    assert "metabot.gg" in names


def test_library_filter_status(tmp_path: Path) -> None:
    env = {"XDG_STATE_HOME": str(tmp_path), **write_fixture_library(tmp_path)}
    proc = run_cli("library", "--status", "avoid", env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    raw = emit_json(proc)
    entries = raw["entries"]
    assert _is_object_list(entries)
    assert len(entries) == 2
    for entry in entries:
        assert _is_mapping(entry)
        assert entry["status"] == "avoid"
    counts = raw["counts"]
    assert _is_mapping(counts)
    assert counts["adopted"] == 0
    assert counts["avoid"] == 2


def test_library_filter_category(tmp_path: Path) -> None:
    env = {"XDG_STATE_HOME": str(tmp_path), **write_fixture_library(tmp_path)}
    proc = run_cli("library", "--category", "stats-site", env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    raw = emit_json(proc)
    entries = raw["entries"]
    assert _is_object_list(entries)
    assert len(entries) == 2
    names = [entry["name"] for entry in entries if _is_mapping(entry)]
    assert names == ["valking.gg", "metabot.gg"]


def test_library_filter_combined(tmp_path: Path) -> None:
    env = {"XDG_STATE_HOME": str(tmp_path), **write_fixture_library(tmp_path)}
    proc = run_cli(
        "library",
        "--category",
        "stats-site",
        "--status",
        "adopted",
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    raw = emit_json(proc)
    entries = raw["entries"]
    assert _is_object_list(entries)
    assert len(entries) == 1
    first = entries[0]
    assert _is_mapping(first)
    assert first["name"] == "valking.gg"
    filters = raw["filters"]
    assert _is_mapping(filters)
    assert filters["category"] == "stats-site"
    assert filters["status"] == "adopted"


def test_env_file_override_loads_keys(
    val_cli: _ValCli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    _ = env_file.write_text(
        "# comment\nVALO_PROBE_KEY=from-file\nBAD LINE\n", encoding="utf-8"
    )
    monkeypatch.setenv("VALO_ENV_FILE", str(env_file))
    monkeypatch.delenv("VALO_PROBE_KEY", raising=False)
    val_cli.load_env_fallback()
    assert os.environ.get("VALO_PROBE_KEY") == "from-file"


def test_env_file_never_overrides_real_env(
    val_cli: _ValCli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    _ = env_file.write_text("VALO_PROBE_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("VALO_ENV_FILE", str(env_file))
    monkeypatch.setenv("VALO_PROBE_KEY", "from-env")
    val_cli.load_env_fallback()
    assert os.environ.get("VALO_PROBE_KEY") == "from-env"


def test_env_fallback_missing_file_is_noop(
    val_cli: _ValCli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VALO_ENV_FILE", str(tmp_path / "absent.env"))
    monkeypatch.delenv("VALO_PROBE_KEY", raising=False)
    val_cli.load_env_fallback()
    assert os.environ.get("VALO_PROBE_KEY") is None


def test_env_fallback_walks_upward(
    val_cli: _ValCli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "proj"
    nested = root / "skills" / "current" / "valo" / "scripts"
    nested.mkdir(parents=True)
    _ = (root / ".env").write_text("VALO_PROBE_KEY=upward\n", encoding="utf-8")
    monkeypatch.delenv("VALO_ENV_FILE", raising=False)
    monkeypatch.delenv("VALO_PROBE_KEY", raising=False)
    monkeypatch.setattr(val_cli, "__file__", str(nested / "cli.py"))
    val_cli.load_env_fallback()
    assert os.environ.get("VALO_PROBE_KEY") == "upward"
