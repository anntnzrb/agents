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
    normalize_atomicity_decision,
    normalize_proposal,
)
from autommit.transaction import Receipt, read_receipt, write_receipt

CLI = SKILL_ROOT / "scripts" / "cli.py"
SCHEMA = "autommit/v1"


class _AppliedCommit(TypedDict):
    summary: str


class _PrepareResult(TypedDict):
    status: str
    context: str
    staged_files: list[str]
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
        self.assertIn("prepare", completed.stdout)

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
        result = self.prepare(scope="staged")
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
        prepared = self.prepare(scope="staged")
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
