"""Unit tests for odooctl test runner, container lifecycle, and CLI subcommands."""

from __future__ import annotations

import argparse
import base64
import configparser
import contextlib
import email.message
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
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

    def test_zero_test_run_is_not_success(self) -> None:
        """Verify a run that executed no tests never reports success."""
        output = (
            "2026-09-15 00:51:38,529 1 WARNING erptech "
            "odoo.tests.result: 0 failed, 0 error(s) of 0 tests when loading "
            "database 'erptech'\n"
        )
        passed, summary = odooctl._evaluate_odoo_test_result(0, output)  # pyright: ignore[reportPrivateUsage]
        assert not passed
        assert any("of 0 tests" in line for line in summary)


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


class TestCmdLint:
    """Tests for cmd_lint integrating Ruff and XML view linter."""

    def test_cmd_lint_success_on_clean_module(self) -> None:
        """Verify cmd_lint returns 0 when both Ruff and XML view linter pass."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mod_dir = tmp_path / "mock_mod"
            views_dir = mod_dir / "views"
            views_dir.mkdir(parents=True)
            xml_file = views_dir / "clean_view.xml"
            xml_file.write_text(
                """<odoo>
                    <record id="clean_view" model="ir.ui.view">
                        <field name="arch" type="xml">
                            <tree string="Clean">
                                <field name="name"/>
                            </tree>
                        </field>
                    </record>
                </odoo>""",
                encoding="utf-8",
            )
            ctx = make_workspace_context(tmp_path)
            args = argparse.Namespace(
                target="mock_mod",
                profile="etech",
                fix=False,
                json=False,
                strict=False,
                skip_views=False,
            )
            mock_proc = MagicMock(returncode=0)
            with (
                patch.object(odooctl, "_resolve_workspace", return_value=ctx),
                patch.object(odooctl, "_resolve_target_paths", return_value=[mod_dir]),
                patch("subprocess.run", return_value=mock_proc),
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                code = odooctl.cmd_lint(args)

            assert code == 0
            assert "XML View Linter" in stdout.getvalue()

    def test_cmd_lint_fails_on_xml_critical_violation(self) -> None:
        """Verify cmd_lint returns 1 when XML view has critical violations even if Ruff returns 0."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mod_dir = tmp_path / "mock_mod"
            views_dir = mod_dir / "views"
            views_dir.mkdir(parents=True)
            xml_file = views_dir / "bad_view.xml"
            xml_file.write_text(
                """<odoo>
                    <record id="bad_view" model="ir.ui.view">
                        <field name="arch" type="xml">
                            <form string="Legacy">
                                <field name="name" attrs="{'invisible': [('state', '=', 'draft')]}"/>
                            </form>
                        </field>
                    </record>
                </odoo>""",
                encoding="utf-8",
            )
            ctx = make_workspace_context(tmp_path)
            args = argparse.Namespace(
                target="mock_mod",
                profile="etech",
                fix=False,
                json=False,
                strict=False,
                skip_views=False,
            )
            mock_proc = MagicMock(returncode=0)
            with (
                patch.object(odooctl, "_resolve_workspace", return_value=ctx),
                patch.object(odooctl, "_resolve_target_paths", return_value=[mod_dir]),
                patch("subprocess.run", return_value=mock_proc),
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                code = odooctl.cmd_lint(args)

            assert code == 1
            assert "ODOO_XML_001" in stdout.getvalue()

    def test_cmd_lint_skip_views(self) -> None:
        """Verify cmd_lint with --skip-views only runs Ruff and ignores XML files."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mod_dir = tmp_path / "mock_mod"
            mod_dir.mkdir(parents=True)
            args = argparse.Namespace(
                target="mock_mod",
                profile="etech",
                fix=False,
                json=False,
                strict=False,
                skip_views=True,
            )
            mock_proc = MagicMock(returncode=0)
            with (
                patch.object(odooctl, "_resolve_target_paths", return_value=[mod_dir]),
                patch("subprocess.run", return_value=mock_proc),
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                code = odooctl.cmd_lint(args)

            assert code == 0
            assert "XML View Linter" not in stdout.getvalue()

    def test_cmd_lint_json_mode(self) -> None:
        """Verify cmd_lint with --json outputs combined python and view violations."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mod_dir = tmp_path / "mock_mod"
            views_dir = mod_dir / "views"
            views_dir.mkdir(parents=True)
            xml_file = views_dir / "clean_view.xml"
            xml_file.write_text(
                """<odoo>
                    <record id="clean_view" model="ir.ui.view">
                        <field name="arch" type="xml">
                            <tree string="Clean">
                                <field name="name"/>
                            </tree>
                        </field>
                    </record>
                </odoo>""",
                encoding="utf-8",
            )
            ctx = make_workspace_context(tmp_path)
            args = argparse.Namespace(
                target="mock_mod",
                profile="etech",
                fix=False,
                json=True,
                strict=False,
                skip_views=False,
            )
            mock_proc = MagicMock(returncode=0, stdout="[]")
            with (
                patch.object(odooctl, "_resolve_workspace", return_value=ctx),
                patch.object(odooctl, "_resolve_target_paths", return_value=[mod_dir]),
                patch("subprocess.run", return_value=mock_proc),
                contextlib.redirect_stdout(io.StringIO()) as stdout,
            ):
                code = odooctl.cmd_lint(args)

            assert code == 0
            payload = cast("dict[str, object]", json.loads(stdout.getvalue()))
            assert payload["success"] is True
            assert payload["total_view_violations"] == 0
            assert payload["total_python_violations"] == 0


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


class TestDbReplicaMaintenance:
    """Tests for filestore-aware cloning, uuid handling, and dump restores."""

    def test_filestore_path_uses_runtime_data_dir(self, tmp_path: Path) -> None:
        """Verify the filestore path resolves inside the runtime data directory."""
        ctx = make_workspace_context(tmp_path)
        path = odooctl._filestore_path(ctx, "prod_work_20260101")  # pyright: ignore[reportPrivateUsage]
        expected = (
            ctx.runtime
            / "data"
            / "web"
            / ".local"
            / "share"
            / "Odoo"
            / "filestore"
            / "prod_work_20260101"
        )
        assert path == expected

    def test_regenerate_db_uuid_deletes_parameter(self) -> None:
        """Verify uuid regeneration deletes the copied config parameter."""
        with patch.object(odooctl, "_exec_sql") as exec_sql:
            odooctl._regenerate_db_uuid("seed")  # pyright: ignore[reportPrivateUsage]
        statement = exec_sql.call_args.args[0]
        assert statement == (
            "DELETE FROM ir_config_parameter WHERE key = 'database.uuid';"
        )
        assert exec_sql.call_args.kwargs["db"] == "seed"

    def test_copy_filestore_warns_when_source_is_missing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify a missing source filestore warns instead of failing the clone."""
        ctx = make_workspace_context(tmp_path)
        copied = odooctl._copy_filestore(ctx, "seed", "work")  # pyright: ignore[reportPrivateUsage]
        assert not copied
        assert "no filestore" in capsys.readouterr().out

    def test_copy_filestore_copies_existing_directory(self, tmp_path: Path) -> None:
        """Verify an existing filestore is copied file by file."""
        ctx = make_workspace_context(tmp_path)
        from_fs = odooctl._filestore_path(ctx, "seed")  # pyright: ignore[reportPrivateUsage]
        from_fs.mkdir(parents=True)
        _ = (from_fs / "attachment").write_text("payload")
        assert odooctl._copy_filestore(ctx, "seed", "work")  # pyright: ignore[reportPrivateUsage]
        to_fs = odooctl._filestore_path(ctx, "work")  # pyright: ignore[reportPrivateUsage]
        assert (to_fs / "attachment").read_text() == "payload"

    def test_cmd_db_clone_copies_filestore_and_regenerates_uuid(
        self, tmp_path: Path
    ) -> None:
        """Verify db-clone carries the filestore and drops the copied uuid."""
        ctx = make_workspace_context(tmp_path)
        seed_fs = odooctl._filestore_path(ctx, "seed")  # pyright: ignore[reportPrivateUsage]
        seed_fs.mkdir(parents=True)
        _ = (seed_fs / "attachment").write_text("payload")
        args = argparse.Namespace(source="seed", target="work", force=True, json=False)
        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(odooctl, "_exec_sql") as exec_sql,
        ):
            assert odooctl.cmd_db_clone(args) == 0
        statements = [call.args[0] for call in exec_sql.call_args_list]
        assert any("CREATE DATABASE" in statement for statement in statements)
        assert any(
            statement.startswith("DELETE FROM ir_config_parameter")
            for statement in statements
        )
        work_fs = odooctl._filestore_path(ctx, "work")  # pyright: ignore[reportPrivateUsage]
        assert (work_fs / "attachment").read_text() == "payload"

    def test_cmd_db_restore_requires_force_when_target_exists(
        self, tmp_path: Path
    ) -> None:
        """Verify restoring over an existing database demands an explicit --force."""
        ctx = make_workspace_context(tmp_path)
        dump = tmp_path / "replica.sql.gz"
        _ = dump.write_bytes(b"")
        args = argparse.Namespace(
            dump=str(dump), target="work", force=False, json=False
        )
        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(odooctl, "_exec_sql_json", return_value=[{"datname": "work"}]),
            pytest.raises(odooctl.CliError, match="already exists"),
        ):
            _ = odooctl.cmd_db_restore(args)

    def test_cmd_db_restore_rejects_unknown_dump_format(self, tmp_path: Path) -> None:
        """Verify Odoo backup archives are rejected with actionable guidance."""
        dump = tmp_path / "backup.zip"
        _ = dump.write_bytes(b"")
        args = argparse.Namespace(
            dump=str(dump), target="work", force=False, json=False
        )
        with pytest.raises(odooctl.CliError, match="Unsupported dump format"):
            _ = odooctl.cmd_db_restore(args)


class TestDatabaseResolution:
    """Tests for database resolution precedence and missing database handling."""

    def test_flag_precedence_over_all(self, tmp_path: Path) -> None:
        """Verify --db CLI flag overrides environment, profile, and odoo.conf."""
        conf = configparser.ConfigParser()
        conf.add_section("options")
        conf.set("options", "db_name", "conf_db")
        args = argparse.Namespace(db="flag_db", profile="etech")
        with patch.dict(os.environ, {"POSTGRES_DB": "env_db"}):
            db, source = odooctl._resolve_effective_database(  # pyright: ignore[reportPrivateUsage]
                args, profile_name="etech", config=conf
            )
        assert db == "flag_db"
        assert source == "flag"

    def test_env_precedence_over_profile_and_conf(self) -> None:
        """Verify POSTGRES_DB environment variable overrides profile and odoo.conf."""
        conf = configparser.ConfigParser()
        conf.add_section("options")
        conf.set("options", "db_name", "conf_db")
        args = argparse.Namespace(db=None, profile="etech")
        with patch.dict(os.environ, {"POSTGRES_DB": "env_db"}):
            db, source = odooctl._resolve_effective_database(  # pyright: ignore[reportPrivateUsage]
                args, profile_name="etech", config=conf
            )
        assert db == "env_db"
        assert source == "env"

    def test_profile_precedence_over_conf(self, tmp_path: Path) -> None:
        """Verify profile default workflow database overrides odoo.conf."""
        prof_file = tmp_path / "mockprof.json"
        prof_file.write_text(
            json.dumps({"workflows": {"crm": {"database": "profile_db"}}}),
            encoding="utf-8",
        )
        conf = configparser.ConfigParser()
        conf.add_section("options")
        conf.set("options", "db_name", "conf_db")
        args = argparse.Namespace(db=None, profile="mockprof")
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(odooctl, "PROFILE_DIR", tmp_path),
        ):
            db, source = odooctl._resolve_effective_database(  # pyright: ignore[reportPrivateUsage]
                args, profile_name="mockprof", config=conf
            )
        assert db == "profile_db"
        assert source == "profile"

    def test_conf_precedence_when_no_flag_env_profile(self, tmp_path: Path) -> None:
        """Verify odoo.conf db_name is used when flag, env, and profile are missing."""
        conf = configparser.ConfigParser()
        conf.add_section("options")
        conf.set("options", "db_name", "conf_db")
        args = argparse.Namespace(db=None, profile="missing")
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(odooctl, "PROFILE_DIR", tmp_path),
        ):
            db, source = odooctl._resolve_effective_database(  # pyright: ignore[reportPrivateUsage]
                args, profile_name="missing", config=conf
            )
        assert db == "conf_db"
        assert source == "odoo.conf"

    def test_unresolved_database_raises_usage_error_code_2(
        self, tmp_path: Path
    ) -> None:
        """Verify missing database resolution raises CliError with exit code 2."""
        conf = configparser.ConfigParser()
        args = argparse.Namespace(db=None, profile="missing")
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(odooctl, "PROFILE_DIR", tmp_path),
            pytest.raises(odooctl.CliError) as exc_info,
        ):
            _ = odooctl._resolve_effective_database(  # pyright: ignore[reportPrivateUsage]
                args, profile_name="missing", config=conf, require=True
            )
        assert exc_info.value.code == 2
        assert "please set the profile database" in str(exc_info.value)

    def test_odoo_replica_never_appears(self) -> None:
        """Verify 'odoo_replica' literal fallback is completely removed."""
        source_code = Path(odooctl.__file__).read_text(encoding="utf-8")
        assert "odoo_replica" not in source_code


class TestDbQueryInputAndOutput:
    """Tests for db-query file/stdin input, mutation formatting, and JSON contracts."""

    def test_db_query_reads_from_file(self, tmp_path: Path) -> None:
        """Verify db-query reads SQL from --file."""
        sql_file = tmp_path / "test.sql"
        sql_file.write_text("SELECT 42;", encoding="utf-8")
        args = argparse.Namespace(
            file=str(sql_file), sql=None, unsafe=False, json=False, db=None
        )
        ctx = make_workspace_context(tmp_path)
        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(odooctl, "_exec_sql", return_value="42") as exec_sql,
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            assert odooctl.cmd_db_query(args) == 0
        assert exec_sql.call_args[0][0] == "SELECT 42;"
        assert "42" in stdout.getvalue()

    def test_db_query_reads_from_stdin_via_dash(self, tmp_path: Path) -> None:
        """Verify db-query reads SQL from stdin when '-' is passed."""
        args = argparse.Namespace(file="-", sql=None, unsafe=False, json=False, db=None)
        ctx = make_workspace_context(tmp_path)
        with (
            patch("sys.stdin", io.StringIO("SELECT 100;")),
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(odooctl, "_exec_sql", return_value="100"),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            assert odooctl.cmd_db_query(args) == 0
        assert "100" in stdout.getvalue()

    def test_db_query_mutation_without_returning_emits_status_rows(
        self, tmp_path: Path
    ) -> None:
        """Verify DML mutation without RETURNING is not wrapped in subselect."""
        args = argparse.Namespace(
            sql="UPDATE res_partner SET name = 'foo';",
            file=None,
            unsafe=True,
            json=True,
            db=None,
        )
        ctx = make_workspace_context(tmp_path)
        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(odooctl, "_exec_sql", return_value="UPDATE 1\n") as exec_sql,
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            assert odooctl.cmd_db_query(args) == 0
        executed_sql = exec_sql.call_args[0][0]
        assert not executed_sql.startswith("SELECT COALESCE(json_agg")
        payload = cast("dict[str, object]", json.loads(stdout.getvalue()))
        assert payload["ok"] is True
        assert payload["status"] == "UPDATE 1"
        assert payload["rows"] == []

    def test_db_query_mutation_with_returning_emits_ok_and_rows(
        self, tmp_path: Path
    ) -> None:
        """Verify DML mutation with RETURNING wraps with CTE and returns rows."""
        args = argparse.Namespace(
            sql="INSERT INTO res_partner (name) VALUES ('bar') RETURNING id, name;",
            file=None,
            unsafe=True,
            json=True,
            db=None,
        )
        ctx = make_workspace_context(tmp_path)
        mock_raw = '[{"id": 1, "name": "bar"}]'
        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(odooctl, "_exec_sql", return_value=mock_raw) as exec_sql,
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            assert odooctl.cmd_db_query(args) == 0
        executed_sql = exec_sql.call_args[0][0]
        assert executed_sql.startswith("WITH _r AS")
        assert "RETURNING id, name" in executed_sql
        payload = cast("dict[str, object]", json.loads(stdout.getvalue()))
        assert payload["ok"] is True
        assert payload["status"] == "SUCCESS"
        assert payload["rows"] == [{"id": 1, "name": "bar"}]

    def test_db_query_error_in_json_mode_emits_ok_false(self, tmp_path: Path) -> None:
        """Verify database errors in JSON mode emit ok: false and non-zero exit."""
        args = argparse.Namespace(
            sql="SELECT syntax error;",
            file=None,
            unsafe=False,
            json=True,
            db=None,
        )
        ctx = make_workspace_context(tmp_path)
        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(
                odooctl,
                "_exec_sql_json",
                side_effect=odooctl.CliError("syntax error at or near 'error'", code=1),
            ),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = odooctl.cmd_db_query(args)
        assert code == 1
        payload = cast("dict[str, object]", json.loads(stdout.getvalue()))
        assert payload["ok"] is False
        assert "syntax error" in str(payload["error"])


class TestCmdShell:
    """Tests for the shell subcommand running Python ORM code."""

    def test_shell_refuses_seed_db(self, tmp_path: Path) -> None:
        """Verify shell refuses to run against a database containing '_seed_'."""
        ctx = make_workspace_context(tmp_path)
        ctx.effective_db_name = "erptech_seed_20260908"
        args = argparse.Namespace(
            db="erptech_seed_20260908", file="test.py", rollback=False
        )
        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            pytest.raises(odooctl.CliError) as exc_info,
        ):
            _ = odooctl.cmd_shell(args)
        assert exc_info.value.code == 2
        assert "untouchable seed database" in str(exc_info.value)

    def test_shell_appends_commit_by_default(self, tmp_path: Path) -> None:
        """Verify shell appends env.cr.commit() by default."""
        script_file = tmp_path / "script.py"
        script_file.write_text("print(env.user.name)", encoding="utf-8")
        ctx = make_workspace_context(tmp_path)
        args = argparse.Namespace(
            db="erptech_work_20260908", file=str(script_file), rollback=False
        )
        mock_run_proc = subprocess.CompletedProcess([], 0, "odoo-web\n")
        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_podman"),
            patch.object(odooctl, "_run", return_value=mock_run_proc),
            patch(
                "subprocess.run", return_value=MagicMock(returncode=0)
            ) as mock_subproc,
        ):
            code = odooctl.cmd_shell(args)
        assert code == 0
        passed_input = mock_subproc.call_args.kwargs["input"]
        assert "env.cr.commit()" in passed_input
        assert "env.cr.rollback()" not in passed_input

    def test_shell_appends_rollback_with_flag(self, tmp_path: Path) -> None:
        """Verify shell appends env.cr.rollback() when --rollback is set."""
        script_file = tmp_path / "script.py"
        script_file.write_text("print(env.user.name)", encoding="utf-8")
        ctx = make_workspace_context(tmp_path)
        args = argparse.Namespace(
            db="erptech_work_20260908", file=str(script_file), rollback=True
        )
        mock_run_proc = subprocess.CompletedProcess([], 0, "odoo-web\n")
        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_podman"),
            patch.object(odooctl, "_run", return_value=mock_run_proc),
            patch(
                "subprocess.run", return_value=MagicMock(returncode=0)
            ) as mock_subproc,
        ):
            code = odooctl.cmd_shell(args)
        assert code == 0
        passed_input = mock_subproc.call_args.kwargs["input"]
        assert "env.cr.rollback()" in passed_input
        assert "env.cr.commit()" not in passed_input

    def test_shell_fails_when_web_container_not_running(self, tmp_path: Path) -> None:
        """Verify shell fails with code 1 if odoo-web container is not running."""
        script_file = tmp_path / "script.py"
        script_file.write_text("print(1)", encoding="utf-8")
        ctx = make_workspace_context(tmp_path)
        args = argparse.Namespace(
            db="erptech_work_20260908", file=str(script_file), rollback=False
        )
        mock_run_proc = subprocess.CompletedProcess([], 0, "")
        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_podman"),
            patch.object(odooctl, "_run", return_value=mock_run_proc),
            pytest.raises(odooctl.CliError) as exc_info,
        ):
            _ = odooctl.cmd_shell(args)
        assert exc_info.value.code == 1
        assert "Please start the development server first" in str(exc_info.value)


class TestCmdHealth:
    """Tests for health probe command."""

    def test_health_returns_0_when_status_200_and_uses_127_0_0_1(self) -> None:
        """Verify health checks 127.0.0.1 and returns 0 when 200 OK."""
        args = argparse.Namespace(port=8069, wait=0, json=False)
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        with (
            patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen,
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = odooctl.cmd_health(args)
        assert code == 0
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://127.0.0.1:8069/web/login"
        assert "ready 200" in stdout.getvalue()

    def test_health_returns_1_when_non_200(self) -> None:
        """Verify health returns 1 when HTTP status is not 200."""
        args = argparse.Namespace(port=8069, wait=0, json=False)
        mock_err = urllib.error.HTTPError(
            "http://127.0.0.1:8069/web/login",
            500,
            "Internal Server Error",
            email.message.Message(),
            None,
        )
        with (
            patch("urllib.request.urlopen", side_effect=mock_err),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = odooctl.cmd_health(args)
        assert code == 1
        assert "not ready: HTTP 500" in stdout.getvalue()

    def test_health_json_output(self) -> None:
        """Verify health emits structured JSON in --json mode."""
        args = argparse.Namespace(port=8069, wait=0, json=True)
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        with (
            patch("urllib.request.urlopen", return_value=mock_resp),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = odooctl.cmd_health(args)
        assert code == 0
        payload = cast("dict[str, object]", json.loads(stdout.getvalue()))
        assert payload["ready"] is True
        assert payload["status"] == 200
        assert payload["url"] == "http://127.0.0.1:8069/web/login"


class TestCmdLogsAndPrune:
    """Tests for logs container selection and test container pruning."""

    def test_logs_container_test_picks_newest_odoo_test(self) -> None:
        """Verify logs --container test selects the newest odoo-test container."""
        json_output = json.dumps(
            [
                {"Names": ["/odoo-test-old"], "Created": 1000},
                {"Names": ["/odoo-test-new"], "Created": 2000},
            ]
        )
        mock_ps = subprocess.CompletedProcess([], 0, json_output)
        args = argparse.Namespace(tail=50, follow=False, container="test")
        with (
            patch.object(odooctl, "_ensure_podman"),
            patch.object(odooctl, "_run", return_value=mock_ps),
            patch(
                "subprocess.run", return_value=MagicMock(returncode=0)
            ) as mock_subproc,
        ):
            code = odooctl.cmd_logs(args)
        assert code == 0
        cmd = mock_subproc.call_args[0][0]
        assert "odoo-test-new" in cmd

    def test_logs_container_test_error_when_no_containers(self) -> None:
        """Verify logs --container test raises CliError when no test containers exist."""
        mock_ps = subprocess.CompletedProcess([], 0, "[]")
        args = argparse.Namespace(tail=50, follow=False, container="test")
        with (
            patch.object(odooctl, "_ensure_podman"),
            patch.object(odooctl, "_run", return_value=mock_ps),
            pytest.raises(odooctl.CliError, match="No test containers found"),
        ):
            _ = odooctl.cmd_logs(args)

    def test_prune_removes_test_containers(self) -> None:
        """Verify prune command removes all odoo-test-* containers."""
        mock_ps = subprocess.CompletedProcess(
            [], 0, "odoo-test-1\nodoo-test-2\nodoo-web\n"
        )
        args = argparse.Namespace(json=True)
        with (
            patch.object(odooctl, "_ensure_podman"),
            patch.object(odooctl, "_run") as mock_run,
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            mock_run.side_effect = [mock_ps, subprocess.CompletedProcess([], 0, "")]
            code = odooctl.cmd_prune(args)
        assert code == 0
        payload = cast("dict[str, object]", json.loads(stdout.getvalue()))
        assert payload["removed"] == ["odoo-test-1", "odoo-test-2"]
        assert payload["count"] == 2


class TestCmdDbListAndDrop:
    """Tests for db-list and db-drop commands."""

    def test_db_list_returns_databases(self, tmp_path: Path) -> None:
        """Verify db-list queries databases and returns name and size."""
        ctx = make_workspace_context(tmp_path)
        mock_rows = [{"name": "espol_work", "size": "150 MB", "size_bytes": 157286400}]
        args = argparse.Namespace(json=True)
        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(odooctl, "_exec_sql_json", return_value=mock_rows),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = odooctl.cmd_db_list(args)
        assert code == 0
        assert json.loads(stdout.getvalue()) == mock_rows

    def test_db_drop_refuses_without_force(self) -> None:
        """Verify db-drop refuses to drop a database without --force."""
        args = argparse.Namespace(
            name="my_database", force=False, allow_seed=False, json=False
        )
        with pytest.raises(odooctl.CliError) as exc_info:
            _ = odooctl.cmd_db_drop(args)
        assert exc_info.value.code == 2
        assert "without --force" in str(exc_info.value)

    def test_db_drop_refuses_seed_without_allow_seed(self) -> None:
        """Verify db-drop refuses to drop a seed database without --allow-seed."""
        args = argparse.Namespace(
            name="prod_seed_20260908", force=True, allow_seed=False, json=False
        )
        with pytest.raises(odooctl.CliError) as exc_info:
            _ = odooctl.cmd_db_drop(args)
        assert exc_info.value.code == 2
        assert "Seed databases are protected" in str(exc_info.value)

    def test_db_drop_success_and_filestore_removal(self, tmp_path: Path) -> None:
        """Verify db-drop terminates connections, drops DB, and removes filestore."""
        ctx = make_workspace_context(tmp_path)
        args = argparse.Namespace(
            name="work_db", force=True, allow_seed=False, json=False
        )
        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(
                odooctl, "_exec_sql_json", return_value=[{"datname": "work_db"}]
            ),
            patch.object(odooctl, "_exec_sql") as mock_exec,
            patch.object(odooctl, "_remove_filestore", return_value=True) as mock_rm_fs,
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = odooctl.cmd_db_drop(args)
        assert code == 0
        assert mock_exec.call_count == 2
        mock_rm_fs.assert_called_once_with(ctx, "work_db")
        assert "[OK] Database dropped: work_db" in stdout.getvalue()


class TestOpLockReentrancy:
    """Tests for the internal operation lock helper."""

    def test_op_lock_reentrancy_within_same_process(self) -> None:
        """Verify _op_lock is reentrant within the same process without deadlocking."""
        assert odooctl._LOCK_STATE.depth == 0  # pyright: ignore[reportPrivateUsage]
        with odooctl._op_lock():  # pyright: ignore[reportPrivateUsage]
            assert odooctl._LOCK_STATE.depth == 1  # pyright: ignore[reportPrivateUsage]
            with odooctl._op_lock():  # pyright: ignore[reportPrivateUsage]
                assert odooctl._LOCK_STATE.depth == 2  # pyright: ignore[reportPrivateUsage]
            assert odooctl._LOCK_STATE.depth == 1  # pyright: ignore[reportPrivateUsage]
        assert odooctl._LOCK_STATE.depth == 0  # pyright: ignore[reportPrivateUsage]


class TestStopWebOnly:
    """Tests for stop --web option."""

    def test_stop_web_only_does_not_remove_pod_or_db(self) -> None:
        """Verify stop --web only stops and removes odoo-web."""
        args = argparse.Namespace(web=True, json=True)
        with (
            patch.object(odooctl, "_ensure_podman"),
            patch.object(odooctl, "_run") as mock_run,
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = odooctl.cmd_stop(args)
        assert code == 0
        run_cmds = [call.args[0] for call in mock_run.call_args_list]
        assert any("stop" in c and "odoo-web" in c for c in run_cmds)
        assert any("rm" in c and "odoo-web" in c for c in run_cmds)
        assert not any("pod" in c for c in run_cmds)
        assert not any("odoo-db" in c for c in run_cmds)
        payload = cast("dict[str, object]", json.loads(stdout.getvalue()))
        assert payload["status"] == "stopped"
        assert payload["container"] == "odoo-web"


class TestSummaryLineParsing:
    """Tests for test result count extraction."""

    def test_extract_test_counts_from_result_line(self) -> None:
        """Verify test counts are accurately extracted from Odoo result lines."""
        output = (
            "2026-09-05 03:28:50,481 1 INFO erptech "
            "odoo.tests.result: 1 failed, 2 error(s) of 117 tests\n"
        )
        counts = odooctl._extract_test_counts(output)  # pyright: ignore[reportPrivateUsage]
        assert counts == (117, 1, 2)


class TestAuthTempAndRestore:
    """Tests for auth-temp and auth-restore commands."""

    def test_passlib_pbkdf2_sha512_known_vector_and_format(self) -> None:
        """Verify _passlib_pbkdf2_sha512 matches direct derivation and format."""
        password = "temp_pass_test_123"  # noqa: S105 - test fixture
        salt = b"0123456789abcdef"
        rounds = 600000
        digest = hashlib.pbkdf2_hmac("sha512", password.encode("utf-8"), salt, rounds)
        expected_salt = (
            base64.b64encode(salt).decode("ascii").replace("+", ".").rstrip("=")
        )
        expected_checksum = (
            base64.b64encode(digest).decode("ascii").replace("+", ".").rstrip("=")
        )
        expected = f"$pbkdf2-sha512${rounds}${expected_salt}${expected_checksum}"

        computed = odooctl._passlib_pbkdf2_sha512(  # pyright: ignore[reportPrivateUsage]
            password, salt, rounds
        )
        assert computed == expected
        pattern = r"^\$pbkdf2-sha512\$600000\$[./A-Za-z0-9]+\$[./A-Za-z0-9]+$"
        assert re.fullmatch(pattern, computed) is not None
        assert "+" not in computed
        assert "=" not in computed

    def test_auth_commands_refuse_seed_db(self, tmp_path: Path) -> None:
        """Verify auth-temp and auth-restore refuse untouchable seed databases."""
        ctx = make_workspace_context(tmp_path)
        ctx.effective_db_name = "erptech_seed_20260908"
        args_temp = argparse.Namespace(
            db="erptech_seed_20260908", login=None, json=False
        )
        args_restore = argparse.Namespace(
            db="erptech_seed_20260908", login=None, json=False
        )
        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            pytest.raises(odooctl.CliError) as exc_temp,
        ):
            _ = odooctl.cmd_auth_temp(args_temp)
        assert exc_temp.value.code == 2
        assert "untouchable seed database" in str(exc_temp.value)

        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            pytest.raises(odooctl.CliError) as exc_restore,
        ):
            _ = odooctl.cmd_auth_restore(args_restore)
        assert exc_restore.value.code == 2
        assert "untouchable seed database" in str(exc_restore.value)

    def test_auth_temp_backup_written_before_update(self, tmp_path: Path) -> None:
        """Verify auth-temp writes backup JSON before executing UPDATE."""
        ctx = make_workspace_context(tmp_path)
        ctx.effective_db_name = "erptech_work"
        args = argparse.Namespace(db="erptech_work", login=None, json=False)
        call_order: list[str] = []

        def mock_write(path: Path, content: str) -> None:
            call_order.append("write_backup")

        def mock_exec(sql: str, **_kw: object) -> str:
            if "UPDATE res_users" in sql:
                call_order.append("exec_update")
            return ""

        fake_rows = [{"id": 2, "login": "admin", "password": "original_hash"}]

        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(odooctl, "_get_state_dir", return_value=tmp_path / "state"),
            patch.object(odooctl, "_exec_sql_json", return_value=fake_rows),
            patch.object(odooctl, "_write_file_0600", side_effect=mock_write),
            patch.object(odooctl, "_exec_sql", side_effect=mock_exec),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = odooctl.cmd_auth_temp(args)

        assert code == 0
        assert call_order == ["write_backup", "exec_update"]
        out = stdout.getvalue()
        assert "Login:    admin" in out
        assert "restore with: cli.py auth-restore --db erptech_work" in out

    def test_auth_temp_existing_backup_not_overwritten(self, tmp_path: Path) -> None:
        """Verify auth-temp reuses existing backup without overwriting it."""
        ctx = make_workspace_context(tmp_path)
        ctx.effective_db_name = "erptech_work"
        args = argparse.Namespace(db="erptech_work", login=None, json=False)
        state_dir = tmp_path / "state"
        auth_dir = state_dir / "auth"
        auth_dir.mkdir(parents=True)
        backup_file = auth_dir / "erptech_work__2.json"
        original_backup = {
            "db": "erptech_work",
            "user_id": 2,
            "login": "admin",
            "password_hash": "pre_existing_hash",
            "created_at": "2026-09-26T00:00:00Z",
        }
        backup_file.write_text(json.dumps(original_backup), encoding="utf-8")

        fake_rows = [{"id": 2, "login": "admin", "password": "current_temp_hash"}]
        mock_write = MagicMock()

        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(odooctl, "_get_state_dir", return_value=state_dir),
            patch.object(odooctl, "_exec_sql_json", return_value=fake_rows),
            patch.object(odooctl, "_write_file_0600", mock_write),
            patch.object(odooctl, "_exec_sql", return_value=""),
        ):
            code = odooctl.cmd_auth_temp(args)

        assert code == 0
        mock_write.assert_not_called()
        assert json.loads(backup_file.read_text(encoding="utf-8")) == original_backup

    def test_auth_restore_verifies_then_deletes_backup(self, tmp_path: Path) -> None:
        """Verify auth-restore restores password, verifies it, then removes backup."""
        ctx = make_workspace_context(tmp_path)
        ctx.effective_db_name = "erptech_work"
        args = argparse.Namespace(db="erptech_work", login=None, json=False)
        state_dir = tmp_path / "state"
        auth_dir = state_dir / "auth"
        auth_dir.mkdir(parents=True)
        backup_file = auth_dir / "erptech_work__2.json"
        backup_file.write_text(
            json.dumps(
                {
                    "db": "erptech_work",
                    "user_id": 2,
                    "login": "admin",
                    "password_hash": "original_secret_hash",
                    "created_at": "2026-09-26T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )

        trace: list[str] = []

        def mock_exec(sql: str, **_kw: object) -> str:
            if "UPDATE res_users" in sql:
                trace.append("update")
            return ""

        def mock_exec_json(sql: str, **_kw: object) -> list[dict[str, object]]:
            if "SELECT password" in sql:
                trace.append("verify_select")
                return [{"password": "original_secret_hash"}]
            return [{"id": 2, "login": "admin"}]

        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(odooctl, "_get_state_dir", return_value=state_dir),
            patch.object(odooctl, "_exec_sql_json", side_effect=mock_exec_json),
            patch.object(odooctl, "_exec_sql", side_effect=mock_exec),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = odooctl.cmd_auth_restore(args)

        assert code == 0
        assert trace == ["update", "verify_select"]
        assert not backup_file.exists()
        assert "restored admin on erptech_work" in stdout.getvalue()

    def test_auth_restore_without_backup_exits_1(self, tmp_path: Path) -> None:
        """Verify auth-restore exits 1 when no backup exists."""
        ctx = make_workspace_context(tmp_path)
        ctx.effective_db_name = "erptech_work"
        args = argparse.Namespace(db="erptech_work", login=None, json=False)
        state_dir = tmp_path / "state"
        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(odooctl, "_get_state_dir", return_value=state_dir),
            pytest.raises(odooctl.CliError) as exc_info,
        ):
            _ = odooctl.cmd_auth_restore(args)

        assert exc_info.value.code == 1
        assert "No auth backup found" in str(exc_info.value)


class TestBaselineComparison:
    """Tests for test --baseline comparison feature."""

    def test_parse_failed_tests_plain_and_timestamped_with_duplicates(
        self,
    ) -> None:
        """Verify _parse_failed_tests handles FAIL/ERROR lines and duplicates."""
        output = (
            "2026-09-05 03:32:36,429 1 ERROR erptech: FAIL: test_x "
            "(odoo.addons.crm.tests.test_crm.TestLead.test_x)\n"
            "FAIL: test_y (odoo.addons.crm.tests.test_crm.TestLead.test_y)\n"
            "2026-09-05 03:32:36,429 1 ERROR erptech: FAIL: TestShort.test_one\n"
            "2026-09-05 03:32:37,100 1 ERROR erptech: ERROR: test_err "
            "(odoo.addons.crm.tests.test_crm.TestLead.test_err)\n"
            "ERROR: TestShort.test_two\n"
            "2026-09-05 03:32:37,200 1 ERROR erptech: FAIL: TestShort.test_one\n"
            "2026-09-05 03:28:49,475 1 ERROR erptech odoo.modules.registry: "
            "Model budget has no table.\n"
        )
        parsed = (
            odooctl._parse_failed_tests(output)  # pyright: ignore[reportPrivateUsage]
        )
        expected = {
            "TestLead.test_x",
            "TestLead.test_y",
            "TestShort.test_one",
            "TestLead.test_err",
            "TestShort.test_two",
        }
        assert parsed == expected

    def test_baseline_set_arithmetic_new_preexisting_fixed(self) -> None:
        """Verify set arithmetic partitions test results correctly."""
        baseline_failed = {"TestA.test_1", "TestB.test_2"}
        current_failed = {"TestB.test_2", "TestC.test_3"}

        new_failures = sorted(current_failed - baseline_failed)
        preexisting = sorted(current_failed & baseline_failed)
        fixed = sorted(baseline_failed - current_failed)

        assert new_failures == ["TestC.test_3"]
        assert preexisting == ["TestB.test_2"]
        assert fixed == ["TestA.test_1"]

    def test_baseline_worktree_removal_even_when_second_run_raises(
        self, tmp_path: Path
    ) -> None:
        """Verify git worktree is cleaned up even if second test run raises."""
        ctx = make_workspace_context(tmp_path)
        args = argparse.Namespace(
            target="crm",
            profile="etech",
            json=False,
            tags=None,
            db=None,
            parallel=False,
            jobs=1,
            baseline="HEAD",
        )
        git_calls: list[list[str]] = []

        def mock_subprocess_run(cmd: list[str], **_kw: object) -> MagicMock:
            git_calls.append(cmd)
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = ""
            proc.stderr = ""
            return proc

        def mock_run_test(
            cmd: list[str], cname: str, *, json_mode: bool
        ) -> tuple[int, str]:
            if "curr" in cname:
                msg = "Crash during current test run"
                raise RuntimeError(msg)
            return 0, "odoo.tests.result: 0 failed, 0 error(s) of 5 tests\n"

        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(odooctl, "_cleanup_stale_test_containers"),
            patch.object(
                odooctl,
                "_resolve_test_targets",
                return_value=("test_db", ["/crm"], ["crm"]),
            ),
            patch("subprocess.run", side_effect=mock_subprocess_run),
            patch.object(odooctl, "_run_test_process", side_effect=mock_run_test),
            pytest.raises(RuntimeError) as exc_info,
        ):
            _ = odooctl.cmd_test(args)

        assert "Crash during current test run" in str(exc_info.value)
        flat_cmds = [" ".join(c) for c in git_calls]
        assert any("worktree remove --force" in c for c in flat_cmds)
        assert any("worktree prune" in c for c in flat_cmds)

    def test_baseline_runs_before_current_call_order(self, tmp_path: Path) -> None:
        """Verify baseline tests execute before current workspace tests."""
        ctx = make_workspace_context(tmp_path)
        args = argparse.Namespace(
            target="crm",
            profile="etech",
            json=False,
            tags=None,
            db=None,
            parallel=False,
            jobs=1,
            baseline="HEAD",
        )
        run_order: list[str] = []

        def mock_subprocess_run(cmd: list[str], **_kw: object) -> MagicMock:
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = ""
            proc.stderr = ""
            return proc

        def mock_run_test(
            cmd: list[str], cname: str, *, json_mode: bool
        ) -> tuple[int, str]:
            run_order.append(cname)
            return 0, "odoo.tests.result: 0 failed, 0 error(s) of 5 tests\n"

        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(odooctl, "_cleanup_stale_test_containers"),
            patch.object(
                odooctl,
                "_resolve_test_targets",
                return_value=("test_db", ["/crm"], ["crm"]),
            ),
            patch("subprocess.run", side_effect=mock_subprocess_run),
            patch.object(odooctl, "_run_test_process", side_effect=mock_run_test),
        ):
            code = odooctl.cmd_test(args)

        assert code == 0
        assert len(run_order) == 2
        assert run_order[0].startswith("odoo-test-base-")
        assert run_order[1].startswith("odoo-test-curr-")

    def test_baseline_exit_code_0_with_only_preexisting_failures(
        self, tmp_path: Path
    ) -> None:
        """Verify exit code 0 when all failures are pre-existing."""
        ctx = make_workspace_context(tmp_path)
        args = argparse.Namespace(
            target="crm",
            profile="etech",
            json=False,
            tags=None,
            db=None,
            parallel=False,
            jobs=1,
            baseline="HEAD",
        )

        def mock_subprocess_run(cmd: list[str], **_kw: object) -> MagicMock:
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = ""
            proc.stderr = ""
            return proc

        def mock_run_test(
            cmd: list[str], cname: str, *, json_mode: bool
        ) -> tuple[int, str]:
            fail_output = (
                "FAIL: test_old (odoo.addons.crm.tests.test_crm.TestLead.test_old)\n"
                "odoo.tests.result: 1 failed, 0 error(s) of 5 tests\n"
            )
            return 1, fail_output

        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(odooctl, "_cleanup_stale_test_containers"),
            patch.object(
                odooctl,
                "_resolve_test_targets",
                return_value=("test_db", ["/crm"], ["crm"]),
            ),
            patch("subprocess.run", side_effect=mock_subprocess_run),
            patch.object(odooctl, "_run_test_process", side_effect=mock_run_test),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = odooctl.cmd_test(args)

        assert code == 0
        out = stdout.getvalue()
        assert "new failures (0):" in out
        assert "pre-existing (1):" in out
        assert "TestLead.test_old" in out
        assert "RESULT baseline=HEAD new=0 preexisting=1 fixed=0" in out

    def test_baseline_exit_code_1_with_new_failure(self, tmp_path: Path) -> None:
        """Verify exit code 1 when there is a new failure."""
        ctx = make_workspace_context(tmp_path)
        args = argparse.Namespace(
            target="crm",
            profile="etech",
            json=False,
            tags=None,
            db=None,
            parallel=False,
            jobs=1,
            baseline="HEAD",
        )

        def mock_subprocess_run(cmd: list[str], **_kw: object) -> MagicMock:
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = ""
            proc.stderr = ""
            return proc

        def mock_run_test(
            cmd: list[str], cname: str, *, json_mode: bool
        ) -> tuple[int, str]:
            if "base" in cname:
                return 0, "odoo.tests.result: 0 failed, 0 error(s) of 5 tests\n"
            fail_output = (
                "FAIL: test_new (odoo.addons.crm.tests.test_crm.TestLead.test_new)\n"
                "odoo.tests.result: 1 failed, 0 error(s) of 5 tests\n"
            )
            return 1, fail_output

        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch.object(odooctl, "_ensure_runtime_pod"),
            patch.object(odooctl, "_cleanup_stale_test_containers"),
            patch.object(
                odooctl,
                "_resolve_test_targets",
                return_value=("test_db", ["/crm"], ["crm"]),
            ),
            patch("subprocess.run", side_effect=mock_subprocess_run),
            patch.object(odooctl, "_run_test_process", side_effect=mock_run_test),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            code = odooctl.cmd_test(args)

        assert code == 1
        out = stdout.getvalue()
        assert "new failures (1):" in out
        assert "TestLead.test_new" in out
        assert "RESULT baseline=HEAD new=1 preexisting=0 fixed=0" in out

    def test_baseline_bad_ref_exits_2(self, tmp_path: Path) -> None:
        """Verify invalid git ref raises usage error with exit code 2."""
        ctx = make_workspace_context(tmp_path)
        args = argparse.Namespace(
            target="crm",
            profile="etech",
            json=False,
            tags=None,
            db=None,
            parallel=False,
            jobs=1,
            baseline="bad-ref-123",
        )

        def mock_subprocess_run(cmd: list[str], **_kw: object) -> MagicMock:
            proc = MagicMock()
            proc.returncode = 128
            proc.stdout = ""
            proc.stderr = "fatal: Not a valid object name"
            return proc

        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            patch("subprocess.run", side_effect=mock_subprocess_run),
            pytest.raises(odooctl.CliError) as exc_info,
        ):
            _ = odooctl.cmd_test(args)

        assert exc_info.value.code == 2
        assert "Invalid baseline ref" in str(exc_info.value)

    def test_cmd_test_refuses_seed_db(self, tmp_path: Path) -> None:
        """Verify test command refuses untouchable seed database."""
        ctx = make_workspace_context(tmp_path)
        args = argparse.Namespace(
            target="crm",
            profile="etech",
            json=False,
            tags=None,
            db="prod_seed_20260908",
            parallel=False,
            jobs=1,
            baseline=None,
        )
        with (
            patch.object(odooctl, "_resolve_workspace", return_value=ctx),
            pytest.raises(odooctl.CliError) as exc_info,
        ):
            _ = odooctl.cmd_test(args)

        assert exc_info.value.code == 2
        assert "untouchable seed database" in str(exc_info.value)
