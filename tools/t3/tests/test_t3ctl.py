# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Regression checks for the T3 v2 update guard."""

import importlib.util
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class BusyThreadsTest(unittest.TestCase):
    def test_pinned_auto_update_is_a_noop_without_runtime_or_network(self) -> None:
        source = Path(__file__).parents[1] / "t3ctl.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "t3ctl.py").write_text(source.read_text(), encoding="utf-8")
            (root / "deployment.json").write_text(
                '{"hosts": ["' + socket.gethostname().split(".")[0]
                + '"], "channel": "0.0.46-nightly.20261004.2657"}',
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(root / "t3ctl.py"), "auto-update"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("automatic updates disabled", result.stdout)

    def test_counts_live_v2_runs_instead_of_legacy_sessions(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "t3ctl", Path(__file__).parents[1] / "t3ctl.py"
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            module.STATE_DB = Path(directory) / "statev2.sqlite"
            with sqlite3.connect(module.STATE_DB) as connection:
                connection.execute(
                    "CREATE TABLE orchestration_v2_projection_runs"
                    " (thread_id TEXT, status TEXT)"
                )
                connection.executemany(
                    "INSERT INTO orchestration_v2_projection_runs VALUES (?, ?)",
                    [
                        ("a", "preparing"),
                        ("b", "starting"),
                        ("c", "running"),
                        ("c", "running"),
                        ("d", "completed"),
                        ("e", "interrupted"),
                    ],
                )
            self.assertEqual(module.busy_threads(), 3)
            with sqlite3.connect(module.STATE_DB) as connection:
                connection.execute(
                    "UPDATE orchestration_v2_projection_runs SET status = 'completed'"
                )
            self.assertEqual(module.busy_threads(), 0)


if __name__ == "__main__":
    unittest.main()
