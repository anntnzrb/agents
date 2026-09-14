"""End-to-end tests for the autommit orchestrator, inventory, and fallback rungs."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast

SKILL_ROOT = Path(__file__).resolve().parents[1]
_ = sys.path.insert(0, str(SKILL_ROOT / "lib"))
from autommit.client import HttpResponse
from autommit.errors import CancelledError
from autommit.fallback import CommitWork, _rung_plumbing
from autommit.inventory import (
    PLAN_SYSTEM,
    CriticEvidence,
    PlannerEvidence,
    build_inventory,
    render_critic_prompt,
    render_planner_prompt,
)
from autommit.orchestrate import RunOptions, run_orchestrated
from autommit.proposal import AllSelector, CommitChange, CommitGroup
from autommit.transaction import read_recovery_point

PLAN = {
    "commits": [
        {
            "summary": "Update tracked value",
            "details": [],
            "dependencies": [],
            "changes": [{"path": "tracked.txt", "hunks": "all"}],
        }
    ]
}

BROAD_PLAN = {
    "commits": [
        {
            "summary": "Update tracked value broadly",
            "details": ["one", "two"],
            "dependencies": [],
            "changes": [{"path": "tracked.txt", "hunks": "all"}],
        }
    ]
}


def _model_reply(payload: object) -> HttpResponse:
    return HttpResponse(
        200, {"choices": [{"message": {"content": json.dumps(payload)}}]}
    )


def _system_of(request: dict[str, object]) -> str:
    messages = cast("list[dict[str, object]]", request["messages"])
    return str(messages[0]["content"])


class _Sandbox(unittest.TestCase):
    """Shared disposable repository fixture."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary_directory.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.email", "autommit@example.test")
        self.git("config", "user.name", "Autommit Test")
        _ = (self.repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        self.git("commit", "-m", "initial")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def git(self, *args: str, cwd: Path | None = None) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout

    def stage(self, content: str = "changed\n") -> None:
        _ = (self.repo / "tracked.txt").write_text(content, encoding="utf-8")
        self.git("add", "tracked.txt")

    def prepare(self) -> dict[str, object]:
        """Run the public prepare command so the environment pins apply."""
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--quiet",
                "--script",
                str(SKILL_ROOT / "scripts" / "cli.py"),
                "prepare",
                "--scope",
                "staged",
            ],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"},
        )
        payload = cast("dict[str, object]", json.loads(completed.stdout))
        return cast("dict[str, object]", payload["result"])

    def options(self, **overrides: object) -> RunOptions:
        values: dict[str, object] = {
            "repo": self.repo,
            "scope": "auto",
            "api_key": "test-key",
            "model": "test-model",
            "base_url": "https://model.test/v1",
        }
        values.update(overrides)
        return RunOptions(**values)  # type: ignore[arg-type]


