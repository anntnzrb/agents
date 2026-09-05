"""Parse and validate untrusted LLM commit proposals."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, cast

from expression import Error, Ok, Result

from autommit.errors import AutommitError

MAX_COMMITS = 16
MAX_CHANGES_PER_COMMIT = 128
MAX_DETAILS = 32
MAX_SUMMARY_LENGTH = 512
MAX_DETAIL_LENGTH = 2048
MAX_PATH_LENGTH = 4096
MAX_CONCERN_LENGTH = 512
MAX_RATIONALE_LENGTH = 2048
_MIN_SPLIT_COMMITS = 27
MAX_OCTAL_DIGITS = 3


@dataclass(frozen=True, slots=True)
class DiffHunk:
    """One 1-based hunk in a unified diff."""

    index: int
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    content: str


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """Parsed file section in a Git diff."""

    filename: str
    is_binary: bool
    content: str
    hunks: tuple[DiffHunk, ...]


@dataclass(frozen=True, slots=True)
class AllSelector:
    """Select an entire file change."""


@dataclass(frozen=True, slots=True)
class IndicesSelector:
    """Select 1-based hunk indices in a diff."""

    indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class LinesSelector:
    """Select 1-based inclusive new-file line ranges."""

    start: int
    end: int


type HunkSelector = AllSelector | IndicesSelector | LinesSelector


@dataclass(frozen=True, slots=True)
class CommitChange:
    """One file or hunk selection inside a commit."""

    path: str
    hunks: HunkSelector


@dataclass(frozen=True, slots=True)
class CommitGroup:
    """One atomic commit specification."""

    summary: str
    details: tuple[str, ...]
    changes: tuple[CommitChange, ...]


@dataclass(frozen=True, slots=True)
class CommitProposal:
    """Normalized multi-commit plan."""

    commits: tuple[CommitGroup, ...]


@dataclass(frozen=True, slots=True)
class AtomicityDecision:
    """Normalized critic verdict."""

    decision: Literal["accept", "split"]
    concerns: tuple[str, ...]
    rationale: str


def _invalid(message: str) -> AutommitError:
    return AutommitError("invalid_plan", message)


def _invalid_decision(message: str) -> AutommitError:
    return AutommitError("invalid_atomicity_decision", message)


def _mapping(value: object, label: str) -> Result[dict[str, object], AutommitError]:
    if not isinstance(value, dict):
        return Error(_invalid(f"{label} must be a JSON object"))
    return Ok(cast("dict[str, object]", value))


def _record(
    value: dict[str, object], label: str, allowed: frozenset[str]
) -> Result[dict[str, object], AutommitError]:
    keys = set(value.keys())
    if not keys.issubset(allowed):
        extra = ", ".join(sorted(keys - allowed))
        return Error(_invalid(f"{label} contains unsupported keys: {extra}"))
    return Ok(value)


def _list(value: object, label: str) -> Result[list[object], AutommitError]:
    if not isinstance(value, list):
        return Error(_invalid(f"{label} must be an array"))
    return Ok(cast("list[object]", value))


def _str(value: object, label: str, max_len: int) -> Result[str, AutommitError]:
    if not isinstance(value, str):
        return Error(_invalid(f"{label} must be a string"))
    stripped = value.strip()
    if not stripped:
        return Error(_invalid(f"{label} must be a non-empty string"))
    if len(stripped) > max_len:
        return Error(_invalid(f"{label} exceeds length limit ({max_len} chars)"))
    return Ok(stripped)


def _integer(value: object, label: str) -> Result[int, AutommitError]:
    if not isinstance(value, int) or isinstance(value, bool):
        return Error(_invalid(f"{label} must be an integer"))
    if value < 1:
        return Error(_invalid(f"{label} must be at least 1"))
    return Ok(value)


def _normalize_selector(value: object) -> Result[HunkSelector, AutommitError]:
    if value == "all":
        return Ok(AllSelector())
    match _mapping(value, "change.hunks"):
        case Result(tag="ok", ok=selector_mapping):
            selector_type = selector_mapping.get("type")
            if selector_type not in ("indices", "lines"):
                return Error(_invalid("change.hunks type must be 'indices' or 'lines'"))
            if selector_type == "indices":
                match _record(
                    selector_mapping,
                    "indices selector",
                    frozenset({"type", "indices"}),
                ):
                    case Result(tag="ok", ok=selector):
                        if "indices" not in selector:
                            return Error(_invalid("indices selector requires indices"))
                        match _list(selector["indices"], "indices selector indices"):
                            case Result(tag="ok", ok=indices_items):
                                if not indices_items:
                                    return Error(
                                        _invalid(
                                            "indices selector must contain "
                                            "a non-empty array"
                                        )
                                    )
                                indices: list[int] = []
                                for item in indices_items:
                                    match _integer(item, "hunk index"):
                                        case Result(tag="ok", ok=idx):
                                            indices.append(idx)
                                        case Result(error=err):
                                            return Error(err)
                                if len(set(indices)) != len(indices):
                                    return Error(
                                        _invalid("hunk indices must be unique")
                                    )
                                return Ok(IndicesSelector(tuple(sorted(indices))))
                            case Result(error=err):
                                return Error(err)
                    case Result(error=err):
                        return Error(err)
            if selector_type == "lines":
                match _record(
                    selector_mapping,
                    "lines selector",
                    frozenset({"type", "start", "end"}),
                ):
                    case Result(tag="ok", ok=selector):
                        if "start" not in selector or "end" not in selector:
                            return Error(
                                _invalid("lines selector requires start and end")
                            )
                        match _integer(selector["start"], "line selector start"):
                            case Result(tag="ok", ok=start):
                                match _integer(selector["end"], "line selector end"):
                                    case Result(tag="ok", ok=end):
                                        if end < start:
                                            return Error(
                                                _invalid(
                                                    "line selectors "
                                                    "require start <= end"
                                                )
                                            )
                                        return Ok(LinesSelector(start, end))
                                    case Result(error=err):
                                        return Error(err)
                            case Result(error=err):
                                return Error(err)
                    case Result(error=err):
                        return Error(err)
            return Error(_invalid("change.hunks must be all, indices, or lines"))
        case Result(error=err):
            return Error(err)


def normalize_proposal(value: object) -> Result[CommitProposal, AutommitError]:
    """Validate and normalize an untrusted proposal JSON value."""
    match _mapping(value, "proposal"):
        case Result(tag="ok", ok=mapping_value):
            match _record(mapping_value, "proposal", frozenset({"commits"})):
                case Result(tag="ok", ok=root):
                    if "commits" not in root:
                        return Error(_invalid("proposal requires commits"))
                    match _list(root["commits"], "commits"):
                        case Result(tag="ok", ok=commits_items):
                            if not 1 <= len(commits_items) <= MAX_COMMITS:
                                return Error(
                                    _invalid(
                                        f"commits must contain between 1 and {MAX_COMMITS} "
                                        "entries"
                                    )
                                )
                            commits: list[CommitGroup] = []
                            for commit_index, raw_commit in enumerate(
                                commits_items, start=1
                            ):
                                match _mapping(raw_commit, f"commit {commit_index}"):
                                    case Result(tag="ok", ok=commit_mapping):
                                        match _record(
                                            commit_mapping,
                                            f"commit {commit_index}",
                                            frozenset(
                                                {"summary", "details", "changes"}
                                            ),
                                        ):
                                            case Result(tag="ok", ok=commit):
                                                if (
                                                    "summary" not in commit
                                                    or "changes" not in commit
                                                ):
                                                    return Error(
                                                        _invalid(
                                                            f"commit {commit_index} requires "
                                                            "summary and changes"
                                                        )
                                                    )
                                                match _str(
                                                    commit["summary"],
                                                    f"commit {commit_index} summary",
                                                    MAX_SUMMARY_LENGTH,
                                                ):
                                                    case Result(tag="ok", ok=summary):
                                                        details_list: list[str] = []
                                                        if "details" in commit:
                                                            match _list(
                                                                commit["details"],
                                                                f"commit {commit_index} details",
                                                            ):
                                                                case Result(
                                                                    tag="ok",
                                                                    ok=details_items,
                                                                ):
                                                                    if (
                                                                        len(
                                                                            details_items
                                                                        )
                                                                        > MAX_DETAILS
                                                                    ):
                                                                        return Error(
                                                                            _invalid(
                                                                                f"commit {commit_index} "
                                                                                "details exceed maximum "
                                                                                f"entries ({MAX_DETAILS})"
                                                                            )
                                                                        )
                                                                    for (
                                                                        detail_index,
                                                                        raw_detail,
                                                                    ) in enumerate(
                                                                        details_items,
                                                                        start=1,
                                                                    ):
                                                                        match _str(
                                                                            raw_detail,
                                                                            f"commit {commit_index} "
                                                                            f"detail {detail_index}",
                                                                            MAX_DETAIL_LENGTH,
                                                                        ):
                                                                            case Result(
                                                                                tag="ok",
                                                                                ok=detail,
                                                                            ):
                                                                                details_list.append(
                                                                                    detail
                                                                                )
                                                                            case Result(
                                                                                error=err
                                                                            ):
                                                                                return Error(
                                                                                    err
                                                                                )
                                                                case Result(error=err):
                                                                    return Error(err)
                                                        match _list(
                                                            commit["changes"],
                                                            f"commit {commit_index} changes",
                                                        ):
                                                            case Result(
                                                                tag="ok",
                                                                ok=changes_items,
                                                            ):
                                                                if (
                                                                    not 1
                                                                    <= len(
                                                                        changes_items
                                                                    )
                                                                    <= MAX_CHANGES_PER_COMMIT
                                                                ):
                                                                    return Error(
                                                                        _invalid(
                                                                            f"commit {commit_index} "
                                                                            "changes must contain "
                                                                            "between 1 and "
                                                                            f"{MAX_CHANGES_PER_COMMIT} "
                                                                            "entries"
                                                                        )
                                                                    )
                                                                changes: list[
                                                                    CommitChange
                                                                ] = []
                                                                for (
                                                                    change_index,
                                                                    raw_change,
                                                                ) in enumerate(
                                                                    changes_items,
                                                                    start=1,
                                                                ):
                                                                    match _mapping(
                                                                        raw_change,
                                                                        f"commit {commit_index} "
                                                                        f"change {change_index}",
                                                                    ):
                                                                        case Result(
                                                                            tag="ok",
                                                                            ok=change_mapping,
                                                                        ):
                                                                            match _record(
                                                                                change_mapping,
                                                                                f"commit {commit_index} "
                                                                                f"change {change_index}",
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
                                                                                    if (
                                                                                        "path"
                                                                                        not in change
                                                                                        or "hunks"
                                                                                        not in change
                                                                                    ):
                                                                                        return Error(
                                                                                            _invalid(
                                                                                                f"commit {commit_index} "
                                                                                                f"change {change_index} "
                                                                                                "requires path "
                                                                                                "and hunks"
                                                                                            )
                                                                                        )
                                                                                    match _str(
                                                                                        change[
                                                                                            "path"
                                                                                        ],
                                                                                        f"commit {commit_index} "
                                                                                        f"change {change_index} path",
                                                                                        MAX_PATH_LENGTH,
                                                                                    ):
                                                                                        case Result(
                                                                                            tag="ok",
                                                                                            ok=path,
                                                                                        ):
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
                                                                                        case Result(
                                                                                            error=err
                                                                                        ):
                                                                                            return Error(
                                                                                                err
                                                                                            )
                                                                                case Result(
                                                                                    error=err
                                                                                ):
                                                                                    return Error(
                                                                                        err
                                                                                    )
                                                                        case Result(
                                                                            error=err
                                                                        ):
                                                                            return (
                                                                                Error(
                                                                                    err
                                                                                )
                                                                            )
                                                                commits.append(
                                                                    CommitGroup(
                                                                        summary,
                                                                        tuple(
                                                                            details_list
                                                                        ),
                                                                        tuple(changes),
                                                                    )
                                                                )
                                                            case Result(error=err):
                                                                return Error(err)
                                                    case Result(error=err):
                                                        return Error(err)
                                            case Result(error=err):
                                                return Error(err)
                                    case Result(error=err):
                                        return Error(err)
                            return Ok(CommitProposal(tuple(commits)))
                        case Result(error=err):
                            return Error(err)
                case Result(error=err):
                    return Error(err)
        case Result(error=err):
            return Error(err)


def normalize_atomicity_decision(
    value: object,
) -> Result[AtomicityDecision, AutommitError]:
    """Validate and normalize an untrusted critic decision JSON object."""
    match _mapping(value, "decision"):
        case Result(tag="ok", ok=decision_mapping):
            match _record(
                decision_mapping,
                "decision",
                frozenset({"decision", "concerns", "rationale"}),
            ):
                case Result(tag="ok", ok=decision_obj):
                    if (
                        "decision" not in decision_obj
                        or "rationale" not in decision_obj
                    ):
                        return Error(
                            _invalid_decision(
                                "decision object requires 'decision' and 'rationale'"
                            )
                        )
                    decision_kind = decision_obj["decision"]
                    if decision_kind not in ("accept", "split"):
                        return Error(
                            _invalid_decision("decision must be 'accept' or 'split'")
                        )
                    match _str(
                        decision_obj["rationale"], "rationale", MAX_RATIONALE_LENGTH
                    ):
                        case Result(tag="ok", ok=rationale):
                            concerns_list: list[str] = []
                            if "concerns" in decision_obj:
                                match _list(decision_obj["concerns"], "concerns"):
                                    case Result(tag="ok", ok=concerns_items):
                                        for idx, raw_concern in enumerate(
                                            concerns_items, start=1
                                        ):
                                            match _str(
                                                raw_concern,
                                                f"concern {idx}",
                                                MAX_CONCERN_LENGTH,
                                            ):
                                                case Result(tag="ok", ok=concern):
                                                    concerns_list.append(concern)
                                                case Result(error=err):
                                                    return Error(err)
                                    case Result(error=err):
                                        return Error(err)
                            if decision_kind == "accept" and concerns_list:
                                return Error(
                                    _invalid_decision(
                                        "decision 'accept' must not contain concerns"
                                    )
                                )
                            if decision_kind == "split" and not concerns_list:
                                return Error(
                                    _invalid_decision(
                                        "decision 'split' requires at least one concern"
                                    )
                                )
                            return Ok(
                                AtomicityDecision(
                                    cast('Literal["accept", "split"]', decision_kind),
                                    tuple(concerns_list),
                                    rationale,
                                )
                            )
                        case Result(error=err):
                            return Error(err)
                case Result(error=err):
                    return Error(err)
        case Result(error=err):
            return Error(err)


def _decode_git_path_token(token: str, start: int) -> tuple[str, int]:
    if token[start : start + 1] != '"':
        end = token.find(" ", start)
        return (token[start:], len(token)) if end < 0 else (token[start:end], end)

    byte_buf = bytearray()
    index = start + 1
    while index < len(token):
        char = token[index]
        if char == '"':
            try:
                decoded_path = byte_buf.decode("utf-8", errors="surrogateescape")
            except UnicodeDecodeError as err:
                raise AutommitError(
                    "invalid_diff", f"Invalid UTF-8 in quoted path: {err}.", 4
                ) from err
            return decoded_path, index + 1
        if char == "\\" and index + 1 < len(token):
            escaped = token[index + 1]
            if escaped in ('"', "\\"):
                byte_buf.append(ord(escaped))
                index += 2
                continue
            if escaped == "n":
                byte_buf.append(ord("\n"))
                index += 2
                continue
            if escaped == "t":
                byte_buf.append(ord("\t"))
                index += 2
                continue
            if escaped.isdigit():
                octal = token[index + 1 : index + 1 + MAX_OCTAL_DIGITS]
                byte_buf.append(int(octal, 8))
                index += 1 + len(octal)
                continue
        byte_buf.extend(char.encode("utf-8", errors="surrogateescape"))
        index += 1
    raise AutommitError("invalid_diff", "Unterminated quoted Git path.", 4)


def _decode_git_path(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith('"'):
        path, _ = _decode_git_path_token(stripped, 0)
        return path
    return stripped


def _diff_filename(header: str, content: str) -> str:
    prefix = "diff --git "
    if not header.startswith(prefix):
        raise AutommitError("invalid_diff", "Invalid Git diff header.", 4)

    for line in content.splitlines()[1:]:
        if line.startswith("rename to "):
            return _decode_git_path(line.removeprefix("rename to "))
        if line.startswith("+++ "):
            new_raw = line.removeprefix("+++ ")
            if new_raw != "/dev/null":
                return _decode_git_path(new_raw).removeprefix("b/")
        if line.startswith("--- "):
            old_raw = line.removeprefix("--- ")
            if old_raw != "/dev/null":
                return _decode_git_path(old_raw).removeprefix("a/")

    remainder = header[len(prefix) :]
    if remainder.startswith('"'):
        _, cursor = _decode_git_path_token(remainder, 0)
        while cursor < len(remainder) and remainder[cursor] == " ":
            cursor += 1
        second_path, _ = _decode_git_path_token(remainder, cursor)
        return second_path.removeprefix("b/")

    separator = remainder.rfind(" ")
    if separator < 0:
        raise AutommitError("invalid_diff", "Invalid Git diff paths.", 4)
    second = remainder[separator + 1 :]
    return _decode_git_path(second).removeprefix("b/")


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
            re.finditer(r"(?m)^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*$", content)
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
                    int(match.group(3)),
                    int(match.group(4)) if match.group(4) is not None else 1,
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
    errors.extend(
        f"Staged file missing from split plan: {filename}"
        for filename in staged_files
        if filename not in selections_by_file
    )
    files_by_name = {file.filename: file for file in parsed_files}
    for filename, selections in selections_by_file.items():
        for left_index, left in enumerate(selections):
            if any(
                _selections_overlap(left, right)
                for right in selections[left_index + 1 :]
            ):
                errors.append(
                    "Overlapping hunk selections across commits: "
                    f"{filename} ({_describe_selector(left)} "
                    "overlaps another selection); "
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
                    "Staged hunk missing from split plan: "
                    f"{filename} (hunk {hunk.index})"
                )
    return tuple(dict.fromkeys(errors))


def _build_lines_patch(
    file: ParsedFile, selector: LinesSelector
) -> Result[str, AutommitError]:
    """Build a zero-context patch covering new lines [start, end]."""
    # Lines selector is supported only for new-file additions (pure additions starting at -0,0)
    # Check that all file hunks are new-file additions (old_lines == 0)
    for hunk in file.hunks:
        if hunk.old_lines != 0:
            return Error(
                AutommitError(
                    "invalid_plan",
                    (
                        f"Lines selector cannot be used on existing file modification {file.filename}. "
                        "Use indices or all selector instead."
                    ),
                )
            )

    selected_hunks: list[str] = []
    for hunk in file.hunks:
        hunk_end = (
            hunk.new_start
            if hunk.new_lines == 0
            else hunk.new_start + hunk.new_lines - 1
        )
        if hunk.new_start <= selector.end and selector.start <= hunk_end:
            # Preserve raw line terminators without splitlines() stripping \r
            lines = hunk.content.split("\n")[1:]
            overlapping_lines: list[str] = []
            current_line = hunk.new_start
            first_included_line: int | None = None
            for line in lines:
                # Check for \ No newline at end of file marker
                if line.startswith("\\ No newline"):
                    if overlapping_lines:
                        overlapping_lines.append(line)
                    continue
                if selector.start <= current_line <= selector.end:
                    if first_included_line is None:
                        first_included_line = current_line
                    overlapping_lines.append(line)
                if line.startswith(("+", " ")):
                    current_line += 1
            if overlapping_lines and first_included_line is not None:
                # Count only content lines (starting with + or space), not trailing no-newline markers
                count = sum(
                    1 for line in overlapping_lines if line.startswith(("+", " "))
                )
                header = (
                    f"@@ -0,0 +{first_included_line},{count} @@"
                    if count != 1
                    else f"@@ -0,0 +{first_included_line} @@"
                )
                selected_hunks.append("\n".join((header, *overlapping_lines)))

    if not selected_hunks:
        return Error(
            AutommitError(
                "invalid_plan",
                (
                    f"No changes selected for {file.filename} in lines "
                    f"{selector.start}-{selector.end}."
                ),
            )
        )
    first_hunk = file.content.find("\n@@")
    file_header = file.content if first_hunk < 0 else file.content[:first_hunk]
    if selector.start > 1:
        diff_header = (
            f"diff --git a/{file.filename} b/{file.filename}\n"
            f"--- a/{file.filename}\n"
            f"+++ b/{file.filename}"
        )
        adjusted_hunks: list[str] = []
        for hunk_str in selected_hunks:
            h_lines = hunk_str.split("\n")
            if h_lines and h_lines[0].startswith("@@ -0,0"):
                h_lines[0] = h_lines[0].replace(
                    "@@ -0,0", f"@@ -{selector.start - 1},0"
                )
            adjusted_hunks.append("\n".join(h_lines))
        return Ok("\n".join((diff_header, *adjusted_hunks)))
    return Ok("\n".join((file_header, *selected_hunks)))


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
    if isinstance(selector, LinesSelector):
        return _build_lines_patch(file, selector)
    hunks = tuple(hunk for hunk in file.hunks if hunk.index in selector.indices)
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
    return Ok("\n".join(parts) + "\n")


def changed_hunk_count(diff_text: str) -> int:
    """Count changed hunks across the staged diff."""
    return sum(len(file.hunks) for file in parse_file_diffs(diff_text))


def requires_atomicity_review(
    proposal: CommitProposal,
    staged_file_count: int,
    diff_text: str,
) -> bool:
    """Match the narrow-proposal critic bypass."""
    if len(proposal.commits) != 1:
        return False
    group = proposal.commits[0]
    return not (
        staged_file_count == 1
        and changed_hunk_count(diff_text) <= 1
        and len(group.details) <= 1
    )
