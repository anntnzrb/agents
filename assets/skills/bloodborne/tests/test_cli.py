from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
CLI = SKILL_DIR / "scripts" / "cli.py"


class BloodborneCliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> str:
        with tempfile.TemporaryDirectory() as cache_dir:
            env = os.environ.copy()
            env["BLOODBORNE_CACHE_DIR"] = cache_dir
            result = subprocess.run(
                [sys.executable, str(CLI), *args],
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(result.stderr, "")
            return result.stdout

    def test_softcaps_lists_core_stats(self) -> None:
        out = self.run_cli("softcaps")
        self.assertIn("- VIT: 30 soft / 50 hard.", out)
        self.assertIn("- STR: 25 first soft / 50 hard.", out)
        self.assertIn("- SKL: 25 first soft / 50 hard.", out)

    def test_upgrade_10_prints_steps_and_material_totals(self) -> None:
        out = self.run_cli("upgrade", "10")
        self.assertIn("+10: 1 Blood Rock", out)
        self.assertIn("Totals: 16 Blood Stone Shard, 16 Twin Blood Stone Shard, 16 Blood Stone Chunk, 1 Blood Rock", out)

    def test_calc_known_weapon_is_deterministic(self) -> None:
        out = self.run_cli("calc", "Saw Cleaver", "25", "25", "7", "8")
        self.assertEqual(out, "Saw Cleaver +10 AR estimate at STR/SKL/BLT/ARC (25, 25, 7, 8): 248\n")

    def test_insight_current_thresholds(self) -> None:
        normal = self.run_cli("insight", "15")
        above = self.run_cli("insight", "16")
        high = self.run_cli("insight", "40")
        self.assertIn("- Current 15: normal/low. Fine to hold.", normal)
        self.assertIn("- Current 16: above difficulty threshold; spend if struggling.", above)
        self.assertIn("- Current 40: high. Spend some if you want a smoother run.", high)

    def test_farm_outputs_selected_route(self) -> None:
        out = self.run_cli("farm", "vials")
        self.assertIn("Farm: vials\n", out)
        self.assertIn("Usually buy vials with farmed echoes instead of farming drops.", out)

    def test_sources_list_and_status_do_not_need_network(self) -> None:
        listed = self.run_cli("sources", "list", "bb-wiki-weapons")
        status = self.run_cli("sources", "status", "bb-wiki-weapons")
        self.assertIn("bb-wiki-weapons: https://www.bloodborne-wiki.com/p/weapons.html", listed)
        self.assertIn("license: CC BY-SA 3.0", listed)
        self.assertIn("use:", listed)
        self.assertEqual(status, "bb-wiki-weapons: missing\n")

    def test_save_command_reads_synthetic_fixture_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_path = Path(tmp) / "USERDATA0000"
            write_synthetic_save(save_path)
            out = self.run_cli("save", str(save_path), "summary")
        self.assertIn("Save stats", out)
        self.assertIn("Level 32", out)
        self.assertIn("Insight 16", out)
        self.assertIn("Vitality 25", out)
        self.assertIn("Materials\n  Blood Stone Shard: 6", out)
        self.assertIn("Important key items\n  Blood Gem Workshop Tool: 1", out)
        self.assertIn("Weapons\n  Saw Cleaver: 1", out)

    def test_save_bosses_filters_to_known_names_and_unknown_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_path = Path(tmp) / "USERDATA0000"
            write_synthetic_save(save_path)
            out = self.run_cli("save", str(save_path), "bosses")
        self.assertIn("Known defeated bosses\n  Cleric Beast", out)
        self.assertIn("Unknown future bosses defeated: 0", out)
        self.assertNotIn("Father Gascoigne", out)


def write_synthetic_save(path: Path) -> None:
    username_offset = 35_503
    inventory_offset = username_offset + 469
    face_offset = inventory_offset + 34_028
    key_inventory_offset = username_offset + 32_201
    size = username_offset + 68_831 + 23_000
    data = bytearray(size)
    data[face_offset : face_offset + 4] = b"FACE"

    stats = {
        -147: 873,
        -119: 103,
        -19: 12345,
        -35: 16,
        -23: 32,
        -103: 25,
        -95: 15,
        -79: 25,
        -71: 18,
        -63: 7,
        -55: 8,
        68_831: 1,
    }
    for rel_offset, value in stats.items():
        width = 1 if rel_offset == 68_831 else 4
        data[username_offset + rel_offset : username_offset + rel_offset + width] = value.to_bytes(width, "little")

    write_weapon_slot(data, inventory_offset, 7_000_000, 1)
    write_item_slot(data, inventory_offset + 16, 3_000, 6)
    write_item_slot(data, key_inventory_offset, 4_103, 1)
    data[username_offset + 68_545 + 21_714] = 8  # Cleric Beast defeated.
    path.write_bytes(data)

def write_item_slot(data: bytearray, offset: int, item_id: int, amount: int) -> None:
    data[offset + 7] = 0xB0
    data[offset + 8 : offset + 11] = item_id.to_bytes(4, "little")[:3]
    data[offset + 11] = 0x40
    data[offset + 12 : offset + 16] = amount.to_bytes(4, "little")


def write_weapon_slot(data: bytearray, offset: int, item_id: int, amount: int) -> None:
    data[offset + 8 : offset + 12] = item_id.to_bytes(4, "little")
    data[offset + 12 : offset + 16] = amount.to_bytes(4, "little")


if __name__ == "__main__":
    unittest.main()
