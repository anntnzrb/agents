# pyright: reportUninitializedInstanceVariable=false
"""Behavioral tests for the portable autommit CLI."""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TypedDict, cast, final

SKILL_ROOT = Path(__file__).resolve().parents[1]
_ = sys.path.insert(0, str(SKILL_ROOT / "lib"))
from autommit.errors import AutommitError
from autommit.git import run_git
from autommit.proposal import (
    MAX_ATOMICITY_DIFF_CHARS,
    compute_apply_order,
    normalize_atomicity_decision,
    normalize_proposal,
    parse_file_diffs,
    requires_atomicity_review,
    truncate_critic_diff,
    validate_proposal_coverage,
)
from autommit.service import MAX_PLAN_FILE_BYTES, _commit_message
from autommit.transaction import Receipt, read_receipt, write_receipt

CLI = SKILL_ROOT / "scripts" / "cli.py"
SCHEMA = "autommit/v1"


class _AppliedCommit(TypedDict):
    summary: str


class _PrepareResult(TypedDict):
    status: str
    context: str
    staged_files: list[str]
    changed_hunk_count: int
    diff: str
    snapshot: str


class _ValidateResult(TypedDict):
    requires_atomicity_review: bool


class _ApplyResult(TypedDict):
    status: str
    commits: list[_AppliedCommit]


class _ErrorDetail(TypedDict):
    code: str
    message: str


