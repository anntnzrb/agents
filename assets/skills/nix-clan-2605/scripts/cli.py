# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Public entrypoint for the Clan documentation updater."""

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
LIB_ROOT = SKILL_ROOT / "lib"
if str(LIB_ROOT) not in sys.path:
    sys.path.insert(0, str(LIB_ROOT))

from nix_clan_updater.cli import main

if __name__ == "__main__":
    raise SystemExit(main(skill_root=SKILL_ROOT))
