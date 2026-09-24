"""End-to-end tests for the autommit orchestrator, inventory, and fallback rungs."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import cast
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
_ = sys.path.insert(0, str(SKILL_ROOT / "lib"))
from autommit import client
from autommit.client import HttpResponse
from autommit.errors import CancelledError
from autommit.fallback import CommitWork, _rung_plumbing
from autommit.inventory import (
    PLAN_SYSTEM,
    CriticEvidence,
    PlannerEvidence,
    build_inventory,
    planner_diff,
    render_critic_prompt,
    render_planner_prompt,
)
from autommit.orchestrate import RunOptions, run_orchestrated
from autommit.proposal import (
    AllSelector,
    CommitChange,
    CommitGroup,
    normalize_proposal,
    parse_file_diffs,
    validate_proposal_coverage,
)
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
                diff="ZERO-DIFF-SENTINEL",
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


class LargeRefactorTests(_Sandbox):
    """Cover move-only commits, rename rendering, and surfaced plan errors."""

    def commit_file(self, name: str, content: str) -> None:
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(content, encoding="utf-8")
        self.git("add", name)
        self.git("commit", "-m", f"add {name}")

    def move(self, source: str, target: str) -> None:
        (self.repo / target).parent.mkdir(parents=True, exist_ok=True)
        self.git("mv", source, target)

    def test_pure_renames_skip_the_model_and_commit_as_one_move(self) -> None:
        self.commit_file("old/moved.txt", "same\n")
        self.move("old/moved.txt", "new/moved.txt")
        self.stage()
        prompts: list[str] = []

        def post(payload: dict[str, object]) -> HttpResponse:
            prompts.append(json.dumps(payload))
            return _model_reply(PLAN)

        code = run_orchestrated(self.options(json_output=True, post=post))
        self.assertEqual(code, 0)
        self.assertEqual(len(prompts), 1)
        self.assertNotIn("new/moved.txt", prompts[0])
        subjects = self.git("log", "-2", "--format=%s").splitlines()
        self.assertEqual(
            subjects, ["Update tracked value", "Move files without content changes"]
        )
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")

    def test_moves_only_snapshot_needs_no_model(self) -> None:
        self.commit_file("old/moved.txt", "same\n")
        self.move("old/moved.txt", "new/moved.txt")

        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            raise AssertionError("a moves-only snapshot must not call the model")

        code = run_orchestrated(self.options(json_output=True, post=post))
        self.assertEqual(code, 0)
        self.assertEqual(
            self.git("log", "-1", "--format=%s").strip(),
            "Move files without content changes",
        )

    def test_critic_still_judges_the_model_commit_next_to_moves(self) -> None:
        self.commit_file("old/moved.txt", "same\n")
        self.move("old/moved.txt", "new/moved.txt")
        self.stage()
        critic_calls: list[int] = []

        def post(payload: dict[str, object]) -> HttpResponse:
            if "Independent atomicity critic" in _system_of(payload):
                critic_calls.append(1)
                return _model_reply(
                    {"decision": "accept", "concerns": [], "rationale": "One."}
                )
            return _model_reply(BROAD_PLAN)

        code = run_orchestrated(self.options(json_output=True, post=post))
        self.assertEqual(code, 0)
        self.assertEqual(len(critic_calls), 1)

    def test_partial_rename_renders_its_source(self) -> None:
        self.commit_file("original.txt", "".join(f"line {n}\n" for n in range(20)))
        self.git("mv", "original.txt", "renamed.txt")
        path = self.repo / "renamed.txt"
        _ = path.write_text(
            path.read_text(encoding="utf-8").replace("line 3\n", "line three\n"),
            encoding="utf-8",
        )
        self.git("add", "renamed.txt")
        prepared = self.prepare()
        staged = tuple(cast("list[str]", prepared["staged_files"]))
        inventory = build_inventory(self.repo, staged, str(prepared["diff"]))
        prompt = render_planner_prompt(
            PlannerEvidence(
                inventory=inventory,
                staged_files=staged,
                repository_context="",
                user_context=(),
                correction=None,
                diff=str(prepared["diff"]),
            )
        )
        self.assertIn(
            "- renamed.txt <- original.txt [R] (rename, whole file only)", prompt
        )
        self.assertFalse(inventory[0].is_pure_rename)

    def test_hunkless_file_selector_is_coerced_to_all(self) -> None:
        _ = (self.repo / "marker").write_text("", encoding="utf-8")
        self.git("add", "marker")
        partial = {
            "commits": [
                {
                    "summary": "Add marker",
                    "details": [],
                    "dependencies": [],
                    "changes": [
                        {"path": "marker", "hunks": {"type": "indices", "indices": [1]}}
                    ],
                }
            ]
        }

        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            return _model_reply(partial)

        code = run_orchestrated(self.options(json_output=True, post=post))
        self.assertEqual(code, 0)
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "Add marker")

    def test_partial_selection_of_an_edited_rename_is_rejected(self) -> None:
        self.commit_file("original.txt", "".join(f"line {n}\n" for n in range(20)))
        self.move("original.txt", "renamed.txt")
        path = self.repo / "renamed.txt"
        _ = path.write_text(
            path.read_text(encoding="utf-8").replace("line 3\n", "line three\n"),
            encoding="utf-8",
        )
        self.git("add", "renamed.txt")
        diff = self.git("diff", "--cached")
        proposal = normalize_proposal(
            {
                "commits": [
                    {
                        "summary": "Rename",
                        "details": [],
                        "dependencies": [],
                        "changes": [
                            {
                                "path": "renamed.txt",
                                "hunks": {"type": "indices", "indices": [1]},
                            }
                        ],
                    }
                ]
            }
        )
        errors = validate_proposal_coverage(
            proposal, ("renamed.txt",), parse_file_diffs(diff)
        )
        self.assertIn("Renamed file cannot be partially selected: renamed.txt", errors)

    def test_exhausted_attempts_surface_the_last_error(self) -> None:
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

        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            return _model_reply(wrong)

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = run_orchestrated(self.options(post=post))
        self.assertNotEqual(code, 0)
        self.assertIn("Last error: Invalid split plan", err.getvalue())
        self.assertIn("file is not staged: other.txt", err.getvalue())


class ProgressAndEfficiencyTests(_Sandbox):
    """Cover per-request progress, timeout fail-fast, and prompt trimming."""

    def test_heartbeat_reports_while_the_model_is_slow(self) -> None:
        self.stage()

        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            time.sleep(0.2)
            return _model_reply(PLAN)

        err = io.StringIO()
        with (
            mock.patch.object(client, "HEARTBEAT_SECONDS", 0.05),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(err),
        ):
            code = run_orchestrated(self.options(post=post))
        self.assertEqual(code, 0)
        self.assertIn("Planning (attempt 1/3): sending (json_schema)", err.getvalue())
        self.assertIn("Planning (attempt 1/3): waiting on model (", err.getvalue())

    def test_timeout_fails_fast_without_resending(self) -> None:
        self.stage()
        calls: list[int] = []

        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            calls.append(1)
            raise TimeoutError

        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = run_orchestrated(self.options(post=post))
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("raise --timeout", err.getvalue())

    def test_invalid_plan_shape_goes_to_correction_not_other_formats(self) -> None:
        self.stage()
        long_subject = {
            "commits": [
                {
                    "summary": "x" * 80,
                    "details": [],
                    "dependencies": [],
                    "changes": [{"path": "tracked.txt", "hunks": "all"}],
                }
            ]
        }
        seen: list[str] = []

        def post(payload: dict[str, object]) -> HttpResponse:
            seen.append(json.dumps(payload))
            return _model_reply(long_subject if len(seen) == 1 else PLAN)

        code = run_orchestrated(self.options(json_output=True, post=post))
        self.assertEqual(code, 0)
        self.assertEqual(len(seen), 2)
        self.assertIn("json_schema", seen[1])
        self.assertIn("CORRECTION REQUIRED", seen[1])

    def test_split_retries_keep_the_critic_concerns(self) -> None:
        self.stage()
        replans: list[str] = []

        def post(payload: dict[str, object]) -> HttpResponse:
            if "Independent atomicity critic" in _system_of(payload):
                return _model_reply(
                    {
                        "decision": "split",
                        "concerns": ["UNIQUE-CONCERN-MARKER"],
                        "rationale": "Two behaviors.",
                    }
                )
            body = json.dumps(payload)
            if "CORRECTION REQUIRED" in body:
                replans.append(body)
            return _model_reply(BROAD_PLAN)

        code = run_orchestrated(self.options(json_output=True, post=post))
        self.assertNotEqual(code, 0)
        self.assertEqual(len(replans), 3)
        for body in replans:
            self.assertIn("UNIQUE-CONCERN-MARKER", body)
        self.assertIn("Your previous plan was rejected", replans[-1])

    def test_whole_file_selected_twice_is_kept_once(self) -> None:
        _ = (self.repo / "other.txt").write_text("other\n", encoding="utf-8")
        self.git("add", "other.txt")
        self.stage()
        duplicated = {
            "commits": [
                {
                    "summary": "Update tracked value",
                    "details": [],
                    "dependencies": [],
                    "changes": [{"path": "tracked.txt", "hunks": "all"}],
                },
                {
                    "summary": "Add other file",
                    "details": [],
                    "dependencies": [0],
                    "changes": [
                        {"path": "other.txt", "hunks": "all"},
                        {"path": "tracked.txt", "hunks": [1]},
                    ],
                },
                {
                    "summary": "Only a duplicate",
                    "details": [],
                    "dependencies": [],
                    "changes": [{"path": "tracked.txt", "hunks": "all"}],
                },
            ]
        }

        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            return _model_reply(duplicated)

        code = run_orchestrated(self.options(json_output=True, post=post))
        self.assertEqual(code, 0)
        subjects = self.git("log", "-2", "--format=%s").splitlines()
        self.assertEqual(subjects, ["Add other file", "Update tracked value"])
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")

    def test_apply_count_reports_the_critic_replan(self) -> None:
        _ = (self.repo / "other.txt").write_text("other\n", encoding="utf-8")
        self.git("add", "other.txt")
        self.stage()
        broad = {
            "commits": [
                {
                    "summary": "Change two things",
                    "details": ["one", "two"],
                    "dependencies": [],
                    "changes": [
                        {"path": "tracked.txt", "hunks": "all"},
                        {"path": "other.txt", "hunks": "all"},
                    ],
                }
            ]
        }
        split = {
            "commits": [
                {
                    "summary": "Update tracked value",
                    "details": [],
                    "dependencies": [],
                    "changes": [{"path": "tracked.txt", "hunks": "all"}],
                },
                {
                    "summary": "Add other file",
                    "details": [],
                    "dependencies": [],
                    "changes": [{"path": "other.txt", "hunks": "all"}],
                },
            ]
        }

        def post(payload: dict[str, object]) -> HttpResponse:
            if "Independent atomicity critic" in _system_of(payload):
                return _model_reply(
                    {"decision": "split", "concerns": ["a", "b"], "rationale": "Two."}
                )
            return _model_reply(
                split if "CORRECTION REQUIRED" in json.dumps(payload) else broad
            )

        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = run_orchestrated(self.options(post=post))
        self.assertEqual(code, 0)
        self.assertIn("Applying 2 commit(s)...", err.getvalue())

    def test_planner_diff_keeps_only_the_head_of_a_deleted_file(self) -> None:
        lines = "".join(f"line {n}\n" for n in range(200))
        _ = (self.repo / "gone.txt").write_text(lines, encoding="utf-8")
        self.git("add", "gone.txt")
        self.git("commit", "-m", "add gone")
        self.git("rm", "-q", "gone.txt")
        diff = self.git("diff", "--cached")
        trimmed = planner_diff(diff, frozenset())
        self.assertIn("-line 39\n", trimmed)
        self.assertNotIn("-line 40\n", trimmed)
        self.assertIn("[160 more deleted line(s) omitted]", trimmed)


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
