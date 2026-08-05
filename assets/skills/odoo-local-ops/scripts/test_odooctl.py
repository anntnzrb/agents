from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).with_name("odooctl.py")


def load_odooctl() -> ModuleType:
    spec = importlib.util.spec_from_file_location("odooctl_contract", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load controller module: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_context(module: ModuleType, runtime_root: Path) -> object:
    runtime = module.RuntimeContext(
        backend="compose",
        root=runtime_root,
        config_path=runtime_root / "odoo.conf",
        config={},
        addons_paths=[],
        compose_command=("docker", "compose"),
    )
    return module.WorkspaceContext(
        root=runtime_root,
        config_path=runtime_root / "odoo.conf",
        config={},
        addons_paths=[],
        effective_db_name=None,
        runtime=runtime,
    )


def make_profile(module: ModuleType, *, workflow: str, database: str) -> object:
    return module.WorkflowProfile(
        profile="contract",
        workflow=workflow,
        database=database,
        modules=("crm",),
        test_modules=("crm",),
    )


class TestWorkflowContainerName(unittest.TestCase):
    def test_name_scopes_a_random_docker_safe_suffix_to_runtime_and_database(
        self,
    ) -> None:
        module = load_odooctl()
        crm = make_profile(module, workflow="crm-b2b", database="crm_b2b")
        other_database = make_profile(
            module, workflow="crm-b2b", database="crm_b2b_other"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            (runtime_root / "runtime-one").mkdir()
            (runtime_root / "runtime-two").mkdir()
            ctx = make_context(module, runtime_root / "runtime-one")
            other_runtime_ctx = make_context(module, runtime_root / "runtime-two")
            with patch.object(
                module.secrets,
                "token_hex",
                side_effect=[
                    "0123456789ab",
                    "fedcba987654",
                    "111111111111",
                    "222222222222",
                ],
            ):
                first_name = module._workflow_container_name(ctx, crm)
                second_name = module._workflow_container_name(ctx, crm)
                other_database_name = module._workflow_container_name(
                    ctx,
                    other_database,
                )
                other_runtime_name = module._workflow_container_name(
                    other_runtime_ctx,
                    crm,
                )

        self.assertTrue(first_name.startswith("odooctl-"))
        self.assertTrue(
            re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", first_name),
        )
        self.assertTrue(first_name.endswith("0123456789ab"))
        self.assertTrue(second_name.endswith("fedcba987654"))
        self.assertNotEqual(first_name, second_name)
        self.assertNotEqual(
            first_name.rsplit("-", maxsplit=1)[0],
            other_database_name.rsplit("-", maxsplit=1)[0],
        )
        self.assertNotEqual(
            first_name.rsplit("-", maxsplit=1)[0],
            other_runtime_name.rsplit("-", maxsplit=1)[0],
        )


class TestWorkflowOdooRunner(unittest.TestCase):
    def test_run_names_container_and_removes_that_exact_container_after_failure(
        self,
    ) -> None:
        module = load_odooctl()
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            ctx = make_context(module, runtime_root)
            container_name = "odooctl-crm-b2b-0123456789ab"
            odoo_args = ["python3", "-m", "odoo", "--stop-after-init"]

            cleanup_result = subprocess.CompletedProcess(
                ["docker", "container", "rm", "--force", container_name],
                returncode=0,
                stdout="",
                stderr="",
            )
            with (
                patch.object(module, "_compose_foreground", return_value=17) as compose,
                patch.object(
                    module,
                    "_run_subprocess",
                    return_value=cleanup_result,
                ) as cleanup,
            ):
                result = module._run_workflow_odoo(
                    ctx,
                    odoo_args,
                    container_name=container_name,
                )

        self.assertEqual(result, 17)
        compose.assert_called_once_with(
            ctx,
            "run",
            "--rm",
            "--no-deps",
            "--name",
            container_name,
            "odoo",
            *odoo_args,
        )
        cleanup.assert_called_once_with(
            ["docker", "container", "rm", "--force", container_name],
            cwd=runtime_root,
        )


class TestWorkflowCommand(unittest.TestCase):
    def test_command_locks_database_and_uses_only_scoped_recovery(self) -> None:
        module = load_odooctl()
        profile = make_profile(module, workflow="crm", database="etech-crm")
        args = module.argparse.Namespace(
            profile="etech",
            workflow="crm",
            allow_write=True,
            db=None,
            mode="test",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            ctx = make_context(module, Path(temp_dir))
            with (
                patch.object(module, "_load_workflow_profile", return_value=profile),
                patch.object(module, "load_workspace", return_value=ctx),
                patch.object(
                    module,
                    "_workflow_container_name",
                    return_value="odooctl-0123456789ab-fedcba987654",
                ),
                patch.object(
                    module,
                    "_workflow_database_lock",
                    return_value=contextlib.nullcontext(),
                ) as lock,
                patch.object(
                    module,
                    "_remove_stale_workflow_containers",
                    return_value=0,
                ) as scoped_cleanup,
                patch.object(module, "_compose_foreground", return_value=0) as compose,
                patch.object(module, "_run_workflow_odoo", return_value=0) as workflow,
            ):
                result = module.cmd_workflow_run(args)

        self.assertEqual(result, 0)
        lock.assert_called_once_with(ctx, "etech-crm")
        scoped_cleanup.assert_called_once_with(ctx, "etech-crm")
        self.assertFalse(hasattr(module, "_remove_stale_odoo"))
        compose.assert_called_once_with(ctx, "up", "-d", "db")
        workflow.assert_called_once_with(
            ctx,
            module._workflow_test_args(profile),
            container_name="odooctl-0123456789ab-fedcba987654",
        )


class TestWorkflowDatabaseLock(unittest.TestCase):
    def test_same_database_fails_fast_while_another_database_can_proceed(self) -> None:
        module = load_odooctl()
        with tempfile.TemporaryDirectory() as temp_dir:
            ctx = make_context(module, Path(temp_dir))

            with contextlib.ExitStack() as stack:
                stack.enter_context(module._workflow_database_lock(ctx, "crm_b2b"))
                with (
                    self.assertRaises(module.CliError),
                    module._workflow_database_lock(ctx, "crm_b2b"),
                ):
                    self.fail("the second lock acquisition must not succeed")
                with module._workflow_database_lock(ctx, "crm_b2b_other"):
                    pass


class TestDatabaseCloneCommand(unittest.TestCase):
    @staticmethod
    def clone_args(module: ModuleType, **overrides: object) -> object:
        values = {
            "source": "erptech_0730",
            "target": "erptech_0730-crm",
            "admin_db": "postgres",
            "allow_write": False,
            "replace": False,
            "confirm_target": None,
            "timeout": 1800.0,
            "json": True,
        }
        values.update(overrides)
        return module.argparse.Namespace(**values)

    @staticmethod
    def preflight(
        *, target_exists: bool, active_connections: int = 0
    ) -> dict[str, object]:
        return {
            "rows": [
                {
                    "role": "source",
                    "name": "erptech_0730",
                    "exists": "true",
                    "active_connections": "0",
                },
                {
                    "role": "target",
                    "name": "erptech_0730-crm",
                    "exists": "true" if target_exists else "false",
                    "active_connections": str(active_connections),
                },
            ],
        }

    def test_dry_run_reports_source_and_target_without_writing(self) -> None:
        module = load_odooctl()
        args = self.clone_args(module)
        ctx = make_context(module, Path(tempfile.mkdtemp()))
        with (
            patch.object(module, "load_workspace", return_value=ctx),
            patch.object(
                module,
                "_run_psql",
                return_value=self.preflight(target_exists=True),
            ) as run_psql,
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            result = module.cmd_db_clone(args)

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "dry-run")
        self.assertEqual(payload["source_database"], "erptech_0730")
        self.assertEqual(payload["target_database"], "erptech_0730-crm")
        run_psql.assert_called_once()
        self.assertTrue(run_psql.call_args.kwargs["read_only"])
        self.assertEqual(run_psql.call_args.kwargs["database"], "postgres")

    def test_write_requires_exact_target_confirmation(self) -> None:
        module = load_odooctl()
        args = self.clone_args(
            module,
            allow_write=True,
            replace=True,
            confirm_target="wrong-target",
        )
        ctx = make_context(module, Path(tempfile.mkdtemp()))
        with (
            patch.object(module, "load_workspace", return_value=ctx),
            patch.object(
                module,
                "_run_psql",
                return_value=self.preflight(target_exists=True),
            ) as run_psql,
            self.assertRaisesRegex(
                module.CliError,
                "--confirm-target must exactly match",
            ),
        ):
            module.cmd_db_clone(args)

        run_psql.assert_called_once()

    def test_replace_runs_drop_and_template_create_after_gate(self) -> None:
        module = load_odooctl()
        args = self.clone_args(
            module,
            allow_write=True,
            replace=True,
            confirm_target="erptech_0730-crm",
        )
        ctx = make_context(module, Path(tempfile.mkdtemp()))
        preflight = self.preflight(target_exists=True)
        with (
            patch.object(module, "load_workspace", return_value=ctx),
            patch.object(
                module,
                "_run_psql",
                side_effect=[preflight, {}, {}, preflight],
            ) as run_psql,
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            result = module.cmd_db_clone(args)

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "cloned")
        self.assertTrue(payload["replaced"])
        self.assertEqual(run_psql.call_count, 4)
        drop_sql = run_psql.call_args_list[1].kwargs["sql"]
        create_sql = run_psql.call_args_list[2].kwargs["sql"]
        self.assertIn('DROP DATABASE "erptech_0730-crm"', drop_sql)
        self.assertIn(
            'CREATE DATABASE "erptech_0730-crm" TEMPLATE "erptech_0730"',
            create_sql,
        )
        self.assertFalse(run_psql.call_args_list[1].kwargs["read_only"])
        self.assertFalse(run_psql.call_args_list[2].kwargs["read_only"])

    def test_active_connections_block_replace_before_writing(self) -> None:
        module = load_odooctl()
        args = self.clone_args(
            module,
            allow_write=True,
            replace=True,
            confirm_target="erptech_0730-crm",
        )
        ctx = make_context(module, Path(tempfile.mkdtemp()))
        with (
            patch.object(module, "load_workspace", return_value=ctx),
            patch.object(
                module,
                "_run_psql",
                return_value=self.preflight(target_exists=True, active_connections=1),
            ) as run_psql,
            self.assertRaisesRegex(module.CliError, "active connection"),
        ):
            module.cmd_db_clone(args)

        run_psql.assert_called_once()

    def test_database_names_cannot_be_equal_or_system_databases(self) -> None:
        module = load_odooctl()
        with self.assertRaisesRegex(module.CliError, "must differ"):
            module._validate_clone_database_names("same", "same", "postgres")
        with self.assertRaisesRegex(module.CliError, "protected"):
            module._validate_clone_database_names("postgres", "copy", "postgres")


if __name__ == "__main__":
    unittest.main()
