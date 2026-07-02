# /// script
# dependencies = ["pycryptodome"]
# ///
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ds3_save import CLASS_NAMES, _event_flag_matches

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

assert CLASS_NAMES == EXPECTED_CLASS_NAMES
assert CLASS_NAMES[1] == "Mercenary"
assert CLASS_NAMES[9] == "Deprived"

assert _event_flag_matches(0x03, 0x02)
assert not _event_flag_matches(0x00, 0x02)
