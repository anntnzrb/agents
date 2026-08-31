"""Diff parsing, model-boundary validation, and patch selection."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from expression import Error, Ok, Result

from autommit.errors import AutommitError

MAX_COMMITS = 16
MAX_CHANGES_PER_COMMIT = 128
MAX_DETAILS = 32
MAX_SUMMARY_LENGTH = 512
MAX_DETAIL_LENGTH = 2_000
MAX_PATH_LENGTH = 4_096
MAX_CONCERNS = 8
MAX_CONCERN_LENGTH = 512
MAX_RATIONALE_LENGTH = 2_000


@dataclass(frozen=True, slots=True)
class DiffHunk:
    """One 1-based hunk in a unified diff."""

    index: int
    new_start: int
    new_lines: int
    content: str


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """One file section in a Git diff."""

    filename: str
    is_binary: bool
    content: str
    hunks: tuple[DiffHunk, ...]


@dataclass(frozen=True, slots=True)
class AllSelector:
    """Select an entire file diff."""

    type: Literal["all"] = "all"


@dataclass(frozen=True, slots=True)
class IndicesSelector:
    """Select 1-based hunk indices."""

    indices: tuple[int, ...]
    type: Literal["indices"] = "indices"


@dataclass(frozen=True, slots=True)
class LinesSelector:
    """Select an inclusive range of changed new-file lines."""

    start: int
    end: int
    type: Literal["lines"] = "lines"


HunkSelector = AllSelector | IndicesSelector | LinesSelector


@dataclass(frozen=True, slots=True)
class CommitChange:
    """One path and selector assigned to a commit."""

    path: str
    hunks: HunkSelector


@dataclass(frozen=True, slots=True)
class CommitGroup:
    """One proposed commit."""

    summary: str
    details: tuple[str, ...]
    changes: tuple[CommitChange, ...]


@dataclass(frozen=True, slots=True)
class CommitProposal:
    """The complete partition of a staged snapshot."""

    commits: tuple[CommitGroup, ...]


@dataclass(frozen=True, slots=True)
class AtomicityDecision:
    """A critic's decision for a broad single-commit proposal."""

    decision: Literal["accept", "split"]
    concerns: tuple[str, ...]
    rationale: str


def _invalid(message: str) -> AutommitError:
    return AutommitError("invalid_plan", f"Invalid autommit proposal: {message}")


def _mapping(value: object, field: str) -> Result[dict[str, object], AutommitError]:
    if not isinstance(value, dict):
        return Error(_invalid(f"{field} must be an object"))
    raw = cast("dict[object, object]", value)
    if any(not isinstance(key, str) for key in raw):
        return Error(_invalid(f"{field} keys must be strings"))
    return Ok({key: item for key, item in raw.items() if isinstance(key, str)})


def _record(
    value: object, field: str, keys: frozenset[str]
) -> Result[dict[str, object], AutommitError]:
    match _mapping(value, field):
        case Result(tag="ok", ok=record):
            if frozenset(record) != keys:
                expected = ", ".join(sorted(keys))
                return Error(_invalid(f"{field} must contain exactly: {expected}"))
            return Ok(record)
        case Result(error=err):
            return Error(err)
        case _:
            return Error(_invalid(f"{field} must be an object"))


def _list(value: object, field: str) -> Result[list[object], AutommitError]:
    if not isinstance(value, list):
        return Error(_invalid(f"{field} must be an array"))
    return Ok(cast("list[object]", value))


def _bounded_text(
    value: object, field: str, maximum: int
) -> Result[str, AutommitError]:
    if not isinstance(value, str):
        return Error(_invalid(f"{field} must be a string"))
    text = value.strip()
    if not text or len(text) > maximum or re.search(r"[\x00-\x1f\x7f]", text):
        return Error(_invalid(f"{field} must be non-empty, bounded text"))
    return Ok(text)


