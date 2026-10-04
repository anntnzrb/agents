# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Land one head-pinned PR, then clean up only its merged branch."""

import argparse
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast

type Json = dict[str, Json] | list[Json] | str | int | float | bool | None
FIELDS = (
    "state,mergeStateStatus,headRefOid,baseRefName,autoMergeRequest,"
    "statusCheckRollup,number,headRefName,isCrossRepository"
)


@dataclass
class Runner:
    """One subprocess boundary, with a deadline shared by all calls."""

    cwd: Path
    deadline: float

    def run(self, *args: str, allowed: tuple[int, ...] = (0,)) -> str:
        """Capture output and fail without retrying a command."""
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Landing timed out; no further actions taken")
        result = subprocess.run(
            args,
            cwd=self.cwd,
            capture_output=True,
            text=True,
            timeout=remaining,
            check=False,
        )
        if result.returncode not in allowed:
            raise RuntimeError(f"{' '.join(args)}: {result.stderr.strip()}")
        return result.stdout.strip()

    def data(self, *args: str, allowed: tuple[int, ...] = (0,)) -> Json:
        """Decode JSON at the external boundary."""
        return cast("Json", json.loads(self.run(*args, allowed=allowed)))

    def view(self, target: str, repo: str) -> dict[str, Json]:
        """Observe the complete landing state."""
        return object_data(
            self.data("gh", "pr", "view", target, "--repo", repo, "--json", FIELDS)
        )

    def write(self, repo: str, target: str, head: str, *args: str) -> None:
        """Dispatch once and reconcile a failed response, never replay it."""
        try:
            _ = self.run("gh", *args)
        except RuntimeError:
            state = self.view(target, repo)
            if (
                state["state"] != "MERGED"
                and (args[0] != "pr" or not state["autoMergeRequest"])
                and state["headRefOid"] == head
            ):
                raise


def object_data(value: Json) -> dict[str, Json]:
    """Require a JSON object."""
    if not isinstance(value, dict):
        raise TypeError("Expected a JSON object")
    return value


def text(value: Json) -> str:
    """Require a nonempty JSON string."""
    if not isinstance(value, str) or not value:
        raise ValueError("Expected a nonempty JSON string")
    return value


def positive(value: str) -> float:
    """Parse finite positive seconds."""
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Expected finite positive seconds")
    return number


def cleanup(  # noqa: C901, PLR0913 - Keep deletion guards beside their writes.
    runner: Runner,
    branch: str,
    head: str,
    base: str,
    *,
    worktree: Path | None,
    steps: list[str],
) -> None:
    """Converge merged-only cleanup, preserving dirty or changed branches."""
    if branch == base:
        raise RuntimeError("Refusing to delete the base branch")
    local = runner.run(
        "git", "for-each-ref", "--format=%(objectname)", f"refs/heads/{branch}"
    )
    if local and local.split()[0] != head:
        raise RuntimeError("Local branch changed; cleanup stopped")
    _ = runner.run(
        "git", "fetch", "origin", f"+refs/heads/{base}:refs/remotes/origin/{base}"
    )
    entries = runner.run("git", "worktree", "list", "--porcelain").split("\n\n")
    base_path = next(
        (
            Path(e.splitlines()[0].removeprefix("worktree "))
            for e in entries
            if f"branch refs/heads/{base}" in e.splitlines()
        ),
        runner.cwd,
    )
    if runner.run("git", "-C", str(base_path), "status", "--porcelain"):
        raise RuntimeError(f"Dirty base checkout: {base_path}")
    _ = runner.run("git", "-C", str(base_path), "switch", base)
    _ = runner.run(
        "git", "-C", str(base_path), "merge", "--ff-only", f"refs/remotes/origin/{base}"
    )
    steps.append(f"Fast-forwarded local base {base}")
    if not worktree and runner.cwd != base_path:
        if runner.run("git", "status", "--porcelain"):
            raise RuntimeError("Dirty task checkout; cleanup stopped")
        if runner.run("git", "branch", "--show-current") == branch:
            _ = runner.run("git", "switch", "--detach", f"refs/remotes/origin/{base}")
    runner.cwd = base_path
    if worktree and worktree.exists():
        if worktree == base_path:
            raise RuntimeError("Cannot remove the base checkout")
        _ = runner.run("git", "worktree", "remove", str(worktree))
        steps.append(f"Removed worktree {worktree}")
    elif worktree:
        steps.append(f"Worktree already absent: {worktree}")
    if local:
        # Exact merged PR head was checked above; squash/rebase need not be ancestors.
        if runner.run("git", "rev-parse", f"refs/heads/{branch}") != head:
            raise RuntimeError("Local branch changed; deletion stopped")
        _ = runner.run("git", "branch", "-D", "--", branch)
        steps.append(f"Deleted local branch {branch}")
    else:
        steps.append(f"Local branch already absent: {branch}")
    remote = runner.run("git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}")
    if remote:
        if remote.split()[0] != head:
            raise RuntimeError("Remote branch changed; deletion stopped")
        lease = f"--force-with-lease=refs/heads/{branch}:{head}"
        _ = runner.run("git", "push", lease, "origin", f":refs/heads/{branch}")
        steps.append(f"Deleted remote branch {branch}")
    else:
        steps.append(f"Remote branch already absent: {branch}")


