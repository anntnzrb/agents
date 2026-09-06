"""Data models and type definitions for mk-changelog."""

from dataclasses import dataclass, field
from typing import TypedDict

CATEGORIES: tuple[str, ...] = (
    "Breaking Changes",
    "Added",
    "Changed",
    "Deprecated",
    "Removed",
    "Fixed",
    "Security",
)

CONVENTIONAL_TYPE_MAP: dict[str, str] = {
    "feat": "Added",
    "feature": "Added",
    "fix": "Fixed",
    "bugfix": "Fixed",
    "perf": "Changed",
    "refactor": "Changed",
    "revert": "Changed",
    "docs": "Changed",
    "deprecate": "Deprecated",
    "deprecated": "Deprecated",
    "remove": "Removed",
    "sec": "Security",
    "security": "Security",
}


class CommitDict(TypedDict):
    """Serialized commit shape."""

    commit_hash: str
    short_hash: str
    author_name: str
    author_email: str
    date: str
    subject: str
    body: str
    category: str
    pr_number: int | None
    pr_url: str | None
    is_revert: bool
    is_bot: bool
    affected_files: list[str]


class BoundaryDict(TypedDict):
    """Serialized boundary shape."""

    changelog_path: str
    relative_path: str
    files: list[str]


class ExistingEntriesDict(TypedDict):
    """Serialized existing entries shape."""

    unreleased_found: bool
    start_line: int
    end_line: int
    entries: dict[str, list[str]]


class PreparedContextDict(TypedDict):
    """Serialized prepared context shape."""

    source_type: str
    spec: str
    commits: list[CommitDict]
    boundaries: list[BoundaryDict]
    existing_entries: dict[str, ExistingEntriesDict]
    contributors: dict[str, str]
    diff_stat: str
    diff_snippet: str


@dataclass(slots=True)
class CommitInfo:
    """Structured commit representation."""

    commit_hash: str
    short_hash: str
    author_name: str
    author_email: str
    date: str
    subject: str
    body: str = ""
    category: str = "Changed"
    pr_number: int | None = None
    pr_url: str | None = None
    is_revert: bool = False
    is_bot: bool = False
    affected_files: list[str] = field(default_factory=list)

    def to_dict(self) -> CommitDict:
        """Convert commit info to typed dictionary."""
        return {
            "commit_hash": self.commit_hash,
            "short_hash": self.short_hash,
            "author_name": self.author_name,
            "author_email": self.author_email,
            "date": self.date,
            "subject": self.subject,
            "body": self.body,
            "category": self.category,
            "pr_number": self.pr_number,
            "pr_url": self.pr_url,
            "is_revert": self.is_revert,
            "is_bot": self.is_bot,
            "affected_files": list(self.affected_files),
        }


@dataclass(slots=True)
class BoundaryInfo:
    """Changelog file boundary representation in a repository or monorepo."""

    changelog_path: str
    relative_path: str
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> BoundaryDict:
        """Convert boundary info to typed dictionary."""
        return {
            "changelog_path": self.changelog_path,
            "relative_path": self.relative_path,
            "files": list(self.files),
        }


@dataclass(slots=True)
class ExistingEntries:
    """Existing unreleased entries in a changelog."""

    unreleased_found: bool
    start_line: int
    end_line: int
    entries: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> ExistingEntriesDict:
        """Convert existing entries info to typed dictionary."""
        return {
            "unreleased_found": self.unreleased_found,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "entries": {k: list(v) for k, v in self.entries.items()},
        }


@dataclass(slots=True)
class PreparedContext:
    """Comprehensive prepared context for AI synthesis."""

    source_type: str
    spec: str
    commits: list[CommitInfo] = field(default_factory=list)
    boundaries: list[BoundaryInfo] = field(default_factory=list)
    existing_entries: dict[str, ExistingEntries] = field(default_factory=dict)
    contributors: dict[str, str] = field(default_factory=dict)
    diff_stat: str = ""
    diff_snippet: str = ""

    def to_dict(self) -> PreparedContextDict:
        """Convert prepared context to typed dictionary."""
        return {
            "source_type": self.source_type,
            "spec": self.spec,
            "commits": [c.to_dict() for c in self.commits],
            "boundaries": [b.to_dict() for b in self.boundaries],
            "existing_entries": {
                k: v.to_dict() for k, v in self.existing_entries.items()
            },
            "contributors": dict(self.contributors),
            "diff_stat": self.diff_stat,
            "diff_snippet": self.diff_snippet,
        }
