"""Exercise platform boundaries without requiring a Windows host."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "lib"))

from autommit.service import _run_smoke
from autommit.transaction import describe_operation_lock, operation_lock


class PortabilityTests(unittest.TestCase):
    def test_lock_does_not_require_unix_hostname_api(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(os, "uname", side_effect=AttributeError, create=True),
        ):
            git_dir = Path(directory)
            lock = git_dir / "autommit" / "operation.lock"
            with operation_lock(git_dir):
                self.assertTrue(lock.is_file())
            self.assertFalse(lock.exists())

    def test_windows_lock_inspection_never_signals_the_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            git_dir = Path(directory)
            with (
                operation_lock(git_dir),
                mock.patch.object(sys, "platform", "win32"),
                mock.patch.object(os, "kill") as kill,
            ):
                hint = describe_operation_lock(git_dir)
                kill.assert_not_called()
                self.assertIsNotNone(hint)
                self.assertIn(str(os.getpid()), str(hint))
                self.assertNotIn("stale", str(hint))
                self.assertTrue((git_dir / "autommit" / "operation.lock").exists())

    def test_windows_smoke_preserves_native_command_line_quoting(self) -> None:
        command = r'C:\Tools\python.exe -c "print(1)"'
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.object(
                subprocess, "run", return_value=subprocess.CompletedProcess(command, 0)
            ) as run,
        ):
            _run_smoke(SKILL_ROOT, command, "refs/heads/main", "before")
            self.assertEqual(run.call_args.args[0], command)
            self.assertFalse(run.call_args.kwargs.get("shell", False))
