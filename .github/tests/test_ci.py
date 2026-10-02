"""Exercise CI selection against real Git changes and deleted packages."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci.py"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-c", "user.name=CI Test", "-c", "user.email=ci@example.test", *args],
        cwd=root,
        text=True,
    ).strip()


def write(root: Path, path: str, text: str = "fixture") -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    for skill in ("alpha", "beta", "prose"):
        write(tmp_path, f"skills/current/{skill}/SKILL.md")
    for skill in ("alpha", "beta"):
        write(tmp_path, f"skills/current/{skill}/scripts/cli.py")
    write(tmp_path, "harnesses/pi/agent/extensions/package.json", "{}")
    write(tmp_path, "harnesses/opencode/package.json", "{}")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "Initial fixtures")
    return tmp_path


def plan(root: Path, *args: str) -> dict[str, list[str]]:
    env = {key: value for key, value in os.environ.items() if key != "GITHUB_OUTPUT"}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "plan", *args],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def commit_change(root: Path) -> str:
    base = git(root, "rev-parse", "HEAD")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "Change fixtures")
    return base


def test_changed_skill_runs_its_suite_only(repo: Path) -> None:
    write(repo, "skills/current/alpha/references/usage.md")
    base = commit_change(repo)
    assert plan(repo, "--base", base) == {"skills": ["alpha"], "harnesses": []}


def test_shared_ci_change_runs_every_owned_suite(repo: Path) -> None:
    write(repo, ".github/workflows/ci.yml")
    base = commit_change(repo)
    assert plan(repo, "--base", base) == {
        "skills": ["alpha", "beta"],
        "harnesses": ["opencode", "pi"],
    }


def test_gate_runner_change_rechecks_all_python_skills(repo: Path) -> None:
    write(repo, "skills/current/skill-creator/scripts/gates.py")
    base = commit_change(repo)
    assert plan(repo, "--base", base) == {
        "skills": ["alpha", "beta"],
        "harnesses": [],
    }


def test_prose_and_archived_skills_do_not_create_code_jobs(repo: Path) -> None:
    write(repo, "skills/current/prose/SKILL.md", "changed")
    write(repo, "skills/legacy/old/scripts/cli.py")
    base = commit_change(repo)
    assert plan(repo, "--base", base) == {"skills": [], "harnesses": []}


def test_deleted_skill_is_not_scheduled(repo: Path) -> None:
    git(repo, "rm", "-r", "skills/current/alpha")
    base = commit_change(repo)
    assert plan(repo, "--base", base) == {"skills": [], "harnesses": []}


def test_rename_rechecks_both_existing_skill_owners(repo: Path) -> None:
    write(repo, "skills/current/alpha/shared.py", "unique fixture")
    commit_change(repo)
    git(repo, "mv", "skills/current/alpha/shared.py", "skills/current/beta/shared.py")
    base = commit_change(repo)
    assert plan(repo, "--base", base) == {
        "skills": ["alpha", "beta"],
        "harnesses": [],
    }


def test_harness_change_selects_only_its_owner(repo: Path) -> None:
    write(repo, "harnesses/pi/agent/extensions/find/index.ts")
    base = commit_change(repo)
    assert plan(repo, "--base", base) == {"skills": [], "harnesses": ["pi"]}


def test_no_base_runs_every_owned_suite(repo: Path) -> None:
    assert plan(repo) == {
        "skills": ["alpha", "beta"],
        "harnesses": ["opencode", "pi"],
    }


@pytest.mark.parametrize(
    ("count", "groups"),
    [
        (0, []),
        (1, [["alpha"]]),
        (4, [["alpha"], ["beta"], ["delta"], ["epsilon"]]),
        (7, [["alpha", "eta"], ["beta", "gamma"], ["delta", "zeta"], ["epsilon"]]),
    ],
)
def test_plan_emits_balanced_nonempty_shards(
    repo: Path, count: int, groups: list[list[str]]
) -> None:
    git(repo, "rm", "-r", "skills/current")
    names = ["alpha", "beta", "delta", "epsilon", "eta", "gamma", "zeta"][:count]
    for name in reversed(names):
        write(repo, f"skills/current/{name}/SKILL.md")
        write(repo, f"skills/current/{name}/scripts/cli.py")
    (repo / "skills/current").mkdir(parents=True, exist_ok=True)
    output = repo / "outputs"
    subprocess.run(
        [sys.executable, str(SCRIPT), "plan"],
        cwd=repo,
        env=os.environ | {"GITHUB_OUTPUT": str(output)},
        check=True,
        capture_output=True,
        text=True,
    )
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    expected = [
        {
            "id": index,
            "skills": group,
            "cache-inputs": "\n".join(
                [
                    path
                    for name in group
                    for path in (
                        f"skills/current/{name}/scripts/cli.py",
                        f"skills/current/{name}/pyproject.toml",
                    )
                ]
                + ["skills/current/skill-creator/scripts/*.py"]
            ),
        }
        for index, group in enumerate(groups)
    ]
    assert json.loads(outputs["skill-shards"]) == expected
    assert json.loads(outputs["skills"]) == names


@pytest.mark.parametrize("fail", [False, True])
def test_skill_shard_runs_each_owner_and_stops_on_failure(
    repo: Path, fail: bool
) -> None:
    binary = repo / "bin/uv"
    write(
        repo,
        "bin/uv",
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['CALLS'], 'a') as log:\n"
        "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "sys.exit(1 if os.environ['FAIL'] == '1' "
        "and sys.argv[-2].endswith('/beta') else 0)\n",
    )
    binary.chmod(0o755)
    calls = repo / "calls.jsonl"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "skills"],
        cwd=repo,
        env=os.environ
        | {
            "PATH": f"{binary.parent}{os.pathsep}{os.environ['PATH']}",
            "SKILLS": json.dumps(["alpha", "beta", "gamma"]),
            "CALLS": str(calls),
            "FAIL": str(int(fail)),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == int(fail)
    expected = ["alpha", "beta"] if fail else ["alpha", "beta", "gamma"]
    assert [json.loads(line) for line in calls.read_text().splitlines()] == [
        [
            "run",
            "--script",
            "skills/current/skill-creator/scripts/cli.py",
            "gates",
            f"skills/current/{name}",
            "--tests",
        ]
        for name in expected
    ]


def test_missing_base_fails_instead_of_silently_skipping(repo: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "plan", "--base", "missing-ref"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "missing-ref" in result.stderr


def required(
    root: Path, *, skill_result: str, selected: list[str]
) -> subprocess.CompletedProcess[str]:
    jobs = {
        "plan": {
            "result": "success",
            "outputs": {"skills": json.dumps(selected), "harnesses": "[]"},
        },
        "repository-checks": {"result": "success"},
        "sync-gates": {"result": "success"},
        "skills": {"result": skill_result},
        "harnesses": {"result": "skipped"},
    }
    return subprocess.run(
        [sys.executable, str(SCRIPT), "required"],
        cwd=root,
        env=os.environ | {"CI_NEEDS": json.dumps(jobs)},
        capture_output=True,
        text=True,
    )


def test_required_accepts_success_and_intentionally_empty_matrix(repo: Path) -> None:
    assert required(repo, skill_result="success", selected=["alpha"]).returncode == 0
    assert required(repo, skill_result="skipped", selected=[]).returncode == 0


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped"])
def test_required_rejects_failed_cancelled_and_unexpectedly_skipped_checks(
    repo: Path, result: str
) -> None:
    completed = required(repo, skill_result=result, selected=["alpha"])
    assert completed.returncode == 1
    assert "skills" in completed.stderr


def test_metadata_rejects_a_skill_directory_without_its_entrypoint(
    tmp_path: Path,
) -> None:
    checker = tmp_path / "skills/current/skill-creator"
    scripts = checker / "scripts"
    scripts.mkdir(parents=True)
    original = SCRIPT.parents[2] / "skills/current/skill-creator/scripts"
    for name in ("cli.py", "quick_validate.py"):
        (original / name).copy(scripts / name)
    write(
        tmp_path,
        "skills/current/skill-creator/SKILL.md",
        "---\nname: skill-creator\n"
        'description: "Use when validating skills."\n'
        "license: AGPL-3.0-or-later\n---\n",
    )
    write(tmp_path, "skills/current/broken/scripts/cli.py")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "metadata"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "SKILL.md not found" in result.stdout
