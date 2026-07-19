"""Validate the Lies of P evaluation corpus contract."""

import json
import re
from pathlib import Path

EXPECTED_CASE_COUNT = 96
MIN_EXPECTATIONS = 3
MAX_EXPECTATIONS = 5


def expect(condition: object, message: object = "") -> None:
    """Raise AssertionError without triggering Ruff's S101 rule."""
    if not condition:
        raise AssertionError(message)


ROOT = Path(__file__).parents[1]
EVALS = ROOT / "evals" / "evals.json"
PLATINUM = ROOT / "resources" / "platinum.json"


def load() -> list[dict[str, object]]:
    """Load and validate the evaluation corpus metadata."""
    data = json.loads(EVALS.read_text())
    expect(data["skill_name"] == "lies-of-p")
    return data["evals"]


def test_schema_and_unique_sequential_cases() -> None:
    """Validate schema, sequencing, and uniqueness invariants."""
    rows = load()
    expect(len(rows) == EXPECTED_CASE_COUNT)
    expect([r["id"] for r in rows] == list(range(1, EXPECTED_CASE_COUNT + 1)))
    expect(len({r["prompt"].strip().lower() for r in rows}) == EXPECTED_CASE_COUNT)
    expect(len({r["expected_output"] for r in rows}) == EXPECTED_CASE_COUNT)
    for row in rows:
        expect(set(row) == {"id", "prompt", "expected_output", "expectations"})
        expect(isinstance(row["prompt"], str) and row["prompt"])
        expect(MIN_EXPECTATIONS <= len(row["expectations"]) <= MAX_EXPECTATIONS)
        expect(all(isinstance(x, str) and x for x in row["expectations"]))


def test_marker_families_and_actual_cli_vocabulary() -> None:
    """Ensure prompts cover markers and CLI vocabulary."""
    rows = load()
    prompts = "\n".join(r["prompt"].lower() for r in rows)
    text = prompts + "\n" + "\n".join(" ".join(r["expectations"]).lower() for r in rows)
    for marker in (
        "beginner",
        "build",
        "weakness",
        "boss",
        "specter",
        "consumable",
        "chapter",
        "trophy",
        "ending",
        "overture",
        "dlc",
        "farm",
        "sources",
        "confidence",
        "unsupported",
        "reddit",
        "github",
        "context7",
        "json",
        "error",
    ):
        expect(marker in text, marker)
    for command in (
        "fresh",
        "build",
        "weaknesses",
        "bosses",
        "route",
        "trophies",
        "checklist",
        "farm",
        "sources",
        "audit",
    ):
        expect(f"scripts/cli.py {command}" in text, command)


def test_expected_output_is_one_scenario_and_command_matches_category() -> None:
    """Ensure each expected output names one permitted scenario."""
    rows = load()
    unrelated = ("the ultimate mystery", "the bastards and sweepers", "rose's memory")
    permitted = {
        "build": {"fresh", "build"},
        "boss": {"bosses", "weaknesses"},
        "matchup": {"bosses", "weaknesses"},
        "chapter": {"route", "checklist"},
        "route": {"route", "checklist"},
        "trophy": {"trophies", "checklist"},
        "ending": {"trophies", "checklist"},
        "farm": {"farm"},
        "source": {"sources", "audit"},
        "json": {"audit", "sources"},
        "unsupported": {"audit"},
        "specter": {"checklist"},
        "dlc": {
            "route",
            "checklist",
            "trophies",
            "bosses",
            "weaknesses",
            "sources",
            "audit",
        },
    }
    for row in rows:
        prompt = row["prompt"].lower()
        text = row["expected_output"] + "\n" + "\n".join(row["expectations"])
        found = set(re.findall(r"scripts/cli\.py\s+([a-z]+)", text.lower()))
        expect(len(found) == 1, (row["id"], found))
        categories = [key for key in permitted if key in prompt]
        expect(categories, row["id"])
        allowed = set().union(*(permitted[key] for key in categories))
        expect(found <= allowed, (row["id"], found, allowed))
        if any(c in prompt for c in ("build", "boss", "chapter")):
            expected = text.lower()
            expect(sum(name in expected for name in unrelated) <= 1)

    rows_text = json.dumps(load(), ensure_ascii=False).lower()
    data = json.loads(PLATINUM.read_text())
    for group in ("base", "dlc", "chapters"):
        for record in data[group]:
            name = str(
                record.get("name") or record.get("title") or record.get("chapter"),
            )
            expect(name.lower() in rows_text, name)
    for boss in (
        "Tyrannical Predator",
        "Markiona",
        "Veronique",
        "Two-faced Overseer",
        "Premetamorphic Green Hunter",
        "Anguished Guardian",
        "Lumacchio",
        "Arlecchino",
    ):
        expect(boss.lower() in rows_text)
    for marker in ("1.12.0.0", "legendary stalker", "--spoilers", "--dlc"):
        expect(marker in rows_text)


def test_all_records_and_policy_markers_are_represented() -> None:
    """Ensure every platinum record and policy marker appears."""
    rows_text = json.dumps(load(), ensure_ascii=False).lower()
    data = json.loads(PLATINUM.read_text())
    for group in ("dlc", "chapters"):
        for record in data[group]:
            name = str(
                record.get("name") or record.get("title") or record.get("chapter"),
            )
            expect(name.lower() in rows_text, name)
    for boss in (
        "Markiona",
        "Veronique",
        "Two-faced Overseer",
        "Premetamorphic Green Hunter",
        "Anguished Guardian",
        "Lumacchio",
    ):
        expect(boss.lower() in rows_text)
    for marker in ("1.12.0.0", "legendary stalker", "--spoilers", "--dlc"):
        expect(marker in rows_text)
