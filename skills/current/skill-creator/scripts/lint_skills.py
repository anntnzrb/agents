# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Mechanical skill lint for the rules docs/skills.md states.

Dispatched via ``scripts/cli.py lint [<skill-dir> ...]``. Without arguments it
checks the skills under ``skills/current`` that differ from ``origin/main``,
including untracked files. Exit codes: 0 clean, 1 findings, 2 usage.
"""

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeIs

from scripts.frontmatter import read_frontmatter

EXIT_OK: Final[int] = 0
EXIT_FINDINGS: Final[int] = 1
EXIT_USAGE: Final[int] = 2

BASE_REF: Final[str] = "origin/main"
CURRENT_SKILLS: Final[str] = "skills/current"
LICENSE: Final[str] = "AGPL-3.0-or-later"
SKILL_MD_HARD_CAP: Final[int] = 250
READS_COLUMNS: Final[frozenset[str]] = frozenset({"Need", "Read", "When"})
READS_TABLE_MISSING: Final[str] = (
    "bundled docs exist but no follow-up reads table with Need, Read, When columns"
)
DASHES: Final[dict[str, str]] = {
    "\N{EN DASH}": "U+2013 en dash",
    "\N{EM DASH}": "U+2014 em dash",
}
# Root files that are not routed documentation.
_NOT_BUNDLED_DOCS: Final[frozenset[str]] = frozenset({"SKILL.md", "NOTICE.md"})
# Git's default core.whitespace checks; git diff --check reports these.
DEFAULT_WHITESPACE_RULES: Final[frozenset[str]] = frozenset(
    {"blank-at-eol", "blank-at-eof", "space-before-tab"}
)
_SKIP_DIRS: Final[frozenset[str]] = frozenset({"__pycache__", "node_modules"})
# skills/current/<name>: a changed path deeper than this belongs to one skill.
_SKILL_DEPTH: Final[int] = 3

_USAGE: Final[str] = "usage: cli.py lint [<skill-dir> ...]"
_FENCE: Final[re.Pattern[str]] = re.compile(r"^\s*(`{3,}|~{3,})")
_INLINE_CODE: Final[re.Pattern[str]] = re.compile(r"(`+)(?:.+?)(?<!`)\1(?!`)")
_LICENSE_LINE: Final[re.Pattern[str]] = re.compile(
    rf"^license:\s*[\"']?{re.escape(LICENSE)}[\"']?\s*$"
)


@dataclass(frozen=True, slots=True)
class Finding:
    """One rule violation at a file line."""

    path: Path
    line: int
    message: str


def _whitespace_rules(value: str) -> frozenset[str]:
    """Resolve a Git whitespace attribute value the way git diff --check does."""
    if value == "unset":
        return frozenset()
    rules = set(DEFAULT_WHITESPACE_RULES)
    if value in {"set", "unspecified"}:
        return frozenset(rules)
    for token in filter(None, (part.strip() for part in value.split(","))):
        name = token.removeprefix("-")
        names = {"blank-at-eol", "blank-at-eof"} if name == "trailing-space" else {name}
        rules = rules - names if token.startswith("-") else rules | names
    return frozenset(rules)


def _skill_files(skill_dir: Path) -> list[tuple[Path, frozenset[str]]]:
    """List publishable files with their whitespace rules.

    Inside Git, list tracked and unignored files and honor the ``whitespace``
    attribute; outside Git, list every non-hidden file with the default rules.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=skill_dir,
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        return [
            (path, DEFAULT_WHITESPACE_RULES)
            for path in sorted(skill_dir.rglob("*"))
            if path.is_file()
            and not any(
                part.startswith(".") or part in _SKIP_DIRS
                for part in path.relative_to(skill_dir).parts
            )
        ]
    names = [
        name
        for name in listed.stdout.decode("utf-8", "surrogateescape").split("\0")
        if name and (skill_dir / name).is_file()
    ]
    attrs = subprocess.run(
        ["git", "check-attr", "-z", "--stdin", "whitespace"],
        cwd=skill_dir,
        input="".join(f"{name}\0" for name in names).encode("utf-8", "surrogateescape"),
        capture_output=True,
        check=True,
    )
    fields = attrs.stdout.decode("utf-8", "surrogateescape").split("\0")
    values = dict(zip(fields[0::3], fields[2::3], strict=False))
    return sorted(
        (skill_dir / name, _whitespace_rules(values.get(name, "unspecified")))
        for name in names
    )


