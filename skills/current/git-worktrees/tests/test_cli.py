# pyright: reportUninitializedInstanceVariable=false
"""End-to-end contract tests for the public git-worktrees CLI."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, TypeIs, override

if TYPE_CHECKING:
    from collections.abc import Callable

_json_loads: Callable[[str], object] = json.loads

SKILL_ROOT = Path(__file__).resolve().parents[1]
CLI = SKILL_ROOT / "scripts" / "cli.py"
SCHEMA = "git-worktrees/v1"


class _LeasePayload(TypedDict):
    lease_id: str
    path: str
    ref: str
    ready: bool
    mode: str
    state: str


class _Capabilities(TypedDict):
    owner_token: str


class _HandoffCapabilities(TypedDict):
    handoff_token: str


class _StatusResult(TypedDict):
    lease: _LeasePayload
    safe_to_release: bool


class _WorktreeEntry(TypedDict, total=False):
    path: str
    locked: str
    prunable: str


class _Finding(TypedDict):
    code: str
    details: dict[str, object]


class _ErrorDetail(TypedDict):
    code: str
    message: str
    details: dict[str, object]


def _is_str_dict(val: object) -> TypeIs[dict[str, object]]:
    return isinstance(val, dict)


def _is_lease_payload(val: object) -> TypeIs[_LeasePayload]:
    return isinstance(val, dict)


def _is_capabilities(val: object) -> TypeIs[_Capabilities]:
    return isinstance(val, dict)


def _is_handoff_capabilities(val: object) -> TypeIs[_HandoffCapabilities]:
    return isinstance(val, dict)


def _is_status_result(val: object) -> TypeIs[_StatusResult]:
    return isinstance(val, dict)


def _is_error_detail(val: object) -> TypeIs[_ErrorDetail]:
    return isinstance(val, dict)


def _is_lease_list(val: object) -> TypeIs[list[_LeasePayload]]:
    return isinstance(val, list)


def _is_worktree_list(val: object) -> TypeIs[list[_WorktreeEntry]]:
    return isinstance(val, list)


def _is_finding_list(val: object) -> TypeIs[list[_Finding]]:
    return isinstance(val, list)


class GitWorktreesCliContractTests(unittest.TestCase):
    """Exercise the wire protocol against disposable local Git repositories."""

    maxDiff: int | None = None
    temporary_directory: tempfile.TemporaryDirectory[str]
    temp_path: Path
    home: Path
    data_home: Path
    repo: Path
    base: str

    @override
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary_directory.name).resolve()
        self.home = self.temp_path / "home"
        self.home.mkdir()
        self.data_home = self.temp_path / "data-home"
        self.repo = self.temp_path / "repo"
        self.repo.mkdir()
        _ = self.git("init")
        _ = self.git("config", "user.email", "contract@example.test")
        _ = self.git("config", "user.name", "Contract Test")
        _ = (self.repo / "README.md").write_text("initial\n", encoding="utf-8")
        _ = self.git("add", "README.md")
        _ = self.git("commit", "-m", "initial")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

    @override
    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def git(
        self, *args: str, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            check=True,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            },
        )

    def cli(
        self, *args: str, use_xdg_default: bool = False
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        environment = {
            **os.environ,
            "HOME": str(self.home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
        if use_xdg_default:
            _ = environment.pop("XDG_DATA_HOME", None)
        else:
            environment["XDG_DATA_HOME"] = str(self.data_home)
        completed = subprocess.run(
            ["uv", "run", "--script", str(CLI), *args],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
            check=False,
        )
        lines = completed.stdout.splitlines()
        self.assertEqual(
            len(lines),
            1,
            f"CLI stdout must be one JSON line; stderr={completed.stderr!r}",
        )
        try:
            raw_payload = _json_loads(lines[0])
        except json.JSONDecodeError as error:
            self.fail(f"CLI stdout was not JSON: {error}: {lines[0]!r}")
        assert _is_str_dict(raw_payload)
        payload = raw_payload
        self.assertEqual(payload.get("schema"), SCHEMA)
        return completed, payload

    def success(self, *args: str) -> dict[str, object]:
        completed, payload = self.cli(*args)
        self.assertEqual(completed.returncode, 0, payload)
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(payload.get("type"), "response")
        self.assertIsInstance(payload.get("command"), str)
        res = payload.get("result")
        assert _is_str_dict(res)
        self.assertEqual(payload.get("warnings"), [])
        return res

    def refusal(self, *args: str) -> _ErrorDetail:
        completed, payload = self.cli(*args)
        self.assertEqual(completed.returncode, 3, payload)
        self.assertFalse(payload.get("ok"), payload)
        self.assertEqual(payload.get("type"), "error")
        error = payload.get("error")
        assert _is_error_detail(error)
        self.assertRegex(str(error.get("code")), r"^[a-z][a-z0-9_]*$")
        self.assertIsInstance(error.get("message"), str)
        self.assertIsInstance(error.get("details"), dict)
        return error

    def acquire(
        self,
        name: str,
        *,
        owner: str = "owner",
        setup_argv: list[str] | None = None,
    ) -> tuple[_LeasePayload, str]:
        arguments = [
            "acquire",
            "--repo",
            str(self.repo),
            "--owner",
            owner,
            "--session-actor",
            f"{owner}-session",
            "--task",
            "contract test",
            "--name",
            name,
            "--mode",
            "new-branch",
            "--base",
            self.base,
        ]
        if setup_argv is not None:
            arguments.extend(["--setup-argv", json.dumps(setup_argv)])
        result = self.success(*arguments)
        lease = result["lease"]
        capabilities = result["capabilities"]
        assert _is_lease_payload(lease)
        assert _is_capabilities(capabilities)
        token = capabilities["owner_token"]
        self.assertIsInstance(token, str)
        self.assertTrue(token)
        return lease, token

    def status(self, lease_id: str) -> _StatusResult:
        result: object = self.success("status", "--lease-id", lease_id)
        assert _is_status_result(result)
        self.assertIsInstance(result.get("lease"), dict)
        self.assertIsInstance(result.get("safe_to_release"), bool)
        return result

    def lease_path(self, lease: _LeasePayload) -> Path:
        path = lease.get("path")
        self.assertIsInstance(path, str)
        return Path(path)

    def assert_ready_new_branch(self, lease: _LeasePayload, name: str) -> Path:
        self.assertIsInstance(lease.get("lease_id"), str)
        self.assertTrue(lease.get("ready"))
        self.assertEqual(lease.get("mode"), "new-branch")
        self.assertEqual(lease.get("ref"), f"work/{name}")
        path = self.lease_path(lease)
        self.assertEqual(
            path,
            (self.data_home / "agents" / "worktrees" / self.repo.name / name).resolve(),
        )
        self.assertTrue(path.is_dir())
        self.assertTrue((path / ".git").is_file())
        self.assertEqual(
            self.git("rev-parse", "--show-toplevel", cwd=path).stdout.strip(),
            str(path),
        )
        return path

    def release(self, lease_id: str, owner_token: str) -> dict[str, object]:
        return self.success(
            "release",
            "--lease-id",
            lease_id,
            "--owner-token",
            owner_token,
            "--quiescent",
        )

    def test_inspect_is_read_only(self) -> None:
        control_root = self.data_home / "agents" / "worktrees"
        self.assertFalse(control_root.exists())

        result = self.success("inspect", "--repo", str(self.repo))

        self.assertEqual(result.get("canonical_root"), str(self.repo.resolve()))
        self.assertEqual(result.get("primary_path"), str(self.repo.resolve()))
        worktrees = result.get("worktrees")
        assert _is_worktree_list(worktrees)
        self.assertTrue(
            any(item.get("path") == str(self.repo.resolve()) for item in worktrees)
        )
        self.assertEqual(result.get("leases"), [])
        self.assertIsInstance(result.get("findings"), list)
        self.assertFalse(
            control_root.exists(),
            "inspect must not create control state or allocations",
        )

    def test_schema_describes_status_result_shape(self) -> None:
        schema = self.success("schema")
        verbs = schema.get("verbs")
        assert _is_str_dict(verbs)
        status_schema = verbs.get("status")
        assert _is_str_dict(status_schema)
        result = status_schema.get("result")
        assert _is_str_dict(result)
        self.assertIn("observation", result)
        self.assertIn("blockers", result)
        self.assertIn("safe_to_release", result)
        self.assertNotIn("observations", result)

    def test_schema_uses_xdg_data_home_and_default(self) -> None:
        configured = self.success("schema")
        self.assertEqual(
            configured.get("root"),
            str((self.data_home / "agents" / "worktrees").resolve()),
        )

        completed, payload = self.cli("schema", use_xdg_default=True)
        self.assertEqual(completed.returncode, 0, payload)
        self.assertTrue(payload.get("ok"), payload)
        result = payload.get("result")
        assert _is_str_dict(result)
        self.assertEqual(
            result.get("root"),
            str((self.home / ".local" / "share" / "agents" / "worktrees").resolve()),
        )

    def test_acquire_returns_ready_linked_worktree_and_one_time_capability(
        self,
    ) -> None:
        lease, owner_token = self.acquire("feature")
        _ = self.assert_ready_new_branch(lease, "feature")

        status = self.status(lease["lease_id"])
        status_lease = status.get("lease")
        self.assertIsInstance(status_lease, dict)
        self.assertEqual(status_lease.get("lease_id"), lease["lease_id"])
        self.assertNotIn(owner_token, json.dumps(status, sort_keys=True))
        self.assertNotIn("owner_token", status_lease)
        status_lease = status.get("lease")
        self.assertIsInstance(status_lease, dict)
        first, _ = self.acquire("collision", owner="first-owner")
        second, _ = self.acquire("collision", owner="second-owner")

        first_path = self.assert_ready_new_branch(first, "collision")
        second_path = self.assert_ready_new_branch(second, "collision-2")
        self.assertNotEqual(first_path, second_path)
        self.assertEqual(first.get("ref"), "work/collision")
        self.assertEqual(second.get("ref"), "work/collision-2")

    def test_setup_failure_preserves_unready_lease_and_worktree(self) -> None:
        arguments = [
            "acquire",
            "--repo",
            str(self.repo),
            "--owner",
            "setup-owner",
            "--session-actor",
            "setup-session",
            "--task",
            "setup failure",
            "--name",
            "setup-failure",
            "--mode",
            "new-branch",
            "--base",
            self.base,
            "--setup-argv",
            json.dumps([sys.executable, "-c", "import sys; sys.exit(7)"]),
        ]
        completed, payload = self.cli(*arguments)
        self.assertEqual(completed.returncode, 4, payload)
        self.assertFalse(payload.get("ok"), payload)
        self.assertEqual(payload.get("type"), "error")
        self.assertIsInstance(payload.get("error"), dict)

        inspection = self.success("inspect", "--repo", str(self.repo))
        leases = inspection.get("leases")
        assert _is_lease_list(leases)
        failed = next(
            (lease for lease in leases if lease.get("ref") == "work/setup-failure"),
            None,
        )
        assert failed is not None
        self.assertFalse(failed.get("ready"))
        self.assertEqual(failed.get("state"), "setup_failed")
        path = self.lease_path(failed)
        self.assertTrue(path.is_dir())
        self.assertTrue((path / ".git").is_file())

    def test_setup_timeout_preserves_unready_lease_and_worktree(self) -> None:
        completed, payload = self.cli(
            "acquire",
            "--repo",
            str(self.repo),
            "--owner",
            "timeout-owner",
            "--session-actor",
            "timeout-session",
            "--task",
            "setup timeout",
            "--name",
            "setup-timeout",
            "--mode",
            "new-branch",
            "--base",
            self.base,
            "--setup-argv",
            json.dumps([sys.executable, "-c", "import time; time.sleep(2)"]),
            "--setup-timeout-seconds",
            "1",
        )
        self.assertEqual(completed.returncode, 4, payload)
        error = payload.get("error", {})
        assert _is_error_detail(error)
        self.assertEqual(error.get("code"), "setup_timeout")

        inspection = self.success("inspect", "--repo", str(self.repo))
        leases = inspection.get("leases")
        assert _is_lease_list(leases)
        failed = next(
            (lease for lease in leases if lease.get("ref") == "work/setup-timeout"),
            None,
        )
        assert failed is not None
        self.assertEqual(failed.get("state"), "setup_failed")
        self.assertFalse(failed.get("ready"))
        self.assertTrue(self.lease_path(failed).is_dir())

    def test_capability_tokens_are_safe_as_separate_cli_arguments(self) -> None:
        from unittest.mock import patch

        sys.path.insert(0, str(SKILL_ROOT / "lib"))
        from git_worktrees.controller import Controller
        from git_worktrees.models import AcquireRequest
        from git_worktrees.service import acquire, handoff

        controller = Controller(self.data_home / "agents" / "worktrees")
        request = AcquireRequest(
            repo=self.repo,
            owner="owner",
            session_actor="owner-session",
            task="dash-prefixed entropy regression",
            name="token-regression",
            mode="new-branch",
            base=self.base,
            branch=None,
        )
        with patch("secrets.token_urlsafe", return_value="-test-entropy"):
            result = acquire(controller, request)
            lease = result["lease"]
            capabilities = result["capabilities"]
            assert _is_lease_payload(lease)
            assert _is_capabilities(capabilities)
            owner_token = capabilities["owner_token"]
            self.assertFalse(owner_token.startswith("-"))
            transferred = handoff(
                controller, lease["lease_id"], owner_token, "worker", "worker-session"
            )
            handoff_capabilities = transferred["capabilities"]
            assert _is_handoff_capabilities(handoff_capabilities)
            handoff_token = handoff_capabilities["handoff_token"]
            self.assertFalse(handoff_token.startswith("-"))
        _ = self.success(
            "complete-handoff",
            "--lease-id",
            lease["lease_id"],
            "--handoff-token",
            handoff_token,
            "--quiescent",
        )
        _ = self.release(lease["lease_id"], owner_token)

    def test_handoff_refuses_a_removed_managed_worktree(self) -> None:
        lease, owner_token = self.acquire("missing-handoff")
        path = self.assert_ready_new_branch(lease, "missing-handoff")
        _ = self.git("worktree", "remove", str(path))
        self.assertFalse(path.exists())

        error = self.refusal(
            "handoff",
            "--lease-id",
            lease["lease_id"],
            "--owner-token",
            owner_token,
            "--actor",
            "worker",
            "--session-actor",
            "worker-session",
        )
        self.assertEqual(error.get("code"), "worktree_unavailable")

    def test_handoff_blocks_release_until_completed(self) -> None:
        lease, owner_token = self.acquire("handoff")
        path = self.assert_ready_new_branch(lease, "handoff")
        lease_id = lease["lease_id"]

        handoff = self.success(
            "handoff",
            "--lease-id",
            lease_id,
            "--owner-token",
            owner_token,
            "--actor",
            "worker",
            "--session-actor",
            "worker-session",
        )
        capabilities = handoff.get("capabilities")
        assert _is_handoff_capabilities(capabilities)
        handoff_token = capabilities["handoff_token"]
        self.assertIsInstance(handoff_token, str)
        self.assertTrue(handoff_token)
        self.assertTrue(path.exists())

        _ = self.success(
            "complete-handoff",
            "--lease-id",
            lease_id,
            "--handoff-token",
            handoff_token,
            "--quiescent",
        )
        _ = self.release(lease_id, owner_token)
        self.assertFalse(path.exists())

    def test_dirty_release_refuses_then_clean_release_removes_and_tombstones(
        self,
    ) -> None:
        lease, owner_token = self.acquire("dirty")
        path = self.assert_ready_new_branch(lease, "dirty")
        lease_id = lease["lease_id"]
        _ = (path / "README.md").write_text("changed\n", encoding="utf-8")

        _ = self.refusal(
            "release",
            "--lease-id",
            lease_id,
            "--owner-token",
            owner_token,
            "--quiescent",
        )
        self.assertTrue(path.exists())

        _ = self.git("checkout", "--", "README.md", cwd=path)
        _ = self.release(lease_id, owner_token)
        self.assertFalse(path.exists())
        released_status = self.status(lease_id)
        released_lease = released_status.get("lease")
        self.assertIsInstance(released_lease, dict)
        self.assertEqual(released_lease.get("state"), "released")
        self.assertFalse(released_status.get("safe_to_release"))

    def test_reacquire_after_release_uses_a_distinct_suffixed_allocation(self) -> None:
        first, first_owner_token = self.acquire("reacquire", owner="first-owner")
        first_path = self.assert_ready_new_branch(first, "reacquire")
        _ = self.release(first["lease_id"], first_owner_token)
        self.assertFalse(first_path.exists())

        second, _ = self.acquire("reacquire", owner="second-owner")
        second_path = self.assert_ready_new_branch(second, "reacquire-2")

        self.assertNotEqual(first["lease_id"], second["lease_id"])
        self.assertNotEqual(first_path, second_path)
        self.assertEqual(second.get("ref"), "work/reacquire-2")
        _ = self.git("show-ref", "--verify", "--quiet", "refs/heads/work/reacquire-2")
        registered = self.git("worktree", "list", "--porcelain", "-z").stdout
        self.assertIn(f"worktree {second_path}\x00", registered)

    def test_inspect_checks_collision_disambiguated_namespace(self) -> None:
        _ = self.acquire("primary")
        other_repo = self.temp_path / "other-parent" / "repo"
        other_repo.mkdir(parents=True)
        _ = self.git("init", cwd=other_repo)
        _ = self.git("config", "user.email", "other@example.test", cwd=other_repo)
        _ = self.git("config", "user.name", "Other", cwd=other_repo)
        _ = (other_repo / "README.md").write_text("other\n", encoding="utf-8")
        _ = self.git("add", "README.md", cwd=other_repo)
        _ = self.git("commit", "-m", "initial", cwd=other_repo)

        common_git_dir = str((other_repo / ".git").resolve())
        slug = f"repo-{sha256(common_git_dir.encode('utf-8')).hexdigest()[:6]}"
        unsafe_parent = (self.data_home / "agents" / "worktrees" / slug).resolve(
            strict=False
        )
        _ = unsafe_parent.write_text("not a directory", encoding="utf-8")

        inspection = self.success("inspect", "--repo", str(other_repo))
        findings = inspection.get("findings")
        assert _is_finding_list(findings)
        self.assertTrue(
            any(
                finding.get("code") == "allocation_parent_unsafe"
                and finding.get("details", {}).get("path") == str(unsafe_parent)
                for finding in findings
            )
        )

    def test_inspect_reports_no_reason_locked_worktree_and_release_refuses(
        self,
    ) -> None:
        lease, owner_token = self.acquire("locked")
        path = self.assert_ready_new_branch(lease, "locked")
        _ = self.git("worktree", "lock", str(path))

        inspection = self.success("inspect", "--repo", str(self.repo))
        worktrees = inspection.get("worktrees")
        assert _is_worktree_list(worktrees)
        locked = next(
            (worktree for worktree in worktrees if worktree.get("path") == str(path)),
            None,
        )
        assert locked is not None
        self.assertEqual(locked.get("locked"), "")

        _ = self.refusal(
            "release",
            "--lease-id",
            lease["lease_id"],
            "--owner-token",
            owner_token,
            "--quiescent",
        )
        self.assertTrue(path.exists())

    def test_inspect_reports_prunable_missing_linked_worktree(self) -> None:
        missing_path = self.temp_path / "missing-linked-worktree"
        _ = self.git(
            "worktree",
            "add",
            "-b",
            "missing-linked-worktree",
            str(missing_path),
            self.base,
        )
        self.assertTrue(missing_path.is_dir())
        _ = missing_path.rename(self.temp_path / "moved-missing-linked-worktree")
        self.assertFalse(missing_path.exists())
        canonical_missing_path = missing_path.resolve(strict=False)

        registered = self.git("worktree", "list", "--porcelain", "-z").stdout
        self.assertIn(f"worktree {canonical_missing_path}\x00", registered)
        self.assertIn(b"prunable", registered.encode())

        inspection = self.success("inspect", "--repo", str(self.repo))
        worktrees = inspection.get("worktrees")
        assert _is_worktree_list(worktrees)
        prunable = next(
            (
                worktree
                for worktree in worktrees
                if worktree.get("path") == str(canonical_missing_path)
            ),
            None,
        )
        assert prunable is not None
        self.assertIsInstance(prunable.get("prunable"), str)

    def test_inspect_sha256_object_format_repository_when_supported(self) -> None:
        sha256_repo = self.temp_path / "sha256-repo"
        initialized = subprocess.run(
            ["git", "init", "--object-format=sha256", str(sha256_repo)],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            },
            check=False,
        )
        if initialized.returncode:
            output = f"{initialized.stdout}\n{initialized.stderr}"
            if re.search(
                r"(?i)(unknown|unrecognized) option.*object-format"
                + r"|invalid (object format|hash algorithm).*sha256"
                + r"|unknown hash algorithm.*sha256"
                + r"|object format.*sha256.*not supported"
                + r"|sha256.*(not supported|unsupported)",
                output,
            ):
                self.skipTest("Git does not support SHA-256 object-format repositories")
            self.fail(f"git init --object-format=sha256 failed: {output}")

        _ = self.git("config", "user.email", "contract@example.test", cwd=sha256_repo)
        _ = self.git("config", "user.name", "Contract Test", cwd=sha256_repo)
        _ = (sha256_repo / "README.md").write_text("initial\n", encoding="utf-8")
        _ = self.git("add", "README.md", cwd=sha256_repo)
        _ = self.git("commit", "-m", "initial", cwd=sha256_repo)
        self.assertEqual(
            self.git(
                "rev-parse", "--show-object-format", cwd=sha256_repo
            ).stdout.strip(),
            "sha256",
        )

        inspection = self.success("inspect", "--repo", str(sha256_repo))
        self.assertEqual(inspection.get("canonical_root"), str(sha256_repo.resolve()))
        self.assertEqual(inspection.get("primary_path"), str(sha256_repo.resolve()))
        worktrees = inspection.get("worktrees")
        assert _is_worktree_list(worktrees)
        self.assertTrue(
            any(
                worktree.get("path") == str(sha256_repo.resolve())
                for worktree in worktrees
            )
        )

    def test_foreign_preexisting_linked_worktree_is_not_adopted_or_removed(
        self,
    ) -> None:
        foreign_path = self.temp_path / "foreign"
        _ = self.git(
            "worktree", "add", "-b", "foreign-branch", str(foreign_path), self.base
        )
        self.assertTrue(foreign_path.is_dir())

        _ = self.refusal(
            "acquire",
            "--repo",
            str(self.repo),
            "--owner",
            "foreign-owner",
            "--session-actor",
            "foreign-session",
            "--task",
            "try foreign branch",
            "--name",
            "foreign",
            "--mode",
            "existing-branch",
            "--branch",
            "foreign-branch",
        )
        canonical_foreign_path = foreign_path.resolve()
        self.assertTrue(canonical_foreign_path.is_dir())
        registered = self.git("worktree", "list", "--porcelain", "-z").stdout
        self.assertIn(f"worktree {canonical_foreign_path}\x00", registered)

        inspection = self.success("inspect", "--repo", str(self.repo))
        leases = inspection.get("leases")
        assert _is_lease_list(leases)
        self.assertFalse(
            any(lease.get("path") == str(canonical_foreign_path) for lease in leases)
        )
        worktrees = inspection.get("worktrees")
        assert _is_worktree_list(worktrees)
        self.assertTrue(
            any(item.get("path") == str(canonical_foreign_path) for item in worktrees)
        )


if __name__ == "__main__":
    _ = unittest.main()
