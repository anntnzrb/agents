# pyright: reportUninitializedInstanceVariable=false
"""Tests for the rewrite mode: history rebuilding with a frozen target tree."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import override

SKILL_ROOT = Path(__file__).resolve().parents[1]
_ = sys.path.insert(0, str(SKILL_ROOT / "lib"))
from autommit.client import HttpResponse
from autommit.orchestrate import RunOptions
from autommit.rewrite import run_rewrite

PLAN = {
    "commits": [
        {
            "summary": "Add alpha and refresh the readme",
            "details": [],
            "dependencies": [],
            "changes": [
                {"path": "alpha.txt", "hunks": "all"},
                {"path": "README.md", "hunks": "all"},
            ],
        },
        {
            "summary": "Add bravo",
            "details": [],
            "dependencies": [],
            "changes": [{"path": "bravo.txt", "hunks": "all"}],
        },
    ]
}

REORDERED = {
    "commits": [
        {
            "summary": "Add bravo",
            "details": [],
            "dependencies": [],
            "changes": [{"path": "bravo.txt", "hunks": "all"}],
        },
        {
            "summary": "Add alpha and refresh the readme",
            "details": [],
            "dependencies": [0],
            "changes": [
                {"path": "alpha.txt", "hunks": "all"},
                {"path": "README.md", "hunks": "all"},
            ],
        },
    ]
}


def _reply(payload: object) -> HttpResponse:
    return HttpResponse(
        200, {"choices": [{"message": {"content": json.dumps(payload)}}]}
    )


class _RewriteSandbox(unittest.TestCase):
    """Repository with two commits since a base revision plus uncommitted work."""

    temporary_directory: tempfile.TemporaryDirectory[str]
    repo: Path
    base: str
    before: str

    @override
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary_directory.name) / "repo"
        self.repo.mkdir()
        _ = self.git("init", "-b", "main")
        _ = self.git("config", "user.email", "autommit@example.test")
        _ = self.git("config", "user.name", "Autommit Test")
        _ = (self.repo / "README.md").write_text("readme\n", encoding="utf-8")
        _ = self.git("add", "README.md")
        _ = self.git("commit", "-m", "base commit")
        self.base = self.git("rev-parse", "HEAD").strip()
        _ = (self.repo / "alpha.txt").write_text("alpha\n", encoding="utf-8")
        _ = self.git("add", "alpha.txt")
        _ = self.git("commit", "-m", "wip alpha")
        _ = (self.repo / "bravo.txt").write_text("bravo\n", encoding="utf-8")
        _ = self.git("add", "bravo.txt")
        _ = self.git("commit", "-m", "wip bravo")
        self.before = self.git("rev-parse", "HEAD").strip()
        _ = (self.repo / "README.md").write_text("readme\nmore\n", encoding="utf-8")

    @override
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

    def options(
        self,
        *,
        api_key: str | None = "test-key",
        base: str | None = None,
        dry_run: bool = False,
        json_output: bool = False,
        post: Callable[[dict[str, object]], HttpResponse] | None = None,
    ) -> RunOptions:
        return RunOptions(
            repo=self.repo,
            base=self.base if base is None else base,
            api_key=api_key,
            model="test-model",
            base_url="https://model.test/v1",
            dry_run=dry_run,
            json_output=json_output,
            post=post,
        )

    def frozen_tree(self) -> str:
        """Recompute the current worktree tree with a temporary index."""
        index = Path(self.temporary_directory.name) / "probe-index"
        env = {**os.environ, "GIT_INDEX_FILE": str(index)}
        _ = subprocess.run(
            ["git", "read-tree", "HEAD"], cwd=self.repo, check=True, env=env
        )
        _ = subprocess.run(["git", "add", "--all"], cwd=self.repo, check=True, env=env)
        completed = subprocess.run(
            ["git", "write-tree"],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        return completed.stdout.strip()


class RewriteTests(_RewriteSandbox):
    """Cover the frozen tree, dependency order, refusals, and dry runs."""

    def test_frozen_tree_whitespace_refuses_before_model(self) -> None:
        _ = (self.repo / "alpha.txt").write_text("alpha \n", encoding="utf-8")
        # Commit the defect: an index-only check would miss it.
        _ = self.git("add", "alpha.txt")
        _ = self.git("commit", "-m", "bad whitespace")
        before = self.git("rev-parse", "HEAD")

        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            raise AssertionError("gate must refuse before inference")

        self.assertEqual(run_rewrite(self.options(post=post)), 4)
        self.assertEqual(self.git("rev-parse", "HEAD"), before)
        self.assertEqual(run_rewrite(self.options(dry_run=True)), 4)
        self.assertEqual(
            run_rewrite(replace(self.options(dry_run=True), no_verify=True)), 0
        )

    def test_gate_judges_worktree_not_index_and_skips_hook(self) -> None:
        _ = (self.repo / "alpha.txt").write_text("alpha \n", encoding="utf-8")
        _ = self.git("add", "alpha.txt")
        _ = (self.repo / "alpha.txt").write_text("alpha\n", encoding="utf-8")
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        _ = hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        hook.chmod(0o755)
        self.assertEqual(run_rewrite(self.options(dry_run=True)), 0)

    def test_unchanged_base_whitespace_is_not_introduced(self) -> None:
        _ = (self.repo / "README.md").write_text("readme \n", encoding="utf-8")
        _ = self.git("add", "README.md")
        _ = self.git("commit", "-m", "legacy whitespace")
        base = self.git("rev-parse", "HEAD").strip()
        _ = (self.repo / "alpha.txt").write_text("alpha changed\n", encoding="utf-8")
        self.assertEqual(run_rewrite(self.options(base=base, dry_run=True)), 0)

    def test_rewrite_rebuilds_commits_and_preserves_the_frozen_tree(self) -> None:
        target = self.frozen_tree()
        calls: list[dict[str, object]] = []

        def post(payload: dict[str, object]) -> HttpResponse:
            calls.append(payload)
            return _reply(PLAN)

        code = run_rewrite(self.options(json_output=True, post=post))
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").strip(), target)
        self.assertEqual(self.git("rev-parse", "HEAD~2").strip(), self.base)
        self.assertEqual(
            self.git(
                "log", "--reverse", "--format=%s", f"{self.base}..HEAD"
            ).splitlines(),
            ["Add alpha and refresh the readme", "Add bravo"],
        )
        self.assertEqual(
            (self.repo / "README.md").read_text(encoding="utf-8"), "readme\nmore\n"
        )
        self.assertTrue((self.repo / "alpha.txt").is_file())
        self.assertTrue((self.repo / "bravo.txt").is_file())
        self.assertEqual(self.git("status", "--short"), "")
        self.assertEqual(self.git("cat-file", "-t", self.before).strip(), "commit")

    def test_declared_dependencies_control_the_rebuild_order(self) -> None:
        target = self.frozen_tree()

        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            return _reply(REORDERED)

        code = run_rewrite(self.options(post=post))
        self.assertEqual(code, 0)
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").strip(), target)
        self.assertEqual(
            self.git(
                "log", "--reverse", "--format=%s", f"{self.base}..HEAD"
            ).splitlines(),
            ["Add bravo", "Add alpha and refresh the readme"],
        )

    def test_dry_run_rewrites_nothing_and_needs_no_key(self) -> None:
        target = self.frozen_tree()

        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            raise AssertionError("dry run must not call the model")

        code = run_rewrite(
            self.options(api_key=None, dry_run=True, json_output=True, post=post)
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.before)
        self.assertEqual(self.frozen_tree(), target)

    def test_provider_error_leaves_history_untouched(self) -> None:
        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            return HttpResponse(403, {"error": {"message": "denied"}})

        code = run_rewrite(self.options(post=post))
        self.assertEqual(code, 1)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.before)

    def test_planner_correction_recovers_from_a_wrong_path(self) -> None:
        target = self.frozen_tree()
        wrong = {
            "commits": [
                {
                    "summary": "Wrong",
                    "details": [],
                    "dependencies": [],
                    "changes": [{"path": "ghost.txt", "hunks": "all"}],
                }
            ]
        }
        seen: list[str] = []

        def post(payload: dict[str, object]) -> HttpResponse:
            seen.append(json.dumps(payload))
            return _reply(wrong if len(seen) == 1 else PLAN)

        code = run_rewrite(self.options(post=post))
        self.assertEqual(code, 0)
        self.assertEqual(len(seen), 2)
        self.assertIn("not staged", seen[1])
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").strip(), target)

    def test_non_ancestor_base_is_refused(self) -> None:
        _ = self.git("checkout", "-q", "-b", "side", self.base)
        _ = (self.repo / "side.txt").write_text("side\n", encoding="utf-8")
        _ = self.git("add", "side.txt")
        _ = self.git("commit", "-m", "side work")
        side = self.git("rev-parse", "HEAD").strip()
        _ = self.git("checkout", "-q", "main")

        def post(payload: dict[str, object]) -> HttpResponse:
            del payload
            raise AssertionError("invalid base must not reach the model")

        code = run_rewrite(self.options(base=side, post=post))
        self.assertEqual(code, 3)
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "wip bravo")


class RewriteCliTests(_RewriteSandbox):
    """Cover the public CLI wiring for the rewrite subcommand."""

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        isolated_home = Path(self.temporary_directory.name) / "home"
        isolated_home.mkdir(exist_ok=True)
        return subprocess.run(
            [
                "uv",
                "run",
                "--quiet",
                "--script",
                str(SKILL_ROOT / "scripts" / "cli.py"),
                *args,
            ],
            cwd=self.repo,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env={
                **os.environ,
                "HOME": str(isolated_home),
                "XDG_CONFIG_HOME": str(isolated_home / ".config"),
                "GIT_CONFIG_NOSYSTEM": "1",
                "LC_ALL": "C",
            },
        )

    def test_cli_dry_run_reports_the_frozen_scope(self) -> None:
        completed = self.cli("rewrite", "--base", self.base, "--dry-run")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Frozen 3 file(s)", completed.stdout)
        self.assertIn("Dry run only: history was not rewritten.", completed.stdout)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.before)


if __name__ == "__main__":
    _ = unittest.main()