def _read_text(path: Path) -> str | None:
    """Return file text, or None for binary or non-UTF-8 content."""
    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _whitespace(path: Path, text: str, rules: frozenset[str]) -> list[Finding]:
    """Report what git diff --check reports, plus a missing final newline."""
    findings: list[Finding] = []
    lines = text.split("\n")
    for number, line in enumerate(lines[:-1], start=1):
        if "blank-at-eol" in rules and line != line.rstrip(" \t\r"):
            findings.append(Finding(path, number, "trailing whitespace"))
        indent = line[: len(line) - len(line.lstrip(" \t"))]
        if "space-before-tab" in rules and " \t" in indent:
            findings.append(Finding(path, number, "space before tab in indent"))
    if not text or "blank-at-eof" not in rules:
        return findings
    if lines[-1]:
        findings.append(Finding(path, len(lines), "no newline at end of file"))
        return findings
    blank = len(lines) - 1
    while blank > 0 and not lines[blank - 1].strip():
        blank -= 1
    if blank < len(lines) - 1:
        findings.append(Finding(path, blank + 1, "blank line at end of file"))
    return findings


def _prose_lines(text: str) -> list[tuple[int, str]]:
    """Yield numbered Markdown lines outside fences, with inline code removed."""
    prose: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        match = _FENCE.match(line)
        if fence is None:
            if match:
                fence = match.group(1)
                continue
            prose.append((number, _INLINE_CODE.sub("", line)))
        elif (
            match
            and match.group(1)[0] == fence[0]
            and len(match.group(1)) >= len(fence)
            and not line.strip().lstrip(fence[0])
        ):
            fence = None
    return prose


def _dashes(path: Path, text: str) -> list[Finding]:
    return [
        Finding(path, number, f"{name} in Markdown prose")
        for number, line in _prose_lines(text)
        for char, name in DASHES.items()
        if char in line
    ]


def _frontmatter(text: str) -> list[str]:
    return list(read_frontmatter(text).lines)


def _has_reads_table(text: str) -> bool:
    for _, line in _prose_lines(text):
        if line.lstrip().startswith("|"):
            cells = {cell.strip() for cell in line.split("|")}
            if cells >= READS_COLUMNS:
                return True
    return False


def _is_str_dict(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict)


def _port_notice(skill_md: Path, text: str) -> list[Finding]:
    """Require preserved notices for ports identified by YAML metadata."""
    result = read_frontmatter(text)
    if result.yaml_error:
        return [Finding(skill_md, 1, "invalid YAML in frontmatter")]
    frontmatter = result.metadata
    if frontmatter is None:
        return []
    metadata = frontmatter.get("metadata")
    if not _is_str_dict(metadata):
        return []
    port = "upstream" in metadata or (
        "author" in metadata and metadata["author"] != "anntnzrb"
    )
    if not port or any(
        (skill_md.parent / notice).is_file()
        for notice in ("NOTICE.md", "references/NOTICE.md")
    ):
        return []
    return [
        Finding(
            skill_md,
            1,
            "port metadata requires NOTICE.md at skill root or references/",
        )
    ]