class OrchestratorTests(_Sandbox):
    """Cover the loop, retries, cancellation, and output modes."""

    def test_dry_run_needs_no_key_and_calls_nothing(self) -> None:
        self.stage()

        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            raise AssertionError("dry run must not call the model")

        code = run_orchestrated(self.options(dry_run=True, api_key=None, post=post))
        self.assertEqual(code, 0)
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "initial")
        self.assertEqual(
            self.git("diff", "--cached", "--name-only").strip(), "tracked.txt"
        )

    def test_full_run_publishes_a_plan_from_the_model(self) -> None:
        self.stage()

        def post(payload: dict[str, object]) -> HttpResponse:
            return _model_reply(PLAN)

        code = run_orchestrated(self.options(json_output=True, post=post))
        self.assertEqual(code, 0)
        self.assertEqual(
            self.git("log", "-1", "--format=%s").strip(), "Update tracked value"
        )
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")
        self.assertEqual(
            (self.repo / "tracked.txt").read_text(encoding="utf-8"), "changed\n"
        )

    def test_planner_correction_feeds_the_validation_error(self) -> None:
        self.stage()
        wrong = {
            "commits": [
                {
                    "summary": "Wrong path",
                    "details": [],
                    "dependencies": [],
                    "changes": [{"path": "other.txt", "hunks": "all"}],
                }
            ]
        }
        seen: list[str] = []

        def post(payload: dict[str, object]) -> HttpResponse:
            seen.append(json.dumps(payload))
            return _model_reply(wrong if len(seen) == 1 else PLAN)

        code = run_orchestrated(self.options(json_output=True, post=post))
        self.assertEqual(code, 0)
        self.assertEqual(len(seen), 2)
        self.assertIn("not staged", seen[1])
        self.assertEqual(
            self.git("log", "-1", "--format=%s").strip(), "Update tracked value"
        )

    def test_provider_error_maps_to_exit_one(self) -> None:
        self.stage()
        calls: list[int] = []

        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            calls.append(1)
            return HttpResponse(403, {"error": {"message": "denied"}})

        code = run_orchestrated(self.options(post=post))
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "initial")

    def test_cancellation_exits_130_and_releases_the_lock(self) -> None:
        self.stage()

        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            raise CancelledError

        code = run_orchestrated(self.options(post=post))
        self.assertEqual(code, 130)
        lock = self.repo / ".git" / "autommit" / "operation.lock"
        self.assertFalse(lock.exists())
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "initial")

    def test_critic_accept_publishes_a_broad_single_commit(self) -> None:
        self.stage()

        def post(payload: dict[str, object]) -> HttpResponse:
            if "Independent atomicity critic" in _system_of(payload):
                return _model_reply(
                    {
                        "decision": "accept",
                        "concerns": [],
                        "rationale": "One cohesive behavior.",
                    }
                )
            return _model_reply(BROAD_PLAN)

        code = run_orchestrated(self.options(json_output=True, post=post))
        self.assertEqual(code, 0)
        self.assertEqual(
            self.git("log", "-1", "--format=%s").strip(),
            "Update tracked value broadly",
        )


class InventoryTests(_Sandbox):
    """Cover deterministic evidence rendering."""

    def test_planner_prompt_is_inventory_only(self) -> None:
        self.stage()
        prepared = self.prepare()
        staged = tuple(cast("list[str]", prepared["staged_files"]))
        inventory = build_inventory(self.repo, staged, str(prepared["diff"]))
        self.assertEqual(inventory[0].path, "tracked.txt")
        self.assertEqual(inventory[0].status, "M")
        self.assertEqual([hunk.id for hunk in inventory[0].hunks], [1])

        prompt = render_planner_prompt(
            PlannerEvidence(
                inventory=inventory,
                staged_files=staged,
                repository_context="# policy",
                user_context=("keep it small",),
                correction="previous rejection",
                zero_diff="ZERO-DIFF-SENTINEL",
            )
        )
        self.assertLess(
            prompt.index("CORRECTION REQUIRED"), prompt.index("USER INSTRUCTIONS")
        )
        self.assertIn("ADVISORY REPOSITORY POLICY", prompt)
        self.assertIn("hunk 1:", prompt)
        self.assertIn("ZERO-DIFF-SENTINEL", prompt)
        self.assertLess(
            prompt.index("----- BEGIN CACHED DIFF -----"),
            prompt.index("----- END CACHED DIFF -----"),
        )

    def test_critic_prompt_bounds_the_diff(self) -> None:
        prompt = render_critic_prompt(
            CriticEvidence(
                summary="One",
                details=("a",),
                staged_count=1,
                hunk_count=1,
                diff="x" * 300_000,
            )
        )
        self.assertIn("truncated for this review", prompt)
        self.assertLess(len(prompt), 300_000)


