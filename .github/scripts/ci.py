# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Select and execute repository CI checks without changing generated homes."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import TypeIs

HARNESS_ROOTS = {
    "opencode": Path("harnesses/opencode"),
    "pi": Path("harnesses/pi/agent/extensions"),
}
SKILL_SHARDS = 4


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    """Run a bounded check and propagate failure to the workflow."""
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True, timeout=1200)


def plan(root: Path, base: str | None) -> dict[str, list[str]]:
    """Select current owners, including both sides of renames."""
    skills = {
        path.name
        for path in (root / "skills/current").iterdir()
        if (path / "SKILL.md").is_file() and any(path.rglob("*.py"))
    }
    harnesses = {name for name, path in HARNESS_ROOTS.items() if (root / path).is_dir()}
    if base is None:
        return {"skills": sorted(skills), "harnesses": sorted(harnesses)}
    diff = subprocess.check_output(
        ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD"],
        cwd=root,
    ).decode("utf-8")
    paths = [Path(name) for name in diff.split("\0") if name]
    shared_ci = any(path.parts[0] == ".github" for path in paths)
    shared_skills = shared_ci or any(
        path.is_relative_to("skills/current/skill-creator")
        or path.as_posix() in {"docs/skills.md", "HARNESS.md"}
        for path in paths
    )
    selected_skills = (
        skills
        if shared_skills
        else {
            path.parts[2]
            for path in paths
            if path.is_relative_to("skills/current") and len(path.parts) > 2
        }
        & skills
    )
    selected_harnesses = (
        harnesses
        if shared_ci
        else {
            path.parts[1]
            for path in paths
            if path.is_relative_to("harnesses") and len(path.parts) > 1
        }
        & harnesses
    )
    return {
        "skills": sorted(selected_skills),
        "harnesses": sorted(selected_harnesses),
    }


def metadata(root: Path) -> None:
    """Validate every published skill with its owning validator."""
    skills = sorted(
        path for path in (root / "skills/current").iterdir() if path.is_dir()
    )
    if not skills:
        raise ValueError("No active skills found")
    validator = "skills/current/skill-creator/scripts/cli.py"
    for skill in skills:
        run(
            ["uv", "run", "--script", validator, "quick-validate", str(skill)],
            cwd=root,
        )
    print(f"Validated {len(skills)} active skills", flush=True)


def skills(root: Path, raw: str) -> None:
    """Run one shard sequentially, reusing uv's tool and dependency caches."""
    names: object = json.loads(raw)
    if not is_str_list(names) or not names:
        raise ValueError("SKILLS must be a nonempty array of skill names")
    for name in names:
        started = perf_counter()
        run(
            [
                "uv",
                "run",
                "--script",
                "skills/current/skill-creator/scripts/cli.py",
                "gates",
                f"skills/current/{name}",
                "--tests",
            ],
            cwd=root,
        )
        print(f"{name}: {perf_counter() - started:.2f}s", flush=True)


def harness(root: Path, name: str) -> None:
    """Install frozen test dependencies in a temporary copy of the owner."""
    with TemporaryDirectory(prefix=f"agents-ci-{name}-") as temporary:
        target = Path(temporary) / name
        shutil.copytree(
            root / HARNESS_ROOTS[name],
            target,
            ignore=shutil.ignore_patterns("node_modules", ".git"),
        )
        run(["bun", "install", "--frozen-lockfile"], cwd=target)
        paths = [str(target / "node_modules/.bin")]
        if name == "pi":
            # Search tests use a standalone, pinned ripgrep binary.
            bundled = sorted((target / "node_modules/@vscode").glob("ripgrep-*/bin"))
            if not bundled:
                raise ValueError(
                    "Pinned ripgrep package did not include its executable"
                )
            paths.extend(str(path) for path in bundled)
        paths.append(os.environ["PATH"])
        env = os.environ | {"PATH": os.pathsep.join(paths)}
        run(
            ["bun", "test", "--preload", str(root / ".github/scripts/offline-bun.ts")],
            cwd=target,
            env=env,
        )


def is_str_dict(value: object) -> TypeIs[dict[str, object]]:
    """Narrow JSON objects at the workflow boundary."""
    return isinstance(value, dict)


def is_object_list(value: object) -> TypeIs[list[object]]:
    """Narrow JSON arrays before checking their elements."""
    return isinstance(value, list)


def is_str_list(value: object) -> TypeIs[list[str]]:
    """Narrow the planned shard's skill names at the workflow boundary."""
    return is_object_list(value) and all(isinstance(name, str) for name in value)


def required(raw: str) -> None:
    """Reject failures and skips unless the selected matrix was empty."""
    needs: object = json.loads(raw)
    if not is_str_dict(needs):
        raise ValueError("CI_NEEDS must be an object")
    planned = needs.get("plan")
    if not is_str_dict(planned) or planned.get("result") != "success":
        raise ValueError("plan did not succeed")
    outputs = planned.get("outputs")
    if not is_str_dict(outputs):
        raise ValueError("Missing plan outputs")
    for name in ("repository-checks", "sync-gates", "skills", "harnesses"):
        job = needs.get(name)
        if not is_str_dict(job):
            raise ValueError(f"Missing job result: {name}")
        result = job.get("result")
        if result == "success":
            continue
        if name in {"skills", "harnesses"} and result == "skipped":
            if outputs.get(name) == "[]":
                continue
        raise ValueError(f"{name} did not succeed: {result}")
    print("Every selected CI check succeeded", flush=True)


def main() -> int:
    """Dispatch the focused check from the repository root."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    selection = commands.add_parser("plan")
    selection.add_argument("--base")
    commands.add_parser("metadata")
    commands.add_parser("skills")
    commands.add_parser("required")
    extension = commands.add_parser("harness")
    extension.add_argument("name", choices=sorted(HARNESS_ROOTS))
    args = parser.parse_args()
    root = Path.cwd()
    try:
        if args.command == "plan":
            selected = plan(root, args.base)
            print(json.dumps(selected))
            if output := os.environ.get("GITHUB_OUTPUT"):
                with Path(output).open("a", encoding="utf-8") as stream:
                    for key, names in selected.items():
                        stream.write(f"{key}={json.dumps(names)}\n")
                    shards: list[dict[str, object]] = []
                    for index in range(min(SKILL_SHARDS, len(selected["skills"]))):
                        names = selected["skills"][index::SKILL_SHARDS]
                        inputs = [
                            f"skills/current/{name}/{file}"
                            for name in names
                            for file in ("scripts/cli.py", "pyproject.toml")
                        ]
                        inputs.append("skills/current/skill-creator/scripts/*.py")
                        shards.append(
                            {
                                "id": index,
                                "skills": names,
                                "cache-inputs": "\n".join(inputs),
                            }
                        )
                    stream.write(f"skill-shards={json.dumps(shards)}\n")
        elif args.command == "metadata":
            metadata(root)
        elif args.command == "skills":
            skills(root, os.environ["SKILLS"])
        elif args.command == "required":
            required(os.environ["CI_NEEDS"])
        else:
            harness(root, args.name)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"CI check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
