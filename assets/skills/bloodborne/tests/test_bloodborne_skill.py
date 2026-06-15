from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
CLI = SCRIPTS_DIR / "cli.py"

sys.path.insert(0, str(SCRIPTS_DIR))

import io
from contextlib import redirect_stdout
from types import SimpleNamespace
import bb_save  # noqa: E402
import cli  # noqa: E402


class CliCommandTests(unittest.TestCase):
    maxDiff = None

    def run_cli(self, *args: str, env: dict[str, str] | None = None) -> str:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        result = subprocess.run(
            ["uv", "run", "--script", str(CLI), *args],
            cwd=str(SKILL_DIR),
            env=merged_env,
            check=True,
            text=True,
            capture_output=True,
        )
        return result.stdout

    def test_softcaps_lists_all_stats(self) -> None:
        out = self.run_cli("softcaps")
        for stat in ("VIT", "END", "STR", "SKL", "BLT", "ARC"):
            self.assertIn(f"- {stat}:", out)
        self.assertIn("40->99 gives no stamina", out)

    def test_upgrade_10_totals(self) -> None:
        out = self.run_cli("upgrade", "10")
        self.assertIn("16 Blood Stone Shard", out)
        self.assertIn("16 Twin Blood Stone Shard", out)
        self.assertIn("16 Blood Stone Chunk", out)
        self.assertIn("1 Blood Rock", out)

    def test_calc_ludwig_quality(self) -> None:
        out = self.run_cli("calc", "Ludwig's Holy Blade", "26", "26", "7", "8")
        self.assertIn("Ludwig's Holy Blade +10 AR estimate", out)
        self.assertIn("327", out)

    def test_sources_status_uses_cache_dir_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = self.run_cli("sources", "status", "bb-wiki-scaling", env={"BLOODBORNE_CACHE_DIR": tmp})
        self.assertIn("bb-wiki-scaling: missing", out)

    def test_sources_list_includes_save_editor_attribution(self) -> None:
        out = self.run_cli("sources", "list", "noxde-save-editor")
        self.assertIn("https://github.com/Noxde/Bloodborne-save-editor", out)
        self.assertIn("GPL-3.0", out)
        self.assertIn("read-only", out)

    def test_insight_threshold_guidance(self) -> None:
        out = self.run_cli("insight", "43")
        self.assertIn("Current 43: high", out)
        self.assertIn("Above 15 Insight", out)

    def test_farm_guidance_no_network(self) -> None:
        out = self.run_cli("farm", "chunks")
        self.assertIn("Chunks are +7 to +9", out)
        self.assertIn("Main weapon first", out)


class PureMechanicsTests(unittest.TestCase):
    def test_saturation_interpolates_known_points(self) -> None:
        self.assertAlmostEqual(cli.sat(25), 0.35)
        self.assertAlmostEqual(cli.sat(30), 0.45)
        self.assertAlmostEqual(cli.sat(27), 0.39)

    def test_find_weapon_partial_and_ambiguous(self) -> None:
        self.assertEqual(cli.find_weapon("Ludwig").name, "Ludwig's Holy Blade")
        with self.assertRaises(SystemExit):
            cli.find_weapon("Saw")

    def test_echo_cost_positive_and_ordered(self) -> None:
        self.assertEqual(cli.echo_cost(10, 10), 0)
        self.assertGreater(cli.echo_cost(64, 69), cli.echo_cost(64, 65))

    def test_sources_registry_has_required_metadata(self) -> None:
        for key, source in cli.SOURCES.items():
            with self.subTest(key=key):
                self.assertTrue(source["url"])
                self.assertTrue(source["license"])
                self.assertTrue(source["use"])
                self.assertIn("risk", source)



