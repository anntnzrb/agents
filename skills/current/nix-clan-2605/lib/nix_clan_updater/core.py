"""Fetch, transform, and stage pinned Clan documentation snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

RELEASE_RE = re.compile(r"\d{2}\.\d{2}\Z")
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
MIN_GIT_ROW_FIELDS = 2
EXPECTED_SINGLE_MATCH = 1
FIRST_LINE_INDEX = 0
NOT_FOUND = -1
SUCCESS_RETURN_CODE = 0
MAX_DESCRIPTION_LENGTH = 120
TOC_LINE_LIMIT = 300
GENERATED_PREFIXES = (
    "reference/options",
    "reference/clan.core",
    "reference/cli",
    "services/official",
)
MARKER_START = "<!-- nix-clan-updater:toc:start -->"
MARKER_END = "<!-- nix-clan-updater:toc:end -->"
TRANSIENT_DIRS = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache"})

DISK_OLD = (
    "This guide provides an example setup for a ext4-single-disk ZFS system "
    "with native encryption, accessible for decryption remotely."
)
DISK_NEW = (
    "This guide provides an example setup for a ZFS system with native "
    "encryption and remote decryption over SSH."
)
REFERENCE_OLD = (
    "This documentation is always built for the main branch.\n"
    "If you need documentation for a specific commit you can build it on your own\n"
    "\n"
    "```bash\n"
    "nix build 'git+https://git.clan.lol/clan/clan-core?ref="
    "0324f4d4b87d932163f351e53b23b0b17f2b5e15#docs'\n"
    "```"
)


class UpdaterError(Exception):
    """A user-actionable updater failure."""

    exit_code: int = 2


class MissingGitError(UpdaterError):
    """Report that the git executable is unavailable."""

    exit_code: int = 127


class ConflictError(UpdaterError):
    """Report that an update would overwrite an existing path."""


@dataclass(frozen=True)
class SourceInfo:
    """Describe the fetched branch checkout used for one update."""

    repo: str
    branch: str
    commit: str
    checkout: Path


@dataclass(frozen=True)
class FileDelta:
    """Describe one path-level change between source and candidate trees."""

    path: str
    status: str
    old_sha256: str | None
    new_sha256: str | None


@dataclass(frozen=True)
class _Frontmatter:
    """Store validated SKILL frontmatter values and line locations."""

    branch: str
    commit: str
    retrieved: str
    end: int
    fields: dict[str, int]


@dataclass
class Summary:
    """Summarize a planned or applied snapshot update."""

    branch: str
    release: str
    skill_name: str
    commit: str
    source_dir: str
    target_dir: str
    applied: bool
    source_markdown: int
    source_embeds: int
    excluded: list[str]
    files: list[FileDelta]
    warnings: list[str]
    source_tree_sha256: str
    candidate_tree_sha256: str

    def to_dict(self) -> dict[str, object]:
        """Return the summary in the public JSON-compatible shape."""
        counts: dict[str, int] = dict.fromkeys(
            ("added", "changed", "deleted", "unchanged"), 0
        )
        for delta in self.files:
            counts[delta.status] += 1
        return {
            "branch": self.branch,
            "release": self.release,
            "skill_name": self.skill_name,
            "commit": self.commit,
            "source_dir": self.source_dir,
            "target_dir": self.target_dir,
            "applied": self.applied,
            "dry_run": not self.applied,
            "source_markdown": self.source_markdown,
            "source_embeds": self.source_embeds,
            "excluded": self.excluded,
            "counts": counts,
            "files": [delta.__dict__ for delta in self.files],
            "warnings": self.warnings,
            "source_tree_sha256": self.source_tree_sha256,
            "candidate_tree_sha256": self.candidate_tree_sha256,
        }


def _run_git(
    args: Sequence[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
    except FileNotFoundError as exc:
        msg = "git is required to fetch the target branch"
        raise MissingGitError(msg) from exc
    except (OSError, UnicodeError) as exc:
        msg = f"git {' '.join(args)} could not be executed"
        raise UpdaterError(msg) from exc


def _git_checked(
    args: Sequence[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    result = _run_git(args, cwd)
    if result.returncode != SUCCESS_RETURN_CODE:
        detail = (result.stderr or result.stdout).strip()
        msg = f"git {' '.join(args)} failed: {detail or 'unknown error'}"
        raise UpdaterError(msg)
    return result


def _resolve_commit(repo: str, branch: str) -> str:
    result = _git_checked(
        ["ls-remote", "--exit-code", "--heads", repo, f"refs/heads/{branch}"]
    )
    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    matches = [
        row[0]
        for row in rows
        if len(row) >= MIN_GIT_ROW_FIELDS and row[1] == f"refs/heads/{branch}"
    ]
    if len(matches) != EXPECTED_SINGLE_MATCH or not SHA_RE.fullmatch(matches[0]):
        msg = f"could not resolve exactly one SHA for branch {branch!r}"
        raise UpdaterError(msg)
    return matches[0]


def _check_symlinks(root: Path, label: str) -> None:
    if root.is_symlink():
        msg = f"{label} contains symlink: {root}"
        raise UpdaterError(msg)
    for path in root.rglob("*"):
        if path.is_symlink():
            msg = f"{label} contains symlink: {path}"
            raise UpdaterError(msg)


def _reject_symlinks(root: Path, label: str) -> None:
    try:
        _check_symlinks(root, label)
    except UpdaterError:
        raise
    except OSError as exc:
        msg = f"could not inspect {label}: {root}"
        raise UpdaterError(msg) from exc


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        msg = f"could not read {label}: {path}"
        raise UpdaterError(msg) from exc


def _read_text(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        msg = f"{label} is not valid UTF-8: {path}"
        raise UpdaterError(msg) from exc
    except OSError as exc:
        msg = f"could not read {label}: {path}"
        raise UpdaterError(msg) from exc


def resolve_source(repo: str, branch: str, work_dir: Path) -> SourceInfo:
    """Resolve and clone one release branch into a temporary checkout."""
    commit = _resolve_commit(repo, branch)
    checkout = work_dir / "clan-core"
    _ = _git_checked(
        ["clone", "--depth", "1", "--no-tags", "--branch", branch, repo, str(checkout)]
    )
    head = _git_checked(["rev-parse", "HEAD"], checkout).stdout.strip()
    if head != commit:
        msg = f"branch {branch} moved while fetching; resolved {commit}, cloned {head}"
        raise UpdaterError(msg)
    docs_root = checkout / "docs" / "src"
    embeds_root = checkout / "docs" / "embeds"
    license_path = checkout / "LICENSE.md"
    _reject_symlinks(docs_root, "fetched docs/src")
    _reject_symlinks(embeds_root, "fetched docs/embeds")
    _reject_symlinks(license_path, "fetched LICENSE.md")
    if not docs_root.is_dir():
        msg = "target checkout has no docs/src directory"
        raise UpdaterError(msg)
    if not embeds_root.is_dir():
        msg = "target checkout has no docs/embeds directory"
        raise UpdaterError(msg)
    if not license_path.is_file():
        msg = "target checkout has no LICENSE.md"
        raise UpdaterError(msg)
    return SourceInfo(repo, branch, commit, checkout)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        msg = f"could not read file for hashing: {path}"
        raise UpdaterError(msg) from exc
    return digest.hexdigest()


def _is_transient(relative: str) -> bool:
    path = Path(relative)
    return path.suffix == ".pyc" or bool(TRANSIENT_DIRS.intersection(path.parts))


def _scan_tree_files(root: Path) -> dict[str, Path]:
    if root.is_symlink():
        msg = f"tree contains symlink: {root}"
        raise UpdaterError(msg)
    result: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            msg = f"tree contains symlink: {path}"
            raise UpdaterError(msg)
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            if not _is_transient(relative):
                result[relative] = path
    return result


def _tree_files(root: Path) -> dict[str, Path]:
    try:
        return _scan_tree_files(root)
    except UpdaterError:
        raise
    except OSError as exc:
        msg = f"could not inspect tree: {root}"
        raise UpdaterError(msg) from exc


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for relative, path in sorted(_tree_files(root).items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256(path)))
    return digest.hexdigest()


def _file_deltas(old_root: Path, new_root: Path) -> list[FileDelta]:
    old = _tree_files(old_root)
    new = _tree_files(new_root)
    deltas: list[FileDelta] = []
    for relative in sorted(set(old) | set(new)):
        old_sha = _sha256(old[relative]) if relative in old else None
        new_sha = _sha256(new[relative]) if relative in new else None
        if old_sha == new_sha:
            status = "unchanged"
        elif old_sha is None:
            status = "added"
        elif new_sha is None:
            status = "deleted"
        else:
            status = "changed"
        deltas.append(FileDelta(relative, status, old_sha, new_sha))
    return deltas


def _find_frontmatter_closing(lines: list[str]) -> int:
    if not lines or lines[0].rstrip("\r\n") != "---":
        msg = "SKILL.md has no YAML frontmatter"
        raise UpdaterError(msg)
    closing = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.rstrip("\r\n") == "---"
        ),
        None,
    )
    if closing is None:
        msg = "SKILL.md frontmatter has no closing delimiter"
        raise UpdaterError(msg)
    return closing


def _scan_nested_field(
    raw: str, index: int, metadata_active: bool, fields: dict[str, int]
) -> None:
    if not metadata_active or not raw.startswith("  ") or raw.startswith("   "):
        msg = "SKILL.md frontmatter has malformed nested fields"
        raise UpdaterError(msg)
    key, separator, _ = raw[2:].partition(":")
    if not separator or not key or key.strip() != key:
        msg = "SKILL.md frontmatter has malformed metadata"
        raise UpdaterError(msg)
    field_name = f"metadata.{key}"
    if key in {"branch", "commit", "retrieved"}:
        if field_name in fields:
            msg = f"SKILL.md frontmatter duplicates {field_name}"
            raise UpdaterError(msg)
        fields[field_name] = index


def _scan_top_field(
    raw: str, index: int, metadata_seen: bool, fields: dict[str, int]
) -> tuple[bool, bool]:
    key, separator, value = raw.partition(":")
    if not separator or not key or key.strip() != key:
        msg = "SKILL.md frontmatter has malformed fields"
        raise UpdaterError(msg)
    metadata_active = key == "metadata"
    if metadata_active:
        if metadata_seen:
            msg = "SKILL.md frontmatter duplicates metadata"
            raise UpdaterError(msg)
        metadata_seen = True
    if key in {"name", "description"}:
        if key in fields:
            msg = f"SKILL.md frontmatter duplicates {key}"
            raise UpdaterError(msg)
        fields[key] = index
        if key == "description" and (
            not value.strip() or value.strip()[0] in {"|", ">"}
        ):
            msg = "SKILL.md description must be a single-line value"
            raise UpdaterError(msg)
    return metadata_active, metadata_seen


def _scan_frontmatter_fields(lines: list[str], closing: int) -> dict[str, int]:
    fields: dict[str, int] = {}
    metadata_seen = False
    metadata_active = False
    for index, line in enumerate(lines[1:closing], start=1):
        raw = line.rstrip("\r\n")
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[0].isspace():
            _scan_nested_field(raw, index, metadata_active, fields)
        else:
            metadata_active, metadata_seen = _scan_top_field(
                raw, index, metadata_seen, fields
            )
    return fields


def _validate_frontmatter_description(
    lines: list[str], desc_index: int, closing: int
) -> None:
    for line in lines[desc_index + 1 : closing]:
        raw = line.rstrip("\r\n")
        if raw and raw[0].isspace():
            msg = "SKILL.md description must not be folded or multiline"
            raise UpdaterError(msg)
        if raw and not raw[0].isspace() and raw.partition(":")[0] == "metadata":
            break
        if raw and not raw[0].isspace() and ":" in raw:
            break


def _validate_frontmatter_values(
    lines: list[str], fields: dict[str, int]
) -> tuple[str, str, str]:
    required = (
        "name",
        "description",
        "metadata.branch",
        "metadata.commit",
        "metadata.retrieved",
    )
    missing = [field for field in required if field not in fields]
    if missing:
        msg = f"SKILL.md frontmatter lacks {', '.join(missing)}"
        raise UpdaterError(msg)

    def value_for(field: str) -> str:
        line = lines[fields[field]].rstrip("\r\n")
        return line.partition(":")[2].strip()

    branch = value_for("metadata.branch")
    commit = value_for("metadata.commit")
    retrieved = value_for("metadata.retrieved")
    if not RELEASE_RE.fullmatch(branch):
        msg = "SKILL.md metadata.branch is not a YY.MM release"
        raise UpdaterError(msg)
    if not SHA_RE.fullmatch(commit):
        msg = "SKILL.md metadata.commit is not a SHA-1"
        raise UpdaterError(msg)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", retrieved):
        msg = "SKILL.md metadata.retrieved is not an ISO date"
        raise UpdaterError(msg)
    return branch, commit, retrieved


def _parse_frontmatter(text: str) -> _Frontmatter:
    lines = text.splitlines(keepends=True)
    closing = _find_frontmatter_closing(lines)
    fields = _scan_frontmatter_fields(lines, closing)
    _validate_frontmatter_description(lines, fields.get("description", 0), closing)
    branch, commit, retrieved = _validate_frontmatter_values(lines, fields)
    return _Frontmatter(
        branch, commit, retrieved, sum(map(len, lines[: closing + 1])), fields
    )


def _replace_frontmatter_line(lines: list[str], index: int, value: str) -> None:
    line = lines[index]
    eol = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    prefix = line.rstrip("\r\n").partition(":")[0]
    lines[index] = f"{prefix}: {value}{eol}"


def _update_skill_body(
    body: str,
    parsed: _Frontmatter,
    release: str,
    commit: str,
    retrieved: str,
) -> str:
    lines = body.splitlines(keepends=True)
    snapshot_lines_left = 0
    for index, line in enumerate(lines):
        raw = line.rstrip("\r\n")
        if re.fullmatch(r"# Clan \d{2}\.\d{2} Documentation", raw):
            eol = (
                "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            )
            lines[index] = f"# Clan {release} Documentation{eol}"
            continue
        if "The bundled snapshot is Clan" in raw:
            snapshot_lines_left = 2
        if snapshot_lines_left:
            lines[index] = (
                lines[index]
                .replace(f"`{parsed.branch}`", f"`{release}`")
                .replace(f"`{parsed.commit}`", f"`{commit}`")
                .replace(f"retrieved {parsed.retrieved}", f"retrieved {retrieved}")
            )
            snapshot_lines_left -= 1
        if "Follow the pinned `https://clan.lol/docs/" in raw:
            lines[index] = re.sub(
                r"(/docs/)\d{2}\.\d{2}(/)",
                rf"\g<1>{release}\g<2>",
                lines[index],
                count=1,
            )
    return "".join(lines)


def update_skill(
    text: str, release: str, commit: str, retrieved: str
) -> tuple[str, str, str]:
    """Update validated SKILL metadata and known snapshot router lines."""
    if not RELEASE_RE.fullmatch(release):
        msg = "generated release is not a YY.MM value"
        raise UpdaterError(msg)
    if not SHA_RE.fullmatch(commit):
        msg = "generated commit is not a SHA-1"
        raise UpdaterError(msg)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", retrieved):
        msg = "generated retrieved value is not an ISO date"
        raise UpdaterError(msg)
    parsed = _parse_frontmatter(text)
    skill_name = f"nix-clan-{release.replace('.', '')}"
    description = (
        f"Use for Clan {release} inventory, services, vars, deployment, migrations, "
        "and NixOS workflow documentation."
    )
    if len(description) > MAX_DESCRIPTION_LENGTH:
        msg = "generated SKILL.md description exceeds 120 characters"
        raise UpdaterError(msg)
    prefix_lines = text[: parsed.end].splitlines(keepends=True)
    _replace_frontmatter_line(prefix_lines, parsed.fields["name"], skill_name)
    _replace_frontmatter_line(prefix_lines, parsed.fields["description"], description)
    _replace_frontmatter_line(prefix_lines, parsed.fields["metadata.branch"], release)
    _replace_frontmatter_line(prefix_lines, parsed.fields["metadata.commit"], commit)
    _replace_frontmatter_line(
        prefix_lines, parsed.fields["metadata.retrieved"], retrieved
    )
    prefix = "".join(prefix_lines)
    body = _update_skill_body(
        text[parsed.end :],
        parsed,
        release,
        commit,
        retrieved,
    )
    return prefix + body, parsed.branch, parsed.commit


def _index_fields(text: str) -> tuple[list[str], dict[str, int]]:
    lines = text.splitlines(keepends=True)
    fields: dict[str, int] = {}
    for index, line in enumerate(lines):
        raw = line.rstrip("\r\n")
        match = re.match(r"^- (Branch|Commit|Retrieved|Vendored):(?:[ \t]*(.*))?$", raw)
        if match:
            field = match.group(1)
            if field in fields:
                msg = f"references/INDEX.md has duplicate {field} field"
                raise UpdaterError(msg)
            fields[field] = index
    required = ("Branch", "Commit", "Retrieved", "Vendored")
    missing = [field for field in required if field not in fields]
    if missing:
        msg = f"references/INDEX.md lacks exactly one of: {', '.join(required)}"
        raise UpdaterError(msg)
    return lines, fields


def _backtick_field(lines: list[str], index: int, field: str) -> str:
    value = lines[index].rstrip("\r\n").partition(":")[2].strip()
    match = re.fullmatch(r"`([^`\r\n]+)`", value)
    if match is None:
        msg = f"references/INDEX.md {field} must be wrapped in backticks"
        raise UpdaterError(msg)
    return match.group(1)


def _index_field_end(lines: list[str], index: int) -> int:
    end = index + 1
    while end < len(lines) and lines[end].strip() and lines[end][0].isspace():
        end += 1
    return end


def _set_index_field(lines: list[str], index: int, value: str) -> None:
    line = lines[index]
    eol = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    prefix = line.rstrip("\r\n").partition(":")[0]
    lines[index] = f"{prefix}: `{value}`{eol}"


def update_index(
    text: str, release: str, commit: str, retrieved: str, markdown_count: int
) -> str:
    """Update only validated INDEX snapshot metadata and generated routes."""
    lines, fields = _index_fields(text)
    old_branch = _backtick_field(lines, fields["Branch"], "Branch")
    old_commit = _backtick_field(lines, fields["Commit"], "Commit")
    _ = _backtick_field(lines, fields["Retrieved"], "Retrieved")
    vendored = lines[fields["Vendored"]].rstrip("\r\n").partition(":")[2].strip()
    if not vendored:
        msg = "references/INDEX.md Vendored field has no value"
        raise UpdaterError(msg)
    if not RELEASE_RE.fullmatch(old_branch) or not SHA_RE.fullmatch(old_commit):
        msg = "references/INDEX.md snapshot metadata is malformed"
        raise UpdaterError(msg)
    title = re.compile(r"^# Clan \d{2}\.\d{2} Reference Index$")
    generated_section = False
    for index, line in enumerate(lines):
        raw = line.rstrip("\r\n")
        if index == FIRST_LINE_INDEX and title.fullmatch(raw):
            eol = (
                "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            )
            lines[index] = f"# Clan {release} Reference Index{eol}"
        if re.match(r"^- Source: `[^`]+/src/branch/\d{2}\.\d{2}/docs/src`$", raw):
            lines[index] = re.sub(
                r"(/src/branch/)\d{2}\.\d{2}(/docs/src`)",
                rf"\g<1>{release}\g<2>",
                lines[index],
                count=1,
            )
        if raw.startswith("## "):
            generated_section = raw == "## Generated documentation"
        if generated_section:
            lines[index] = re.sub(
                r"(https://clan\.lol/docs/)\d{2}\.\d{2}(/)",
                rf"\g<1>{release}\g<2>",
                lines[index],
            )

    _set_index_field(lines, fields["Branch"], release)
    _set_index_field(lines, fields["Commit"], commit)
    _set_index_field(lines, fields["Retrieved"], retrieved)
    vendored_index = fields["Vendored"]
    eol = (
        "\r\n"
        if lines[vendored_index].endswith("\r\n")
        else "\n"
        if lines[vendored_index].endswith("\n")
        else ""
    )
    vendored_lines = [
        (
            f"- Vendored: {markdown_count} Markdown files from upstream `docs/src`; "
            f"excludes{eol}"
        ),
        (
            f"  `test.md`, non-Markdown sources such as `index.svelte`, and "
            f"generated-prefix{eol}"
        ),
        f"  Markdown pages when present.{eol}",
    ]
    lines[vendored_index : _index_field_end(lines, vendored_index)] = vendored_lines
    return "".join(lines)


def update_notice(
    repo: str, branch: str, commit: str, retrieved: str, license_bytes: bytes
) -> bytes:
    """Build provenance text followed by the upstream license bytes verbatim."""
    try:
        _ = license_bytes.decode("utf-8")
    except UnicodeError as exc:
        msg = "target LICENSE.md is not valid UTF-8"
        raise UpdaterError(msg) from exc
    header = (
        "# Upstream Notice\n\n"
        f"- Upstream repository: `{repo}`\n"
        f"- Source branch: `{branch}`\n"
        f"- Snapshot commit: `{commit}`\n"
        f"- Retrieved: `{retrieved}`\n"
        f"- License source: `{repo}/src/branch/{branch}/LICENSE.md`\n\n"
    ).encode()
    return header + license_bytes


def _source_docs(checkout: Path) -> tuple[list[Path], list[str]]:
    root = checkout / "docs" / "src"
    _reject_symlinks(root, "fetched docs/src")
    if not root.is_dir():
        msg = "target checkout has no docs/src directory"
        raise UpdaterError(msg)
    excluded: list[str] = []
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            msg = f"fetched docs/src contains symlink: {path}"
            raise UpdaterError(msg)
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        display = path.relative_to(checkout).as_posix()
        if path.name == "test.md":
            excluded.append(display)
        elif path.suffix != ".md":
            excluded.append(f"{display} (non-Markdown)")
        elif _generated(relative):
            excluded.append(f"{display} (generated)")
        else:
            files.append(path)
    return files, excluded


def _source_embeds(checkout: Path) -> tuple[list[Path], list[str]]:
    root = checkout / "docs" / "embeds"
    _reject_symlinks(root, "fetched docs/embeds")
    if not root.is_dir():
        msg = "target checkout has no docs/embeds directory"
        raise UpdaterError(msg)
    excluded: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            msg = f"fetched docs/embeds contains symlink: {path}"
            raise UpdaterError(msg)
        if path.is_file() and path.name == "test.nix":
            excluded.append(path.relative_to(checkout).as_posix())
    files = [
        path
        for path in sorted(root.rglob("*.nix"))
        if path.is_file() and not path.is_symlink() and path.name != "test.nix"
    ]
    return files, excluded


def _embed_map(paths: Iterable[Path], checkout: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for path in paths:
        relative = path.relative_to(checkout / "docs" / "embeds").as_posix()
        result[relative] = _read_bytes(path, "upstream embed")
    return result


def _slug(value: str) -> str:
    value = re.sub(r"<[^>]*>", "", value)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", value).lower()
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    return re.sub(r"-+", "-", re.sub(r"\s+", "-", value)).strip("-")


def _headings(text: str) -> list[tuple[int, str, str]]:
    found: list[tuple[int, str, str]] = []
    seen: dict[str, int] = {}
    fence_char: str | None = None
    fence_length = 0
    for line in text.splitlines():
        fence = re.match(r"^\s{0,3}(?P<run>`{3,}|~{3,})(?P<info>.*)$", line)
        if fence_char is not None:
            if (
                fence
                and fence.group("run")[0] == fence_char
                and len(fence.group("run")) >= fence_length
            ):
                fence_char = None
                fence_length = 0
            continue
        if fence:
            run = fence.group("run")
            fence_char = run[0]
            fence_length = len(run)
            continue
        match = re.match(r"^(#{2,6})\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        title = match.group(2)
        if title.strip().lower() in {"table of contents", "contents"}:
            continue
        anchor = _slug(title)
        if not anchor:
            continue
        count = seen.get(anchor, 0)
        seen[anchor] = count + 1
        if count:
            anchor = f"{anchor}-{count}"
        found.append((len(match.group(1)), title, anchor))
    return found


def _toc_block(text: str) -> tuple[int, int, list[str]] | None:
    lines = text.splitlines(keepends=True)
    marker_start = next(
        (i for i, line in enumerate(lines) if line.strip() == MARKER_START), None
    )
    if marker_start is not None:
        marker_end = next(
            (
                i
                for i in range(marker_start + 1, len(lines))
                if lines[i].strip() == MARKER_END
            ),
            None,
        )
        if marker_end is None:
            msg = "updater TOC marker has no end marker"
            raise UpdaterError(msg)
        return marker_start, marker_end + 1, lines[marker_start : marker_end + 1]
    heading = next(
        (
            i
            for i, line in enumerate(lines)
            if re.match(r"^## (?:Table of Contents|Contents)\s*$", line.strip())
        ),
        None,
    )
    if heading is None:
        return None
    end = heading + 1
    while end < len(lines) and not re.match(r"^##\s+", lines[end].strip()):
        end += 1
    return heading, end, lines[heading:end]


def _toc_is_managed(block: Iterable[str]) -> bool:
    lines = [line.strip() for line in block]
    return bool(lines) and lines[0] == MARKER_START and lines[-1] == MARKER_END


def _toc_entries(block: Iterable[str]) -> list[tuple[str, str]] | None:
    entries: list[tuple[str, str]] = []
    for line in block:
        stripped = line.strip()
        if (
            not stripped
            or stripped in {MARKER_START, MARKER_END}
            or stripped.startswith("## ")
        ):
            continue
        match = re.fullmatch(r"[-*]\s+\[([^\]]+)\]\(#([^)]+)\)", stripped)
        if match is None:
            return None
        entries.append((match.group(1), match.group(2)))
    return entries


def _make_toc(headings: list[tuple[int, str, str]], eol: str) -> list[str]:
    lines = [MARKER_START + eol, "## Table of Contents" + eol]
    lines.extend(
        "  " * (level - 2) + f"- [{title}](#{anchor})" + eol
        for level, title, anchor in headings
    )
    lines.extend((MARKER_END + eol, eol))
    return lines


def _insert_toc(text: str, block: list[str]) -> str:
    lines = text.splitlines(keepends=True)
    index = next(
        (i for i, line in enumerate(lines) if re.match(r"^##\s+", line)), len(lines)
    )
    lines[index:index] = block
    return "".join(lines)


def _replace_toc(text: str, toc: tuple[int, int, list[str]], block: list[str]) -> str:
    lines = text.splitlines(keepends=True)
    lines[toc[0] : toc[1]] = block
    return "".join(lines)


def _toc_for(text: str, existing: str | None) -> str:
    headings = _headings(text)
    expected = [(title, anchor) for _, title, anchor in headings]
    current_toc = _toc_block(text)
    eol = "\r\n" if "\r\n" in text else "\n"
    if current_toc is not None:
        if _toc_is_managed(current_toc[2]):
            return _replace_toc(text, current_toc, _make_toc(headings, eol))
        if _toc_entries(current_toc[2]) == expected:
            return text
    if len(text.splitlines()) <= TOC_LINE_LIMIT:
        return text
    if existing is not None:
        old_toc = _toc_block(existing)
        if (
            old_toc is not None
            and not _toc_is_managed(old_toc[2])
            and _toc_entries(old_toc[2]) == expected
        ):
            return _insert_toc(text, old_toc[2])
    return _insert_toc(text, _make_toc(headings, eol))


def _route_candidates(route: str) -> list[str]:
    route = route.strip("/")
    if route.endswith(".md"):
        return [route]
    return [f"{route}.md", f"{route}/index.md"]


def _generated(route: str) -> bool:
    return any(
        route == prefix or route.startswith(prefix + "/")
        for prefix in GENERATED_PREFIXES
    )


def _docs_route(target: str) -> tuple[str, str, str] | None:
    parsed = urlsplit(target)
    if target.startswith("/docs/") or (
        parsed.netloc == "clan.lol" and parsed.path.startswith("/docs/")
    ):
        route = parsed.path[len("/docs/") :]
    else:
        return None
    version = re.match(r"(\d{2}\.\d{2})/(.*)", route)
    if version:
        route = version.group(2)
    return route.strip("/"), parsed.query, parsed.fragment


def _parse_destination_bounds(line: str, start: int) -> tuple[int, int, int] | None:
    if line[start] == "<":
        destination_start = start + 1
        destination_end = line.find(">", destination_start)
        if destination_end == NOT_FOUND:
            return None
        cursor = destination_end + 1
    else:
        destination_start = start
        cursor = start
        while cursor < len(line):
            if line[cursor] == "\\":
                cursor += 2
                continue
            if line[cursor].isspace() or line[cursor] == ")":
                break
            cursor += 1
        destination_end = cursor
    if destination_end == destination_start:
        return None
    return destination_start, destination_end, cursor


def _skip_quoted_title(line: str, cursor: int, quote: str) -> int:
    cursor += 1
    while cursor < len(line):
        if line[cursor] == "\\":
            cursor += 2
            continue
        if line[cursor] == quote:
            cursor += 1
            break
        cursor += 1
    return cursor


def _skip_parenthesized_title(line: str, cursor: int) -> int:
    depth = 1
    cursor += 1
    while cursor < len(line) and depth:
        if line[cursor] == "\\":
            cursor += 2
            continue
        if line[cursor] == "(":
            depth += 1
        elif line[cursor] == ")":
            depth -= 1
        cursor += 1
    return cursor


def _skip_markdown_title(line: str, cursor: int) -> int:
    if line[cursor] in {'"', "'"}:
        return _skip_quoted_title(line, cursor, line[cursor])
    if line[cursor] == "(":
        return _skip_parenthesized_title(line, cursor)
    while cursor < len(line) and line[cursor] != ")":
        cursor += 1
    return cursor


def _parse_markdown_link(line: str, index: int) -> tuple[int, int, int] | None:
    start = index + 2
    if start >= len(line):
        return None
    bounds = _parse_destination_bounds(line, start)
    if bounds is None:
        return None
    destination_start, destination_end, cursor = bounds
    while cursor < len(line) and line[cursor].isspace():
        cursor += 1
    if cursor >= len(line):
        return None
    if line[cursor] != ")":
        cursor = _skip_markdown_title(line, cursor)
        while cursor < len(line) and line[cursor].isspace():
            cursor += 1
    if cursor >= len(line) or line[cursor] != ")":
        return None
    return destination_start, destination_end, cursor


def _resolve_markdown_route(
    route_info: tuple[str, str, str],
    source_relative: str,
    copied: set[str],
    release: str,
) -> str:
    route, query, fragment = route_info
    if _generated(route):
        replacement = f"https://clan.lol/docs/{release}/{route}"
    else:
        destination = next(
            (
                candidate
                for candidate in _route_candidates(route)
                if candidate in copied
            ),
            None,
        )
        if destination is None:
            msg = f"unknown manual docs link in {source_relative}: /docs/{route}"
            raise UpdaterError(msg)
        replacement = posixpath.relpath(
            destination, posixpath.dirname(source_relative) or "."
        )
    if query:
        replacement += f"?{query}"
    if fragment:
        replacement += f"#{fragment}"
    return replacement


def _rewrite_markdown_line(
    line: str,
    source_relative: str,
    copied: set[str],
    release: str,
) -> str:
    output: list[str] = []
    index = 0
    while index < len(line):
        if line[index] == "`":
            run = 1
            while index + run < len(line) and line[index + run] == "`":
                run += 1
            marker = "`" * run
            closing = line.find(marker, index + run)
            if closing == NOT_FOUND:
                output.append(line[index:])
                break
            output.append(line[index : closing + run])
            index = closing + run
            continue
        if line.startswith("](", index):
            parsed = _parse_markdown_link(line, index)
            if parsed is None:
                output.append(line[index])
                index += 1
                continue
            destination_start, destination_end, close = parsed
            target = line[destination_start:destination_end]
            route_info = _docs_route(target)
            if route_info is None:
                output.append(line[index : close + 1])
                index = close + 1
                continue
            replacement = _resolve_markdown_route(
                route_info, source_relative, copied, release
            )
            output.append(line[index:destination_start])
            output.append(replacement)
            output.append(line[destination_end : close + 1])
            index = close + 1
            continue
        output.append(line[index])
        index += 1
    return "".join(output)


def _rewrite_markdown_links(
    text: str, source_relative: str, copied: set[str], release: str
) -> str:
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    fence_char: str | None = None
    fence_length = 0
    for line in lines:
        fence = re.match(
            r"^\s*(?:(?:[-+*]|\d+[.)])\s+)?(?P<run>`{3,}|~{3,})",
            line.rstrip("\r\n"),
        )
        if fence_char is not None:
            if (
                fence
                and fence.group("run")[0] == fence_char
                and len(fence.group("run")) >= fence_length
            ):
                fence_char = None
                fence_length = 0
            output.append(line)
            continue
        if fence:
            run = fence.group("run")
            fence_char = run[0]
            fence_length = len(run)
            output.append(line)
            continue
        output.append(_rewrite_markdown_line(line, source_relative, copied, release))
    return "".join(output)


def _pin_bare_docs_urls(text: str, release: str) -> str:
    pattern = re.compile(r"https://clan\.lol/docs/(?:\d{2}\.\d{2}/)?[^\s<>'\"]+")

    def replace(match: re.Match[str]) -> str:
        value = match.group(0).rstrip(".,;)")
        suffix = match.group(0)[len(value) :]
        parsed = urlsplit(value)
        route = parsed.path[len("/docs/") :].lstrip("/")
        version = re.match(r"\d{2}\.\d{2}/(.*)", route)
        if version:
            route = version.group(1)
        pinned = urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                f"/docs/{release}/{route}",
                parsed.query,
                parsed.fragment,
            )
        )
        return pinned + suffix

    return pattern.sub(replace, text)


def _pin_clan_urls(text: str, branch: str) -> str:
    text = re.sub(
        (
            r"(https://git\.clan\.lol/clan/clan-core/"
            r"(?:archive|src/branch|raw/branch)/)main(?=[^A-Za-z0-9]|$)"
        ),
        rf"\g<1>{branch}",
        text,
    )
    pattern = re.compile(r"github:clan/clan-core(?P<suffix>[^\s\"'<>)]*)")

    def replace(match: re.Match[str]) -> str:
        suffix = match.group("suffix")
        trailing = ""
        while suffix.endswith((".", ",", ";")):
            trailing = suffix[-1] + trailing
            suffix = suffix[:-1]
        fragment = ""
        if "#" in suffix:
            suffix, fragment_value = suffix.split("#", 1)
            fragment = f"#{fragment_value}"
        if suffix.startswith("?"):
            query = suffix[1:]
            params: list[str] = query.split("&") if query else []
            replaced = False
            for index, parameter in enumerate(params):
                if parameter.startswith("ref="):
                    params[index] = f"ref={branch}"
                    replaced = True
                    break
            if not replaced:
                params.insert(0, f"ref={branch}")
            suffix = "?" + "&".join(params)
        else:
            suffix = f"?ref={branch}" + (
                f"&{suffix[1:]}" if suffix.startswith("&") else suffix
            )
        return f"github:clan/clan-core{suffix}{fragment}{trailing}"

    return pattern.sub(replace, text)


def _inline_embeds(text: str, embeds: dict[str, bytes]) -> str:
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    index = 0
    fence = re.compile(
        r"^\s*```(?P<language>[A-Za-z0-9_-]+)(?P<rest>.*?\s+embed=(?P<name>[^\s]+))\s*$"
    )
    while index < len(lines):
        line = lines[index]
        match = fence.match(line.rstrip("\r\n"))
        if not match:
            output.append(line)
            index += 1
            continue
        if index + 1 >= len(lines) or lines[index + 1].strip() != "```":
            msg = f"embed fence {match.group('name')!r} is not an empty placeholder"
            raise UpdaterError(msg)
        name = match.group("name")
        if name not in embeds:
            msg = f"embed {name!r} is missing from docs/embeds"
            raise UpdaterError(msg)
        eol = "\r\n" if line.endswith("\r\n") else "\n"
        rest = match.group("rest")
        label_match = re.search(r"(\[[^]]+\])", rest)
        label = f" {label_match.group(1)}" if label_match else ""
        output.append(f"```{match.group('language')}{label}{eol}")
        try:
            embedded = embeds[name].decode("utf-8")
        except UnicodeError as exc:
            msg = f"embed {name!r} is not valid UTF-8"
            raise UpdaterError(msg) from exc
        output.append(embedded)
        if embedded and not embedded.endswith(("\n", "\r")):
            output.append(eol)
        output.append(f"```{eol}")
        index += 2
    return "".join(output)


def _compatibility_patches(
    relative: str, text: str, release: str, commit: str, warnings: list[str]
) -> str:
    if relative == "guides/disk-encryption.md":
        if DISK_OLD in text:
            text = text.replace(DISK_OLD, DISK_NEW, 1)
        elif DISK_NEW not in text:
            warnings.append(
                "compatibility patch skipped: disk-encryption wording changed upstream"
            )
    if relative == "reference/index.md":
        if REFERENCE_OLD in text:
            replacement = (
                f"This bundled overview is from Clan `{release}`, `clan-core` commit\n"
                + f"`{commit}`. Generated option, `clan.core`,\n"
                + "CLI, and official-service pages are not vendored here; follow the "
                + "pinned\n"
                + "rendered routes:\n\n"
                + "- [CLI](/docs/reference/cli)\n"
                + "- [Clan options](/docs/reference/options/clan)\n"
                + "- [`clan.core`](/docs/reference/clan.core)\n"
                + "- [Official services](/docs/services/official/)\n\n"
                + "Do not invent local generated pages or substitute `main`/`latest`."
            )
            text = text.replace(REFERENCE_OLD, replacement, 1)
        elif "This bundled overview is from Clan" not in text:
            warnings.append(
                "compatibility patch skipped: reference/index main-only guidance "
                + "changed upstream"
            )
    return text


@dataclass(frozen=True)
class _TransformContext:
    checkout: Path
    copied: set[str]
    embeds: dict[str, bytes]
    release: str
    branch: str
    commit: str
    warnings: list[str]


def _transform_page(
    source_path: Path,
    context: _TransformContext,
    existing: bytes | None,
) -> bytes:
    relative = source_path.relative_to(context.checkout / "docs" / "src").as_posix()
    text = _read_text(source_path, "upstream Markdown")
    text = _compatibility_patches(
        relative, text, context.release, context.commit, context.warnings
    )
    text = text.replace("{{ version }}", context.release)
    text = _pin_clan_urls(text, context.branch)
    text = _inline_embeds(text, context.embeds)
    text = _rewrite_markdown_links(text, relative, context.copied, context.release)
    text = _pin_bare_docs_urls(text, context.release)
    existing_text = None
    if existing is not None:
        try:
            existing_text = existing.decode("utf-8")
        except UnicodeError as exc:
            msg = f"existing Markdown is not valid UTF-8: {relative}"
            raise UpdaterError(msg) from exc
    text = _toc_for(text, existing_text)
    return text.encode("utf-8")


def _write_if_changed(path: Path, data: bytes) -> None:
    if path.is_symlink():
        msg = f"refusing to write through symlink: {path}"
        raise UpdaterError(msg)
    try:
        if path.is_file() and path.read_bytes() == data:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_bytes(data)
    except OSError as exc:
        msg = f"could not write generated file: {path}"
        raise UpdaterError(msg) from exc


def _remove_stale_files(root: Path, keep: set[str]) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_symlink():
            msg = f"candidate tree contains symlink: {path}"
            raise UpdaterError(msg)
        if path.is_file() and path.relative_to(root).as_posix() not in keep:
            path.unlink()


def _prune_empty_dirs(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                if any(path.iterdir()):
                    continue
                raise


def _remove_stale(root: Path, keep: set[str]) -> None:
    if not root.is_dir():
        return
    _reject_symlinks(root, "candidate tree")
    try:
        _remove_stale_files(root, keep)
        _prune_empty_dirs(root)
    except UpdaterError:
        raise
    except OSError as exc:
        msg = f"could not remove stale files under: {root}"
        raise UpdaterError(msg) from exc


def build_candidate(
    source_dir: Path, target: SourceInfo, candidate: Path
) -> tuple[int, int, list[str], list[str]]:
    """Copy and transform source material into an isolated candidate tree."""
    _reject_symlinks(source_dir, "source skill")
    try:
        _ = shutil.copytree(
            source_dir,
            candidate,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache"
            ),
        )
    except (OSError, shutil.Error) as exc:
        msg = f"could not copy source skill: {source_dir}"
        raise UpdaterError(msg) from exc
    old_docs_root = candidate / "references" / "docs"
    if old_docs_root.is_dir():
        _reject_symlinks(old_docs_root, "candidate docs")
        old_docs = {
            path.relative_to(old_docs_root).as_posix(): _read_bytes(
                path, "existing Markdown"
            )
            for path in old_docs_root.rglob("*.md")
            if path.is_file()
        }
    else:
        old_docs = {}
    old_embeds_root = candidate / "references" / "embeds"

    source_docs, excluded_docs = _source_docs(target.checkout)
    source_embeds, excluded_embeds = _source_embeds(target.checkout)
    copied = {
        path.relative_to(target.checkout / "docs" / "src").as_posix()
        for path in source_docs
    }
    embeds = _embed_map(source_embeds, target.checkout)
    _remove_stale(old_docs_root, copied)
    _remove_stale(old_embeds_root, set(embeds))
    warnings: list[str] = []
    transform_context = _TransformContext(
        checkout=target.checkout,
        copied=copied,
        embeds=embeds,
        release=target.branch,
        branch=target.branch,
        commit=target.commit,
        warnings=warnings,
    )
    output_docs_root = candidate / "references" / "docs"
    for source_path in source_docs:
        relative = source_path.relative_to(target.checkout / "docs" / "src").as_posix()
        generated = _transform_page(
            source_path,
            transform_context,
            old_docs.get(relative),
        )
        _write_if_changed(output_docs_root / relative, generated)
    output_embeds_root = candidate / "references" / "embeds"
    for source_path in source_embeds:
        relative = source_path.relative_to(
            target.checkout / "docs" / "embeds"
        ).as_posix()
        _write_if_changed(
            output_embeds_root / relative, _read_bytes(source_path, "upstream embed")
        )

    skill_path = candidate / "SKILL.md"
    skill_text = _read_text(skill_path, "SKILL.md")
    retrieved = _parse_frontmatter(skill_text).retrieved
    updated_skill, _, _ = update_skill(
        skill_text, target.branch, target.commit, retrieved
    )
    _write_if_changed(skill_path, updated_skill.encode("utf-8"))
    index_path = candidate / "references" / "INDEX.md"
    index_text = _read_text(index_path, "references/INDEX.md")
    updated_index = update_index(
        index_text, target.branch, target.commit, retrieved, len(source_docs)
    )
    _write_if_changed(index_path, updated_index.encode("utf-8"))
    license_path = target.checkout / "LICENSE.md"
    license_bytes = _read_bytes(license_path, "upstream LICENSE.md")
    notice = update_notice(
        target.repo, target.branch, target.commit, retrieved, license_bytes
    )
    _write_if_changed(candidate / "references" / "NOTICE.md", notice)
    return (
        len(source_docs),
        len(source_embeds),
        excluded_docs + excluded_embeds,
        warnings,
    )


def _move_tree_contents(candidate: Path, target: Path) -> None:
    for child in sorted(candidate.iterdir()):
        destination = target / child.name
        if os.path.lexists(destination):
            msg = f"target path appeared during apply: {destination}"
            raise ConflictError(msg)
        if child.is_symlink():
            msg = f"candidate tree contains symlink: {child}"
            raise UpdaterError(msg)
        if child.is_dir():
            destination.mkdir()
            _publish_candidate(child, destination)
        else:
            os.link(child, destination)
            child.unlink()
    candidate.rmdir()


def _publish_candidate(candidate: Path, target: Path) -> None:
    if not target.is_dir() or target.is_symlink():
        msg = f"target directory reservation is invalid: {target}"
        raise ConflictError(msg)
    try:
        _move_tree_contents(candidate, target)
    except (ConflictError, UpdaterError):
        raise
    except OSError as exc:
        msg = f"could not publish candidate tree: {target}"
        raise UpdaterError(msg) from exc


def _validate_source_dir(source_dir: Path) -> Path:
    source_dir = source_dir.expanduser()
    if source_dir.is_symlink():
        msg = f"source skill contains symlink: {source_dir}"
        raise UpdaterError(msg)
    try:
        source_dir = source_dir.resolve()
    except OSError as exc:
        msg = f"could not resolve source skill: {source_dir}"
        raise UpdaterError(msg) from exc
    if not source_dir.is_dir() or not (source_dir / "SKILL.md").is_file():
        msg = f"source skill directory is invalid: {source_dir}"
        raise UpdaterError(msg)
    _reject_symlinks(source_dir, "source skill")
    return source_dir


def _resolve_target_dir(
    source_dir: Path,
    target_dir: Path | None,
    skill_name: str,
    apply: bool,
) -> Path:
    requested_target = (target_dir or source_dir.parent / skill_name).expanduser()
    target_exists = os.path.lexists(requested_target)
    try:
        resolved = requested_target.resolve()
    except OSError as exc:
        msg = f"could not resolve target directory: {requested_target}"
        raise UpdaterError(msg) from exc
    if resolved.name != skill_name:
        msg = f"target directory must be named {skill_name}"
        raise UpdaterError(msg)
    if resolved == source_dir and apply:
        msg = "--apply cannot replace the source directory; use a sibling target"
        raise ConflictError(msg)
    if resolved != source_dir and target_exists:
        msg = f"target directory already exists: {resolved}"
        raise ConflictError(msg)
    if not resolved.parent.is_dir():
        msg = f"target parent directory does not exist: {resolved.parent}"
        raise UpdaterError(msg)
    return resolved


def _reserve_target_dir(target_dir: Path) -> None:
    try:
        target_dir.mkdir()
    except FileExistsError as exc:
        msg = f"target directory already exists: {target_dir}"
        raise ConflictError(msg) from exc
    except OSError as exc:
        msg = f"could not reserve target directory: {target_dir}"
        raise UpdaterError(msg) from exc


def _apply_candidate_tree(
    repo: str,
    branch: str,
    target: SourceInfo,
    candidate: Path,
    target_dir: Path,
) -> None:
    latest = _resolve_commit(repo, branch)
    if latest != target.commit:
        msg = (
            f"branch {branch} moved before apply; resolved "
            + f"{target.commit}, now {latest}"
        )
        raise UpdaterError(msg)
    if not os.path.lexists(target_dir) or target_dir.is_symlink():
        msg = f"target reservation disappeared: {target_dir}"
        raise ConflictError(msg)
    _publish_candidate(candidate, target_dir)


def _cleanup_reserved_dir(target_dir: Path) -> None:
    try:
        if (
            target_dir.is_dir()
            and not target_dir.is_symlink()
            and not any(target_dir.iterdir())
        ):
            target_dir.rmdir()
    except OSError:
        pass


def update(
    *,
    repo: str,
    branch: str,
    source_dir: Path,
    target_dir: Path | None,
    apply: bool,
) -> Summary:
    """Plan or apply a pinned release snapshot update."""
    if not RELEASE_RE.fullmatch(branch):
        msg = "--to-branch must match exactly YY.MM"
        raise UpdaterError(msg)
    validated_source = _validate_source_dir(source_dir)
    skill_name = f"nix-clan-{branch.replace('.', '')}"
    resolved_target = _resolve_target_dir(
        validated_source, target_dir, skill_name, apply
    )

    reserved = False
    if apply:
        _reserve_target_dir(resolved_target)
        reserved = True

    try:
        temp_parent = str(resolved_target.parent) if apply else None
        with tempfile.TemporaryDirectory(
            prefix=".nix-clan-update-", dir=temp_parent
        ) as work:
            target = resolve_source(repo, branch, Path(work))
            stage_root = Path(work) / "stage"
            candidate = stage_root / skill_name
            source_markdown, source_embeds, excluded, warnings = build_candidate(
                validated_source,
                target,
                candidate,
            )
            files = _file_deltas(validated_source, candidate)
            summary = Summary(
                branch=branch,
                release=branch,
                skill_name=skill_name,
                commit=target.commit,
                source_dir=str(validated_source),
                target_dir=str(resolved_target),
                applied=False,
                source_markdown=source_markdown,
                source_embeds=source_embeds,
                excluded=excluded,
                files=files,
                warnings=warnings,
                source_tree_sha256=_tree_digest(validated_source),
                candidate_tree_sha256=_tree_digest(candidate),
            )
            if apply:
                _apply_candidate_tree(repo, branch, target, candidate, resolved_target)
                reserved = False
                summary.applied = True
            return summary
    except OSError as exc:
        msg = "filesystem failure during update"
        raise UpdaterError(msg) from exc
    finally:
        if reserved:
            _cleanup_reserved_dir(resolved_target)


def render_summary(summary: Summary, as_json: bool) -> str:
    """Render a summary as JSON or human-readable CLI output."""
    if as_json:
        return json.dumps(summary.to_dict(), indent=2, sort_keys=True)
    counts: dict[str, int] = dict.fromkeys(
        ("added", "changed", "deleted", "unchanged"), 0
    )
    for delta in summary.files:
        counts[delta.status] += 1
    lines = [
        f"Clan {summary.release} @ {summary.commit}",
        f"source: {summary.source_dir}",
        f"target: {summary.target_dir} ({'applied' if summary.applied else 'dry-run'})",
        f"snapshot: {summary.source_markdown} Markdown, {summary.source_embeds} embeds",
        "files: " + ", ".join(f"{key}={value}" for key, value in counts.items()),
        f"source tree SHA-256: {summary.source_tree_sha256}",
        f"candidate tree SHA-256: {summary.candidate_tree_sha256}",
    ]
    lines.extend(
        f"  {delta.status:7} {delta.path}"
        for delta in summary.files
        if delta.status != "unchanged"
    )
    lines.extend(f"warning: {warning}" for warning in summary.warnings)
    if summary.excluded:
        lines.append("excluded: " + ", ".join(summary.excluded))
    return "\n".join(lines)
