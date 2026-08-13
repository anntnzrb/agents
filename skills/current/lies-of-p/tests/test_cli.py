"""Contract tests for the Lies of P companion CLI."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

CLI_VERSION = "1.12.0.0 + Overture"
CLI_RC_INVALID_ARGS = 2
BASE_TROPHY_COUNT = 43
DLC_TROPHY_COUNT = 11
RIGHT_SINGLE_QUOTE = "\N{RIGHT SINGLE QUOTATION MARK}"
DISPLAYED_AR_SPLIT = 130
ADJUSTED_HIT_CRIT = 135
EXPECTED_HIT_CRIT = 175.5
COMMUNITY_TOP_LEVEL_COUNT = 6


def expect(condition: object, message: object = "") -> None:
    """Raise AssertionError without triggering Ruff's S101 rule."""
    if not condition:
        raise AssertionError(message)


CLI = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"
REPO_ROOT = Path(__file__).resolve().parents[4]


def run_cli(
    *args: str,
    cwd: Path | str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the CLI as a subprocess, preserving its real process contract."""
    # The executable and arguments are fixed by this test's subprocess contract.
    return subprocess.run(  # noqa: S603
        [sys.executable, str(CLI), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def test_audit_and_fresh_work_from_any_cwd(tmp_path: Path) -> None:
    """Resources resolve relative to the script, not the caller's directory."""
    for cwd in (REPO_ROOT, tmp_path):
        audit = run_cli("audit", cwd=cwd)
        expect(audit.returncode == 0, audit.stderr)
        expect('"ok": true' in audit.stdout)

        fresh = run_cli("fresh", "--json", cwd=cwd)
        payload = json.loads(fresh.stdout)
        expect(payload["version"] == "1.12.0.0 + Overture")
        expect(payload["difficulty"].startswith("Legendary Stalker"))
        expect(payload["build"]["early_weapon"].startswith("Path of the Bastard"))
        expect("optional_pivot" in payload["build"])


def test_invalid_arguments_are_rc2() -> None:
    """Required chapter arguments remain enforced by argparse."""
    result = run_cli("route")
    expect(result.returncode == CLI_RC_INVALID_ARGS)
    expect("--chapter" in result.stderr)


@pytest.mark.parametrize(
    "command",
    ["fresh", "weaknesses", "bosses", "audit", "sources"],
)
def test_help_exposes_commands(command: str) -> None:
    """The top-level help lists every representative command."""
    result = run_cli("--help")
    expect(result.returncode == 0)
    expect(command in result.stdout)


def test_routes_cover_base_dlc_counts_and_endings() -> None:
    """Route/checklist commands expose concrete progression and branch data."""
    for chapter, marker in (
        (1, "Parade Master"),
        (3, "Venigni"),
        (6, "Romeo"),
        (10, "Relic of Trismegistus"),
        (11, "Nameless Puppet"),
    ):
        result = run_cli("route", "--chapter", str(chapter), "--spoilers", "--json")
        expect(result.returncode == 0, result.stderr)
        payload = json.loads(result.stdout)
        expect(
            payload
            and any(marker.casefold() in json.dumps(row).casefold() for row in payload),
        )

    for chapter in (1, 2):
        result = run_cli("checklist", "--chapter", str(chapter), "--dlc", "--json")
        expect(result.returncode == 0, result.stderr)
        payload = json.loads(result.stdout)
        expect(payload and payload[0]["checklist"])
        checklist_text = json.dumps(payload)
        if chapter == 1:
            expect("Star's Chrysalis" in checklist_text)
            expect("Path of Pilgrim" in checklist_text)
            expect("Point of No Return" not in checklist_text)
        else:
            expect("Rose Garden Point of No Return" in checklist_text)
    trophies = json.loads(run_cli("trophies", "--json").stdout)
    dlc_trophies = json.loads(run_cli("trophies", "--dlc", "--json").stdout)
    expect(len(trophies) == BASE_TROPHY_COUNT)
    expect(len(dlc_trophies) == DLC_TROPHY_COUNT)

    endings = json.loads(
        run_cli("route", "--chapter", "11", "--spoilers", "--json").stdout,
    )
    ending_text = json.dumps(endings).casefold()
    expect("nameless puppet" in ending_text)
    expect("sophia/gepetto" in ending_text)

    ending_trophies = json.loads(run_cli("trophies", "--spoilers", "--json").stdout)

    expect(ending_trophies and any("requirements" in row for row in ending_trophies))


def test_farm_query_filters_records() -> None:
    """Farm queries return only records matching the requested location."""
    result = run_cli("farm", "Krat", "--json")
    expect(result.returncode == 0, result.stderr)
    payload = json.loads(result.stdout)
    expect(payload)
    expect(all("krat" in json.dumps(row).casefold() for row in payload))
    expect(len(payload) < len(json.loads(run_cli("farm", "--json").stdout)))


def test_bosses_hide_dlc_by_default_and_allow_explicit_spoilers() -> None:
    """DLC bosses stay hidden unless the opt-in flag is present."""
    default = run_cli("bosses", "--json")
    expect(default.returncode == 0, default.stderr)
    default_payload = json.loads(default.stdout)
    expect(
        not any(
            name.casefold() in json.dumps(default_payload).casefold()
            for name in (
                "Tyrannical Predator",
                "Markiona",
                "Veronique",
                "Two-faced Overseer",
                "Premetamorphic Green Hunter",
                "Anguished Guardian",
                "Lumacchio",
                "Arlecchino",
            )
        ),
    )

    hidden = run_cli("bosses", "Markiona", "--json")
    expect(hidden.returncode == 0, hidden.stderr)
    hidden_payload = json.loads(hidden.stdout)
    expect("Markiona" not in json.dumps(hidden_payload))
    expect("future DLC" in json.dumps(hidden_payload))

    shown = run_cli("bosses", "Markiona", "--spoilers", "--json")
    expect(shown.returncode == 0, shown.stderr)
    expect(any(row["name"] == "Markiona" for row in json.loads(shown.stdout)))

    all_shown = run_cli("bosses", "--spoilers", "--json")
    expect(all_shown.returncode == 0, all_shown.stderr)
    expect(
        {row["name"] for row in json.loads(all_shown.stdout) if row.get("dlc")}
        == {
            "Tyrannical Predator",
            "Markiona",
            "Veronique",
            "Two-faced Overseer",
            "Premetamorphic Green Hunter",
            "Anguished Guardian",
            "Lumacchio",
            "Arlecchino",
        },
    )


def test_bosses_preserve_base_exact_name_query() -> None:
    """Named base-game queries continue to return their concise guidance."""
    result = run_cli("bosses", "Nameless Puppet", "--json")
    expect(result.returncode == 0, result.stderr)
    expect(
        json.loads(result.stdout)
        == [
            {
                "name": "Nameless Puppet",
                "guidance": "Base-game boss; use guard, stagger, and fatal attacks.",
            },
        ],
    )


def test_trophy_queries_preserve_exact_titles_and_actionable_requirements() -> None:
    """Trophy searches return exact source titles and useful requirements."""
    first = run_cli("trophies", "the first puppet", "--json")
    expect(first.returncode == 0, first.stderr)
    first_rows = json.loads(first.stdout)
    expect(len(first_rows) == 1)
    expect(first_rows[0]["name"] == "The First Puppet")
    expect("Nameless Puppet" in first_rows[0]["requirements"])

    melody = run_cli("trophies", "GOLDEN MELODY", "--json")
    expect(melody.returncode == 0, melody.stderr)
    melody_rows = json.loads(melody.stdout)
    expect(len(melody_rows) == 1)
    expect(melody_rows[0]["name"] == "Golden Melody")
    melody_requirements = melody_rows[0]["requirements"]
    expect("every base-game record" in melody_requirements)
    expect("NG+" in melody_requirements)

    rise = run_cli("trophies", "RISE OF P", "--json")
    expect(rise.returncode == 0, rise.stderr)
    rise_rows = json.loads(rise.stdout)
    expect(len(rise_rows) == 1)
    rise_requirements = rise_rows[0]["requirements"]
    for term in ("Humanity", "Sophia", "refuse Geppetto"):
        expect(term in rise_requirements)


def test_trophy_query_is_case_insensitive_with_exact_unicode_punctuation() -> None:
    """Unicode punctuation in source titles remains queryable without normalization."""
    result = run_cli("trophies", f"STARGAZER{RIGHT_SINGLE_QUOTE}S GUIDE", "--json")
    expect(result.returncode == 0, result.stderr)
    payload = json.loads(result.stdout)
    expect(len(payload) == 1)
    expect(payload[0]["name"] == f"Stargazer{RIGHT_SINGLE_QUOTE}s Guide")


def test_compare_ranks_displayed_inputs_without_inventing_hidden_ar() -> None:
    """The default ranking uses only retained displayed attack values."""
    result = run_cli(
        "compare",
        "--candidate",
        "Physical,120,0,0,10",
        "--candidate",
        "Split,80,50,0,8",
        "--json",
    )
    expect(result.returncode == 0, result.stderr)
    payload = json.loads(result.stdout)
    expect(payload["candidates"][0]["name"] == "Split")
    expect(payload["candidates"][0]["displayed_ar"] == DISPLAYED_AR_SPLIT)
    expect(payload["candidates"][0]["expected_hit"] is None)
    expect("hidden scaling/saturation" in payload["excluded"])


def test_compare_applies_retention_motion_and_optional_critical_expectation() -> None:
    """User-supplied modifiers have explicit, reproducible arithmetic."""
    result = run_cli(
        "compare",
        "--candidate",
        "Crit,100,20,30,12",
        "--candidate",
        "Raw,125,0,0,11",
        "--physical-retained",
        "0.8",
        "--elemental-retained",
        "0.5",
        "--motion",
        "1.5",
        "--critical-multiplier",
        "2",
        "--json",
    )
    expect(result.returncode == 0, result.stderr)
    payload = json.loads(result.stdout)
    crit = next(row for row in payload["candidates"] if row["name"] == "Crit")
    expect(crit["adjusted_hit"] == ADJUSTED_HIT_CRIT)
    expect(crit["expected_hit"] == EXPECTED_HIT_CRIT)
    expect(payload["candidates"][0]["name"] == "Crit")


@pytest.mark.parametrize(
    ("candidate", "extra", "message"),
    [
        ("missing,1,2", (), "candidate must be"),
        ("bad,-1,0,0,1", (), "physical must be nonnegative"),
        ("bad,1,0,101,1", (), "crit_percent must be between"),
        ("bad,1,0,nan,1", (), "crit_percent must be between"),
        ("bad,1,0,0,inf", (), "weight must be nonnegative"),
        ("ok,1,0,0,1", ("--physical-retained", "1.1"), "physical_retained"),
        (
            "ok,1,0,100,1",
            ("--critical-multiplier", "0.5"),
            "critical_multiplier must be at least 1",
        ),
    ],
)
def test_compare_rejects_malformed_or_unbounded_inputs(
    candidate: str,
    extra: tuple[str, ...],
    message: str,
) -> None:
    """Invalid calculator inputs fail with rc2 and a specific diagnostic."""
    result = run_cli("compare", "--candidate", candidate, *extra)
    expect(result.returncode == CLI_RC_INVALID_ARGS)
    expect(message in result.stderr)


def test_community_query_returns_consensus_dissent_and_sources() -> None:
    """Equipment sentiment remains visibly qualified and sourced."""
    result = run_cli("community", "Trident of the Covenant", "--json")
    expect(result.returncode == 0, result.stderr)
    payload = json.loads(result.stdout)
    expect(len(payload["weapons"]) == 1)
    trident = payload["weapons"][0]
    expect(trident["name"] == "Trident of the Covenant")
    expect(trident["sentiment"])
    expect(trident["dissent"])
    expect(trident["sources"])


def test_community_hides_spoiler_and_dlc_records_until_opted_in() -> None:
    """Community sentiment obeys the same explicit spoiler boundary."""
    hidden = run_cli("community", "--json")
    expect(hidden.returncode == 0, hidden.stderr)
    hidden_text = json.dumps(json.loads(hidden.stdout))
    for name in ("Nameless Puppet", "Arlecchino", "Tyrannical Predator"):
        expect(name not in hidden_text)

    shown = run_cli(
        "community",
        "Arlecchino",
        "--spoilers",
        "--json",
    )
    expect(shown.returncode == 0, shown.stderr)
    payload = json.loads(shown.stdout)
    expect([row["name"] for row in payload["boss_walls"]] == ["Arlecchino"])


def test_audit_includes_community_resource_contract() -> None:
    """The source audit covers the newly bundled evidence corpus."""
    result = run_cli("audit", "--json")
    expect(result.returncode == 0, result.stderr)
    payload = json.loads(result.stdout)
    expect(payload["ok"] is True)
    expect(payload["counts"]["community.json"] == COMMUNITY_TOP_LEVEL_COUNT)
    expect(payload["missing"]["community.json"] == [])