def _normalize_path(value: object) -> Result[str, AutommitError]:
    match _bounded_text(value, "change.path", MAX_PATH_LENGTH):
        case Result(tag="ok", ok=path):
            if (
                path.startswith(("/", "\\"))
                or "\\" in path
                or path in {".", ".."}
                or ".." in path.split("/")
            ):
                return Error(_invalid(f"unsupported change path: {path}"))
            return Ok(path)
        case Result(error=err):
            return Error(err)
        case _:
            return Error(_invalid("change.path must be a string"))


def _integer(value: object, field: str, minimum: int = 1) -> Result[int, AutommitError]:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        return Error(_invalid(f"{field} must be an integer >= {minimum}"))
    return Ok(value)


def _normalize_selector(value: object) -> Result[HunkSelector, AutommitError]:
    if value == "all":
        return Ok(AllSelector())
    match _mapping(value, "change.hunks"):
        case Result(tag="ok", ok=selector_mapping):
            selector_type = selector_mapping.get("type")
            if selector_type == "all":
                match _record(selector_mapping, "all selector", frozenset({"type"})):
                    case Result(tag="ok"):
                        return Ok(AllSelector())
                    case Result(error=err):
                        return Error(err)
                    case _:
                        return Error(_invalid("invalid all selector"))
            if selector_type == "indices":
                match _record(
                    selector_mapping,
                    "indices selector",
                    frozenset({"type", "indices"}),
                ):
                    case Result(tag="ok", ok=selector):
                        match _list(selector["indices"], "indices selector indices"):
                            case Result(tag="ok", ok=indices_items):
                                if not indices_items:
                                    return Error(
                                        _invalid(
                                            "indices selector must contain a non-empty array"
                                        )
                                    )
                                indices: list[int] = []
                                for item in indices_items:
                                    match _integer(item, "hunk index"):
                                        case Result(tag="ok", ok=idx):
                                            indices.append(idx)
                                        case Result(error=err):
                                            return Error(err)
                                        case _:
                                            return Error(_invalid("invalid hunk index"))
                                if len(set(indices)) != len(indices):
                                    return Error(
                                        _invalid("hunk indices must be unique")
                                    )
                                return Ok(IndicesSelector(tuple(sorted(indices))))
                            case Result(error=err):
                                return Error(err)
                            case _:
                                return Error(_invalid("indices must be an array"))
                    case Result(error=err):
                        return Error(err)
                    case _:
                        return Error(_invalid("invalid indices selector"))
            if selector_type == "lines":
                match _record(
                    selector_mapping,
                    "lines selector",
                    frozenset({"type", "start", "end"}),
                ):
                    case Result(tag="ok", ok=selector):
                        match _integer(selector["start"], "line selector start"):
                            case Result(tag="ok", ok=start):
                                match _integer(selector["end"], "line selector end"):
                                    case Result(tag="ok", ok=end):
                                        if end < start:
                                            return Error(
                                                _invalid(
                                                    "line selectors require start <= end"
                                                )
                                            )
                                        return Ok(LinesSelector(start, end))
                                    case Result(error=err):
                                        return Error(err)
                                    case _:
                                        return Error(
                                            _invalid("invalid line selector end")
                                        )
                            case Result(error=err):
                                return Error(err)
                            case _:
                                return Error(_invalid("invalid line selector start"))
                    case Result(error=err):
                        return Error(err)
                    case _:
                        return Error(_invalid("invalid lines selector"))
            return Error(_invalid("change.hunks must be all, indices, or lines"))
        case Result(error=err):
            return Error(err)
        case _:
            return Error(_invalid("change.hunks must be an object or 'all'"))


