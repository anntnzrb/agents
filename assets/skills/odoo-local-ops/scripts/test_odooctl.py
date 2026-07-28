from __future__ import annotations

import contextlib
import importlib.util
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


if __name__ == "__main__":
    unittest.main()
