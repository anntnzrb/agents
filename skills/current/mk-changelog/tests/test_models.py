"""Unit tests for models."""

from models import (
    BoundaryInfo,
    CommitInfo,
    ExistingEntries,
    PreparedContext,
)


def test_commit_info_serialization():
    commit = CommitInfo(
        commit_hash="a1b2c3d4e5f6",
        short_hash="a1b2c3d",
        author_name="Jane Doe",
        author_email="jane@example.com",
        date="2026-09-06",
        subject="feat(cli): add dry-run flag (#10)",
        category="Added",
        pr_number=10,
        affected_files=["src/cli.ts"],
    )
    d = commit.to_dict()
    assert d["commit_hash"] == "a1b2c3d4e5f6"
    assert d["short_hash"] == "a1b2c3d"
    assert d["author_name"] == "Jane Doe"
    assert d["pr_number"] == 10
    assert d["category"] == "Added"
    assert d["affected_files"] == ["src/cli.ts"]


def test_prepared_context_serialization():
    boundary = BoundaryInfo(
        changelog_path="/path/to/CHANGELOG.md",
        relative_path="CHANGELOG.md",
        files=["src/main.ts"],
    )
    existing = ExistingEntries(
        unreleased_found=True,
        start_line=5,
        end_line=12,
        entries={"Added": ["Feature X"]},
    )
    ctx = PreparedContext(
        source_type="range",
        spec="v1.0..HEAD",
        boundaries=[boundary],
        existing_entries={"CHANGELOG.md": existing},
        diff_stat="1 file changed, 10 insertions(+)",
    )
    d = ctx.to_dict()
    assert d["source_type"] == "range"
    assert len(d["boundaries"]) == 1
    assert d["boundaries"][0]["relative_path"] == "CHANGELOG.md"
    assert d["existing_entries"]["CHANGELOG.md"]["unreleased_found"] is True