def normalize_proposal(value: object) -> Result[CommitProposal, AutommitError]:
    """Validate and normalize an untrusted proposal JSON value."""
    match _record(value, "proposal", frozenset({"commits"})):
        case Result(tag="ok", ok=root):
            match _list(root["commits"], "commits"):
                case Result(tag="ok", ok=commits_items):
                    if not 1 <= len(commits_items) <= MAX_COMMITS:
                        return Error(
                            _invalid(
                                f"commits must contain between 1 and {MAX_COMMITS} entries"
                            )
                        )
                    commits: list[CommitGroup] = []
                    for commit_index, raw_commit in enumerate(commits_items, start=1):
                        match _mapping(raw_commit, f"commit {commit_index}"):
                            case Result(tag="ok", ok=commit):
                                allowed_keys = {"summary", "changes", "details"}
                                if set(commit) - allowed_keys or not {
                                    "summary",
                                    "changes",
                                } <= set(commit):
                                    return Error(
                                        _invalid(
                                            f"commit {commit_index} must contain summary, changes, and optional details"
                                        )
                                    )
                                match _bounded_text(
                                    commit["summary"],
                                    f"commit {commit_index} summary",
                                    MAX_SUMMARY_LENGTH,
                                ):
                                    case Result(tag="ok", ok=summary):
                                        match _list(
                                            commit.get("details", []),
                                            f"commit {commit_index} details",
                                        ):
                                            case Result(tag="ok", ok=details_items):
                                                if len(details_items) > MAX_DETAILS:
                                                    return Error(
                                                        _invalid(
                                                            f"commit {commit_index} details must contain at most {MAX_DETAILS} items"
                                                        )
                                                    )
                                                details: list[str] = []
                                                for (
                                                    detail_index,
                                                    detail,
                                                ) in enumerate(details_items, start=1):
                                                    match _bounded_text(
                                                        detail,
                                                        f"commit {commit_index} detail {detail_index}",
                                                        MAX_DETAIL_LENGTH,
                                                    ):
                                                        case Result(tag="ok", ok=txt):
                                                            details.append(txt)
                                                        case Result(error=err):
                                                            return Error(err)
                                                        case _:
                                                            return Error(
                                                                _invalid(
                                                                    "invalid detail text"
                                                                )
                                                            )
                                                match _list(
                                                    commit["changes"],
                                                    f"commit {commit_index} changes",
                                                ):
                                                    case Result(
                                                        tag="ok", ok=changes_items
                                                    ):
                                                        if (
                                                            not 1
                                                            <= len(changes_items)
                                                            <= MAX_CHANGES_PER_COMMIT
                                                        ):
                                                            return Error(
                                                                _invalid(
                                                                    f"commit {commit_index} must contain between 1 and "
                                                                    f"{MAX_CHANGES_PER_COMMIT} changes"
                                                                )
                                                            )
                                                        changes: list[CommitChange] = []
                                                        seen_paths: set[str] = set()
                                                        for raw_change in changes_items:
                                                            match _record(
                                                                raw_change,
                                                                f"commit {commit_index} change",
                                                                frozenset(
                                                                    {
                                                                        "path",
                                                                        "hunks",
                                                                    }
                                                                ),
                                                            ):
                                                                case Result(
                                                                    tag="ok",
                                                                    ok=change,
                                                                ):
                                                                    match (
                                                                        _normalize_path(
                                                                            change[
                                                                                "path"
                                                                            ]
                                                                        )
                                                                    ):
                                                                        case Result(
                                                                            tag="ok",
                                                                            ok=path,
                                                                        ):
                                                                            if (
                                                                                path
                                                                                in seen_paths
                                                                            ):
                                                                                return Error(
                                                                                    _invalid(
                                                                                        f"commit {commit_index} lists {path} more than once"
                                                                                    )
                                                                                )
                                                                            seen_paths.add(
                                                                                path
                                                                            )
                                                                            match _normalize_selector(
                                                                                change[
                                                                                    "hunks"
                                                                                ]
                                                                            ):
                                                                                case Result(
                                                                                    tag="ok",
                                                                                    ok=selector,
                                                                                ):
                                                                                    changes.append(
                                                                                        CommitChange(
                                                                                            path,
                                                                                            selector,
                                                                                        )
                                                                                    )
                                                                                case Result(
                                                                                    error=err
                                                                                ):
                                                                                    return Error(
                                                                                        err
                                                                                    )
                                                                                case _:
                                                                                    return Error(
                                                                                        _invalid(
                                                                                            "invalid change selector"
                                                                                        )
                                                                                    )
                                                                        case Result(
                                                                            error=err
                                                                        ):
                                                                            return (
                                                                                Error(
                                                                                    err
                                                                                )
                                                                            )
                                                                        case _:
                                                                            return Error(
                                                                                _invalid(
                                                                                    "invalid change path"
                                                                                )
                                                                            )
                                                                case Result(error=err):
                                                                    return Error(err)
                                                                case _:
                                                                    return Error(
                                                                        _invalid(
                                                                            "invalid change record"
                                                                        )
                                                                    )
                                                        commits.append(
                                                            CommitGroup(
                                                                summary,
                                                                tuple(details),
                                                                tuple(changes),
                                                            )
                                                        )
                                                    case Result(error=err):
                                                        return Error(err)
                                                    case _:
                                                        return Error(
                                                            _invalid(
                                                                "changes must be an array"
                                                            )
                                                        )
                                            case Result(error=err):
                                                return Error(err)
                                            case _:
                                                return Error(
                                                    _invalid("details must be an array")
                                                )
                                    case Result(error=err):
                                        return Error(err)
                                    case _:
                                        return Error(
                                            _invalid("summary must be a string")
                                        )
                            case Result(error=err):
                                return Error(err)
                            case _:
                                return Error(_invalid("commit must be an object"))
                    return Ok(CommitProposal(tuple(commits)))
                case Result(error=err):
                    return Error(err)
                case _:
                    return Error(_invalid("commits must be an array"))
        case Result(error=err):
            return Error(err)
        case _:
            return Error(_invalid("proposal must be an object"))


