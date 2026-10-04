"""Exercise landing through the public CLI and real Git repositories."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast, final

import pytest

CLI = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"
FAKE_GH = """#!{python}
import json, os, subprocess, sys
from pathlib import Path
root = Path(os.environ["FIXTURE"])
config = json.loads((root / "config.json").read_text())
statefile = root / "state.json"
state = (json.loads(statefile.read_text()) if statefile.exists()
         else {{"queued": False, "updated": False, "polls": 0}})
args = sys.argv[1:]
with (root / "commands.jsonl").open("a") as out:
    out.write(json.dumps(args) + "\\n")
def git(*args):
    return subprocess.check_output(
        ["git", "--git-dir", str(root / "origin.git"), *args], text=True).strip()
if args[:2] == ["repo", "view"]:
    print(json.dumps({{"nameWithOwner": "owner/repo"}}))
elif args[:2] == ["pr", "checks"]:
    failed = config["scenario"] == "failed"
    print(json.dumps([{{"name": "CI required",
        "bucket": "fail" if failed else "pass",
        "link": "https://example.test/run/42"}}]))
    sys.exit(1 if failed else 0)
elif args[:2] == ["pr", "merge"]:
    state["queued"] = True
    if config["scenario"] == "uncertain":
        statefile.write_text(json.dumps(state))
        sys.exit(1)
elif args[:2] == ["api", "-X"]:
    state["updated"] = True
    state["queued"] = False
    tree = git("rev-parse", "main^{{tree}}")
    new = subprocess.check_output(["git", "--git-dir", str(root / "origin.git"),
        "commit-tree", tree, "-p", config["head"]],
        input="Rebased\\n", text=True).strip()
    git("update-ref", "refs/heads/topic", new)
    state["head"] = new
elif args[:2] == ["pr", "view"]:
    state["polls"] += int(state["queued"])
    scenario = config["scenario"]
    merged = (state["queued"] and state["polls"] >= 2
        and scenario not in ["failed", "timeout", "closed"]
        and (scenario != "behind" or state["updated"]))
    head = state.get("head", config["head"])
    if merged:
        git("update-ref", "refs/heads/main", head)
    if merged and scenario == "remote_deleted":
        git("update-ref", "-d", "refs/heads/topic")
    print(json.dumps({{"number": 7, "title": "Scoped change",
        "headRefName": "topic",
        "headRefOid": "0" * 40 if scenario == "mismatch" else head,
        "baseRefName": config.get("base", "main"),
        "state": "MERGED" if merged else "CLOSED" if scenario == "closed" else "OPEN",
        "mergeStateStatus": "BEHIND" if scenario == "behind"
            and not state["updated"] else "CLEAN",
        "autoMergeRequest": {{"mergeMethod": "MERGE"}} if state["queued"] else None,
        "statusCheckRollup": [], "isCrossRepository": False}}))
else:
    sys.exit("unexpected gh command: " + repr(args))
