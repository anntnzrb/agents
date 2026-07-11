from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import TypedDict, cast


class OriginRecord(TypedDict):
    name: str
    level: int
    stats: dict[str, int]


class UpgradePathRecord(TypedDict):
    name: str
    max_level: int
    reinforcement: str


class EquipLoadState(TypedDict):
    roll: str


class GuideManifest(TypedDict):
    format: str
    source_pdf_tracked: bool
    copyable: bool
    constraints: list[str]
    chunk_count: int


class GuideChunk(TypedDict):
    h: list[str]
    k: str
    t: str


class AchievementEntry(TypedDict):
    static_support: bool
    save_backed: bool


class UnsupportedSaveState(TypedDict):
    supported: bool
    reason: str
    evidence: str


class AchievementResult(TypedDict):
    supported: bool
    static: bool
    save_backed: bool
    achievements: list[AchievementEntry]
    save_state: UnsupportedSaveState


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
RESOURCES_DIR = SKILL_DIR / "resources"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ds1_catalog as catalog  # noqa: E402
import ds1_core as core  # noqa: E402
import ds1_save as save  # noqa: E402


class CatalogMechanicsTests(unittest.TestCase):
    def test_origin_lookup_is_canonical_and_returns_independent_data(self) -> None:
        knight = cast(OriginRecord, catalog.origin_lookup("KNIGHT"))
        self.assertEqual(knight["name"], "Knight")
        self.assertEqual(knight["level"], 5)
        self.assertIn("strength", knight["stats"])

        knight["stats"]["strength"] = -1
        other_knight = cast(OriginRecord, catalog.origin_lookup("knight"))
        self.assertEqual(other_knight["stats"]["strength"], 11)

    def test_softcaps_and_attunement_thresholds_are_explicit(self) -> None:
        self.assertEqual(core.SOFTCAPS["vitality"][0][0], 27)
        self.assertEqual(core.SOFTCAPS["vitality"][1][0], 40)
        self.assertEqual(core.SOFTCAPS["endurance"][0][0], 40)
        self.assertEqual(core.attunement_slots(9), 0)
        self.assertEqual(core.attunement_slots(10), 1)
        self.assertEqual(core.attunement_slots(49), 10)
        self.assertEqual(core.attunement_slots(50), 12)
        with self.assertRaises(ValueError):
            core.attunement_slots(100)

    def test_soul_cost_is_target_level_formula_with_boundaries(self) -> None:
        self.assertEqual(catalog.soul_cost(10), 487)
        self.assertLess(catalog.soul_cost(10), catalog.soul_cost(11))
        with self.assertRaises(catalog.CatalogError):
            catalog.soul_cost(1)
        with self.assertRaises(catalog.CatalogError):
            catalog.soul_cost(714)
        with self.assertRaises(catalog.CatalogError):
            catalog.soul_cost(True)

    def test_equip_load_thresholds_are_inclusive_at_quarter_and_half(self) -> None:
        self.assertEqual(
            cast(EquipLoadState, catalog.equip_load_state(25, 100))["roll"], "fast"
        )
        self.assertEqual(
            cast(EquipLoadState, catalog.equip_load_state(25.01, 100))["roll"], "medium"
        )
        self.assertEqual(
            cast(EquipLoadState, catalog.equip_load_state(50, 100))["roll"], "medium"
        )
        self.assertEqual(
            cast(EquipLoadState, catalog.equip_load_state(50.01, 100))["roll"], "fat"
        )
        self.assertEqual(
            cast(EquipLoadState, catalog.equip_load_state(100.01, 100))["roll"],
            "overburdened",
        )
        with self.assertRaises(catalog.CatalogError):
            catalog.equip_load_state(1, 0)

    def test_upgrade_path_metadata_and_cli_path_data_agree(self) -> None:
        normal = cast(UpgradePathRecord, catalog.upgrade_path_lookup("NORMAL"))
        self.assertEqual(normal["name"], "normal")
        self.assertEqual(normal["max_level"], 15)
        self.assertIn("Titanite Shard", normal["reinforcement"])
        self.assertEqual(len(core.UPGRADE_PATHS["normal"]), normal["max_level"])
        self.assertEqual(core.UPGRADE_PATHS["normal"][0][2], {"titanite_shard": 1})
        with self.assertRaises(catalog.CatalogError):
            catalog.upgrade_path_lookup("not-a-path")


class GuideCorpusTests(unittest.TestCase):
    def test_manifest_and_jsonl_use_the_declared_transformed_row_schema(self) -> None:
        guide_dir = RESOURCES_DIR / "guides" / "dsr_plat_guide"
        manifest = cast(
            GuideManifest,
            json.loads(
                (guide_dir / "dsr-plat-guide.manifest.json").read_text(encoding="utf-8")
            ),
        )
        self.assertEqual(manifest["format"], "dsr-guide-chunks-v1")
        self.assertFalse(manifest["source_pdf_tracked"])
        self.assertFalse(manifest["copyable"])
        self.assertTrue(
            any(
                "pdf" in str(constraint).casefold()
                and "not copied" in str(constraint).casefold()
                and "tracked" in str(constraint).casefold()
                for constraint in manifest["constraints"]
            )
        )

        rows: list[GuideChunk] = []
        with (guide_dir / "dsr-plat-guide.chunks.jsonl").open(
            encoding="utf-8"
        ) as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                row = cast(GuideChunk, json.loads(line))
                self.assertEqual(set(row), {"h", "k", "t"}, f"line {line_number}")
                self.assertIsInstance(row["h"], list)
                self.assertTrue(all(isinstance(item, str) for item in row["h"]))
                self.assertIsInstance(row["k"], str)
                self.assertIsInstance(row["t"], str)
                self.assertTrue(row["t"].strip())
                rows.append(row)
        self.assertEqual(len(rows), manifest["chunk_count"])
        self.assertGreater(len(rows), 0)


class StaticAchievementAndSaveTests(unittest.TestCase):
    def test_achievements_are_static_only_and_save_state_is_unsupported(self) -> None:
        result = cast(AchievementResult, save.read_achievements())
        self.assertTrue(result["supported"])
        self.assertTrue(result["static"])
        self.assertFalse(result["save_backed"])
        self.assertIsInstance(result["achievements"], list)
        for entry in result["achievements"]:
            self.assertTrue(entry["static_support"])
            self.assertFalse(entry["save_backed"])
        self.assertFalse(result["save_state"]["supported"])

    def test_malformed_save_raises_without_writing_or_mutating_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "DRAKS0005.sl2"
            path.write_bytes(b"malformed save")
            before_bytes = path.read_bytes()
            before_mtime = path.stat().st_mtime_ns
            time.sleep(0.01)
            with self.assertRaises(save.SaveReadError) as context:
                save.read_save(path)
            self.assertIn("Unsupported DSR save size", str(context.exception))
            self.assertEqual(path.read_bytes(), before_bytes)
            self.assertEqual(path.stat().st_mtime_ns, before_mtime)
            self.assertEqual(list(Path(temporary).iterdir()), [path])


class CacheEnvironmentTests(unittest.TestCase):
    def test_cache_environment_name_is_stable(self) -> None:
        self.assertEqual(core.CACHE_ENV, "DS1_CACHE_DIR")


if __name__ == "__main__":
    unittest.main()
