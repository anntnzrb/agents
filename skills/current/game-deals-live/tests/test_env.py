"""Environment source precedence tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from game_deals.env import load_environment


class EnvironmentTests(unittest.TestCase):
    def test_process_beats_explicit_and_skill_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            skill = root / "skill"
            skill.mkdir()
            explicit = root / "explicit.env"
            explicit.write_text(
                "GG_DEALS_API_KEY=explicit\nITAD_API_KEY=itad\n",
                encoding="utf-8",
            )
            (skill / ".env").write_text("GG_DEALS_API_KEY=skill\n", encoding="utf-8")
            values = load_environment(
                environ={
                    "GG_DEALS_API_KEY": "process",
                    "GAME_DEALS_ENV_FILE": str(explicit),
                },
                skill_dir=skill,
                cwd=root,
            )
            self.assertEqual(values["GG_DEALS_API_KEY"], "process")
            self.assertEqual(values["ITAD_API_KEY"], "itad")

    def test_ancestor_uses_only_scoped_skill_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            cwd = root / "workspace" / "nested"
            cwd.mkdir(parents=True)
            scoped = root / "skills" / "game-deals-live"
            scoped.mkdir(parents=True)
            (root / ".env").write_text("BAD=loaded\n", encoding="utf-8")
            (scoped / ".env").write_text("GG_DEALS_API_KEY=scoped\n", encoding="utf-8")
            values = load_environment(environ={}, skill_dir=root / "missing", cwd=cwd)
            self.assertEqual(values["GG_DEALS_API_KEY"], "scoped")
            self.assertNotIn("BAD", values)


if __name__ == "__main__":
    unittest.main()