statefile.write_text(json.dumps(state))
"""


@final
class Repository:
    """Temporary real repository with a scripted GitHub boundary."""

    def __init__(self, root: Path) -> None:
        """Create the repository, branch, worktree, and fake executable."""
        self.root = root
        self.repo = root / "repo"
        self.worktree = root / "task"
        self.env = os.environ | {
            "HOME": str(root),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.test",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.test",
            "FIXTURE": str(root),
            "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"],
        }
        self.repo.mkdir()
        _ = self.git("init", "--bare", str(root / "origin.git"))
        _ = self.git("init", "-b", "main")
        _ = self.git("commit", "--allow-empty", "-m", "Base")
        _ = self.git("remote", "add", "origin", str(root / "origin.git"))
        _ = self.git("push", "origin", "main")
        _ = self.git("worktree", "add", "-b", "topic", str(self.worktree))
        _ = self.git("-C", str(self.worktree), "commit", "--allow-empty", "-m", "Task")
        self.head = self.git("rev-parse", "topic")
        _ = self.git("push", "origin", "topic")
        (root / "bin").mkdir()
        fake = root / "bin" / "gh"
        _ = fake.write_text(FAKE_GH.format(python=sys.executable), encoding="utf-8")
        fake.chmod(0o755)

    def git(self, *args: str) -> str:
        """Run real Git in the fixture."""
        return subprocess.check_output(
            ["git", *args],
            cwd=self.repo,
            env=self.env,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()

    def land(self, scenario: str, *args: str) -> subprocess.CompletedProcess[str]:
        """Run the public entry point with a scripted remote state."""
        _ = (self.root / "config.json").write_text(
            json.dumps({"scenario": scenario, "head": self.head}), encoding="utf-8"
        )
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "land",
                "7",
                "--repo",
                "owner/repo",
                "--worktree",
                str(self.worktree),
                "--timeout",
                "2",
                "--interval",
                "0.01",
                *args,
            ],
            cwd=self.worktree,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )

    def commands(self) -> list[list[str]]:
        """Read the command evidence recorded at the remote boundary."""
        return [
            cast("list[str]", json.loads(line))
            for line in (self.root / "commands.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]

    def assert_preserved(self) -> None:
        """Assert that failure retains both branches and the checkout."""
        assert self.worktree.is_dir()
        assert self.git("rev-parse", "topic") == self.head
        assert (
            self.git("ls-remote", "origin", "refs/heads/topic").split()[0] == self.head
        )


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    """Provide an isolated real Git repository."""
    return Repository(tmp_path)


def test_failed_check_preserves_branch_and_worktree(repository: Repository) -> None:
    """Regression: failed CI must never fall through into cleanup."""
    result = repository.land("failed")
    assert result.returncode == 1
    repository.assert_preserved()
    assert "CI required" in result.stderr
    assert "https://example.test/run/42" in result.stderr


@pytest.mark.parametrize("scenario", ["closed", "mismatch", "timeout"])
def test_stops_without_cleanup(repository: Repository, scenario: str) -> None:
    """Terminal errors and a bounded wait retain all task state."""
    result = repository.land(
        scenario, "--timeout", "0.5" if scenario == "timeout" else "2"
    )
    assert result.returncode == 1
    repository.assert_preserved()
    assert {"closed": "CLOSED", "mismatch": "Head mismatch", "timeout": "timed out"}[
        scenario
    ] in result.stderr
    if scenario == "mismatch":
        assert not any(c[:2] == ["pr", "merge"] for c in repository.commands())


@pytest.mark.parametrize("scenario", ["clean", "behind", "uncertain", "remote_deleted"])
def test_merge_then_cleanup(repository: Repository, scenario: str) -> None:
    """Only merged PRs remove the worktree and both branch refs."""
    result = repository.land(scenario)
    assert result.returncode == 0, result.stderr
    assert not repository.worktree.exists()
    assert repository.git("branch", "--list", "topic") == ""
    assert repository.git("ls-remote", "origin", "refs/heads/topic") == ""
    assert repository.git("rev-parse", "main") == repository.git(
        "rev-parse", "origin/main"
    )
    commands = repository.commands()
    merges = [c for c in commands if c[:2] == ["pr", "merge"]]
    assert "--match-head-commit" in merges[0]
    assert repository.head in merges[0]
    updates = [c for c in commands if c[:2] == ["api", "-X"]]
    if scenario == "behind":
        assert len(updates) == 1
        assert "update_method=rebase" in updates[0]
        assert f"expected_head_sha={repository.head}" in updates[0]
        assert len(merges) == 2  # noqa: PLR2004 - Two heads need two queue requests.
    else:
        assert updates == []
        assert len(merges) == 1


def test_json_result(repository: Repository) -> None:
    """JSON mode emits one result, not progress mixed with JSON."""
    result = repository.land("clean", "--json")
    assert result.returncode == 0, result.stderr
    payload = cast("dict[str, object]", json.loads(result.stdout))
    assert payload["state"] == "MERGED"
    assert isinstance(payload["steps"], list)
    assert "Deleted local branch topic" in payload["steps"]


def test_base_assertion_does_not_retarget(repository: Repository) -> None:
    """A base assertion mismatch stops before queuing."""
    result = repository.land("clean", "--base", "parent")
    assert result.returncode == 1
    assert "PR targets main" in result.stderr
    repository.assert_preserved()
    assert not any(c[:2] == ["pr", "merge"] for c in repository.commands())


def test_dirty_worktree_is_not_removed(repository: Repository) -> None:
    """Merged cleanup refuses a checkout with unrelated files."""
    dirty = repository.worktree / "unfinished.txt"
    _ = dirty.write_text("Keep this work", encoding="utf-8")
    result = repository.land("clean")
    assert result.returncode == 1
    assert dirty.read_text(encoding="utf-8") == "Keep this work"
    repository.assert_preserved()


def test_repeat_merged_cleanup(repository: Repository) -> None:
    """A second invocation reconciles missing branches and worktrees."""
    first = repository.land("clean")
    assert first.returncode == 0, first.stderr
    second = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "land",
            "7",
            "--repo",
            "owner/repo",
            "--worktree",
            str(repository.worktree),
            "--json",
        ],
        cwd=repository.repo,
        env=repository.env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    payload = cast("dict[str, object]", json.loads(second.stdout))
    assert payload["state"] == "MERGED"
    assert "Local branch already absent: topic" in cast("list[str]", payload["steps"])


def test_current_branch_and_default_repo(repository: Repository) -> None:
    """Omitting the target resolves the current branch and gh repository."""
    _ = (repository.root / "config.json").write_text(
        json.dumps({"scenario": "clean", "head": repository.head}), encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(CLI), "land", "--worktree", str(repository.worktree)],
        cwd=repository.worktree,
        env=repository.env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "PR #7 is MERGED" in result.stdout
    assert not repository.worktree.exists()


def test_no_worktree_option_retains_checkout(repository: Repository) -> None:
    """Optional removal leaves the task directory but deletes merged refs."""
    _ = (repository.root / "config.json").write_text(
        json.dumps({"scenario": "clean", "head": repository.head}), encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(CLI), "land", "7", "--repo", "owner/repo"],
        cwd=repository.worktree,
        env=repository.env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert repository.worktree.is_dir()
    assert repository.git("branch", "--list", "topic") == ""
    assert repository.git("ls-remote", "origin", "refs/heads/topic") == ""


def test_usage_error(repository: Repository) -> None:
    """Invalid limits stop before any remote access."""
    result = repository.land("clean", "--timeout", "0")
    assert result.returncode == 2  # noqa: PLR2004 - Public usage exit code.
    repository.assert_preserved()
    assert "positive seconds" in result.stderr