def land(args: argparse.Namespace, steps: list[str]) -> str:  # noqa: C901, PLR0915 - Keep the state machine in execution order.
    """Reconcile each action from live PR state, never replay an uncertain write."""
    runner = Runner(Path.cwd(), time.monotonic() + cast("float", args.timeout))
    repo = cast("str | None", args.repo) or text(
        object_data(runner.data("gh", "repo", "view", "--json", "nameWithOwner"))[
            "nameWithOwner"
        ]
    )
    origin = runner.run("git", "remote", "get-url", "origin")
    origin_repo = object_data(
        runner.data("gh", "repo", "view", origin, "--json", "nameWithOwner")
    )["nameWithOwner"]
    if origin_repo != repo:
        raise RuntimeError("origin does not match the selected repository")
    target = cast("str | None", args.pr) or runner.run(
        "git", "branch", "--show-current"
    )
    if not target or target.startswith("-"):
        raise ValueError("Expected a PR number or current branch")
    initial = runner.view(target, repo)
    if initial["isCrossRepository"]:
        raise RuntimeError("Fork PRs require separate head-remote ownership; stopped")
    number = str(initial["number"])
    branch = text(initial["headRefName"])
    base = text(initial["baseRefName"])
    head = text(initial["headRefOid"])
    expected_base = cast("str | None", args.base)
    method = cast("str", args.method)
    worktree = cast("Path | None", args.worktree)
    if worktree:
        worktree = worktree.resolve()
        if worktree.exists():
            common = runner.run(
                "git", "rev-parse", "--path-format=absolute", "--git-common-dir"
            )
            other = runner.run(
                "git",
                "-C",
                str(worktree),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            )
            if Path(common).resolve() != Path(other).resolve():
                raise RuntimeError("Worktree belongs to another repository")
            runner.cwd = worktree
            if runner.run("git", "branch", "--show-current") != branch:
                raise RuntimeError("Worktree is not on the PR branch")
    if expected_base and expected_base != base:
        raise RuntimeError(f"Expected base {expected_base}; PR targets {base}")
    local = runner.run(
        "git", "for-each-ref", "--format=%(objectname)", f"refs/heads/{branch}"
    )
    if (local and local.split()[0] != head) or (
        not local and initial["state"] != "MERGED"
    ):
        raise RuntimeError(f"Head mismatch: local branch must equal PR head {head}")
    steps.append(f"Pinned {branch} at {head}")
    queued: set[str] = set()
    updated: set[str] = set()
    pending_update = ""
    state = initial
    while True:
        if state["baseRefName"] != base or state["headRefName"] != branch:
            raise RuntimeError("PR base or branch changed; stopped")
        if state["state"] not in ("OPEN", "MERGED"):
            raise RuntimeError(f"PR #{number} is CLOSED without merge; no cleanup")
        current = text(state["headRefOid"])
        if current != head:
            if pending_update != head:
                raise RuntimeError("PR head changed outside the requested rebase")
            if runner.run("git", "status", "--porcelain"):
                raise RuntimeError("Dirty checkout; cannot adopt rebased head")
            if runner.run("git", "branch", "--show-current") != branch:
                raise RuntimeError("Rebase adoption requires the PR branch checkout")
            _ = runner.run("git", "fetch", "origin", branch)
            if runner.run("git", "rev-parse", "FETCH_HEAD") != current:
                raise RuntimeError("Fetched branch does not match the PR head")
            _ = runner.run("git", "switch", "--detach")
            _ = runner.run("git", "update-ref", f"refs/heads/{branch}", current, head)
            _ = runner.run("git", "switch", branch)
            head = current
            pending_update = ""
            steps.append(f"Re-pinned rebased head {head}")
        if state["state"] == "MERGED":
            steps.append(f"PR #{number} is MERGED")
            cleanup(runner, branch, head, base, worktree=worktree, steps=steps)
            return "MERGED"
        if runner.run("git", "rev-parse", f"refs/heads/{branch}") != head:
            raise RuntimeError("Local branch changed; landing stopped")
        check_args = ("gh", "pr", "checks", number, "--repo", repo, "--required")
        checks = runner.data(
            *check_args, "--json", "name,bucket,link", allowed=(0, 1, 8)
        )
        if not isinstance(checks, list):
            raise TypeError("Expected required check list")
        failures = [
            f"{text(c['name'])}: {text(c['link'])}"
            for item in checks
            if (c := object_data(item))["bucket"] in ("fail", "cancel")
        ]
        # Check data belongs to the head only if a second live observation agrees.
        fresh = runner.view(number, repo)
        if any(
            fresh[key] != state[key]
            for key in (
                "state",
                "headRefOid",
                "baseRefName",
                "headRefName",
                "autoMergeRequest",
                "mergeStateStatus",
            )
        ):
            state = fresh
            continue
        if failures:
            raise RuntimeError("Required checks failed: " + "; ".join(failures))
        if not state["autoMergeRequest"] and head not in queued:
            queued.add(head)
            merge_args = ("pr", "merge", number, "--repo", repo, "--auto")
            runner.write(
                repo,
                number,
                head,
                *merge_args,
                f"--{method}",
                "--match-head-commit",
                head,
            )
            steps.append(f"Queued auto-merge for {head}")
        elif state["mergeStateStatus"] == "BEHIND" and head not in updated:
            updated.add(head)
            pending_update = head
            endpoint = f"repos/{repo}/pulls/{number}/update-branch"
            runner.write(
                repo,
                number,
                head,
                "api",
                "-X",
                "PUT",
                endpoint,
                "-f",
                "update_method=rebase",
                "-f",
                f"expected_head_sha={head}",
            )
            steps.append(f"Requested rebase for {head}")
        else:
            time.sleep(
                min(
                    cast("float", args.interval),
                    max(0, runner.deadline - time.monotonic()),
                )
            )
        state = runner.view(number, repo)


