"""Parse and validate untrusted LLM commit proposals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from autommit.errors import AutommitError

MAX_COMMITS = 16
MAX_CHANGES_PER_COMMIT = 128
MAX_DETAILS = 32
MAX_SUMMARY_LENGTH = 512
MAX_DETAIL_LENGTH = 2048
MAX_PATH_LENGTH = 4096
MAX_CONCERN_LENGTH = 512
MAX_RATIONALE_LENGTH = 2048
_MIN_SPLIT_COMMITS = 2
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
    trailer: str = ""


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """Parsed file section in a Git diff."""

    filename: str
    content: str
    is_binary: bool
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


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _invalid(f"{label} must be a JSON object")
    return cast("dict[str, object]", value)


def _record(
    value: dict[str, object], label: str, allowed: frozenset[str]
) -> dict[str, object]:
    keys = set(value.keys())
    extra = sorted(keys - allowed)
    if extra:
        raise _invalid(f"{label} has unrecognized fields: {', '.join(extra)}")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise _invalid(f"{label} must be an array")
    return cast("list[object]", value)


def _str(value: object, label: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{label} must be a string")
    stripped = value.strip()
    if not stripped:
        raise _invalid(f"{label} must not be empty")
    if len(stripped) > max_len:
        raise _invalid(f"{label} exceeds maximum length of {max_len}")
    return stripped


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _invalid(f"{label} must be an integer")
    return value


def _normalize_selector(value: object) -> HunkSelector:
    if value == "all":
        return AllSelector()
    if isinstance(value, list):
        if not value:
            raise _invalid("hunk indices array must not be empty")
        indices: list[int] = []
        for idx, item in enumerate(value):
            int_val = _integer(item, f"hunk index [{idx}]")
            if int_val < 1:
                raise _invalid(f"hunk index [{idx}] must be >= 1")
            indices.append(int_val)
        if len(set(indices)) != len(indices):
            raise _invalid("duplicate hunk index in selector")
        return IndicesSelector(tuple(sorted(indices)))
    if isinstance(value, dict):
        obj = _mapping(value, "hunks selector")
        sel_type = obj.get("type") or obj.get("kind")
        if sel_type in ("indices", "index") or "indices" in obj:
            _record(obj, "indices selector", frozenset({"indices", "type", "kind"}))
            raw_indices = obj.get("indices")
            if not isinstance(raw_indices, list) or not raw_indices:
                raise _invalid("hunk indices must be a non-empty array")
            ind_list: list[int] = []
            for idx, item in enumerate(raw_indices):
                int_val = _integer(item, f"hunk index [{idx}]")
                if int_val < 1:
                    raise _invalid(f"hunk index [{idx}] must be >= 1")
                ind_list.append(int_val)
            if len(set(ind_list)) != len(ind_list):
                raise _invalid("duplicate hunk index in selector")
            return IndicesSelector(tuple(sorted(ind_list)))
        if "start" in obj or "end" in obj or sel_type == "lines":
            _record(obj, "lines selector", frozenset({"start", "end", "type", "kind"}))
            start = _integer(obj.get("start"), "lines.start")
            end = _integer(obj.get("end"), "lines.end")
            if start < 1:
                raise _invalid("lines.start must be >= 1")
            if end < start:
                raise _invalid(
                    f"lines.end ({end}) cannot be less than lines.start ({start})"
                )
            return LinesSelector(start, end)
    raise _invalid(
        "hunks selector must be 'all', an array of hunk indices, or {start, end}"
    )


def _normalize_change(value: object, label: str) -> CommitChange:
    obj = _mapping(value, label)
    _record(obj, label, frozenset({"path", "hunks"}))
    path = _str(obj.get("path"), f"{label}.path", MAX_PATH_LENGTH)
    path = path.removeprefix("./")
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise _invalid(f"{label}.path must be a clean relative path: {path}")
    raw_hunks = obj.get("hunks")
    if raw_hunks is None:
        raise _invalid(f"{label} missing required field 'hunks'")
    selector = _normalize_selector(raw_hunks)
    return CommitChange(path, selector)


def _normalize_commit(value: object, index: int) -> CommitGroup:
    label = f"commits[{index}]"
    obj = _mapping(value, label)
    _record(obj, label, frozenset({"summary", "details", "changes"}))
    summary = _str(obj.get("summary"), f"{label}.summary", MAX_SUMMARY_LENGTH)
    raw_details = obj.get("details", [])
    details_list = _list(raw_details, f"{label}.details")
    if len(details_list) > MAX_DETAILS:
        raise _invalid(f"{label}.details exceeds maximum length of {MAX_DETAILS}")
    details = tuple(
        _str(item, f"{label}.details[{i}]", MAX_DETAIL_LENGTH)
        for i, item in enumerate(details_list)
    )
    raw_changes = obj.get("changes")
    if raw_changes is None:
        raise _invalid(f"{label} missing required field 'changes'")
    changes_list = _list(raw_changes, f"{label}.changes")
    if not changes_list:
        raise _invalid(f"{label}.changes must not be empty")
    if len(changes_list) > MAX_CHANGES_PER_COMMIT:
        raise _invalid(
            f"{label}.changes exceeds maximum length of {MAX_CHANGES_PER_COMMIT}"
        )
    changes = tuple(
        _normalize_change(item, f"{label}.changes[{i}]")
        for i, item in enumerate(changes_list)
    )
    return CommitGroup(summary, details, changes)


def normalize_proposal(value: object) -> CommitProposal:
    """Validate and normalize an untrusted proposal JSON value."""
    obj = _mapping(value, "proposal")
    _record(obj, "proposal", frozenset({"commits"}))
    raw_commits = obj.get("commits")
    if raw_commits is None:
        raise _invalid("proposal missing required field 'commits'")
    commits_list = _list(raw_commits, "proposal.commits")
    if not commits_list:
        raise _invalid("proposal.commits must not be empty")
    if len(commits_list) > MAX_COMMITS:
        raise _invalid(f"proposal.commits exceeds maximum of {MAX_COMMITS} commits")
    commits = tuple(_normalize_commit(item, i) for i, item in enumerate(commits_list))
    return CommitProposal(commits)


def normalize_atomicity_decision(value: object) -> AtomicityDecision:
    """Validate and normalize an untrusted critic decision JSON object."""
    if not isinstance(value, dict):
        raise _invalid_decision("atomicity decision must be a JSON object")
    keys = set(value.keys())
    allowed = {"decision", "concerns", "rationale"}
    extra = sorted(keys - allowed)
    if extra:
        raise _invalid_decision(
            f"atomicity decision has unrecognized fields: {', '.join(extra)}"
        )
    raw_decision = value.get("decision")
    if raw_decision not in ("accept", "split"):
        raise _invalid_decision("decision must be either 'accept' or 'split'")
    raw_concerns = value.get("concerns", [])
    if not isinstance(raw_concerns, list):
        raise _invalid_decision("concerns must be an array")
    concerns = tuple(
        _str(c, f"concerns[{i}]", MAX_CONCERN_LENGTH)
        for i, c in enumerate(raw_concerns)
    )
    raw_rationale = value.get("rationale", "")
    rationale = _str(raw_rationale, "rationale", MAX_RATIONALE_LENGTH)
    if raw_decision == "split" and not concerns:
        raise _invalid_decision("a 'split' decision must list at least one concern")
    return AtomicityDecision(raw_decision, concerns, rationale)


def _decode_git_path_token(token: str, start: int) -> tuple[str, int]:
    if token[start : start + 1] != '"':
        # For unquoted paths, the first path token starts with a/ and ends before " b/"
        if token.startswith("a/"):
            b_idx = token.find(" b/", start)
            if b_idx >= 0:
                return token[start:b_idx], b_idx
        return (token[start:], len(token))
    idx = start + 1
    chars: list[str] = []
    while idx < len(token):
        ch = token[idx]
        if ch == '"':
            return "".join(chars), idx + 1
        if ch == "\\":
            idx += 1
            if idx >= len(token):
                break
            esc = token[idx]
            if esc in ('"', "\\"):
                chars.append(esc)
            elif esc == "n":
                chars.append("\n")
            elif esc == "t":
                chars.append("\t")
            elif esc.isdigit() and esc in "01234567":
                octal = esc
                for _ in range(MAX_OCTAL_DIGITS - 1):
                    if idx + 1 < len(token) and token[idx + 1] in "01234567":
                        idx += 1
                        octal += token[idx]
                    else:
                        break
                chars.append(chr(int(octal, 8)))
            else:
                chars.append(esc)
        else:
            chars.append(ch)
        idx += 1
    raise AutommitError("invalid_diff", "Unterminated quoted Git path.", 4)


def _decode_git_path(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith('"') and stripped.endswith('"'):
        res, _ = _decode_git_path_token(stripped, 0)
        return res
    return stripped


def _diff_filename(header: str, content: str) -> str:
    prefix = "diff --git "
    if not header.startswith(prefix):
        raise AutommitError("invalid_diff", "Malformed diff file header.", 4)
    after = header[len(prefix) :]
    _first, end = _decode_git_path_token(after, 0)
    second, _ = _decode_git_path_token(after[end + 1 :], 0)
    is_rename = (
        "\nrename from " in content
        or content.startswith("rename from ")
        or "\nsimilarity index " in content
    )
    if is_rename:
        for line in content.splitlines():
            if line.startswith("rename to "):
                return _decode_git_path(line.removeprefix("rename to "))
    path_str = _decode_git_path(second)
    return path_str.removeprefix("b/")


def parse_file_diffs(diff_text: str) -> tuple[ParsedFile, ...]:
    """Parse file sections and assign 1-based hunk indices."""
    if not diff_text.strip():
        return ()
    parts = diff_text.split("\ndiff --git ")
    files: list[ParsedFile] = []
    for idx, part in enumerate(parts):
        chunk = part if idx == 0 else f"diff --git {part}"
        lines = chunk.splitlines()
        first_line = lines[0] if lines else ""
        filename = _diff_filename(first_line, chunk)
        is_binary = "Binary files " in chunk or "GIT binary patch" in chunk
        hunks: list[DiffHunk] = []
        hunk_idx = 1
        current_hunk_lines: list[str] = []
        cur_old_start = cur_old_lines = cur_new_start = cur_new_lines = 0
        cur_trailer = ""

        for line in lines:
            if line.startswith("@@ "):
                if current_hunk_lines:
                    hunks.append(
                        DiffHunk(
                            hunk_idx,
                            cur_old_start,
                            cur_old_lines,
                            cur_new_start,
                            cur_new_lines,
                            "\n".join(current_hunk_lines),
                            cur_trailer,
                        )
                    )
                    hunk_idx += 1
                    current_hunk_lines = []
                parts_hdr = line.split(" @@", 1)
                cur_trailer = parts_hdr[1] if len(parts_hdr) > 1 else ""
                hdr = parts_hdr[0].removeprefix("@@ -")
                old_part, new_part = hdr.split(" +", 1)
                old_toks = old_part.split(",")
                cur_old_start = int(old_toks[0])
                cur_old_lines = int(old_toks[1]) if len(old_toks) > 1 else 1
                new_toks = new_part.split(",")
                cur_new_start = int(new_toks[0])
                cur_new_lines = int(new_toks[1]) if len(new_toks) > 1 else 1
                current_hunk_lines.append(line)
            elif current_hunk_lines:
                current_hunk_lines.append(line)

        if current_hunk_lines:
            hunks.append(
                DiffHunk(
                    hunk_idx,
                    cur_old_start,
                    cur_old_lines,
                    cur_new_start,
                    cur_new_lines,
                    "\n".join(current_hunk_lines),
                    cur_trailer,
                )
            )

        files.append(ParsedFile(filename, chunk, is_binary, tuple(hunks)))
    return tuple(files)


def _selected_hunk_indices(
    selector: HunkSelector, parsed: ParsedFile | None
) -> set[int]:
    if isinstance(selector, AllSelector):
        return {h.index for h in parsed.hunks} if parsed else set()
    if isinstance(selector, IndicesSelector):
        return set(selector.indices)
    if isinstance(selector, LinesSelector):
        if not parsed:
            return set()
        matched: set[int] = set()
        for hunk in parsed.hunks:
            hunk_end = (
                hunk.new_start
                if hunk.new_lines == 0
                else hunk.new_start + hunk.new_lines - 1
            )
            if hunk.new_start <= selector.end and selector.start <= hunk_end:
                matched.add(hunk.index)
        return matched
    return set()


def _selections_overlap(
    left: HunkSelector, right: HunkSelector, parsed: ParsedFile | None = None
) -> bool:
    if isinstance(left, AllSelector) or isinstance(right, AllSelector):
        return True
    if isinstance(left, IndicesSelector) and isinstance(right, IndicesSelector):
        return not set(left.indices).isdisjoint(set(right.indices))
    if isinstance(left, LinesSelector) and isinstance(right, LinesSelector):
        return left.start <= right.end and right.start <= left.end
    if parsed:
        left_hunks = _selected_hunk_indices(left, parsed)
        right_hunks = _selected_hunk_indices(right, parsed)
        if left_hunks and right_hunks:
            return not left_hunks.isdisjoint(right_hunks)
    return True


def _describe_selector(selector: HunkSelector) -> str:
    match selector:
        case AllSelector():
            return "all"
        case IndicesSelector(indices):
            return f"hunks {list(indices)}"
        case LinesSelector(start, end):
            return f"new-file lines {start}-{end}"


def _changed_new_lines(hunk: DiffHunk) -> tuple[int, ...]:
    lines = hunk.content.splitlines()[1:]
    changed: list[int] = []
    line_num = hunk.new_start
    for line in lines:
        if line.startswith("+"):
            changed.append(line_num)
            line_num += 1
        elif line.startswith(" "):
            line_num += 1
    return tuple(changed) or (hunk.new_start,)


def _selector_intersects_hunk(selector: HunkSelector, hunk: DiffHunk) -> bool:
    match selector:
        case AllSelector():
            return True
        case IndicesSelector(indices):
            return hunk.index in indices
        case LinesSelector(start, end):
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
    files_by_name = {file.filename: file for file in parsed_files}
    errors: list[str] = []

    for commit_index, commit in enumerate(proposal.commits, start=1):
        commit_seen: dict[str, list[HunkSelector]] = {}
        for change in commit.changes:
            if change.path not in staged_set:
                errors.append(
                    f"Commit {commit_index}: file is not staged: {change.path}"
                )
                continue
            parsed = files_by_name.get(change.path)
            prior = commit_seen.get(change.path, [])
            if any(_selections_overlap(prev, change.hunks, parsed) for prev in prior):
                errors.append(
                    f"Overlapping hunk selections in commit {commit.summary}: {change.path}"
                )
                continue
            commit_seen.setdefault(change.path, []).append(change.hunks)
            selections_by_file.setdefault(change.path, []).append(change.hunks)

    errors.extend(
        f"Staged file missing from split plan: {filename}"
        for filename in staged_files
        if filename not in selections_by_file
    )

    for filename, selections in selections_by_file.items():
        parsed = files_by_name.get(filename)
        for left_index, left in enumerate(selections):
            if any(
                _selections_overlap(left, right, parsed)
                for right in selections[left_index + 1 :]
            ):
                errors.append(
                    "Overlapping hunk selections across commits: "
                    f"{filename} ({_describe_selector(left)} "
                    "overlaps another selection); "
                    "line ranges are inclusive and must be disjoint"
                )
                break
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


def _build_lines_patch(file: ParsedFile, selector: LinesSelector) -> str:
    """Build a zero-context patch covering new lines [start, end]."""
    if not file.hunks:
        raise AutommitError(
            "invalid_plan", f"No hunks found to slice for {file.filename}."
        )
    first_hunk = file.content.find("\n@@")
    file_header = file.content if first_hunk < 0 else file.content[:first_hunk]
    selected_hunks: list[str] = []
    old_line_cursor = 1
    new_line_cursor = 1

    for hunk in file.hunks:
        hunk_end = (
            hunk.new_start
            if hunk.new_lines == 0
            else hunk.new_start + hunk.new_lines - 1
        )
        if hunk_end < selector.start or hunk.new_start > selector.end:
            old_line_cursor += hunk.old_lines
            new_line_cursor += hunk.new_lines
            continue

        hunk_lines = hunk.content.splitlines()[1:]
        kept_lines: list[str] = []
        hunk_old_start = hunk.old_start if selector.start == 1 else selector.start
        hunk_old_count = 0
        hunk_new_start = 1 if selector.start == 1 else selector.start
        hunk_new_count = 0
        cur_old = hunk.old_start
        cur_new = hunk.new_start

        for line in hunk_lines:
            if line.startswith("-"):
                if selector.start <= cur_new <= selector.end:
                    kept_lines.append(line)
                    hunk_old_count += 1
                cur_old += 1
            elif line.startswith("+"):
                if selector.start <= cur_new <= selector.end:
                    kept_lines.append(line)
                    hunk_new_count += 1
                cur_new += 1
            elif line.startswith(" "):
                if selector.start <= cur_new <= selector.end:
                    kept_lines.append(line)
                    hunk_old_count += 1
                    hunk_new_count += 1
                cur_old += 1
                cur_new += 1

        if kept_lines:
            old_spec = (
                f"{hunk_old_start}"
                if hunk_old_count == 1
                else f"{hunk_old_start},{hunk_old_count}"
            )
            new_spec = (
                f"{hunk_new_start}"
                if hunk_new_count == 1
                else f"{hunk_new_start},{hunk_new_count}"
            )
            hunk_header = f"@@ -{old_spec} +{new_spec} @@"
            selected_hunks.append("\n".join((hunk_header, *kept_lines)))
    if not selected_hunks:
        raise AutommitError("invalid_plan", f"No changes selected for {file.filename}.")

    if selector.start > 1:
        header_lines = [
            line
            for line in file_header.splitlines()
            if not line.startswith("new file mode ")
            and not line.startswith("--- /dev/null")
        ]
        if not any(line.startswith("--- a/") for line in header_lines):
            header_lines.append(f"--- a/{file.filename}")
        file_header = "\n".join(header_lines)

    return "\n".join((file_header, *selected_hunks))


def select_patch(file: ParsedFile, selector: HunkSelector) -> str:
    """Select one whole file or a subset of its hunks."""
    if file.is_binary and not isinstance(selector, AllSelector):
        raise AutommitError(
            "invalid_plan", f"Cannot partially select binary file {file.filename}."
        )
    is_rename = "\nrename from " in file.content or file.content.startswith(
        "rename from "
    )
    if is_rename and not isinstance(selector, AllSelector):
        raise AutommitError(
            "invalid_plan",
            f"Cannot partially select renamed file {file.filename}; "
            "entire file change must be committed together.",
        )
    if isinstance(selector, AllSelector):
        return file.content
    if isinstance(selector, LinesSelector):
        return _build_lines_patch(file, selector)

    hunks = [hunk for hunk in file.hunks if hunk.index in selector.indices]
    if not hunks:
        raise AutommitError("invalid_plan", f"No changes selected for {file.filename}.")

    first_hunk = file.content.find("\n@@")
    header = file.content if first_hunk < 0 else file.content[:first_hunk]
    return "\n".join((header, *(hunk.content for hunk in hunks)))


def build_commit_patch(
    changes: tuple[CommitChange, ...],
    staged_diff: str,
    zero_diff: str,
) -> str:
    """Build one patch from normalized commit changes with dynamic offset calculation."""
    regular_files = {file.filename: file for file in parse_file_diffs(staged_diff)}
    zero_files = {file.filename: file for file in parse_file_diffs(zero_diff)}
    parts: list[str] = []

    for change in changes:
        files = zero_files if isinstance(change.hunks, LinesSelector) else regular_files
        file = files.get(change.path)
        if file is None:
            raise AutommitError(
                "invalid_plan", f"No staged diff found for {change.path}."
            )
        parts.append(select_patch(file, change.hunks))

    return "\n".join(parts) + "\n"


def changed_hunk_count(diff_text: str) -> int:
    """Count changed hunks across the staged diff."""
    return sum(len(file.hunks) for file in parse_file_diffs(diff_text))


def requires_atomicity_review(proposal: CommitProposal, staged_diff: str) -> bool:
    """Match the narrow-proposal critic bypass."""
    if len(proposal.commits) > 1:
        return False
    return not (
        len(proposal.commits) == 1
        and len(proposal.commits[0].changes) == 1
        and isinstance(proposal.commits[0].changes[0].hunks, AllSelector)
        and changed_hunk_count(staged_diff) <= 1
    )
