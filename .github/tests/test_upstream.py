"""Detect upstream drift for ported skills from pinned tree hashes."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import upstream  # noqa: E402

PIN = {
    "repo": "owner/repo",
    "release": "v1.0.0",
    "commit": "a" * 40,
    "trees": {"skills/x": "1" * 40, "skills/y": "2" * 40},
}


def write_pin(root: Path, name: str, pin: object) -> None:
    path = root / "skills/current" / name / "UPSTREAM.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(pin), encoding="utf-8")


def test_pins_reads_only_skills_with_upstream_files(tmp_path: Path) -> None:
    write_pin(tmp_path, "ported", PIN)
    (tmp_path / "skills/current/native").mkdir(parents=True)
    pins = upstream.pins(tmp_path)
    assert [pin.skill for pin in pins] == ["ported"]
    assert pins[0].repo == "owner/repo"
    assert pins[0].trees == PIN["trees"]


def test_pins_rejects_malformed_files(tmp_path: Path) -> None:
    write_pin(tmp_path, "broken", {"repo": "owner/repo", "trees": {}})
    with pytest.raises(ValueError, match="broken"):
        _ = upstream.pins(tmp_path)


def test_changed_lists_modified_and_removed_paths() -> None:
    pin = upstream.Pin.parse("x", PIN)
    assert upstream.changed(pin, {"skills/x": "1" * 40, "skills/y": "2" * 40}) == []
    assert upstream.changed(pin, {"skills/x": "9" * 40, "skills/y": "2" * 40}) == [
        "skills/x"
    ]
    assert upstream.changed(pin, {"skills/x": "1" * 40}) == ["skills/y"]


def test_issue_title_names_the_skill_and_release() -> None:
    pin = upstream.Pin.parse("paseo", PIN)
    assert upstream.issue_title(pin, "v1.1.0") == (
        "skills(paseo): upstream owner/repo v1.1.0 changed ported skills"
    )


def test_issue_body_links_the_comparison() -> None:
    pin = upstream.Pin.parse("paseo", PIN)
    body = upstream.issue_body(pin, "v1.1.0", ["skills/x"])
    assert "https://github.com/owner/repo/compare/v1.0.0...v1.1.0" in body
    assert "`skills/x`" in body
    assert "skills/current/paseo/UPSTREAM.json" in body