def main() -> int:
    """Parse arguments and emit one final result."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("land", help="Land a reviewed open PR")
    _ = command.add_argument(
        "pr", nargs="?", help="PR number; defaults to current branch"
    )
    _ = command.add_argument("--repo", help="owner/name; defaults to gh repo view")
    _ = command.add_argument("--base", help="Assert expected base, never retarget")
    _ = command.add_argument(
        "--worktree", type=Path, help="Task checkout to remove after merge"
    )
    _ = command.add_argument(
        "--method", choices=("merge", "squash", "rebase"), default="merge"
    )
    _ = command.add_argument(
        "--timeout", type=positive, default=1800, help="Total seconds (default 1800)"
    )
    _ = command.add_argument(
        "--interval", type=positive, default=10, help="Polling seconds (default 10)"
    )
    _ = command.add_argument("--json", action="store_true", help="Emit one JSON result")
    args = parser.parse_args()
    steps: list[str] = []
    error = ""
    state = "STOPPED"
    try:
        state = land(args, steps)
    except (
        RuntimeError,
        TypeError,
        ValueError,
        KeyError,
        OSError,
        subprocess.TimeoutExpired,
    ) as exc:
        error = str(exc)
    if cast("bool", args.json):
        print(json.dumps({"state": state, "steps": steps, "error": error or None}))
    else:
        for step in steps:
            print(step)
        if error:
            print(error, file=sys.stderr)
    return int(bool(error))


if __name__ == "__main__":
    sys.exit(main())