def read_json_file(path: Path, kind: str) -> Result[object, AutommitError]:
    """Read one bounded UTF-8 JSON document."""
    try:
        size = path.stat().st_size
        if size > 1024 * 1024:
            return Error(
                AutommitError("invalid_json", f"{kind} exceeds the 1 MiB limit.")
            )
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return Error(
            AutommitError("invalid_json", f"Unable to read {kind} {path}: {error}")
        )
    try:
        return Ok(json.loads(text))
    except json.JSONDecodeError as error:
        return Error(AutommitError("invalid_json", f"Invalid {kind} JSON: {error}"))


def normalize_atomicity_decision(
    value: object,
) -> Result[AtomicityDecision, AutommitError]:
    """Validate a critic result at the model boundary."""
    match _record(
        value,
        "atomicity decision",
        frozenset({"decision", "concerns", "rationale"}),
    ):
        case Result(tag="ok", ok=decision_record):
            decision_value = decision_record["decision"]
            concerns_value = decision_record["concerns"]
            rationale_value = decision_record["rationale"]
            if decision_value not in {"accept", "split"} or not isinstance(
                decision_value, str
            ):
                return Error(
                    AutommitError(
                        "invalid_atomicity_decision",
                        "Invalid atomicity decision value.",
                    )
                )
            if not isinstance(concerns_value, list):
                return Error(
                    AutommitError(
                        "invalid_atomicity_decision",
                        "Invalid atomicity concerns.",
                    )
                )
            concern_items = cast("list[object]", concerns_value)
            if len(concern_items) > MAX_CONCERNS:
                return Error(
                    AutommitError(
                        "invalid_atomicity_decision",
                        "Invalid atomicity concerns.",
                    )
                )
            concerns: list[str] = []
            for concern in concern_items:
                if not isinstance(concern, str):
                    return Error(
                        AutommitError(
                            "invalid_atomicity_decision",
                            "Invalid atomicity concern.",
                        )
                    )
                normalized = concern.strip()
                if not normalized or len(normalized) > MAX_CONCERN_LENGTH:
                    return Error(
                        AutommitError(
                            "invalid_atomicity_decision",
                            "Invalid atomicity concern.",
                        )
                    )
                concerns.append(normalized)
            if not isinstance(rationale_value, str):
                return Error(
                    AutommitError(
                        "invalid_atomicity_decision",
                        "Invalid atomicity rationale.",
                    )
                )
            rationale = rationale_value.strip()
            if not rationale or len(rationale) > MAX_RATIONALE_LENGTH:
                return Error(
                    AutommitError(
                        "invalid_atomicity_decision",
                        "Invalid atomicity rationale.",
                    )
                )
            if decision_value == "accept" and concerns:
                return Error(
                    AutommitError(
                        "invalid_atomicity_decision",
                        "An accept decision cannot contain concerns.",
                    )
                )
            if decision_value == "split" and (
                len(concerns) < 2 or len(set(concerns)) != len(concerns)
            ):
                return Error(
                    AutommitError(
                        "invalid_atomicity_decision",
                        "A split decision requires at least two distinct concerns.",
                    )
                )
            decision = cast("Literal['accept', 'split']", decision_value)
            return Ok(AtomicityDecision(decision, tuple(concerns), rationale))
        case _:
            return Error(
                AutommitError(
                    "invalid_atomicity_decision",
                    "Invalid atomicity decision: expected exactly decision, concerns, and rationale.",
                )
            )


