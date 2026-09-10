"""Unit tests for odooctl test runner, container lifecycle, and CLI subcommands."""

from __future__ import annotations

import argparse
import configparser
import contextlib
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

import odooctl
import pytest

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


class TestDatabaseAndSafetyValidation:
    """Tests for database identifier safety, query write checks, and local endpoint validation."""

    def test_is_local_container_endpoint(self) -> None:
        """Verify endpoint parser strictly validates loopback IPs/hosts without substring bypasses."""
        # Valid local endpoints
        assert (
            odooctl._is_local_container_endpoint("unix:///var/run/podman.sock") is True
        )  # pyright: ignore[reportPrivateUsage]
        assert (
            odooctl._is_local_container_endpoint("/Users/user/.podman/podman.sock")
            is True
        )  # pyright: ignore[reportPrivateUsage]
        assert (
            odooctl._is_local_container_endpoint(
                "ssh://core@127.0.0.1:52134/podman.sock"
            )
            is True
        )  # pyright: ignore[reportPrivateUsage]
        assert (
            odooctl._is_local_container_endpoint("ssh://core@[::1]:52134/podman.sock")
            is True
        )  # pyright: ignore[reportPrivateUsage]
        assert odooctl._is_local_container_endpoint("tcp://localhost:2999") is True  # pyright: ignore[reportPrivateUsage]

        # Untrusted/remote endpoints (including substring deception attempts)
        assert (
            odooctl._is_local_container_endpoint(
                "ssh://127.0.0.1@evil.com:22/podman.sock"
            )
            is False
        )  # pyright: ignore[reportPrivateUsage]
        assert (
            odooctl._is_local_container_endpoint("tcp://localhost.evil.com:2999")
            is False
        )  # pyright: ignore[reportPrivateUsage]
        assert (
            odooctl._is_local_container_endpoint(
                "ssh://user@192.168.1.50:22/podman.sock"
            )
            is False
        )  # pyright: ignore[reportPrivateUsage]
        assert odooctl._is_local_container_endpoint("tcp://10.0.0.1:2999") is False  # pyright: ignore[reportPrivateUsage]

    def test_validate_db_name_accepts_valid_names(self) -> None:
        """Verify alphanumeric, underscore, and hyphen database names pass."""
        assert odooctl._validate_db_name("erptech_0908") == "erptech_0908"  # pyright: ignore[reportPrivateUsage]
        assert odooctl._validate_db_name("erptech-crm") == "erptech-crm"  # pyright: ignore[reportPrivateUsage]
        assert odooctl._validate_db_name("test_123") == "test_123"  # pyright: ignore[reportPrivateUsage]

    def test_validate_db_name_rejects_malicious_inputs(self) -> None:
        """Verify SQL injection, newlines, and path traversal attempts in db names raise CliError."""
        for bad in (
            "",
            "db\n",
            "db\r\n",
            "db; DROP TABLE res_partner;",
            "db' OR '1'='1",
            'db" WITH TEMPLATE',
            "../../etc/passwd",
            "db name with spaces",
            "db/slash",
        ):
            with pytest.raises(odooctl.CliError):
                _ = odooctl._validate_db_name(bad)  # pyright: ignore[reportPrivateUsage]

    def test_cmd_db_clone_rejects_identical_source_and_target(self) -> None:
        """Verify cloning database to itself raises CliError before runtime execution."""
        args = argparse.Namespace(
            source="erptech_test",
            target="erptech_test",
            force=True,
            json=False,
        )
        with pytest.raises(odooctl.CliError, match="cannot be identical"):
            _ = odooctl.cmd_db_clone(args)

    def test_load_workflow_profile_rejects_path_traversal(self) -> None:
        """Verify path traversal in profile names raises CliError."""
        for bad_prof in ("../etc/passwd", "../../secret", "sub/folder"):
            with pytest.raises(odooctl.CliError):
                _ = odooctl._load_workflow_profile(bad_prof, "crm")  # pyright: ignore[reportPrivateUsage]

    def test_cmd_db_query_blocks_multi_statements_without_unsafe(self) -> None:
        """Verify chained multi-statement queries are blocked when --unsafe is False."""
        args = argparse.Namespace(
            sql="SELECT 1; DELETE FROM res_partner;",
            db="erptech_test",
            unsafe=False,
            json=False,
        )
        with pytest.raises(
            odooctl.CliError, match="Multi-statement queries are blocked"
        ):
            _ = odooctl.cmd_db_query(args)

    def test_exec_sql_json_decodes_rows(self) -> None:
        """Verify _exec_sql_json parses JSON array into list of dicts."""
        mock_raw = '[{"id": 1, "name": "Admin"}, {"id": 2, "name": "User"}]'
        with patch.object(odooctl, "_exec_sql", return_value=mock_raw):
            rows = odooctl._exec_sql_json("SELECT id, name FROM res_users")  # pyright: ignore[reportPrivateUsage]
        assert len(rows) == 2
        assert rows[0]["id"] == 1
        assert rows[1]["name"] == "User"

    def test_invalid_database_output_cannot_look_like_empty_audit(self) -> None:
        """Reject corrupt or non-record output rather than reporting zero rows."""
        for raw in ("", "ERROR: denied", "null", "[1]", '{"id": 1}'):
            with (
                patch.object(odooctl, "_exec_sql", return_value=raw),
                pytest.raises(odooctl.CliError, match="Database query"),
            ):
                odooctl._exec_sql_json("SELECT id FROM res_users")

    def test_ensure_podman_checks_container_host(self) -> None:
        """Verify _ensure_podman accepts local sockets/machine and rejects external remote hosts."""
        with patch("shutil.which", return_value="/usr/bin/podman"):
            # Local endpoints pass
            for local_uri in (
                "unix:///Users/user/.local/share/containers/podman/machine/podman.sock",
                "ssh://core@127.0.0.1:52134/run/user/501/podman/podman.sock",
                "tcp://localhost:2999",
            ):
                with patch.dict(os.environ, {"CONTAINER_HOST": local_uri}):
                    odooctl._ensure_podman()  # pyright: ignore[reportPrivateUsage]

            # Remote endpoints rejected
            for remote_uri in (
                "ssh://user@192.168.1.50:22/run/podman/podman.sock",
                "tcp://remote-odoo-server.internal:2999",
            ):
                with (
                    patch.dict(os.environ, {"CONTAINER_HOST": remote_uri}),
                    pytest.raises(
                        odooctl.CliError, match="Remote Podman host detected"
                    ),
                ):
                    odooctl._ensure_podman()  # pyright: ignore[reportPrivateUsage]

    def test_saved_remote_connection_is_rejected(self) -> None:
        """Reject a saved production connection even without CONTAINER_HOST."""
        metadata = json.dumps(
            [
                {
                    "Name": "production",
                    "Default": True,
                    "URI": "ssh://ops@remote.example/podman.sock",
                }
            ]
        )
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("shutil.which", return_value="/usr/bin/podman"),
            patch.object(
                odooctl,
                "_run",
                return_value=subprocess.CompletedProcess([], 0, metadata),
            ),
            pytest.raises(odooctl.CliError, match="Remote Podman host"),
        ):
            odooctl._ensure_podman()
