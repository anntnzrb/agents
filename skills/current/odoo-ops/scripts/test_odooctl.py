"""Unit tests for odooctl test runner, container lifecycle, and CLI subcommands."""

from __future__ import annotations

import argparse
import configparser
import contextlib
import io
import json
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

import pytest

import odooctl

if TYPE_CHECKING:
    from collections.abc import Sequence


def make_workspace_context(workspace_root: Path) -> odooctl.WorkspaceContext:
    """Create mock workspace context for testing."""
    runtime = workspace_root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    source = runtime / "source" / "odoo-17.0"
    source.mkdir(parents=True, exist_ok=True)
    (runtime / "config").mkdir(parents=True, exist_ok=True)
    (runtime / "data" / "web").mkdir(parents=True, exist_ok=True)
    config = configparser.ConfigParser()
    return odooctl.WorkspaceContext(
        root=workspace_root,
        config_path=runtime / "config" / "odoo.conf",
        config=config,
        addons_paths=[workspace_root],
        effective_db_name="erptech_test",
        runtime=runtime,
    )


class TestEvaluateOdooTestResult:
    """Tests for _evaluate_odoo_test_result parsing logic."""

    def test_successful_run_with_expected_error_logs(self) -> None:
        """Verify successful test run parses correctly despite log warnings."""
        output = (
            "2026-09-05 03:28:29,928 1 ERROR erptech "
            "odoo.addons.whatsapp_utils: Fallo interno simulado\n"
            "2026-09-05 03:28:49,475 1 ERROR erptech "
            "odoo.modules.registry: Model budget has no table.\n"
            "2026-09-05 03:28:50,481 1 INFO erptech "
            "odoo.tests.stats: whatsapp_utils: 129 tests 73.55s\n"
            "2026-09-05 03:28:50,481 1 INFO erptech "
            "odoo.tests.result: 0 failed, 0 error(s) of 117 tests\n"
        )
        passed, summary = odooctl._evaluate_odoo_test_result(0, output)  # pyright: ignore[reportPrivateUsage]
        assert passed
        assert any("0 failed, 0 error(s)" in s for s in summary)

    def test_failed_run_with_test_failure(self) -> None:
        """Verify failed test run flags failures accurately."""
        output = (
            "2026-09-05 03:32:36,429 1 ERROR erptech: FAIL: TestFoo.test_bar\n"
            "2026-09-05 03:32:37,701 1 ERROR erptech "
            "odoo.modules.loading: Module foo: 1 failures, 0 errors of 10 tests\n"
            "2026-09-05 03:32:38,000 1 ERROR erptech "
            "odoo.tests.result: 1 failed, 0 error(s) of 10 tests\n"
        )
        passed, summary = odooctl._evaluate_odoo_test_result(1, output)  # pyright: ignore[reportPrivateUsage]
        assert not passed
        assert any("1 failed" in s for s in summary)

    def test_failed_run_with_module_loading_error(self) -> None:
        """Verify module loading error marks test run as failed."""
        output = (
            "2026-09-05 03:28:50,449 1 ERROR erptech "
            "odoo.modules.loading: At least one test failed when loading the modules.\n"
        )
        passed, _ = odooctl._evaluate_odoo_test_result(0, output)  # pyright: ignore[reportPrivateUsage]
        assert not passed

    def test_nonzero_exit_code_always_fails(self) -> None:
        """Verify non-zero exit code always fails regardless of output."""
        output = "Odoo crashed during initialization"
        passed, _ = odooctl._evaluate_odoo_test_result(127, output)  # pyright: ignore[reportPrivateUsage]
        assert not passed