def _decode_git_path_token(value: str, start: int) -> tuple[str, int]:
    if start >= len(value):
        return "", start
    if value[start] != '"':
        end = value.find(" ", start)
        if end < 0:
            end = len(value)
        return value[start:end], end
    data = bytearray()
    index = start + 1
    escapes = {
        "a": 7,
        "b": 8,
        "t": 9,
        "n": 10,
        "v": 11,
        "f": 12,
        "r": 13,
        "\\": 92,
        '"': 34,
    }
    while index < len(value):
        character = value[index]
        if character == '"':
            return data.decode("utf-8", errors="surrogateescape"), index + 1
        if character != "\\":
            data.extend(character.encode("utf-8", errors="surrogateescape"))
            index += 1
            continue
        index += 1
        if index >= len(value):
            break
        escaped = value[index]
        if escaped in escapes:
            data.append(escapes[escaped])
            index += 1
            continue
        if escaped in "01234567":
            octal = escaped
            index += 1
            while index < len(value) and len(octal) < 3 and value[index] in "01234567":
                octal += value[index]
                index += 1
            data.append(int(octal, 8))
            continue
        data.extend(escaped.encode("utf-8", errors="surrogateescape"))
        index += 1
    raise AutommitError("invalid_diff", "Unterminated quoted path in Git diff.", 4)


def _decode_git_path(value: str) -> str:
    if not value.startswith('"'):
        return value.split("\t", 1)[0]
    decoded, end = _decode_git_path_token(value, 0)
    if value[end:] and not value[end:].startswith("\t"):
        raise AutommitError("invalid_diff", "Unexpected text after quoted Git path.", 4)
    return decoded


def _diff_filename(header: str, content: str) -> str:
    prefix = "diff --git "
    if not header.startswith(prefix):
        raise AutommitError("invalid_diff", "Invalid Git diff header.", 4)

    old_path = ""
    for line in content.splitlines()[1:]:
        if line.startswith("rename to "):
            return _decode_git_path(line.removeprefix("rename to "))
        if line.startswith("--- "):
            old_path = _decode_git_path(line.removeprefix("--- "))
        if line.startswith("+++ "):
            new_path = _decode_git_path(line.removeprefix("+++ "))
            if new_path != "/dev/null":
                return re.sub(r"^[a-z]/", "", new_path)
    if old_path and old_path != "/dev/null":
        return re.sub(r"^[a-z]/", "", old_path)

    remainder = header[len(prefix) :]
    if remainder.startswith('"'):
        _, cursor = _decode_git_path_token(remainder, 0)
        while cursor < len(remainder) and remainder[cursor] == " ":
            cursor += 1
        second, _ = _decode_git_path_token(remainder, cursor)
    else:
        separator = remainder.rfind(" ")
        if separator < 0:
            raise AutommitError("invalid_diff", "Invalid Git diff paths.", 4)
        second = remainder[separator + 1 :]
    return re.sub(r"^[a-z]/", "", second)


