"""End-to-end contract tests for the public git-worktrees CLI."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
CLI = SKILL_ROOT / "scripts" / "cli.py"
SCHEMA = "git-worktrees/v1"


class GitWorktreesCliContractTests(unittest.TestCase):
    """Exercise the wire protocol against disposable local Git repositories."""

    maxDiff = None

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary_directory.name)
        self.home = self.temp_path / "home"
        self.home.mkdir()
        self.repo = self.temp_path / "repo"
        self.repo.mkdir()
        self.git("init")
        self.git("config", "user.email", "contract@example.test")
        self.git("config", "user.name", "Contract Test")
        (self.repo / "README.md").write_text("initial\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-m", "initial")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
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

    def cli(self, *args: str) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
        completed = subprocess.run(
            ["uv", "run", "--script", str(CLI), *args],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            env={
                **os.environ,
                "HOME": str(self.home),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            },
        )
        lines = completed.stdout.splitlines()
        self.assertEqual(
            len(lines),
            1,
            f"CLI stdout must be one JSON line; stderr={completed.stderr!r}",
        )
        try:
            payload = json.loads(lines[0])
        except json.JSONDecodeError as error:
            self.fail(f"CLI stdout was not JSON: {error}: {lines[0]!r}")
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("schema"), SCHEMA)
        return completed, payload

    def success(self, *args: str) -> dict[str, Any]:
        completed, payload = self.cli(*args)
        self.assertEqual(completed.returncode, 0, payload)
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(payload.get("type"), "response")
        self.assertIsInstance(payload.get("command"), str)
        self.assertIsInstance(payload.get("result"), dict)
        self.assertEqual(payload.get("warnings"), [])
        return payload["result"]

    def refusal(self, *args: str) -> dict[str, Any]:
        completed, payload = self.cli(*args)
        self.assertEqual(completed.returncode, 3, payload)
        self.assertFalse(payload.get("ok"), payload)
        self.assertEqual(payload.get("type"), "error")
        error = payload.get("error")
        self.assertIsInstance(error, dict)
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
    ) -> tuple[dict[str, Any], str]:
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
        lease = result.get("lease")
        capabilities = result.get("capabilities")
        self.assertIsInstance(lease, dict)
        self.assertIsInstance(capabilities, dict)
        token = capabilities.get("owner_token")
        self.assertIsInstance(token, str)
        self.assertTrue(token)
        return lease, token

    def lease_path(self, lease: dict[str, Any]) -> Path:
        path = lease.get("path")
        self.assertIsInstance(path, str)
        return Path(path)

    def assert_ready_new_branch(
        self, lease: dict[str, Any], name: str
    ) -> Path:
        self.assertIsInstance(lease.get("lease_id"), str)
        self.assertTrue(lease.get("ready"))
        self.assertEqual(lease.get("mode"), "new-branch")
        self.assertEqual(lease.get("ref"), f"work/{name}")
        path = self.lease_path(lease)
        self.assertEqual(
            path,
            (self.home / ".agents" / "worktrees" / self.repo.name / name).resolve(),
        )
        self.assertTrue(path.is_dir())
        self.assertTrue((path / ".git").is_file())
        self.assertEqual(
            self.git("rev-parse", "--show-toplevel", cwd=path).stdout.strip(),
            str(path),
        )
        return path

    def status(self, lease_id: str) -> dict[str, Any]:
        result = self.success("status", "--lease-id", lease_id)
        self.assertIsInstance(result.get("lease"), dict)
        self.assertIsInstance(result.get("safe_to_release"), bool)
        return result

    def release(self, lease_id: str, owner_token: str) -> dict[str, Any]:
        return self.success(
            "release",
            "--lease-id",
            lease_id,
            "--owner-token",
            owner_token,
            "--quiescent",
        )

    def test_inspect_is_read_only(self) -> None:
        control_root = self.home / ".agents" / "worktrees"
        self.assertFalse(control_root.exists())

        result = self.success("inspect", "--repo", str(self.repo))

        self.assertEqual(result.get("canonical_root"), str(self.repo.resolve()))
        self.assertEqual(result.get("primary_path"), str(self.repo.resolve()))
        worktrees = result.get("worktrees")
        self.assertIsInstance(worktrees, list)
        self.assertTrue(any(item.get("path") == str(self.repo.resolve()) for item in worktrees))
        self.assertEqual(result.get("leases"), [])
        self.assertIsInstance(result.get("findings"), list)
        self.assertFalse(control_root.exists(), "inspect must not create control state or allocations")

    def test_schema_describes_status_result_shape(self) -> None:
        schema = self.success("schema")
        verbs = schema.get("verbs")
        self.assertIsInstance(verbs, dict)
        status_schema = verbs.get("status")
        self.assertIsInstance(status_schema, dict)
        result = status_schema.get("result")
        self.assertIsInstance(result, dict)
        self.assertIn("observation", result)
        self.assertIn("blockers", result)
        self.assertIn("safe_to_release", result)
        self.assertNotIn("observations", result)

    def test_acquire_returns_ready_linked_worktree_and_one_time_capability(self) -> None:
        lease, owner_token = self.acquire("feature")
        path = self.assert_ready_new_branch(lease, "feature")

        status = self.status(lease["lease_id"])
        status_lease = status.get("lease")
        self.assertIsInstance(status_lease, dict)
        self.assertEqual(status_lease.get("lease_id"), lease["lease_id"])
        self.assertNotIn(owner_token, json.dumps(status, sort_keys=True))
        self.assertNotIn("owner_token", status_lease)
        self.assertTrue(path.exists())

    def test_acquire_allocates_a_new_name_for_path_and_branch_collision(self) -> None:
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
        self.assertIsInstance(leases, list)
        failed = next((lease for lease in leases if lease.get("ref") == "work/setup-failure"), None)
        self.assertIsInstance(failed, dict)
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
        self.assertEqual(payload.get("error", {}).get("code"), "setup_timeout")

        inspection = self.success("inspect", "--repo", str(self.repo))
        leases = inspection.get("leases")
        self.assertIsInstance(leases, list)
        failed = next((lease for lease in leases if lease.get("ref") == "work/setup-timeout"), None)
        self.assertIsInstance(failed, dict)
        self.assertEqual(failed.get("state"), "setup_failed")
        self.assertFalse(failed.get("ready"))
        self.assertTrue(self.lease_path(failed).is_dir())

    def test_handoff_refuses_a_removed_managed_worktree(self) -> None:
        lease, owner_token = self.acquire("missing-handoff")
        path = self.assert_ready_new_branch(lease, "missing-handoff")
        self.git("worktree", "remove", str(path))
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
        self.assertIsInstance(capabilities, dict)
        handoff_token = capabilities.get("handoff_token")
        self.assertIsInstance(handoff_token, str)
        self.assertTrue(handoff_token)

        self.refusal(
            "release",
            "--lease-id",
            lease_id,
            "--owner-token",
            owner_token,
            "--quiescent",
        )
        self.assertTrue(path.exists())

        self.success(
            "complete-handoff",
            "--lease-id",
            lease_id,
            "--handoff-token",
            handoff_token,
            "--quiescent",
        )
        self.release(lease_id, owner_token)
        self.assertFalse(path.exists())

    def test_dirty_release_refuses_then_clean_release_removes_and_tombstones(self) -> None:
        lease, owner_token = self.acquire("dirty")
        path = self.assert_ready_new_branch(lease, "dirty")
        lease_id = lease["lease_id"]
        (path / "README.md").write_text("changed\n", encoding="utf-8")

        self.refusal(
            "release",
            "--lease-id",
            lease_id,
            "--owner-token",
            owner_token,
            "--quiescent",
        )
        self.assertTrue(path.exists())

        self.git("checkout", "--", "README.md", cwd=path)
        self.release(lease_id, owner_token)
        self.assertFalse(path.exists())
        released_status = self.status(lease_id)
        released_lease = released_status.get("lease")
        self.assertIsInstance(released_lease, dict)
        self.assertEqual(released_lease.get("state"), "released")
        self.assertFalse(released_status.get("safe_to_release"))

    def test_reacquire_after_release_uses_a_distinct_suffixed_allocation(self) -> None:
        first, first_owner_token = self.acquire("reacquire", owner="first-owner")
        first_path = self.assert_ready_new_branch(first, "reacquire")
        self.release(first["lease_id"], first_owner_token)
        self.assertFalse(first_path.exists())

        second, _ = self.acquire("reacquire", owner="second-owner")
        second_path = self.assert_ready_new_branch(second, "reacquire-2")

        self.assertNotEqual(first["lease_id"], second["lease_id"])
        self.assertNotEqual(first_path, second_path)
        self.assertEqual(second.get("ref"), "work/reacquire-2")
        self.git("show-ref", "--verify", "--quiet", "refs/heads/work/reacquire-2")
        registered = self.git("worktree", "list", "--porcelain", "-z").stdout
        self.assertIn(f"worktree {second_path}\x00", registered)

    def test_inspect_checks_collision_disambiguated_namespace(self) -> None:
        self.acquire("primary")
        other_repo = self.temp_path / "other-parent" / "repo"
        other_repo.mkdir(parents=True)
        self.git("init", cwd=other_repo)
        self.git("config", "user.email", "other@example.test", cwd=other_repo)
        self.git("config", "user.name", "Other", cwd=other_repo)
        (other_repo / "README.md").write_text("other\n", encoding="utf-8")
        self.git("add", "README.md", cwd=other_repo)
        self.git("commit", "-m", "initial", cwd=other_repo)

        common_git_dir = str((other_repo / ".git").resolve())
        slug = f"repo-{sha256(common_git_dir.encode('utf-8')).hexdigest()[:6]}"
        unsafe_parent = (self.home / ".agents" / "worktrees" / slug).resolve(strict=False)
        unsafe_parent.write_text("not a directory", encoding="utf-8")

        inspection = self.success("inspect", "--repo", str(other_repo))
        findings = inspection.get("findings")
        self.assertIsInstance(findings, list)
        self.assertTrue(
            any(
                finding.get("code") == "allocation_parent_unsafe"
                and finding.get("details", {}).get("path") == str(unsafe_parent)
                for finding in findings
            )
        )

    def test_inspect_reports_no_reason_locked_worktree_and_release_refuses(self) -> None:
        lease, owner_token = self.acquire("locked")
        path = self.assert_ready_new_branch(lease, "locked")
        self.git("worktree", "lock", str(path))

        inspection = self.success("inspect", "--repo", str(self.repo))
        worktrees = inspection.get("worktrees")
        self.assertIsInstance(worktrees, list)
        locked = next(
            (worktree for worktree in worktrees if worktree.get("path") == str(path)),
            None,
        )
        self.assertIsInstance(locked, dict)
        self.assertEqual(locked.get("locked"), "")

        self.refusal(
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
        self.git(
            "worktree",
            "add",
            "-b",
            "missing-linked-worktree",
            str(missing_path),
            self.base,
        )
        self.assertTrue(missing_path.is_dir())
        missing_path.rename(self.temp_path / "moved-missing-linked-worktree")
        self.assertFalse(missing_path.exists())
        canonical_missing_path = missing_path.resolve(strict=False)

        registered = self.git("worktree", "list", "--porcelain", "-z").stdout
        self.assertIn(f"worktree {canonical_missing_path}\x00", registered)
        self.assertIn(b"prunable", registered.encode())

        inspection = self.success("inspect", "--repo", str(self.repo))
        worktrees = inspection.get("worktrees")
        self.assertIsInstance(worktrees, list)
        prunable = next(
            (
                worktree
                for worktree in worktrees
                if worktree.get("path") == str(canonical_missing_path)
            ),
            None,
        )
        self.assertIsInstance(prunable, dict)
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
        )
        if initialized.returncode:
            output = f"{initialized.stdout}\n{initialized.stderr}"
            if re.search(
                r"(?i)(unknown|unrecognized) option.*object-format"
                r"|invalid (object format|hash algorithm).*sha256"
                r"|unknown hash algorithm.*sha256"
                r"|object format.*sha256.*not supported"
                r"|sha256.*(not supported|unsupported)",
                output,
            ):
                self.skipTest("Git does not support SHA-256 object-format repositories")
            self.fail(f"git init --object-format=sha256 failed: {output}")

        self.git("config", "user.email", "contract@example.test", cwd=sha256_repo)
        self.git("config", "user.name", "Contract Test", cwd=sha256_repo)
        (sha256_repo / "README.md").write_text("initial\n", encoding="utf-8")
        self.git("add", "README.md", cwd=sha256_repo)
        self.git("commit", "-m", "initial", cwd=sha256_repo)
        self.assertEqual(
            self.git("rev-parse", "--show-object-format", cwd=sha256_repo).stdout.strip(),
            "sha256",
        )

        inspection = self.success("inspect", "--repo", str(sha256_repo))
        self.assertEqual(inspection.get("canonical_root"), str(sha256_repo.resolve()))
        self.assertEqual(inspection.get("primary_path"), str(sha256_repo.resolve()))
        worktrees = inspection.get("worktrees")
        self.assertIsInstance(worktrees, list)
        self.assertTrue(
            any(worktree.get("path") == str(sha256_repo.resolve()) for worktree in worktrees)
        )

    def test_foreign_preexisting_linked_worktree_is_not_adopted_or_removed(self) -> None:
        foreign_path = self.temp_path / "foreign"
        self.git("worktree", "add", "-b", "foreign-branch", str(foreign_path), self.base)
        self.assertTrue(foreign_path.is_dir())

        self.refusal(
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
        self.assertIsInstance(leases, list)
        self.assertFalse(any(lease.get("path") == str(canonical_foreign_path) for lease in leases))
        worktrees = inspection.get("worktrees")
        self.assertIsInstance(worktrees, list)
        self.assertTrue(any(item.get("path") == str(canonical_foreign_path) for item in worktrees))


if __name__ == "__main__":
    unittest.main()