@final
class AutommitCliTests(unittest.TestCase):
    """Exercise autommit against disposable Git repositories."""

    maxDiff: int | None = None

    # typing.override needs 3.12+; this ignore marks the intentional override.
    def setUp(self) -> None:  # pyright: ignore[reportImplicitOverride]
        # unittest setUp initializes these instance variables.
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temporary_directory.name)
        self.home = self.temp_path / "home"
        self.home.mkdir()
        self.repo = self.temp_path / "repo"
        self.repo.mkdir()
        _ = self.git("init", "-b", "main")
        _ = self.git("config", "user.email", "autommit@example.test")
        _ = self.git("config", "user.name", "Autommit Test")
        _ = (self.repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        _ = self.git("add", "tracked.txt")
        _ = self.git("commit", "-m", "initial")

    # typing.override needs 3.12+; this ignore marks the intentional override.
    def tearDown(self) -> None:  # pyright: ignore[reportImplicitOverride]
        self.temporary_directory.cleanup()

    def environment(self) -> dict[str, str]:
        return {
            **os.environ,
            "HOME": str(self.home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }

    def git(
        self,
        *args: str,
        cwd: Path | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            check=check,
            capture_output=True,
            text=True,
            env=self.environment(),
        )

    def cli(
        self,
        *args: str,
        expected_code: int = 0,
    ) -> dict[str, object]:
        completed = subprocess.run(
            ["uv", "run", "--quiet", "--script", str(CLI), *args],
            cwd=self.repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=self.environment(),
        )
        self.assertEqual(
            completed.returncode,
            expected_code,
            f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}",
        )
        stream = completed.stdout if expected_code == 0 else completed.stderr
        lines = stream.splitlines()
        self.assertEqual(len(lines), 1, completed)
        payload = cast("dict[str, object]", json.loads(lines[0]))
        self.assertEqual(payload.get("schema"), SCHEMA)
        self.assertEqual(payload.get("ok"), expected_code == 0)
        return payload

    def write_json(self, name: str, value: object) -> Path:
        path = self.temp_path / name
        _ = path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def prepare(self, *context: str, scope: str | None = None) -> _PrepareResult:
        arguments = ["prepare"]
        if scope is not None:
            arguments.extend(["--scope", scope])
        for value in context:
            arguments.extend(["--context", value])
        payload = self.cli(*arguments)
        result = cast("_PrepareResult", payload["result"])
        self.assertEqual(result["status"], "prepared")
        return result

    @staticmethod
    def whole_file_plan(
        *paths: str, summary: str = "Update files"
    ) -> dict[str, object]:
        return {
            "commits": [
                {
                    "summary": summary,
                    "details": [],
                    "changes": [{"path": path, "hunks": "all"} for path in paths],
                }
            ]
        }

    def test_schema_and_help_are_available_without_repository_mutation(self) -> None:
        payload = self.cli("schema")
        result = cast("dict[str, object]", payload["result"])
        self.assertEqual(result["protocol"], SCHEMA)
        commands = cast("dict[str, object]", result["commands"])
        self.assertIn("prepare", commands)
        self.assertIn("apply", commands)
        self.assertFalse((self.repo / ".git" / "autommit").exists())

        completed = subprocess.run(
            ["uv", "run", "--quiet", "--script", str(CLI), "--help"],
            cwd=self.repo,
            check=False,
            capture_output=True,
            text=True,
            env=self.environment(),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--dry-run", completed.stdout)
        self.assertIn("--smoke", completed.stdout)

    def test_prepare_stages_all_only_when_the_index_is_empty(self) -> None:
        _ = (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        result = self.prepare("keep formatting out", "split docs")

        self.assertEqual(result["context"], "keep formatting out\n\nsplit docs")
        self.assertEqual(result["staged_files"], ["tracked.txt"])
        self.assertIn("+changed", result["diff"])
        self.assertEqual(self.git("diff", "--name-only").stdout, "")

        _ = (self.repo / "tracked.txt").write_text("staged\n", encoding="utf-8")
        _ = self.git("add", "tracked.txt")
        _ = (self.repo / "tracked.txt").write_text(
            "staged\nunstaged\n", encoding="utf-8"
        )
        _ = (self.repo / "untracked.txt").write_text("leave out\n", encoding="utf-8")
        index_tree = self.git("write-tree").stdout
        result = self.prepare()
        self.assertEqual(self.git("write-tree").stdout, index_tree)
        self.assertEqual(result["staged_files"], ["tracked.txt"])
        self.assertIn("+staged", result["diff"])
        self.assertNotIn("+unstaged", result["diff"])
        self.assertEqual(self.git("diff", "--name-only").stdout.strip(), "tracked.txt")

    def test_apply_commits_exact_staged_snapshot_and_preserves_unstaged_work(
        self,
    ) -> None:
        _ = (self.repo / "tracked.txt").write_text("staged\n", encoding="utf-8")
        _ = self.git("add", "tracked.txt")
        _ = (self.repo / "tracked.txt").write_text(
            "staged\nunstaged\n", encoding="utf-8"
        )
        prepared = self.prepare()
        plan = self.write_json(
            "plan.json",
            self.whole_file_plan("tracked.txt", summary="Update tracked value"),
        )

        validation = cast(
            "_ValidateResult",
            self.cli(
                "validate-plan",
                "--snapshot",
                prepared["snapshot"],
                "--plan-file",
                str(plan),
            )["result"],
        )
        self.assertFalse(validation["requires_atomicity_review"])

        applied = cast(
            "_ApplyResult",
            self.cli(
                "apply",
                "--snapshot",
                prepared["snapshot"],
                "--plan-file",
                str(plan),
            )["result"],
        )
        self.assertEqual(applied["status"], "committed")
        self.assertEqual(len(applied["commits"]), 1)
        self.assertEqual(applied["commits"][0]["summary"], "Update tracked value")
        self.assertEqual(self.git("show", "HEAD:tracked.txt").stdout, "staged\n")
        self.assertEqual(
            (self.repo / "tracked.txt").read_text(encoding="utf-8"),
            "staged\nunstaged\n",
        )
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, "")
        self.assertEqual(self.git("diff", "--name-only").stdout.strip(), "tracked.txt")

    def test_broad_single_commit_requires_valid_atomicity_acceptance(self) -> None:
        _ = (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        _ = (self.repo / "other.txt").write_text("other\n", encoding="utf-8")
        _ = self.git("add", "tracked.txt", "other.txt")
        prepared = self.prepare()
        plan = self.write_json(
            "broad-plan.json",
            self.whole_file_plan("tracked.txt", "other.txt"),
        )

        validation = cast(
            "_ValidateResult",
            self.cli(
                "validate-plan",
                "--snapshot",
                prepared["snapshot"],
                "--plan-file",
                str(plan),
            )["result"],
        )
        self.assertTrue(validation["requires_atomicity_review"])
        split_error = cast(
            "_ErrorDetail",
            self.cli(
                "validate-plan",
                "--snapshot",
                prepared["snapshot"],
                "--plan-file",
                str(plan),
                "--require-split",
                expected_code=2,
            )["error"],
        )
        self.assertEqual(split_error["code"], "split_required")
        _ = self.cli(
            "apply",
            "--snapshot",
            prepared["snapshot"],
            "--plan-file",
            str(plan),
            expected_code=2,
        )

        decision = self.write_json(
            "decision.json",
            {"decision": "accept", "concerns": [], "rationale": "One behavior."},
        )
        applied = cast(
            "_ApplyResult",
            self.cli(
                "apply",
                "--snapshot",
                prepared["snapshot"],
                "--plan-file",
                str(plan),
                "--decision-file",
                str(decision),
            )["result"],
        )
        self.assertEqual(applied["status"], "committed")

    def test_split_plan_applies_bottom_up_and_matches_the_index_tree(self) -> None:
        original = "\n".join(f"line {index}" for index in range(1, 13)) + "\n"
        changed_lines = original.splitlines()
        changed_lines[0] = "first changed"
        changed_lines[10] = "eleventh changed"
        _ = (self.repo / "tracked.txt").write_text(original, encoding="utf-8")
        _ = self.git("add", "tracked.txt")
        _ = self.git("commit", "-m", "expand fixture")
        _ = (self.repo / "tracked.txt").write_text(
            "\n".join(changed_lines) + "\n",
            encoding="utf-8",
        )
        _ = self.git("add", "tracked.txt")
        prepared = self.prepare()
        expected_tree = self.git("write-tree").stdout.strip()
        plan = self.write_json(
            "split-plan.json",
            {
                "commits": [
                    {
                        "summary": "Change first line",
                        "details": [],
                        "changes": [
                            {
                                "path": "tracked.txt",
                                "hunks": {"type": "indices", "indices": [1]},
                            }
                        ],
                    },
                    {
                        "summary": "Change eleventh line",
                        "details": [],
                        "changes": [
                            {
                                "path": "tracked.txt",
                                "hunks": {"type": "indices", "indices": [2]},
                            }
                        ],
                    },
                ]
            },
        )

        applied = cast(
            "_ApplyResult",
            self.cli(
                "apply",
                "--snapshot",
                prepared["snapshot"],
                "--plan-file",
                str(plan),
            )["result"],
        )
        self.assertEqual(len(applied["commits"]), 2)
        self.assertEqual(
            self.git("rev-parse", "HEAD^{tree}").stdout.strip(), expected_tree
        )
        self.assertEqual(
            self.git("log", "-2", "--format=%s").stdout.splitlines(),
            ["Change eleventh line", "Change first line"],
        )

    def test_apply_refuses_when_the_prepared_snapshot_changed(self) -> None:
        _ = (self.repo / "tracked.txt").write_text("first\n", encoding="utf-8")
        _ = self.git("add", "tracked.txt")
        prepared = self.prepare()
        plan = self.write_json("plan.json", self.whole_file_plan("tracked.txt"))
        _ = (self.repo / "tracked.txt").write_text("second\n", encoding="utf-8")
        _ = self.git("add", "tracked.txt")

        error = cast(
            "_ErrorDetail",
            self.cli(
                "apply",
                "--snapshot",
                prepared["snapshot"],
                "--plan-file",
                str(plan),
                expected_code=3,
            )["error"],
        )
        self.assertEqual(error["code"], "snapshot_changed")
        self.assertEqual(self.git("log", "-1", "--format=%s").stdout.strip(), "initial")

    def test_invalid_plan_cannot_omit_or_overlap_staged_changes(self) -> None:
        _ = (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        _ = (self.repo / "other.txt").write_text("other\n", encoding="utf-8")
        _ = self.git("add", "tracked.txt", "other.txt")
        prepared = self.prepare()
        plan = self.write_json(
            "invalid-plan.json",
            {
                "commits": [
                    {
                        "summary": "One",
                        "details": [],
                        "changes": [{"path": "tracked.txt", "hunks": "all"}],
                    },
                    {
                        "summary": "Two",
                        "details": [],
                        "changes": [{"path": "tracked.txt", "hunks": "all"}],
                    },
                ]
            },
        )

        error = cast(
            "_ErrorDetail",
            self.cli(
                "validate-plan",
                "--snapshot",
                prepared["snapshot"],
                "--plan-file",
                str(plan),
                expected_code=2,
            )["error"],
        )
        message = error["message"]
        self.assertIn("other.txt", message)
        self.assertIn("Overlapping", message)

    def test_models_lists_ids_without_a_configured_model(self) -> None:
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--quiet",
                "--script",
                str(CLI),
                "models",
                "--filter",
                "nonexistent",
                "--base-url",
                "https://models.example.test/v1",
                "--api-key",
                "keyless",
            ],
            cwd=self.repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env=self.environment(),
        )
        self.assertNotIn("missing_model", completed.stderr)
        self.assertNotIn("missing_base_url", completed.stderr)
        # The placeholder endpoint does not resolve, so discovery fails at
        # transport rather than at configuration.
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertIn("provider_error", completed.stderr)

    def test_oversized_plan_file_is_rejected(self) -> None:
        _ = (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        _ = self.git("add", "tracked.txt")
        prepared = self.prepare()
        plan = self.temp_path / "huge-plan.json"
        _ = plan.write_text("x" * (MAX_PLAN_FILE_BYTES + 1), encoding="utf-8")

        payload = self.cli(
            "apply",
            "--snapshot",
            prepared["snapshot"],
            "--plan-file",
            str(plan),
            expected_code=2,
        )

        error = cast("_ErrorDetail", payload["error"])
        self.assertEqual(error["code"], "invalid_file")
        self.assertEqual(self.git("log", "-1", "--format=%s").stdout.strip(), "initial")

    def test_context_options_match_the_pi_command_contract(self) -> None:
        _ = (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--quiet",
                "--script",
                str(CLI),
                "prepare",
                "first",
                "--context",
                "second",
                "--context=third",
                "--",
                "-literal",
            ],
            cwd=self.repo,
            check=False,
            capture_output=True,
            text=True,
            env=self.environment(),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = cast("_PrepareResult", json.loads(completed.stdout)["result"])
        self.assertEqual(result["context"], "first\n\nsecond\n\nthird\n\n-literal")

    def test_recovers_a_prepared_pi_receipt_before_planning_new_work(self) -> None:
        _ = (self.repo / "tracked.txt").write_text("recovered\n", encoding="utf-8")
        _ = self.git("add", "tracked.txt")
        before = self.git("rev-parse", "HEAD").stdout.strip()
        index_tree = self.git("write-tree").stdout.strip()
        after = self.git(
            "commit-tree",
            index_tree,
            "-p",
            before,
            "-m",
            "recovered commit",
        ).stdout.strip()
        transaction_dir = self.repo / ".git" / "autommit"
        transaction_dir.mkdir()
        receipt = transaction_dir / "receipt.json"
        _ = receipt.write_text(
            json.dumps(
                {
                    "version": 1,
                    "state": "prepared",
                    "ref": "refs/heads/main",
                    "before": before,
                    "after": after,
                    "indexTree": index_tree,
                }
            ),
            encoding="utf-8",
        )

        result = cast("_PrepareResult", self.cli("prepare")["result"])
        self.assertEqual(result["status"], "recovered")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), after)
        self.assertFalse(receipt.exists())

    def test_never_removes_an_existing_operation_lock(self) -> None:
        _ = (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        transaction_dir = self.repo / ".git" / "autommit"
        transaction_dir.mkdir()
        lock = transaction_dir / "operation.lock"
        _ = lock.write_text('{"pid":999999,"token":"stale"}\n', encoding="utf-8")

        error = cast("_ErrorDetail", self.cli("prepare", expected_code=3)["error"])
        self.assertEqual(error["code"], "operation_locked")
        self.assertTrue(lock.exists())

    @unittest.skipIf(os.name == "nt", "symlink creation is not reliably available")
    def test_refuses_a_symlinked_receipt_without_touching_its_target(self) -> None:
        _ = (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        transaction_dir = self.repo / ".git" / "autommit"
        transaction_dir.mkdir()
        outside = self.temp_path / "outside-receipt.json"
        _ = outside.write_text("outside\n", encoding="utf-8")
        receipt = transaction_dir / "receipt.json"
        receipt.symlink_to(outside)

        error = cast("_ErrorDetail", self.cli("prepare", expected_code=2)["error"])
        self.assertEqual(error["code"], "invalid_receipt_file")
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")
        self.assertTrue(receipt.is_symlink())

    def test_commits_a_quoted_path_with_spaces(self) -> None:
        filename = "space name.txt"
        _ = (self.repo / filename).write_text("content\n", encoding="utf-8")
        _ = self.git("add", filename)
        prepared = self.prepare()
        self.assertEqual(prepared["staged_files"], [filename])
        plan = self.write_json(
            "space-plan.json",
            self.whole_file_plan(filename, summary="Add spaced path"),
        )

        result = cast(
            "_ApplyResult",
            self.cli(
                "apply",
                "--snapshot",
                prepared["snapshot"],
                "--plan-file",
                str(plan),
            )["result"],
        )
        self.assertEqual(result["status"], "committed")
        self.assertEqual(self.git("show", f"HEAD:{filename}").stdout, "content\n")

    def test_concurrent_worktrees_can_commit_independently(self) -> None:
        worktree_path = self.temp_path / "other-worktree"
        _ = self.git("worktree", "add", "-b", "feature-branch", str(worktree_path))
        _ = (self.repo / "main_file.txt").write_text("main changes\n", encoding="utf-8")
        _ = (worktree_path / "feature_file.txt").write_text(
            "feature changes\n", encoding="utf-8"
        )

        prep_main = self.prepare()
        prep_feat = cast(
            "_PrepareResult",
            self.cli("prepare", "--repo", str(worktree_path))["result"],
        )

        plan_main = self.write_json(
            "main-plan.json",
            self.whole_file_plan("main_file.txt", summary="Main commit"),
        )
        plan_feat = self.write_json(
            "feat-plan.json",
            self.whole_file_plan("feature_file.txt", summary="Feature commit"),
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut_main = executor.submit(
                self.cli,
                "apply",
                "--snapshot",
                prep_main["snapshot"],
                "--plan-file",
                str(plan_main),
            )
            fut_feat = executor.submit(
                self.cli,
                "apply",
                "--snapshot",
                prep_feat["snapshot"],
                "--plan-file",
                str(plan_feat),
                "--repo",
                str(worktree_path),
            )
            res_main = fut_main.result()
            res_feat = fut_feat.result()

        applied_main = cast("_ApplyResult", res_main["result"])
        applied_feat = cast("_ApplyResult", res_feat["result"])

        self.assertEqual(applied_main["status"], "committed")
        self.assertEqual(applied_feat["status"], "committed")
        self.assertEqual(
            self.git("show", "HEAD:main_file.txt").stdout, "main changes\n"
        )
        completed_feat = subprocess.run(
            ["git", "-C", str(worktree_path), "show", "HEAD:feature_file.txt"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(completed_feat.stdout, "feature changes\n")

    def test_lines_selector_splits_added_file_cleanly(self) -> None:
        added_content = "line1\nline2\nline3\nline4\n"
        _ = (self.repo / "split_file.txt").write_text(added_content, encoding="utf-8")
        prepared = self.prepare()
        expected_tree = self.git("write-tree").stdout.strip()
        plan = self.write_json(
            "lines-plan.json",
            {
                "commits": [
                    {
                        "summary": "Add first half",
                        "details": [],
                        "changes": [
                            {
                                "path": "split_file.txt",
                                "hunks": {"type": "lines", "start": 1, "end": 2},
                            }
                        ],
                    },
                    {
                        "summary": "Add second half",
                        "details": [],
                        "changes": [
                            {
                                "path": "split_file.txt",
                                "hunks": {"type": "lines", "start": 3, "end": 4},
                            }
                        ],
                    },
                ]
            },
        )
        applied = cast(
            "_ApplyResult",
            self.cli(
                "apply",
                "--snapshot",
                prepared["snapshot"],
                "--plan-file",
                str(plan),
            )["result"],
        )
        self.assertEqual(len(applied["commits"]), 2)
        self.assertEqual(
            self.git("rev-parse", "HEAD^{tree}").stdout.strip(), expected_tree
        )
        self.assertEqual(self.git("show", "HEAD:split_file.txt").stdout, added_content)

    def test_quoted_octal_utf8_path_decodes_and_commits_cleanly(self) -> None:
        filename = "é_file.txt"
        _ = (self.repo / filename).write_text(
            "accented filename content\n", encoding="utf-8"
        )
        prepared = self.prepare()
        plan = self.write_json(
            "utf8-plan.json",
            self.whole_file_plan(filename, summary="Add accented file"),
        )
        applied = cast(
            "_ApplyResult",
            self.cli(
                "apply",
                "--snapshot",
                prepared["snapshot"],
                "--plan-file",
                str(plan),
            )["result"],
        )
        self.assertEqual(applied["status"], "committed")
        self.assertEqual(
            self.git("show", f"HEAD:{filename}").stdout, "accented filename content\n"
        )

    def test_missing_required_keys_in_proposal_returns_invalid_plan(self) -> None:
        _ = (self.repo / "test.txt").write_text("content\n", encoding="utf-8")
        prepared = self.prepare()
        plan = self.write_json("empty-plan.json", {})
        error = cast(
            "_ErrorDetail",
            self.cli(
                "validate-plan",
                "--snapshot",
                prepared["snapshot"],
                "--plan-file",
                str(plan),
                expected_code=2,
            )["error"],
        )
        self.assertEqual(error["code"], "invalid_plan")

    def test_dependencies_drive_the_apply_order(self) -> None:
        for name, content in (
            ("a.txt", "alpha\n"),
            ("b.txt", "bravo\n"),
            ("c.txt", "charlie\n"),
        ):
            _ = (self.repo / name).write_text(content, encoding="utf-8")
        _ = self.git("add", "--all")
        prepared = self.prepare()
        expected_tree = self.git("write-tree").stdout.strip()
        plan = self.write_json(
            "dependency-plan.json",
            {
                "commits": [
                    {
                        "summary": "Third file",
                        "details": [],
                        "dependencies": [2],
                        "changes": [{"path": "c.txt", "hunks": "all"}],
                    },
                    {
                        "summary": "Second file",
                        "details": [],
                        "dependencies": [2],
                        "changes": [{"path": "b.txt", "hunks": "all"}],
                    },
                    {
                        "summary": "First file",
                        "details": [],
                        "dependencies": [],
                        "changes": [{"path": "a.txt", "hunks": "all"}],
                    },
                ]
            },
        )

        applied = cast(
            "_ApplyResult",
            self.cli(
                "apply",
                "--snapshot",
                prepared["snapshot"],
                "--plan-file",
                str(plan),
            )["result"],
        )
        self.assertEqual(len(applied["commits"]), 3)
        self.assertEqual(
            self.git("rev-parse", "HEAD^{tree}").stdout.strip(), expected_tree
        )
        self.assertEqual(
            self.git("log", "-3", "--format=%s").stdout.splitlines(),
            ["Second file", "Third file", "First file"],
        )

    def test_diff_indices_survive_hostile_git_configuration(self) -> None:
        original = "\n".join(f"line {index}" for index in range(1, 25)) + "\n"
        _ = (self.repo / "tracked.txt").write_text(original, encoding="utf-8")
        _ = self.git("add", "tracked.txt")
        _ = self.git("commit", "-m", "expand fixture")
        changed = original.splitlines()
        changed[0] = "first changed"
        changed[11] = "twelfth changed"
        _ = (self.repo / "tracked.txt").write_text(
            "\n".join(changed) + "\n", encoding="utf-8"
        )
        _ = self.git("add", "tracked.txt")
        _ = self.git("config", "diff.interHunkContext", "12")
        _ = self.git("config", "diff.algorithm", "minimal")
        previous = os.environ.get("GIT_DIFF_OPTS")
        os.environ["GIT_DIFF_OPTS"] = "--unified=12"
        try:
            prepared = self.prepare()
        finally:
            if previous is None:
                _ = os.environ.pop("GIT_DIFF_OPTS", None)
            else:
                os.environ["GIT_DIFF_OPTS"] = previous
        self.assertEqual(prepared["changed_hunk_count"], 2)
        self.assertEqual(prepared["staged_files"], ["tracked.txt"])

    def test_refuses_while_a_git_operation_is_in_progress(self) -> None:
        _ = (self.repo / "tracked.txt").write_text("merged\n", encoding="utf-8")
        _ = self.git("add", "tracked.txt")
        git_dir = Path(self.git("rev-parse", "--absolute-git-dir").stdout.strip())
        _ = (git_dir / "MERGE_HEAD").write_text("0" * 40 + "\n", encoding="utf-8")

        payload = self.cli("prepare", expected_code=3)
        error = cast("_ErrorDetail", payload["error"])
        self.assertEqual(error["code"], "in_progress_state")
        self.assertEqual(self.git("log", "-1", "--format=%s").stdout.strip(), "initial")
        self.assertEqual(
            self.git("diff", "--cached", "--name-only").stdout.strip(), "tracked.txt"
        )

    def test_ignores_a_finished_rebase_marker(self) -> None:
        _ = (self.repo / "tracked.txt").write_text("after rebase\n", encoding="utf-8")
        _ = self.git("add", "tracked.txt")
        git_dir = Path(self.git("rev-parse", "--absolute-git-dir").stdout.strip())
        # A completed rebase can leave REBASE_HEAD behind. Only the rebase-merge or
        # rebase-apply directory marks a rebase that is still running.
        _ = (git_dir / "REBASE_HEAD").write_text("0" * 40 + "\n", encoding="utf-8")

        prepared = self.prepare()

        self.assertEqual(prepared["staged_files"], ["tracked.txt"])

    def test_refuses_while_a_rebase_directory_exists(self) -> None:
        _ = (self.repo / "tracked.txt").write_text("rebasing\n", encoding="utf-8")
        _ = self.git("add", "tracked.txt")
        git_dir = Path(self.git("rev-parse", "--absolute-git-dir").stdout.strip())
        (git_dir / "rebase-merge").mkdir()

        payload = self.cli("prepare", expected_code=3)

        error = cast("_ErrorDetail", payload["error"])
        self.assertEqual(error["code"], "in_progress_state")
        self.assertEqual(self.git("log", "-1", "--format=%s").stdout.strip(), "initial")


class AutommitUnitTests(unittest.TestCase):
    """Unit tests for normalized proposals and Git helpers."""

    def test_normalize_proposal(self) -> None:
        valid = {
            "commits": [
                {
                    "summary": "feat: test",
                    "details": ["one change"],
                    "changes": [{"path": "a.txt", "hunks": "all"}],
                }
            ]
        }
        proposal = normalize_proposal(valid)
        self.assertEqual(len(proposal.commits), 1)
        self.assertEqual(proposal.commits[0].summary, "feat: test")

        # 0-based hunk index must be rejected with invalid_plan error
        invalid_zero_index = {
            "commits": [
                {
                    "summary": "feat: zero index",
                    "details": [],
                    "changes": [{"path": "a.txt", "hunks": [0]}],
                }
            ]
        }
        with self.assertRaises(AutommitError):
            _ = normalize_proposal(invalid_zero_index)

    def test_normalize_atomicity_decision(self) -> None:
        valid_accept = {
            "decision": "accept",
            "concerns": [],
            "rationale": "Single concern.",
        }
        decision = normalize_atomicity_decision(valid_accept)
        self.assertEqual(decision.decision, "accept")

        invalid_split = {
            "decision": "split",
            "concerns": [],
            "rationale": "Needs split.",
        }
        with self.assertRaises(AutommitError):
            _ = normalize_atomicity_decision(invalid_split)

    def test_dependencies_reject_self_range_duplicates_and_cycles(self) -> None:
        def single_commit(dependencies: object) -> dict[str, object]:
            return {
                "commits": [
                    {
                        "summary": "One",
                        "details": [],
                        "dependencies": dependencies,
                        "changes": [{"path": "tracked.txt", "hunks": "all"}],
                    }
                ]
            }

        for invalid in ([0], [1], [0, 0]):
            with self.assertRaises(AutommitError) as raised:
                _ = normalize_proposal(single_commit(invalid))
            self.assertEqual(raised.exception.code, "invalid_plan")

        cyclic = {
            "commits": [
                {
                    "summary": "One",
                    "details": [],
                    "dependencies": [1],
                    "changes": [{"path": "a.txt", "hunks": "all"}],
                },
                {
                    "summary": "Two",
                    "details": [],
                    "dependencies": [0],
                    "changes": [{"path": "b.txt", "hunks": "all"}],
                },
            ]
        }
        with self.assertRaises(AutommitError) as raised_cycle:
            _ = normalize_proposal(cyclic)
        self.assertEqual(raised_cycle.exception.code, "invalid_plan")

        chain = {
            "commits": [
                {
                    "summary": "One",
                    "details": [],
                    "dependencies": [1],
                    "changes": [{"path": "a.txt", "hunks": "all"}],
                },
                {
                    "summary": "Two",
                    "details": [],
                    "dependencies": [],
                    "changes": [{"path": "b.txt", "hunks": "all"}],
                },
            ]
        }
        proposal = normalize_proposal(chain)
        self.assertEqual(compute_apply_order(proposal.commits), (1, 0))

    def test_critic_diff_cap_bounds_only_oversized_diffs(self) -> None:
        small = "diff --git a/x b/x\n"
        self.assertEqual(truncate_critic_diff(small), (small, False))
        oversized = "x" * (MAX_ATOMICITY_DIFF_CHARS + 64)
        bounded, truncated = truncate_critic_diff(oversized)
        self.assertTrue(truncated)
        self.assertEqual(len(bounded), MAX_ATOMICITY_DIFF_CHARS)

    def test_single_commit_with_extra_details_requires_review(self) -> None:
        diff = "diff --git a/a.txt b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"

        def plan(details: list[str]) -> dict[str, object]:
            return {
                "commits": [
                    {
                        "summary": "Broad change",
                        "details": details,
                        "changes": [{"path": "a.txt", "hunks": "all"}],
                    }
                ]
            }

        broad = normalize_proposal(plan(["one", "two"]))
        narrow = normalize_proposal(plan([]))
        self.assertTrue(requires_atomicity_review(broad, diff))
        self.assertFalse(requires_atomicity_review(narrow, diff))

        split = normalize_proposal(
            {
                "commits": [
                    {
                        "summary": "Broad change",
                        "details": [],
                        "changes": [{"path": "a.txt", "hunks": "all"}],
                    },
                    {
                        "summary": "Second change",
                        "details": ["one"],
                        "changes": [{"path": "b.txt", "hunks": "all"}],
                    },
                ]
            }
        )
        self.assertFalse(requires_atomicity_review(split, diff))

    def test_plans_are_not_capped_by_arbitrary_counts(self) -> None:
        commits = [
            {
                "summary": f"Change {index}",
                "details": [f"detail {number}" for number in range(80)],
                "changes": [
                    {"path": f"path-{number}.txt", "hunks": "all"}
                    for number in range(300)
                ],
                "dependencies": list(range(index)),
            }
            for index in range(40)
        ]
        proposal = normalize_proposal({"commits": commits})
        self.assertEqual(len(proposal.commits), 40)
        self.assertEqual(len(proposal.commits[0].details), 80)
        self.assertEqual(len(proposal.commits[0].changes), 300)
        self.assertEqual(len(proposal.commits[-1].dependencies), 39)

    def test_subjects_are_capped_at_seventy_two_characters(self) -> None:
        def plan(summary: str) -> dict[str, object]:
            return {
                "commits": [
                    {
                        "summary": summary,
                        "details": [],
                        "changes": [{"path": "a.txt", "hunks": "all"}],
                    }
                ]
            }

        self.assertEqual(len(normalize_proposal(plan("a" * 72)).commits), 1)
        with self.assertRaises(AutommitError) as raised:
            _ = normalize_proposal(plan("a" * 73))
        self.assertEqual(raised.exception.code, "invalid_plan")

    def test_commit_message_normalizes_the_subject_period(self) -> None:
        proposal = normalize_proposal(
            {
                "commits": [
                    {
                        "summary": "Add retry to the planner.",
                        "details": [
                            "Retry once after a transport failure.",
                            "- Keeps the ladder",
                        ],
                        "changes": [{"path": "a.txt", "hunks": "all"}],
                    }
                ]
            }
        )
        self.assertEqual(
            _commit_message(proposal.commits[0]),
            "Add retry to the planner\n\n"
            "- Retry once after a transport failure.\n"
            "- Keeps the ladder",
        )

    def test_commit_message_keeps_a_subject_without_a_period(self) -> None:
        proposal = normalize_proposal(
            {
                "commits": [
                    {
                        "summary": "Add retry to the planner",
                        "details": [],
                        "changes": [{"path": "a.txt", "hunks": "all"}],
                    }
                ]
            }
        )
        self.assertEqual(
            _commit_message(proposal.commits[0]), "Add retry to the planner"
        )

    def test_lines_selector_coverage_accepts_a_modified_file(self) -> None:
        diff = (
            "diff --git a/a.txt b/a.txt\n"
            "index 1111111..2222222 100644\n"
            "--- a/a.txt\n"
            "+++ b/a.txt\n"
            "@@ -1,3 +1,4 @@\n"
            "-one\n"
            "+one changed\n"
            " two\n"
            " three\n"
            "+four\n"
        )
        proposal = normalize_proposal(
            {
                "commits": [
                    {
                        "summary": "Change the first line",
                        "details": [],
                        "changes": [
                            {
                                "path": "a.txt",
                                "hunks": {"type": "lines", "start": 1, "end": 1},
                            }
                        ],
                    },
                    {
                        "summary": "Add the fourth line",
                        "details": [],
                        "changes": [
                            {
                                "path": "a.txt",
                                "hunks": {"type": "lines", "start": 4, "end": 4},
                            }
                        ],
                    },
                ]
            }
        )
        parsed = parse_file_diffs(diff)
        self.assertEqual(
            validate_proposal_coverage(proposal, ("a.txt",), parsed),
            (),
        )

    def test_lines_selector_coverage_rejects_overlapping_ranges(self) -> None:
        diff = (
            "diff --git a/a.txt b/a.txt\n"
            "index 1111111..2222222 100644\n"
            "--- a/a.txt\n"
            "+++ b/a.txt\n"
            "@@ -1,3 +1,3 @@\n"
            "-one\n"
            "+one changed\n"
            "-two\n"
            "+two changed\n"
            " three\n"
        )
        proposal = normalize_proposal(
            {
                "commits": [
                    {
                        "summary": "Change the first line",
                        "details": [],
                        "changes": [
                            {
                                "path": "a.txt",
                                "hunks": {"type": "lines", "start": 1, "end": 2},
                            }
                        ],
                    },
                    {
                        "summary": "Change the second line",
                        "details": [],
                        "changes": [
                            {
                                "path": "a.txt",
                                "hunks": {"type": "lines", "start": 2, "end": 3},
                            }
                        ],
                    },
                ]
            }
        )
        errors = validate_proposal_coverage(
            proposal, ("a.txt",), parse_file_diffs(diff)
        )
        self.assertTrue(any("Overlapping" in error for error in errors), errors)

    def test_run_git(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            _ = run_git(repo, "init", "-b", "main")
            with self.assertRaises(AutommitError):
                _ = run_git(repo, "non-existent-subcommand")

    def test_receipt_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            common_dir = Path(temp_dir)
            self.assertIsNone(read_receipt(common_dir))

            receipt = Receipt(
                version=1,
                state="prepared",
                ref="refs/heads/main",
                before="1" * 40,
                after="2" * 40,
                index_tree="3" * 40,
            )
            write_receipt(common_dir, receipt)
            read_back = read_receipt(common_dir)
            self.assertIsNotNone(read_back)
            if read_back is not None:
                self.assertEqual(read_back.ref, "refs/heads/main")
                self.assertEqual(read_back.after, "2" * 40)


if __name__ == "__main__":
    _ = unittest.main()
