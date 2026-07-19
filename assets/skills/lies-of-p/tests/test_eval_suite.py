"""Validate the Lies of P evaluation corpus contract."""

import json
import re
from pathlib import Path
from typing import Never, TypedDict


class EvalRecord(TypedDict):
    """One validated evaluation scenario."""

    id: int
    prompt: str
    expected_output: str
    expectations: list[str]


class EvalDocument(TypedDict):
    """Top-level evaluation corpus structure."""

    skill_name: str
    evals: list[EvalRecord]


EXPECTED_CASE_COUNT = 96
MIN_EXPECTATIONS = 3
MAX_EXPECTATIONS = 5


def expect(condition: object, message: object = "") -> None:
    """Raise AssertionError without triggering Ruff's S101 rule."""
    if not condition:
        raise AssertionError(message)


def fail(message: str) -> Never:
    """Fail a boundary validation with a concise diagnostic."""
    raise AssertionError(message)


ROOT = Path(__file__).parents[1]
EVALS = ROOT / "evals" / "evals.json"
PLATINUM = ROOT / "resources" / "platinum.json"


def _load_platinum_records(group: str) -> list[dict[str, object]]:
    """Load one platinum group after narrowing the decoded JSON shape."""
    decoded: object = json.loads(PLATINUM.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        fail("invalid platinum document")
    records = decoded.get(group)
    if not isinstance(records, list) or not all(
        isinstance(record, dict) for record in records
    ):
        fail("invalid platinum records")
    return records


def load() -> list[EvalRecord]:
    """Load and validate the evaluation corpus metadata."""
    decoded: object = json.loads(EVALS.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict) or decoded.get("skill_name") != "lies-of-p":
        fail("invalid evaluation document")
    raw_evals = decoded.get("evals")
    if not isinstance(raw_evals, list):
        fail("invalid evaluation records")
    records: list[EvalRecord] = []
    for raw in raw_evals:
        expect(isinstance(raw, dict))
        record = {
            "id": raw.get("id"),
            "prompt": raw.get("prompt"),
            "expected_output": raw.get("expected_output"),
            "expectations": raw.get("expectations"),
        }
        id_value = record["id"]
        prompt_value = record["prompt"]
        output_value = record["expected_output"]
        expectations_value = record["expectations"]
        if not (
            isinstance(id_value, int)
            and isinstance(prompt_value, str)
            and isinstance(output_value, str)
            and isinstance(expectations_value, list)
            and all(isinstance(item, str) for item in expectations_value)
        ):
            fail("invalid evaluation record")
        records.append(
            {
                "id": id_value,
                "prompt": prompt_value,
                "expected_output": output_value,
                "expectations": expectations_value,
            },
        )
    return records


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
    unrelated = ("the ultimate mystery", "the bastards and sweepers", "rose's memory")
    rows = load()
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
    for group in ("base", "dlc", "chapters"):
        for record in _load_platinum_records(group):
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
    for group in ("dlc", "chapters"):
        for record in _load_platinum_records(group):
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