class DirectCliFunctionTests(unittest.TestCase):
    def capture(self, func, **kwargs: object) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            func(SimpleNamespace(**kwargs))
        return buf.getvalue()

    def test_core_command_functions_emit_expected_content(self) -> None:
        self.assertIn("Sources registered", self.capture(cli.cmd_fresh))
        self.assertIn("VIT:", self.capture(cli.cmd_softcaps))
        self.assertIn("Military Veteran", self.capture(cli.cmd_origins, filter="quality"))
        self.assertIn("Totals:", self.capture(cli.cmd_upgrade, level=10))
        self.assertIn("Ludwig's Holy Blade", self.capture(cli.cmd_weapons, name=["Ludwig"]))
        self.assertIn("327", self.capture(cli.cmd_calc, weapon="Ludwig's Holy Blade", str=26, skl=26, blt=7, arc=8))
        self.assertTrue(self.capture(cli.cmd_echo_cost, current=64, target=69).strip().isdigit())
        self.assertIn("Current 43: high", self.capture(cli.cmd_insight, current=43))
        self.assertIn("Moon:", self.capture(cli.cmd_runes))
        self.assertIn("Tempering", self.capture(cli.cmd_gems))
        self.assertIn("Chunks are +7 to +9", self.capture(cli.cmd_farm, kind="chunks"))

    def test_sources_status_and_validation_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = cli.CACHE_DIR
            cli.CACHE_DIR = Path(tmp)
            try:
                self.assertEqual(cli.source_keys(["noxde-save-editor"]), ["noxde-save-editor"])
                with self.assertRaises(SystemExit):
                    cli.source_keys(["missing-source"])
                out = self.capture(cli.cmd_sources, action="status", keys=["noxde-save-editor"], force=False)
                self.assertIn("noxde-save-editor: missing", out)
                listed = self.capture(cli.cmd_sources, action="list", keys=["noxde-save-editor"], force=False)
                self.assertIn("GPL-3.0", listed)
            finally:
                cli.CACHE_DIR = old


    def test_tracking_and_recommendation_paths(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as fh:
            fh.write(
                "# Player Tracking\n"
                "LVL 44\n"
                "Insight 12\n"
                "| VIT | 24 |\n"
                "| END | 14 |\n"
                "| STR | 20 |\n"
                "| SKL | 18 |\n"
                "| BLT | 7 |\n"
                "| ARC | 8 |\n"
                "Ludwig's Holy Blade +6\n"
            )
            path = Path(fh.name)
        try:
            summary = self.capture(cli.cmd_track, path=str(path), section="summary")
            self.assertIn("LVL 44", summary)
            self.assertIn("Ludwig's Holy Blade +6", summary)
            recommendation = self.capture(cli.cmd_recommend, path=str(path))
            self.assertIn("Level VIT toward 30", recommendation)
        finally:
            path.unlink(missing_ok=True)

    def test_cache_metadata_and_fetch_source_with_mocked_network(self) -> None:
        class HeaderDict(dict):
            def get(self, key: str, default: str = "") -> str:
                return str(super().get(key, default))

        class FakeResponse:
            headers = HeaderDict({"content-type": "text/html"})

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b"<html>fresh</html>"

            def geturl(self) -> str:
                return "https://example.test/fresh"

        with tempfile.TemporaryDirectory() as tmp:
            old_cache = cli.CACHE_DIR
            old_urlopen = cli.urllib.request.urlopen
            cli.CACHE_DIR = Path(tmp)
            cli.urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse()  # type: ignore[assignment]
            try:
                html_path, meta_path = cli.source_paths("bb-wiki-scaling")
                meta_path.parent.mkdir(parents=True, exist_ok=True)
                meta_path.write_text("{bad json", encoding="utf-8")
                self.assertIsNone(cli.cache_meta("bb-wiki-scaling"))
                meta = cli.fetch_source("bb-wiki-scaling", force=True)
                self.assertEqual(meta["status"], "refreshed")
                self.assertTrue(html_path.exists())
                self.assertEqual(cli.fetch_source("bb-wiki-scaling")["status"], "fresh-cache")
                self.assertIsNotNone(cli.cache_age_hours(cli.cache_meta("bb-wiki-scaling")))
            finally:
                cli.CACHE_DIR = old_cache
                cli.urllib.request.urlopen = old_urlopen  # type: ignore[assignment]

    def test_more_cli_error_and_branch_paths(self) -> None:
        with self.assertRaises(SystemExit):
            cli.cmd_upgrade(SimpleNamespace(level=11))
        self.assertIn("Milquetoast", self.capture(cli.cmd_origins, filter=None))
        self.assertIn("Saw Cleaver", self.capture(cli.cmd_weapons, name=[]))
        self.assertIn("normal/low", self.capture(cli.cmd_insight, current=5))
        self.assertIn("above difficulty threshold", self.capture(cli.cmd_insight, current=20))
        parser = cli.build_parser()
        args = parser.parse_args(["softcaps"])
        self.assertIs(args.func, cli.cmd_softcaps)


    def test_invalid_save_fails_cleanly(self) -> None:
        with tempfile.NamedTemporaryFile() as fh:
            fh.write(b"not a bloodborne save")
            fh.flush()
            with self.assertRaisesRegex(ValueError, "FACE marker"):
                bb_save.read_stats(fh.name)


class DocumentationAndResourceTests(unittest.TestCase):
    def test_skill_docs_explain_routing_boundaries(self) -> None:
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("save <savefile>", text)
        self.assertIn("read-only", text)
        self.assertIn("stateless", text.lower())
        self.assertIn("sources status", text)
        self.assertIn("live web research", text.lower())
        for forbidden in ("oh-my-pi", "Oh My Pi"):
            self.assertNotIn(forbidden, text)

    def test_skill_docs_include_natural_language_routing_matrix(self) -> None:
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("## Natural-language routing", text)
        for phrase in (
            "current stats",
            "weapon AR",
            "upgrade materials",
            "route planning",
            "source-backed",
            "shadPS4/decrypted save analysis",
        ):
            self.assertIn(phrase, text)

    def test_vendored_resources_exist_and_are_valid_json(self) -> None:
        resource_dir = SCRIPTS_DIR / "resources" / "bloodborne_save"
        for name in ("offsets.json", "bosses.json", "items.json", "weapons.json", "armors.json", "upgrades.json"):
            with self.subTest(name=name):
                payload = json.loads((resource_dir / name).read_text(encoding="utf-8"))
                self.assertTrue(payload)
        self.assertIn("GPL-3.0", (resource_dir / "SOURCES.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
