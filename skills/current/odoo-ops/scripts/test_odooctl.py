"""Unit tests for odooctl test runner, container lifecycle, and CLI subcommands."""

from __future__ import annotations

import argparse
import configparser
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

SCRIPT_PATH = Path(__file__).with_name("odooctl.py")


def load_odooctl() -> ModuleType:
    spec = importlib.util.spec_from_file_location("odooctl", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load controller module: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_workspace_context(module: ModuleType, workspace_root: Path) -> object:
    runtime = workspace_root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    source = runtime / "source" / "odoo-17.0"
    source.mkdir(parents=True, exist_ok=True)
    (runtime / "config").mkdir(parents=True, exist_ok=True)
    (runtime / "data" / "web").mkdir(parents=True, exist_ok=True)
    config = configparser.ConfigParser()
    return module.WorkspaceContext(
        root=workspace_root,
        config_path=runtime / "config" / "odoo.conf",
        config=config,
        addons_paths=[workspace_root],
        effective_db_name="erptech_test",
        runtime=runtime,
    )


class TestEvaluateOdooTestResult(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_odooctl()

    def test_successful_run_with_expected_error_logs(self) -> None:
        output = (
            "2026-09-05 03:28:29,928 1 ERROR erptech odoo.addons.whatsapp_utils: Fallo interno simulado\n"
            "2026-09-05 03:28:49,475 1 ERROR erptech odoo.modules.registry: Model budget has no table.\n"
            "2026-09-05 03:28:50,481 1 INFO erptech odoo.tests.stats: whatsapp_utils: 129 tests 73.55s\n"
            "2026-09-05 03:28:50,481 1 INFO erptech odoo.tests.result: 0 failed, 0 error(s) of 117 tests\n"
        )
        passed, summary = self.module._evaluate_odoo_test_result(0, output)
        self.assertTrue(passed)
        self.assertTrue(any("0 failed, 0 error(s)" in s for s in summary))

    def test_failed_run_with_test_failure(self) -> None:
        output = (
            "2026-09-05 03:32:36,429 1 ERROR erptech: FAIL: TestFoo.test_bar\n"
            "2026-09-05 03:32:37,701 1 ERROR erptech odoo.modules.loading: Module foo: 1 failures, 0 errors of 10 tests\n"
            "2026-09-05 03:32:38,000 1 ERROR erptech odoo.tests.result: 1 failed, 0 error(s) of 10 tests\n"
        )
        passed, summary = self.module._evaluate_odoo_test_result(1, output)
        self.assertFalse(passed)
        self.assertTrue(any("1 failed" in s for s in summary))

    def test_failed_run_with_module_loading_error(self) -> None:
        output = (
            "2026-09-05 03:28:50,449 1 ERROR erptech odoo.modules.loading: At least one test failed when loading the modules.\n"
        )
        passed, _ = self.module._evaluate_odoo_test_result(0, output)
        self.assertFalse(passed)

    def test_nonzero_exit_code_always_fails(self) -> None:
        output = "Odoo crashed during initialization"
        passed, _ = self.module._evaluate_odoo_test_result(127, output)
        self.assertFalse(passed)


class TestCmdTestLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_odooctl()

    def test_cmd_test_cleans_stale_containers_and_runs_successfully(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = make_workspace_context(self.module, tmp_path)
            mod_dir = tmp_path / "my_module"
            mod_dir.mkdir()

            mock_ps = subprocess.CompletedProcess(
                ["podman", "ps"], returncode=0, stdout="odoo-test-999\nodoo-web\n", stderr=""
            )
            mock_rm = subprocess.CompletedProcess(
                ["podman", "rm"], returncode=0, stdout="", stderr=""
            )

            mock_proc = MagicMock()
            mock_proc.stdout = [
                "Running test...\n",
                "odoo.tests.result: 0 failed, 0 error(s) of 10 tests\n",
            ]
            mock_proc.wait.return_value = 0

            args = argparse.Namespace(
                target="my_module",
                profile="etech",
                json=False,
            )

            with (
                patch.object(self.module, "_resolve_workspace", return_value=ctx),
                patch.object(self.module, "_ensure_runtime_pod"),
                patch.object(
                    self.module,
                    "_run",
                    side_effect=lambda cmd, **kw: mock_ps if "ps" in cmd else mock_rm,
                ) as mock_run,
                patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                code = self.module.cmd_test(args)

            self.assertEqual(code, 0)
            mock_popen.assert_called_once()
            # Verify stale container cleanup
            rm_calls = [call.args[0] for call in mock_run.call_args_list if "rm" in call.args[0]]
            self.assertTrue(any("odoo-test-999" in cmd for cmd in rm_calls))
            self.assertIn("[OK] All Odoo unit tests passed successfully.", stdout.getvalue())

    def test_cmd_test_cleans_container_on_keyboard_interrupt(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = make_workspace_context(self.module, tmp_path)
            mod_dir = tmp_path / "my_module"
            mod_dir.mkdir()

            mock_ps = subprocess.CompletedProcess(
                ["podman", "ps"], returncode=0, stdout="", stderr=""
            )
            mock_rm = subprocess.CompletedProcess(
                ["podman", "rm"], returncode=0, stdout="", stderr=""
            )

            def raise_interrupt(*args: object, **kwargs: object) -> MagicMock:
                raise KeyboardInterrupt()

            args = argparse.Namespace(
                target="my_module",
                profile="etech",
                json=False,
            )

            with (
                patch.object(self.module, "_resolve_workspace", return_value=ctx),
                patch.object(self.module, "_ensure_runtime_pod"),
                patch.object(
                    self.module,
                    "_run",
                    side_effect=lambda cmd, **kw: mock_ps if "ps" in cmd else mock_rm,
                ) as mock_run,
                patch("subprocess.Popen", side_effect=raise_interrupt),
                self.assertRaises(KeyboardInterrupt),
            ):
                self.module.cmd_test(args)

            # Verify podman stop and podman rm -f were called
            run_commands = [call.args[0] for call in mock_run.call_args_list]
            self.assertTrue(any("stop" in cmd for cmd in run_commands))
            self.assertTrue(any("rm" in cmd for cmd in run_commands))

    def test_cmd_test_json_mode_preserves_clean_stdout(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = make_workspace_context(self.module, tmp_path)
            mod_dir = tmp_path / "my_module"
            mod_dir.mkdir()

            mock_ps = subprocess.CompletedProcess(
                ["podman", "ps"], returncode=0, stdout="", stderr=""
            )
            mock_rm = subprocess.CompletedProcess(
                ["podman", "rm"], returncode=0, stdout="", stderr=""
            )

            mock_proc = MagicMock()
            mock_proc.stdout = [
                "2026-09-05 INFO odoo: Starting test...\n",
                "2026-09-05 INFO odoo.tests.result: 0 failed, 0 error(s) of 5 tests\n",
            ]
            mock_proc.wait.return_value = 0

            args = argparse.Namespace(
                target="my_module",
                profile="etech",
                json=True,
            )

            with (
                patch.object(self.module, "_resolve_workspace", return_value=ctx),
                patch.object(self.module, "_ensure_runtime_pod"),
                patch.object(
                    self.module,
                    "_run",
                    side_effect=lambda cmd, **kw: mock_ps if "ps" in cmd else mock_rm,
                ),
                patch("subprocess.Popen", return_value=mock_proc),
                contextlib.redirect_stdout(io.StringIO()) as stdout,
                contextlib.redirect_stderr(io.StringIO()) as stderr,
            ):
                code = self.module.cmd_test(args)

            self.assertEqual(code, 0)
            # Live logs streamed to stderr
            self.assertIn("Starting test...", stderr.getvalue())
            # Clean JSON parseable from stdout
            json_payload = json.loads(stdout.getvalue())
            self.assertTrue(json_payload["success"])
            self.assertEqual(json_payload["target"], "my_module")
            self.assertEqual(json_payload["exit_code"], 0)


class TestStopAndDevLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_odooctl()

    def test_cmd_stop_removes_containers_and_pod(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_workspace_context(self.module, Path(tmp))
            args = argparse.Namespace(json=True)

            with (
                patch.object(self.module, "_resolve_workspace", return_value=ctx),
                patch.object(self.module, "_ensure_podman"),
                patch.object(self.module, "_run") as mock_run,
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                code = self.module.cmd_stop(args)

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "stopped")
            self.assertEqual(mock_run.call_count, 3)


if __name__ == "__main__":
    unittest.main()
