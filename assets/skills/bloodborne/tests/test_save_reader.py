from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import bb_save  # noqa: E402

USERNAME_OFFSET = 30_000
INVENTORY_OFFSET = USERNAME_OFFSET + bb_save.USERNAME_TO_INV_OFFSET
FACE_OFFSET = INVENTORY_OFFSET + 34_028
SAVE_SIZE = USERNAME_OFFSET + bb_save.USERNAME_TO_AOB + 23_200


def _put_uint(data: bytearray, offset: int, value: int, length: int = 4) -> None:
    data[offset : offset + length] = value.to_bytes(length, "little")


def _put_item_slot(data: bytearray, offset: int, item_id: int, amount: int) -> None:
    slot = bytearray(16)
    slot[7] = 0xB0
    slot[8:11] = item_id.to_bytes(4, "little")[:3]
    slot[11] = 0x40
    slot[12:16] = amount.to_bytes(4, "little")
    data[offset : offset + 16] = slot


def _synthetic_save() -> bytearray:
    data = bytearray(SAVE_SIZE)
    data[FACE_OFFSET : FACE_OFFSET + 4] = b"FACE"
    data[USERNAME_OFFSET : USERNAME_OFFSET + 7] = b"hunter\x00"

    stat_values = {
        "Health": 987,
        "Stamina": 121,
        "Echoes": 54_321,
        "Insight": 17,
        "Level": 44,
        "Vitality": 30,
        "Endurance": 18,
        "Strength": 25,
        "Skill": 20,
        "Bloodtinge": 7,
        "Arcane": 9,
        "Ng": 2,
    }
    for spec in bb_save.OFFSETS:
        value = stat_values.get(spec["name"], 0)
        _put_uint(data, USERNAME_OFFSET + spec["rel_offset"], value, spec["length"])

    _put_item_slot(data, INVENTORY_OFFSET, 3000, 16)
    _put_item_slot(data, INVENTORY_OFFSET + 16, 999999, 5)
    _put_item_slot(data, USERNAME_OFFSET + bb_save.USERNAME_TO_KEY_INV_OFFSET, 4003, 1)
    _put_item_slot(data, INVENTORY_OFFSET + bb_save.INV_TO_STORAGE_OFFSET, 3010, 8)

    for boss in bb_save.BOSSES:
        if boss["name"] in {"Cleric Beast", "Rom"}:
            for flag in boss["flags"]:
                data[USERNAME_OFFSET + bb_save.USERNAME_TO_AOB + flag["rel_offset"]] |= flag["dead_value"]
    return data


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SaveReaderSyntheticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.save_path = Path(self.tmp.name) / "userdata.bin"
        self.save_path.write_bytes(_synthetic_save())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_layout_detection_and_stats_extraction(self) -> None:
        data, layout = bb_save.read_save(self.save_path)
        self.assertEqual(len(data), SAVE_SIZE)
        self.assertEqual(layout.username_offset, USERNAME_OFFSET)
        self.assertEqual(layout.inventory_offset, INVENTORY_OFFSET)
        self.assertEqual(layout.face_offset, FACE_OFFSET)
        self.assertEqual(layout.key_inventory_offset, USERNAME_OFFSET + bb_save.USERNAME_TO_KEY_INV_OFFSET)
        self.assertEqual(layout.storage_offset, INVENTORY_OFFSET + bb_save.INV_TO_STORAGE_OFFSET)

        stats = bb_save.read_stats(self.save_path)
        expected = {
            "Level": 44,
            "Health": 987,
            "Stamina": 121,
            "Echoes": 54_321,
            "Insight": 17,
            "Vitality": 30,
            "Endurance": 18,
            "Strength": 25,
            "Skill": 20,
            "Bloodtinge": 7,
            "Arcane": 9,
            "Ng": 2,
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(stats[key], value)

    def test_material_key_item_extraction_and_filters(self) -> None:
        entries = bb_save.read_inventory(self.save_path)
        mats = {(entry.location, entry.name): entry.amount for entry in bb_save.materials(entries)}
        self.assertEqual(mats, {("inventory", "Blood Stone Shard"): 16, ("storage", "Twin Blood Stone Shards"): 8})
        keys = bb_save.important_key_items(entries)
        self.assertEqual([(entry.location, entry.name, entry.amount) for entry in keys], [("key_inventory", "Cainhurst Summons", 1)])
        self.assertTrue(all(entry.item_id != 999999 for entry in entries))

    def test_boss_filtering_reports_known_defeated_only(self) -> None:
        bosses = bb_save.read_bosses(self.save_path)
        defeated = {boss.name: boss for boss in bosses if boss.defeated}
        self.assertEqual(set(defeated), {"Cleric Beast", "Rom"})
        self.assertTrue(defeated["Cleric Beast"].known)
        self.assertEqual(bb_save.safe_boss_name("Rom"), "Byrgenwerth boss (Rom)")
        self.assertTrue(all(boss.known for boss in defeated.values()))

    def test_python_api_and_cli_do_not_mutate_save_file(self) -> None:
        before_hash = _digest(self.save_path)
        before_stat = self.save_path.stat()
        bb_save.read_stats(self.save_path)
        bb_save.read_inventory(self.save_path)
        bb_save.read_bosses(self.save_path)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "cli.py"), "save", str(self.save_path), "summary"],
            check=True,
            text=True,
            capture_output=True,
        )
        after_stat = self.save_path.stat()
        self.assertEqual(_digest(self.save_path), before_hash)
        self.assertEqual(after_stat.st_size, before_stat.st_size)
        self.assertEqual(after_stat.st_mtime_ns, before_stat.st_mtime_ns)
        self.assertIn("Save stats", result.stdout)
        self.assertIn("Blood Stone Shard: 16", result.stdout)
        self.assertIn("Cainhurst Summons: 1", result.stdout)
        self.assertIn("Cleric Beast", result.stdout)
        self.assertIn("Byrgenwerth boss (Rom)", result.stdout)

    def test_cli_save_sections_route_to_expected_readers(self) -> None:
        commands = {
            "stats": ("Save stats", "Materials"),
            "materials": ("Blood Stone Shard: 16", "Known defeated bosses"),
            "keys": ("Cainhurst Summons: 1", "Known defeated bosses"),
            "bosses": ("Known defeated bosses", "Blood Stone Shard"),
        }
        for section, (included, excluded) in commands.items():
            with self.subTest(section=section):
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS_DIR / "cli.py"), "save", str(self.save_path), section],
                    check=True,
                    text=True,
                    capture_output=True,
                )
                self.assertIn(included, result.stdout)
                self.assertNotIn(excluded, result.stdout)

    def test_invalid_files_raise_clear_errors(self) -> None:
        empty = Path(self.tmp.name) / "empty.bin"
        empty.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "empty"):
            bb_save.read_save(empty)

        missing_marker = Path(self.tmp.name) / "not-a-save.bin"
        missing_marker.write_bytes(b"not a userdata file" * 1024)
        with self.assertRaisesRegex(ValueError, "FACE marker"):
            bb_save.read_save(missing_marker)


class SaveReaderRealFixtureTests(unittest.TestCase):
    def test_external_save_fixture_is_read_only_when_configured(self) -> None:
        fixture_env = os.environ.get("BLOODBORNE_TEST_SAVE")
        if not fixture_env:
            self.skipTest("Set BLOODBORNE_TEST_SAVE to exercise an external save fixture")
        fixture = Path(fixture_env)
        if not fixture.exists() or fixture.is_dir():
            self.skipTest("Optional user save fixture is unavailable")

        before_hash = _digest(fixture)
        before_stat = fixture.stat()
        stats = bb_save.read_stats(fixture)
        entries = bb_save.read_inventory(fixture)
        bosses = bb_save.read_bosses(fixture)
        after_stat = fixture.stat()

        self.assertTrue(stats)
        self.assertIsInstance(entries, list)
        self.assertTrue(bosses)
        self.assertEqual(_digest(fixture), before_hash)
        self.assertEqual(after_stat.st_size, before_stat.st_size)
        self.assertEqual(after_stat.st_mtime_ns, before_stat.st_mtime_ns)


if __name__ == "__main__":
    unittest.main(verbosity=2)
