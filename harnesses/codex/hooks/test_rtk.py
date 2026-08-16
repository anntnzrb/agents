"""Colocated unit tests for the Codex RTK rewrite hook."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HOOK_DIR = Path(__file__).resolve().parent
if str(HOOK_DIR) not in sys.path:
    sys.path.insert(0, str(HOOK_DIR))

import rtk  # noqa: E402


class FakeResult:
    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode = returncode
        self.stdout = stdout


def run_main(payload: object) -> str:
    stream = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        with contextlib.redirect_stdout(stream):
            rtk.main()
    return stream.getvalue()


class RewriteTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(rtk.shutil, "which", return_value="/usr/local/bin/rtk")
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_rewrites_supported_command(self) -> None:
        with mock.patch.object(
            rtk.subprocess, "run", return_value=FakeResult(3, "rtk git status --short\n")
        ) as run:
            self.assertEqual(rtk.rewrite("git status --short"), "rtk git status --short")
        run.assert_called_once_with(
            ["rtk", "rewrite", "git status --short"],
            capture_output=True,
            text=True,
            timeout=rtk.REWRITE_TIMEOUT_SECONDS,
            check=False,
        )

    def test_exit_zero_rewrites(self) -> None:
        with mock.patch.object(
            rtk.subprocess, "run", return_value=FakeResult(0, "rtk ls\n")
        ):
            self.assertEqual(rtk.rewrite("ls"), "rtk ls")

    def test_unsupported_exit_fails_open(self) -> None:
        for code in (1, 2, 127):
            with self.subTest(code=code):
                with mock.patch.object(
                    rtk.subprocess, "run", return_value=FakeResult(code, "rtk ls\n")
                ):
                    self.assertIsNone(rtk.rewrite("ls"))

    def test_same_rewrite_fails_open(self) -> None:
        with mock.patch.object(
            rtk.subprocess, "run", return_value=FakeResult(3, "rtk git status\n")
        ):
            self.assertIsNone(rtk.rewrite("rtk git status"))

    def test_empty_rewrite_fails_open(self) -> None:
        with mock.patch.object(rtk.subprocess, "run", return_value=FakeResult(3, "   \n")):
            self.assertIsNone(rtk.rewrite("ls"))

    def test_timeout_fails_open(self) -> None:
        with mock.patch.object(
            rtk.subprocess,
            "run",
            side_effect=rtk.subprocess.TimeoutExpired("rtk", 3.0),
        ):
            self.assertIsNone(rtk.rewrite("ls"))

    def test_missing_rtk_binary_fails_open(self) -> None:
        with mock.patch.object(rtk.shutil, "which", return_value=None):
            with mock.patch.object(rtk.subprocess, "run") as run:
                self.assertIsNone(rtk.rewrite("ls"))
            run.assert_not_called()


class MainTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(rtk.shutil, "which", return_value="/usr/local/bin/rtk")
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_emits_allow_with_updated_command(self) -> None:
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git status --short"},
        }
        with mock.patch.object(
            rtk.subprocess, "run", return_value=FakeResult(3, "rtk git status --short\n")
        ):
            output = run_main(payload)
        self.assertEqual(
            json.loads(output),
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "updatedInput": {"command": "rtk git status --short"},
                }
            },
        )

    def test_malformed_input_fails_open(self) -> None:
        for payload in [
            None,
            "not a dict",
            ["list"],
            {},
            {"tool_input": None},
            {"tool_input": {"command": None}},
            {"tool_input": {"command": 42}},
            {"tool_input": {"command": ""}},
        ]:
            with self.subTest(payload=payload):
                with mock.patch.object(rtk.subprocess, "run") as run:
                    self.assertEqual(run_main(payload), "")
                run.assert_not_called()

    def test_unsupported_rewrite_fails_open(self) -> None:
        payload = {"tool_input": {"command": "pwd"}}
        with mock.patch.object(rtk.subprocess, "run", return_value=FakeResult(1, "")):
            self.assertEqual(run_main(payload), "")

    def test_same_rewrite_fails_open(self) -> None:
        payload = {"tool_input": {"command": "rtk git status"}}
        with mock.patch.object(
            rtk.subprocess, "run", return_value=FakeResult(3, "rtk git status\n")
        ):
            self.assertEqual(run_main(payload), "")

    def test_missing_rtk_fails_open(self) -> None:
        payload = {"tool_input": {"command": "ls"}}
        with mock.patch.object(rtk.shutil, "which", return_value=None):
            with mock.patch.object(rtk.subprocess, "run") as run:
                self.assertEqual(run_main(payload), "")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