class TestCmdTestLifecycle:
    """Tests for cmd_test execution, cleanup, and signal handling."""

    def test_cmd_test_cleans_stale_containers_and_runs_successfully(
        self,
    ) -> None:
        """Verify cmd_test cleans prior containers and runs cleanly."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = make_workspace_context(tmp_path)
            mod_dir = tmp_path / "my_module"
            mod_dir.mkdir()

            mock_ps = subprocess.CompletedProcess(
                ["podman", "ps"],
                returncode=0,
                stdout="odoo-test-999\nodoo-web\n",
                stderr="",
            )
            mock_rm = subprocess.CompletedProcess(
                ["podman", "rm"], returncode=0, stdout="", stderr=""
            )

            mock_proc = MagicMock()
            mock_proc.stdout = [
                "Running test...\n",
                "odoo.tests.result: 0 failed, 0 error(s) of 10 tests\n",
            ]
            mock_wait = MagicMock(return_value=0)
            mock_proc.wait = mock_wait

            args = argparse.Namespace(
                target="my_module",
                profile="etech",
                json=False,
            )

            def mock_run_side_effect(
                cmd: Sequence[str], **_kw: object
            ) -> subprocess.CompletedProcess[str]:
                return mock_ps if "ps" in cmd else mock_rm

            with (
                patch.object(odooctl, "_resolve_workspace", return_value=ctx),
                patch.object(odooctl, "_ensure_runtime_pod"),
                patch.object(
                    odooctl, "_run", side_effect=mock_run_side_effect
                ) as mock_run,
                patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                code = odooctl.cmd_test(args)

            assert code == 0
            mock_popen.assert_called_once()
            # Verify stale container cleanup
            rm_calls = [
                cast("list[str]", call.args[0])
                for call in mock_run.call_args_list
                if "rm" in call.args[0]
            ]
            assert any("odoo-test-999" in cmd for cmd in rm_calls)
            assert "[OK] All Odoo unit tests passed successfully." in stdout.getvalue()

    def test_cmd_test_cleans_container_on_keyboard_interrupt(self) -> None:
        """Verify container is stopped and cleaned on SIGINT / KeyboardInterrupt."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = make_workspace_context(tmp_path)
            mod_dir = tmp_path / "my_module"
            mod_dir.mkdir()

            mock_ps = subprocess.CompletedProcess(
                ["podman", "ps"], returncode=0, stdout="", stderr=""
            )
            mock_rm = subprocess.CompletedProcess(
                ["podman", "rm"], returncode=0, stdout="", stderr=""
            )

            def raise_interrupt(*_args: object, **_kwargs: object) -> MagicMock:
                raise KeyboardInterrupt

            args = argparse.Namespace(
                target="my_module",
                profile="etech",
                json=False,
            )

            def mock_run_side_effect(
                cmd: Sequence[str], **_kw: object
            ) -> subprocess.CompletedProcess[str]:
                return mock_ps if "ps" in cmd else mock_rm

            with (
                patch.object(odooctl, "_resolve_workspace", return_value=ctx),
                patch.object(odooctl, "_ensure_runtime_pod"),
                patch.object(
                    odooctl, "_run", side_effect=mock_run_side_effect
                ) as mock_run,
                patch("subprocess.Popen", side_effect=raise_interrupt),
                pytest.raises(KeyboardInterrupt),
            ):
                _ = odooctl.cmd_test(args)

            # Verify podman stop and podman rm -f were called
            run_commands = [
                cast("list[str]", call.args[0]) for call in mock_run.call_args_list
            ]
            assert any("stop" in cmd for cmd in run_commands)
            assert any("rm" in cmd for cmd in run_commands)

    def test_cmd_test_json_mode_preserves_clean_stdout(self) -> None:
        """Verify json mode writes logs to stderr and raw json to stdout."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ctx = make_workspace_context(tmp_path)
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
            mock_wait = MagicMock(return_value=0)
            mock_proc.wait = mock_wait

            args = argparse.Namespace(
                target="my_module",
                profile="etech",
                json=True,
            )

            def mock_run_side_effect(
                cmd: Sequence[str], **_kw: object
            ) -> subprocess.CompletedProcess[str]:
                return mock_ps if "ps" in cmd else mock_rm

            with (
                patch.object(odooctl, "_resolve_workspace", return_value=ctx),
                patch.object(odooctl, "_ensure_runtime_pod"),
                patch.object(odooctl, "_run", side_effect=mock_run_side_effect),
                patch("subprocess.Popen", return_value=mock_proc),
                contextlib.redirect_stdout(io.StringIO()) as stdout,
                contextlib.redirect_stderr(io.StringIO()) as stderr,
            ):
                code = odooctl.cmd_test(args)

            assert code == 0
            # Live logs streamed to stderr
            assert "Starting test..." in stderr.getvalue()
            # Clean JSON parseable from stdout
            json_payload = cast("dict[str, object]", json.loads(stdout.getvalue()))
            assert bool(json_payload["success"]) is True
            assert json_payload["target"] == "my_module"
            assert json_payload["exit_code"] == 0


class TestStopAndDevLifecycle:
    """Tests for stack teardown and dev server lifecycle."""

    def test_cmd_stop_removes_containers_and_pod(self) -> None:
        """Verify cmd_stop tears down web, db, and pod resources."""
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_workspace_context(Path(tmp))
            args = argparse.Namespace(json=True)

            with (
                patch.object(odooctl, "_resolve_workspace", return_value=ctx),
                patch.object(odooctl, "_ensure_podman"),
                patch.object(odooctl, "_run") as mock_run,
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                code = odooctl.cmd_stop(args)

            assert code == 0
            payload = cast("dict[str, object]", json.loads(stdout.getvalue()))
            assert payload["status"] == "stopped"
            assert mock_run.call_count == 3
