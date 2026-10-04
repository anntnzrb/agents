# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Report upstream changes to ported skills pinned by UPSTREAM.json files.

Each `skills/current/<skill>/UPSTREAM.json` records the upstream repository,
the commit the port was last synchronized with, and the Git tree hash of every
upstream directory the port derives from. A pin either follows the latest
release (`release`) or the head of a branch (`branch`). An optional `watch`
lists every entry of an upstream directory known at the pin, so new upstream
directories are reported too.

The script compares the pin with the current upstream target through `gh`.
With `--issues-repo`, it keeps one open issue per drifted skill, creating it
or updating its body. A maintainer ports what matters and updates the pin.
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


def _strings(skill: str, field: str, value: object) -> dict[str, str]:
    if not is_record(value) or not value:
        raise ValueError(f"{skill}: {field} must be a non-empty object")
    parsed: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(item, str):
            raise ValueError(f"{skill}: {field}[{key}] must be a string")
        parsed[key] = item
    return parsed


def _watch(skill: str, value: object) -> dict[str, frozenset[str]]:
    if value is None:
        return {}
    if not is_record(value):
        raise ValueError(f"{skill}: watch must map directories to name lists")
    parsed: dict[str, frozenset[str]] = {}
    for parent, names in value.items():
        if not is_list(names) or not all(isinstance(n, str) for n in names):
            raise ValueError(f"{skill}: watch[{parent}] must be a list of names")
        parsed[parent] = frozenset(str(n) for n in names)
    return parsed


@dataclass(frozen=True)
class Pin:
    skill: str
    repo: str
    commit: str
    release: str | None
    branch: str | None
    trees: dict[str, str]
    watch: dict[str, frozenset[str]]

    @classmethod
    def parse(cls, skill: str, raw: object) -> Pin:
        if not is_record(raw):
            raise ValueError(f"{skill}: UPSTREAM.json must be an object")
        repo, commit = raw.get("repo"), raw.get("commit")
        release, branch = raw.get("release"), raw.get("branch")
        if not isinstance(repo, str) or not isinstance(commit, str):
            raise ValueError(f"{skill}: repo and commit must be strings")
        if (release is None) == (branch is None):
            raise ValueError(f"{skill}: set exactly one of release or branch")
        if not isinstance(release or branch, str):
            raise ValueError(f"{skill}: release or branch must be a string")
        return cls(
            skill,
            repo,
            commit,
            release if isinstance(release, str) else None,
            branch if isinstance(branch, str) else None,
            _strings(skill, "trees", raw.get("trees")),
            _watch(skill, raw.get("watch")),
        )

    @property
    def baseline(self) -> str:
        """The upstream ref the port matches: its release tag or pinned commit."""
        return self.release or self.commit


@dataclass(frozen=True)
class Drift:
    changed: list[str]
    added: list[str]

    def __bool__(self) -> bool:
        return bool(self.changed or self.added)


def pins(root: Path) -> list[Pin]:
    found: list[Pin] = []
    for path in sorted((root / "skills/current").glob("*/UPSTREAM.json")):
        skill = path.parent.name
        found.append(Pin.parse(skill, json.loads(path.read_text(encoding="utf-8"))))
    return found


def lookup_parents(pin: Pin) -> list[str]:
    parents = {str(Path(path).parent) for path in pin.trees} | set(pin.watch)
    return sorted(parents)


def drift(pin: Pin, current: dict[str, str]) -> Drift:
    """Pinned paths that changed or vanished, and unknown watched entries."""
    changed = [path for path, tree in pin.trees.items() if current.get(path) != tree]
    added = sorted(
        path
        for path in current
        if (parent := str(Path(path).parent)) in pin.watch
        and Path(path).name not in pin.watch[parent]
    )
    return Drift(changed, added)


def issue_title(pin: Pin) -> str:
    return f"skills({pin.skill}): upstream {pin.repo} changed ported sources"


def issue_body(pin: Pin, target: str, found: Drift) -> str:
    sections = [
        f"Upstream `{pin.repo}` moved from `{pin.baseline}` to `{target}`.",
        f"Compare: https://github.com/{pin.repo}/compare/{pin.baseline}...{target}",
    ]
    if found.changed:
        listed = "\n".join(f"- `{path}`" for path in found.changed)
        paths = " ".join(found.changed)
        sections.append(
            f"Changed or removed pinned directories:\n\n{listed}\n\n"
            "Upstream-only diff, unaffected by local adaptations:\n\n"
            f"```sh\ngit diff {pin.baseline} {target} -- {paths}\n```"
        )
    if found.added:
        listed = "\n".join(f"- `{path}`" for path in found.added)
        sections.append(f"New upstream directories not yet reviewed:\n\n{listed}")
    sections.append(
        f"Port the relevant upstream changes into `skills/current/{pin.skill}/`, "
        "keeping local adaptations. Then update "
        f"`skills/current/{pin.skill}/UPSTREAM.json`: the commit, the release "
        "for release pins, every tree hash, and each reviewed new directory in "
        "`watch`, ported or not. This issue is updated while the pin stays behind."
    )
    return "\n\n".join(sections)


def gh(*args: str) -> str:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True, timeout=120
    ).stdout.strip()


def target_ref(pin: Pin) -> str:
    if pin.branch is not None:
        return gh("api", f"repos/{pin.repo}/commits/{pin.branch}", "--jq", ".sha")
    return gh("api", f"repos/{pin.repo}/releases/latest", "--jq", ".tag_name")


def tree_hashes(repo: str, ref: str, parents: list[str]) -> dict[str, str]:
    """Map each directory under `parents` at `ref` to its tree hash."""
    hashes: dict[str, str] = {}
    for parent in parents:
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


def report(repo: str, title: str, body: str) -> None:
    """Create the open issue with this title, or refresh its body."""
    number = gh(
        "issue", "list", "--repo", repo, "--state", "open", "--search",
        f'"{title}" in:title', "--json", "number,title", "--jq",
        f'map(select(.title == "{title}")) | first | .number // empty',
    )  # fmt: skip
    if number:
        _ = gh("issue", "edit", number, "--repo", repo, "--body", body)
        print(f"updated #{number}: {title}")
        return
    print(gh("issue", "create", "--repo", repo, "--title", title, "--body", body))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issues-repo", help="report drift as issues in owner/repo")
    args = parser.parse_args()
    issues_repo: str | None = args.issues_repo
    root = Path(__file__).resolve().parents[2]
    behind = 0
    for pin in pins(root):
        target = target_ref(pin)
        found = drift(pin, tree_hashes(pin.repo, target, lookup_parents(pin)))
        if not found:
            print(f"{pin.skill}: current with {pin.repo} {target}")
            continue
        behind += 1
        print(
            f"{pin.skill}: {len(found.changed)} changed, {len(found.added)} new "
            f"in {pin.repo} {target}"
        )
        if issues_repo:
            report(issues_repo, issue_title(pin), issue_body(pin, target, found))
    return 0 if issues_repo or not behind else 1


if __name__ == "__main__":
    sys.exit(main())