class PlumbingRungTests(_Sandbox):
    """Cover the third fallback rung against a staged snapshot."""

    def test_plumbing_rung_reproduces_the_staged_snapshot(self) -> None:
        _ = (self.repo / "doomed.txt").write_text("doomed\n", encoding="utf-8")
        self.git("add", "doomed.txt")
        self.git("commit", "-m", "add doomed")
        (self.repo / "doomed.txt").unlink()
        _ = (self.repo / "added.txt").write_text("added\n", encoding="utf-8")
        self.stage("changed\n")
        self.git("add", "--all")
        index_tree = self.git("write-tree").strip()
        worktree = Path(self.temporary_directory.name) / "wt"
        self.git("worktree", "add", "--detach", str(worktree), "HEAD")
        work = CommitWork(
            repo=self.repo,
            worktree=worktree,
            patch_dir=Path(self.temporary_directory.name),
            index_tree=index_tree,
            ref="refs/heads/main",
            before=self.git("rev-parse", "HEAD").strip(),
            staged_diff=self.git("diff", "--cached"),
            zero_diff=self.git("diff", "--cached", "--unified=0"),
        )
        group = CommitGroup(
            summary="Plumbing",
            details=(),
            changes=(
                CommitChange("tracked.txt", AllSelector()),
                CommitChange("added.txt", AllSelector()),
                CommitChange("doomed.txt", AllSelector()),
            ),
            dependencies=(),
        )
        detail = _rung_plumbing(work, group)
        self.assertEqual(detail, "")
        staged = self.git("diff", "--cached", "--name-status", cwd=worktree).strip()
        self.assertEqual(staged, "A\tadded.txt\nD\tdoomed.txt\nM\ttracked.txt")
        self.assertEqual(
            (worktree / "tracked.txt").read_text(encoding="utf-8"), "changed\n"
        )
        self.assertEqual(
            (worktree / "added.txt").read_text(encoding="utf-8"), "added\n"
        )
        self.assertFalse((worktree / "doomed.txt").exists())
        self.assertIsNone(read_recovery_point(self.repo / ".git"))


class ProgressFeedbackTests(_Sandbox):
    """Cover the human progress lines and the local-commit summary wording."""

    def test_human_progress_goes_to_stderr_and_the_summary_says_created(self) -> None:
        self.stage()

        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            return _model_reply(PLAN)

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = run_orchestrated(self.options(post=post))

        self.assertEqual(code, 0)
        self.assertIn("Planning...", err.getvalue())
        self.assertIn("Applying 1 commit(s)...", err.getvalue())
        self.assertIn("Created 1 commit(s) on", out.getvalue())
        self.assertNotIn("Published", out.getvalue() + err.getvalue())

    def test_json_mode_emits_one_line_and_no_progress(self) -> None:
        self.stage()

        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            return _model_reply(PLAN)

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = run_orchestrated(self.options(json_output=True, post=post))

        self.assertEqual(code, 0)
        self.assertEqual(len(out.getvalue().splitlines()), 1)
        self.assertEqual(err.getvalue(), "")

    def test_dry_run_prints_no_progress(self) -> None:
        self.stage()

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = run_orchestrated(self.options(dry_run=True))

        self.assertEqual(code, 0)
        self.assertEqual(err.getvalue(), "")


class ModelContractTests(unittest.TestCase):
    """Keep the runtime prompts and their documented mirror in step."""

    def test_planner_contract_keeps_policy_subjects_and_opinionated_limits(
        self,
    ) -> None:
        self.assertIn("matching repository policy", PLAN_SYSTEM)
        self.assertIn("reuse their prefixes, scopes, and language", PLAN_SYSTEM)
        self.assertIn("NEVER more than 72", PLAN_SYSTEM)
        self.assertIn("the count is never limited", PLAN_SYSTEM)
        self.assertIn("RFC 2119", PLAN_SYSTEM)

    def test_documented_planner_mirror_carries_the_same_rules(self) -> None:
        mirror = (SKILL_ROOT / "references" / "prompts.md").read_text(encoding="utf-8")

        self.assertIn("matching repository policy", mirror)
        self.assertIn("reuse their prefixes, scopes, and language", mirror)
        self.assertIn("NEVER more than 72", mirror)
        self.assertIn("the count is never limited", mirror)


if __name__ == "__main__":
    _ = unittest.main()