def parse_file_diffs(diff_text: str) -> tuple[ParsedFile, ...]:
    """Parse file sections and assign 1-based hunk indices."""
    starts = [match.start() for match in re.finditer(r"(?m)^diff --git ", diff_text)]
    files: list[ParsedFile] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(diff_text)
        content = diff_text[start:end]
        header_end = content.find("\n")
        if header_end < 0:
            continue
        filename = _diff_filename(content[:header_end], content)
        hunk_matches = list(
            re.finditer(r"(?m)^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@.*$", content)
        )
        hunks: list[DiffHunk] = []
        for hunk_index, match in enumerate(hunk_matches, start=1):
            hunk_end = (
                hunk_matches[hunk_index].start()
                if hunk_index < len(hunk_matches)
                else len(content)
            )
            hunks.append(
                DiffHunk(
                    hunk_index,
                    int(match.group(1)),
                    int(match.group(2)) if match.group(2) is not None else 1,
                    content[match.start() : hunk_end].rstrip("\n"),
                )
            )
        body = content[header_end + 1 :]
        is_binary = not hunks and (
            "Binary files " in body or "GIT binary patch" in body
        )
        files.append(
            ParsedFile(filename, is_binary, content.rstrip("\n"), tuple(hunks))
        )
    return tuple(files)


def _selections_overlap(left: HunkSelector, right: HunkSelector) -> bool:
    match (left, right):
        case (AllSelector(), _) | (_, AllSelector()):
            return True
        case (IndicesSelector(indices=left_idx), IndicesSelector(indices=right_idx)):
            return bool(set(left_idx) & set(right_idx))
        case (
            LinesSelector(start=l_start, end=l_end),
            LinesSelector(start=r_start, end=r_end),
        ):
            return l_start <= r_end and r_start <= l_end
        case _:
            return True


def _describe_selector(selector: HunkSelector) -> str:
    match selector:
        case AllSelector():
            return "all"
        case IndicesSelector(indices=indices):
            return f"hunks {','.join(str(index) for index in indices)}"
        case LinesSelector(start=start, end=end):
            return f"new-file lines {start}-{end}"


def _changed_new_lines(hunk: DiffHunk) -> tuple[int, ...]:
    lines = hunk.content.splitlines()[1:]
    changed: list[int] = []
    new_line = hunk.new_start
    for line in lines:
        marker = line[:1]
        if marker == "+":
            changed.append(new_line)
            new_line += 1
        elif marker == " ":
            new_line += 1
    return tuple(changed) or (hunk.new_start,)


def _selector_intersects_hunk(selector: HunkSelector, hunk: DiffHunk) -> bool:
    match selector:
        case AllSelector():
            return True
        case IndicesSelector(indices=indices):
            return hunk.index in indices
        case LinesSelector(start=start, end=end):
            hunk_end = (
                hunk.new_start
                if hunk.new_lines == 0
                else hunk.new_start + hunk.new_lines - 1
            )
            return hunk.new_start <= end and start <= hunk_end


