from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import TypedDict, cast


class CalcPayload(TypedDict):
    name: str
    approximate: bool
    requirements_met: bool
    estimated_ar: float
    warning: str


class CompareRow(TypedDict):
    name: str
    approximate: bool


class HiddenGuidePayload(TypedDict):
    row: int
    spoilers: str
    warning: str


class RevealedGuidePayload(TypedDict):
    row: int
    h: list[str]
    t: str


class RevealedGuidePayloadWithOptionalSpoilers(RevealedGuidePayload, total=False):
    spoilers: str


SKILL_DIR = Path(__file__).resolve().parents[1]


def run_cli(
    *arguments: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    return subprocess.run(
        ["uv", "run", "--script", "scripts/cli.py", *arguments],
        cwd=SKILL_DIR,
        env=process_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


class CliSmokeTests(unittest.TestCase):
    def test_fresh_and_calc_json_are_deterministic_contracts(self) -> None:
        fresh = run_cli("fresh")
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        self.assertIn("Dark Souls Remastered", fresh.stdout)
        self.assertIn("Next: softcaps", fresh.stdout)

        calculated = run_cli("calc", "Claymore", "40", "40", "--json")
        self.assertEqual(calculated.returncode, 0, calculated.stderr)
        payload = cast(CalcPayload, json.loads(calculated.stdout))
        self.assertEqual(payload["name"], "Claymore")
        self.assertTrue(payload["approximate"])
        self.assertTrue(payload["requirements_met"])
        self.assertIn("estimated_ar", payload)
        self.assertIn("status screen", payload["warning"])

    def test_compare_json_contains_both_requested_weapons(self) -> None:
        compared = run_cli(
            "compare", "Longsword", "Claymore", "--str", "40", "--dex", "40", "--json"
        )
        self.assertEqual(compared.returncode, 0, compared.stderr)
        rows = cast(list[CompareRow], json.loads(compared.stdout))
        self.assertEqual({row["name"] for row in rows}, {"Longsword", "Claymore"})
        self.assertTrue(all(row["approximate"] for row in rows))

    def test_sources_status_uses_only_the_process_cache_environment(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
        ):
            first_result = run_cli("sources", "status", env={"DS1_CACHE_DIR": first})
            second_result = run_cli("sources", "status", env={"DS1_CACHE_DIR": second})
            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            self.assertIn(f"Cache directory: {first}", first_result.stdout)
            self.assertIn(f"Cache directory: {second}", second_result.stdout)
            self.assertNotIn(f"Cache directory: {second}", first_result.stdout)
            self.assertNotIn(f"Cache directory: {first}", second_result.stdout)
            self.assertEqual(list(Path(first).iterdir()), [])
            self.assertEqual(list(Path(second).iterdir()), [])

    def test_audit_reports_an_integrated_clean_skill(self) -> None:
        result = run_cli("audit")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            "OK: DS1 core, source metadata, guide schema, and catalog checks passed",
            result.stdout,
        )

    def test_guide_get_hides_transformed_text_by_default(self) -> None:
        redacted = run_cli("guide", "get", "1", "--json")
        self.assertEqual(redacted.returncode, 0, redacted.stderr)
        hidden = cast(HiddenGuidePayload, json.loads(redacted.stdout))
        self.assertEqual(hidden["row"], 1)
        self.assertEqual(hidden["spoilers"], "hidden")
        self.assertNotIn("h", hidden)
        self.assertNotIn("t", hidden)
        warning = hidden.get("warning")
        self.assertIsInstance(warning, str)
        self.assertIn("Local guide lookup:", warning)
        self.assertIn("transformed", warning)
        self.assertIn("non-authoritative", warning)
        self.assertIn("not save/parser truth", warning)

        revealed = run_cli("guide", "get", "1", "--json", "--spoilers")
        self.assertEqual(revealed.returncode, 0, revealed.stderr)
        row = cast(
            RevealedGuidePayloadWithOptionalSpoilers, json.loads(revealed.stdout)
        )
        self.assertEqual(row["row"], 1)
        self.assertIsInstance(row["h"], list)
        self.assertTrue(row["t"].strip())
        self.assertNotEqual(row["spoilers"] if "spoilers" in row else None, "hidden")

    def test_achievement_cli_exposes_static_labels_only_with_spoilers(self) -> None:
        hidden = run_cli("achievements")
        self.assertEqual(hidden.returncode, 0, hidden.stderr)
        self.assertIn("names hidden; use --spoilers", hidden.stdout)
        self.assertNotIn("Enkindle", hidden.stdout)

        visible = run_cli("achievements", "--spoilers")
        self.assertEqual(visible.returncode, 0, visible.stderr)
        self.assertIn("- Enkindle", visible.stdout)

    def test_malformed_save_cli_fails_without_writing_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.sl2"
            path.write_bytes(b"not a DSR save")
            before = path.read_bytes()
            result = run_cli("save", str(path), "summary")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unsupported DSR save size", result.stderr)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(temporary).iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
