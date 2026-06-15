#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Contract tests for the generic/stateless Bloodborne skill."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
CLI_PATH = SCRIPTS_DIR / "cli.py"
SAVE_RESOURCE_DIR = SCRIPTS_DIR / "resources" / "bloodborne_save"

RESOURCE_JSON = (
    "offsets.json",
    "bosses.json",
    "items.json",
    "weapons.json",
    "armors.json",
    "upgrades.json",
)
FORBIDDEN_HARNESS_NAMES = (
    "OMP",
    "Oh My Pi",
    "Oh-My-Pi",
    "Claude Code",
)


def load_cli():
    sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location("bloodborne_cli_contract", CLI_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load CLI from {CLI_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CLI = load_cli()


class DocumentationContractTests(unittest.TestCase):
    def test_skill_doc_mentions_save_stateless_cache_and_registry_boundaries(self) -> None:
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        lowered = text.lower()

        self.assertIn("uv run --script <skill-dir>/scripts/cli.py save", text)
        self.assertIn("read-only", lowered)
        self.assertIn("stateless", lowered)
        self.assertIn("source registry", lowered)
        self.assertIn("cache", lowered)
        self.assertIn("24-hour ttl", lowered)
        self.assertIn("~/.cache/bloodborne-companion", text)
        self.assertIn("BLOODBORNE_CACHE_DIR", text)
        for forbidden in FORBIDDEN_HARNESS_NAMES:
            self.assertNotIn(forbidden, text)

    def test_save_resource_sources_doc_preserves_read_only_attribution(self) -> None:
        text = (SAVE_RESOURCE_DIR / "SOURCES.md").read_text(encoding="utf-8")
        lowered = text.lower()

        self.assertIn("Noxde/Bloodborne-save-editor", text)
        self.assertIn("GPL-3.0", text)
        self.assertIn("read-only", lowered)
        self.assertIn("without modifying", lowered)
        for filename in RESOURCE_JSON:
            self.assertIn(filename, text)
        for forbidden in FORBIDDEN_HARNESS_NAMES:
            self.assertNotIn(forbidden, text)


class VendoredResourceTests(unittest.TestCase):
    def test_vendored_save_resources_exist_and_are_valid_json(self) -> None:
        for filename in RESOURCE_JSON:
            with self.subTest(filename=filename):
                path = SAVE_RESOURCE_DIR / filename
                self.assertTrue(path.is_file(), f"missing vendored resource: {filename}")
                with path.open("r", encoding="utf-8") as handle:
                    parsed = json.load(handle)
                self.assertTrue(parsed, f"empty JSON resource: {filename}")
                self.assertIsInstance(parsed, (dict, list), filename)

    def test_license_file_exists_for_vendored_gpl_resources(self) -> None:
        license_path = SAVE_RESOURCE_DIR / "Noxde-Bloodborne-save-editor-GPL-3.0-LICENSE"
        self.assertTrue(license_path.is_file())
        self.assertIn("GNU GENERAL PUBLIC LICENSE", license_path.read_text(encoding="utf-8", errors="replace"))


class SourceRegistryContractTests(unittest.TestCase):
    def test_source_registry_has_required_metadata_and_save_source(self) -> None:
        self.assertEqual(CLI.CACHE_TTL_HOURS, 24)
        self.assertIn("noxde-save-editor", CLI.SOURCES)
        for key, source in CLI.SOURCES.items():
            with self.subTest(key=key):
                self.assertRegex(key, r"^[a-z0-9_.-]+$")
                self.assertTrue(str(source.get("url", "")).startswith(("https://", "http://")))
                self.assertTrue(source.get("license"))
                self.assertTrue(source.get("use"))
                self.assertIn(source.get("machine"), (True, False))
                self.assertTrue(source.get("risk"))

        save_source = CLI.SOURCES["noxde-save-editor"]
        self.assertIn("read-only", save_source["use"] + " " + save_source["risk"])
        self.assertIn("GPL-3.0", save_source["license"])

    def test_cache_status_uses_ttl_and_local_cache_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["BLOODBORNE_CACHE_DIR"] = tmp
            result = subprocess.run(
                ["uv", "run", "--script", str(CLI_PATH), "sources", "status", "noxde-save-editor"],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
        self.assertIn("noxde-save-editor: missing", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_source_key_validation_rejects_unknown_registry_key(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            CLI.source_keys(["not-a-source"])
        self.assertIn("Unknown source", str(raised.exception))


class CliRoutingContractTests(unittest.TestCase):
    def test_parser_exposes_save_and_source_routes(self) -> None:
        parser = CLI.build_parser()
        save_args = parser.parse_args(["save", "userdata0000", "materials"])
        self.assertIs(save_args.func, CLI.cmd_save)
        self.assertEqual(save_args.path, "userdata0000")
        self.assertEqual(save_args.section, "materials")

        sources_args = parser.parse_args(["sources", "status", "noxde-save-editor"])
        self.assertIs(sources_args.func, CLI.cmd_sources)
        self.assertEqual(sources_args.action, "status")
        self.assertEqual(sources_args.keys, ["noxde-save-editor"])

    def test_fresh_route_reports_cache_policy_and_registry_count(self) -> None:
        result = subprocess.run(
            ["uv", "run", "--script", str(CLI_PATH), "fresh"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("Cache policy", result.stdout)
        self.assertIn("24h", result.stdout)
        self.assertIn(f"Sources registered: {len(CLI.SOURCES)}", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
