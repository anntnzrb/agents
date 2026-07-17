# /// script
# dependencies = ["pycryptodome"]
# ///
"""Regression checks for DS3 class names and event-mask semantics."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ds3_save import CLASS_NAMES, _event_flag_matches  # noqa: E402

EXPECTED_CLASS_NAMES = {
    0: "Knight",
    1: "Mercenary",
    2: "Warrior",
    3: "Herald",
    4: "Thief",
    5: "Assassin",
    6: "Sorcerer",
    7: "Pyromancer",
    8: "Cleric",
    9: "Deprived",
}


def test_class_names_match_save_identifiers() -> None:
    assert CLASS_NAMES == EXPECTED_CLASS_NAMES
    assert CLASS_NAMES[1] == "Mercenary"
    assert CLASS_NAMES[9] == "Deprived"


def test_event_flag_matching_uses_bit_masks() -> None:
    assert _event_flag_matches(0x03, 0x02)
    assert not _event_flag_matches(0x00, 0x02)