def validate_proposal_coverage(
    proposal: CommitProposal,
    staged_files: tuple[str, ...],
    parsed_files: tuple[ParsedFile, ...],
) -> tuple[str, ...]:
    """Require every staged change exactly once overall."""
    staged_set = set(staged_files)
    selections_by_file: dict[str, list[HunkSelector]] = {}
    errors: list[str] = []
    for commit_index, commit in enumerate(proposal.commits, start=1):
        for change in commit.changes:
            if change.path not in staged_set:
                errors.append(
                    f"Commit {commit_index}: file is not staged: {change.path}"
                )
                continue
            selections_by_file.setdefault(change.path, []).append(change.hunks)
    for filename in staged_files:
        if filename not in selections_by_file:
            errors.append(f"Staged file missing from split plan: {filename}")
    files_by_name = {file.filename: file for file in parsed_files}
    for filename, selections in selections_by_file.items():
        for left_index, left in enumerate(selections):
            if any(
                _selections_overlap(left, right)
                for right in selections[left_index + 1 :]
            ):
                errors.append(
                    "Overlapping hunk selections across commits: "
                    f"{filename} ({_describe_selector(left)} overlaps another selection); "
                    "line ranges are inclusive and must be disjoint"
                )
                break
        parsed = files_by_name.get(filename)
        if parsed is None:
            errors.append(f"No staged diff found for {filename}")
            continue
        if parsed.is_binary and any(
            not isinstance(item, AllSelector) for item in selections
        ):
            errors.append(f"Binary file cannot be partially selected: {filename}")
        if not parsed.hunks and any(
            not isinstance(item, AllSelector) for item in selections
        ):
            errors.append(
                f"Metadata-only file cannot be partially selected: {filename}"
            )
        for hunk in parsed.hunks:
            covered = all(
                any(
                    selector.start <= line <= selector.end
                    if isinstance(selector, LinesSelector)
                    else _selector_intersects_hunk(selector, hunk)
                    for selector in selections
                )
                for line in _changed_new_lines(hunk)
            )
            if not covered:
                errors.append(
                    f"Staged hunk missing from split plan: {filename} (hunk {hunk.index})"
                )
    return tuple(dict.fromkeys(errors))


def select_patch(
    file: ParsedFile, selector: HunkSelector
) -> Result[str, AutommitError]:
    """Select one whole file or a subset of its hunks."""
    if file.is_binary and not isinstance(selector, AllSelector):
        return Error(
            AutommitError(
                "invalid_plan",
                f"Cannot partially select binary file {file.filename}.",
            )
        )
    if isinstance(selector, AllSelector):
        return Ok(file.content)
    if isinstance(selector, IndicesSelector):
        hunks = tuple(hunk for hunk in file.hunks if hunk.index in selector.indices)
    else:
        hunks = tuple(
            hunk
            for hunk in file.hunks
            if hunk.new_start <= selector.end
            and selector.start
            <= (
                hunk.new_start
                if hunk.new_lines == 0
                else hunk.new_start + hunk.new_lines - 1
            )
        )
    if not hunks:
        return Error(
            AutommitError("invalid_plan", f"No changes selected for {file.filename}.")
        )
    first_hunk = file.content.find("\n@@")
    header = file.content if first_hunk < 0 else file.content[:first_hunk]
    return Ok("\n".join((header, *(hunk.content for hunk in hunks))))


def build_commit_patch(
    changes: tuple[CommitChange, ...],
    staged_diff: str,
    zero_context_diff: str,
) -> Result[str, AutommitError]:
    """Build one patch from normalized commit changes."""
    regular_files = {file.filename: file for file in parse_file_diffs(staged_diff)}
    zero_files = {file.filename: file for file in parse_file_diffs(zero_context_diff)}
    parts: list[str] = []
    for change in changes:
        files = zero_files if isinstance(change.hunks, LinesSelector) else regular_files
        file = files.get(change.path)
        if file is None:
            return Error(
                AutommitError(
                    "invalid_plan", f"No staged diff found for {change.path}."
                )
            )
        match select_patch(file, change.hunks):
            case Result(tag="ok", ok=patch_part):
                parts.append(patch_part)
            case Result(error=err):
                return Error(err)
            case _:
                return Error(
                    AutommitError(
                        "invalid_plan",
                        f"Failed to select patch for {change.path}.",
                    )
                )
    return Ok("\n".join(parts) + "\n")


def changed_hunk_count(diff_text: str) -> int:
    """Count changed hunks across the staged diff."""
    return sum(len(file.hunks) for file in parse_file_diffs(diff_text))


def requires_atomicity_review(
    proposal: CommitProposal,
    staged_file_count: int,
    diff_text: str,
) -> bool:
    """Match the Pi command's narrow-proposal critic bypass."""
    if len(proposal.commits) != 1:
        return False
    group = proposal.commits[0]
    return not (
        staged_file_count == 1
        and changed_hunk_count(diff_text) <= 1
        and len(group.details) <= 1
    )