def _skill_md(skill_md: Path, text: str, *, bundled_docs: bool) -> list[Finding]:
    findings = _port_notice(skill_md, text)
    if not any(_LICENSE_LINE.match(line) for line in _frontmatter(text)):
        findings.append(Finding(skill_md, 1, f"frontmatter lacks license: {LICENSE}"))
    if not bundled_docs:
        return findings
    if not _has_reads_table(text):
        findings.append(
            Finding(
                skill_md,
                1,
                READS_TABLE_MISSING,
            )
        )
    count = len(text.splitlines())
    if count > SKILL_MD_HARD_CAP:
        findings.append(
            Finding(
                skill_md,
                SKILL_MD_HARD_CAP + 1,
                f"SKILL.md has {count} lines; hard cap is {SKILL_MD_HARD_CAP}",
            )
        )
    return findings


def lint_skill(skill_dir: Path) -> list[Finding]:
    """Check one skill directory against the mechanical skill-gate rules."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return [Finding(skill_md, 1, "SKILL.md not found")]
    findings: list[Finding] = []
    bundled_docs = False
    for path, rules in _skill_files(skill_dir):
        rel = path.relative_to(skill_dir)
        if path.suffix == ".md" and rel.as_posix() not in _NOT_BUNDLED_DOCS:
            bundled_docs = True
        text = _read_text(path)
        if text is None:
            continue
        findings.extend(_whitespace(path, text, rules))
        if path.suffix == ".md":
            findings.extend(_dashes(path, text))
    text = skill_md.read_text(encoding="utf-8")
    findings.extend(_skill_md(skill_md, text, bundled_docs=bundled_docs))
    upstream = skill_dir / "UPSTREAM.json"
    if upstream.is_file() and not (skill_dir / "NOTICE.md").is_file():
        findings.append(
            Finding(upstream, 1, "UPSTREAM.json exists but NOTICE.md is missing")
        )
    return findings


class _UsageError(Exception):
    """Raised for bad arguments or an unusable Git checkout."""


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, check=False
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise _UsageError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.decode("utf-8", "surrogateescape")


def _git_names(cwd: Path, command: str, *args: str) -> list[str]:
    return [name for name in _git(cwd, command, "-z", *args).split("\0") if name]


def changed_skills(cwd: Path) -> list[Path]:
    """Return current skills that differ from origin/main or hold untracked files."""
    top = Path(_git(cwd, "rev-parse", "--show-toplevel").strip())
    names = _git_names(top, "diff", "--name-only", "--merge-base", BASE_REF)
    names += _git_names(
        top, "ls-files", "--others", "--exclude-standard", "--", CURRENT_SKILLS
    )
    skills: set[Path] = set()
    for name in names:
        parts = Path(name).parts
        if len(parts) > _SKILL_DEPTH and "/".join(parts[:2]) == CURRENT_SKILLS:
            skill = top.joinpath(*parts[:_SKILL_DEPTH])
            if skill.is_dir():
                skills.add(skill)
    return sorted(skills)


def _display(path: Path) -> Path:
    try:
        return path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return path


def main(argv: list[str]) -> int:
    """Lint the given skills, or the changed ones; return the exit code."""
    if any(arg in {"-h", "--help"} for arg in argv):
        print(_USAGE)
        return EXIT_OK
    try:
        if unknown := [arg for arg in argv if arg.startswith("-")]:
            raise _UsageError(f"unknown option: {unknown[0]}")
        if argv:
            skills = [Path(arg) for arg in argv]
            if missing := [str(path) for path in skills if not path.is_dir()]:
                raise _UsageError(f"not a directory: {', '.join(missing)}")
        else:
            skills = [_display(path) for path in changed_skills(Path.cwd())]
            if not skills:
                print(f"No skills under {CURRENT_SKILLS} differ from {BASE_REF}.")
                return EXIT_OK
    except _UsageError as exc:
        print(f"{exc}\n{_USAGE}", file=sys.stderr)
        return EXIT_USAGE
    findings = [finding for skill in skills for finding in lint_skill(skill)]
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.message}")
    if findings:
        return EXIT_FINDINGS
    print(f"Linted {len(skills)} skill(s): no findings.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
