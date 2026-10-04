"""Detect upstream drift for ported skills from pinned tree hashes."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import upstream  # noqa: E402

COMMIT = "a" * 40
RELEASE_PIN = {
    "repo": "owner/repo",
    "release": "v1.0.0",
    "commit": COMMIT,
    "trees": {"skills/x": "1" * 40, "skills/y": "2" * 40},
}
BRANCH_PIN = {
    "repo": "owner/repo",
    "branch": "main",
    "commit": COMMIT,
    "trees": {"pack/skills/x": "1" * 40},
    "watch": {"pack/skills": ["x", "skipped"]},
}


def write_pin(root: Path, name: str, pin: object) -> None:
    path = root / "skills/current" / name / "UPSTREAM.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(pin), encoding="utf-8")


def test_pins_reads_only_skills_with_upstream_files(tmp_path: Path) -> None:
    write_pin(tmp_path, "ported", RELEASE_PIN)
    (tmp_path / "skills/current/native").mkdir(parents=True)
    pins = upstream.pins(tmp_path)
    assert [pin.skill for pin in pins] == ["ported"]
    assert pins[0].repo == "owner/repo"
    assert pins[0].trees == RELEASE_PIN["trees"]


@pytest.mark.parametrize(
    "raw",
    [
        {"repo": "owner/repo", "commit": COMMIT, "trees": {}},
        {"repo": "owner/repo", "trees": {"a": "1"}, "release": "v1"},
        {"repo": "owner/repo", "commit": COMMIT, "trees": {"a": "1"}},
        {
            "repo": "owner/repo",
            "commit": COMMIT,
            "release": "v1",
            "branch": "main",
            "trees": {"a": "1"},
        },
        {**BRANCH_PIN, "watch": {"pack/skills": "x"}},
    ],
)
def test_pins_rejects_malformed_files(tmp_path: Path, raw: object) -> None:
    write_pin(tmp_path, "broken", raw)
    with pytest.raises(ValueError, match="broken"):
        _ = upstream.pins(tmp_path)


def test_baseline_is_the_release_or_the_commit() -> None:
    assert upstream.Pin.parse("x", RELEASE_PIN).baseline == "v1.0.0"
    assert upstream.Pin.parse("x", BRANCH_PIN).baseline == COMMIT


def test_drift_lists_modified_removed_and_new_paths() -> None:
    pin = upstream.Pin.parse("x", BRANCH_PIN)
    same = {"pack/skills/x": "1" * 40, "pack/skills/skipped": "3" * 40}
    assert upstream.drift(pin, same) == upstream.Drift([], [])
    edited = {**same, "pack/skills/x": "9" * 40}
    assert upstream.drift(pin, edited).changed == ["pack/skills/x"]
    assert upstream.drift(pin, {}).changed == ["pack/skills/x"]
    added = {**same, "pack/skills/new": "4" * 40}
    assert upstream.drift(pin, added) == upstream.Drift([], ["pack/skills/new"])


def test_drift_ignores_unwatched_new_paths() -> None:
    pin = upstream.Pin.parse("x", RELEASE_PIN)
    current = {"skills/x": "1" * 40, "skills/y": "2" * 40, "skills/z": "3" * 40}
    assert not upstream.drift(pin, current)


def test_lookup_parents_cover_pinned_and_watched_directories() -> None:
    pin = upstream.Pin.parse("x", BRANCH_PIN)
    assert upstream.lookup_parents(pin) == ["pack/skills"]


def test_issue_title_names_the_skill_and_repository() -> None:
    pin = upstream.Pin.parse("paseo", RELEASE_PIN)
    assert upstream.issue_title(pin) == (
        "skills(paseo): upstream owner/repo changed ported sources"
    )


def test_issue_body_diffs_upstream_against_itself() -> None:
    pin = upstream.Pin.parse("pstack", BRANCH_PIN)
    found = upstream.Drift(["pack/skills/x"], ["pack/skills/new"])
    body = upstream.issue_body(pin, "b" * 40, found)
    assert f"https://github.com/owner/repo/compare/{COMMIT}...{'b' * 40}" in body
    assert "`pack/skills/x`" in body
    assert "`pack/skills/new`" in body
    assert f"git diff {COMMIT} {'b' * 40} -- pack/skills/x" in body
    assert "skills/current/pstack/UPSTREAM.json" in body
