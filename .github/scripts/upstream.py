# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Report upstream changes to ported skills pinned by UPSTREAM.json files.

Each `skills/current/<skill>/UPSTREAM.json` records the upstream repository,
the release it was ported from, and the Git tree hash of every upstream
directory the port derives from. This script resolves each repository's
latest release through `gh`, compares tree hashes, and opens one issue per
skill and release when a pinned directory changed or disappeared. A
maintainer reviews the issue, ports what matters, and updates the pin.
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TypeIs


def is_record(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict)


def is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


@dataclass(frozen=True)
class Pin:
    skill: str
    repo: str
    release: str
    trees: dict[str, str]

    @classmethod
    def parse(cls, skill: str, raw: object) -> Pin:
        if not is_record(raw):
            raise ValueError(f"{skill}: UPSTREAM.json must be an object")
        repo, release, trees = raw.get("repo"), raw.get("release"), raw.get("trees")
        if not isinstance(repo, str) or not isinstance(release, str):
            raise ValueError(f"{skill}: repo and release must be strings")
        if not is_record(trees) or not trees:
            raise ValueError(f"{skill}: trees must map upstream paths to hashes")
        parsed: dict[str, str] = {}
        for path, tree in trees.items():
            if not isinstance(tree, str):
                raise ValueError(f"{skill}: tree hash for {path} must be a string")
            parsed[path] = tree
        return cls(skill, repo, release, parsed)


def pins(root: Path) -> list[Pin]:
    found: list[Pin] = []
    for path in sorted((root / "skills/current").glob("*/UPSTREAM.json")):
        skill = path.parent.name
        found.append(Pin.parse(skill, json.loads(path.read_text(encoding="utf-8"))))
    return found


def changed(pin: Pin, current: dict[str, str]) -> list[str]:
    """Pinned paths whose upstream tree differs or no longer exists."""
    return [path for path, tree in pin.trees.items() if current.get(path) != tree]


def issue_title(pin: Pin, release: str) -> str:
    return f"skills({pin.skill}): upstream {pin.repo} {release} changed ported skills"


def issue_body(pin: Pin, release: str, paths: list[str]) -> str:
    listed = "\n".join(f"- `{path}`" for path in paths)
    return (
        f"Upstream `{pin.repo}` released `{release}`. These directories changed "
        f"since the pinned `{pin.release}`:\n\n{listed}\n\n"
        f"Compare: https://github.com/{pin.repo}/compare/{pin.release}...{release}\n\n"
        f"Port relevant changes into `skills/current/{pin.skill}/`, then update "
        f"`skills/current/{pin.skill}/UPSTREAM.json` to `{release}`, its commit, "
        "and the new tree hashes. Close this issue without porting if nothing "
        "applies, and still update the pin."
    )


def gh(*args: str) -> str:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True, timeout=120
    ).stdout.strip()


def latest_release(repo: str) -> str:
    return gh("api", f"repos/{repo}/releases/latest", "--jq", ".tag_name")


def tree_hashes(repo: str, ref: str, paths: list[str]) -> dict[str, str]:
    """Look up each path's tree hash at `ref`; absent paths are omitted."""
    hashes: dict[str, str] = {}
    for parent in sorted({str(Path(path).parent) for path in paths}):
        listing: object = json.loads(
            gh("api", f"repos/{repo}/contents/{parent}?ref={ref}")
        )
        entries: list[object] = listing if is_list(listing) else []
        for entry in entries:
            if is_record(entry) and entry.get("type") == "dir":
                path, sha = entry.get("path"), entry.get("sha")
                if isinstance(path, str) and isinstance(sha, str):
                    hashes[path] = sha
    return hashes


def open_issue(repo: str, title: str, body: str) -> None:
    existing = gh(
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "all",
        "--search",
        f'"{title}" in:title',
        "--json",
        "title",
        "--jq",
        ".[].title",
    )
    if title in existing.splitlines():
        print(f"exists: {title}")
        return
    print(gh("issue", "create", "--repo", repo, "--title", title, "--body", body))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issues-repo", help="open issues in this owner/repo")
    args = parser.parse_args()
    issues_repo: str | None = args.issues_repo
    root = Path(__file__).resolve().parents[2]
    drifted = 0
    for pin in pins(root):
        release = latest_release(pin.repo)
        paths = changed(pin, tree_hashes(pin.repo, release, list(pin.trees)))
        if not paths:
            print(f"{pin.skill}: current with {pin.repo} {release}")
            continue
        drifted += 1
        print(f"{pin.skill}: {', '.join(paths)} changed in {pin.repo} {release}")
        if issues_repo:
            open_issue(
                issues_repo, issue_title(pin, release), issue_body(pin, release, paths)
            )
    return 0 if issues_repo or not drifted else 1


if __name__ == "__main__":
    sys.exit(main())
