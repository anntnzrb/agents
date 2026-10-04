"""Parse and validate untrusted LLM commit proposals."""

from dataclasses import dataclass
from typing import Literal, TypeIs

from autommit.errors import AutommitError


def _is_dict(val: object) -> TypeIs[dict[str, object]]:
    return isinstance(val, dict)


def _is_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


MAX_SUBJECT_LENGTH = 72
MAX_DETAIL_LENGTH = 2048
MAX_PATH_LENGTH = 4096
MAX_CONCERN_LENGTH = 512
MAX_RATIONALE_LENGTH = 2048
_MIN_SPLIT_COMMITS = 2
MAX_OCTAL_DIGITS = 3
MAX_ATOMICITY_DIFF_CHARS = 256 * 1024


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
    dependencies: tuple[int, ...] = ()


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
    if not _is_dict(value):
        raise _invalid(f"{label} must be a JSON object")
    return dict(value)


def _record(
    value: dict[str, object], label: str, allowed: frozenset[str]
) -> dict[str, object]:
    keys = set(value.keys())
    extra = sorted(keys - allowed)
    if extra:
        raise _invalid(f"{label} has unrecognized fields: {', '.join(extra)}")
    return value


def _list(value: object, label: str) -> list[object]:
    if not _is_list(value):
        raise _invalid(f"{label} must be an array")
    return list(value)


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


def _parse_indices_list(raw_indices: object, empty_error: str) -> tuple[int, ...]:
    if not _is_list(raw_indices) or not raw_indices:
        raise _invalid(empty_error)
    ind_list: list[int] = []
    for idx, item in enumerate(raw_indices):
        int_val = _integer(item, f"hunk index [{idx}]")
        if int_val < 1:
            raise _invalid(f"hunk index [{idx}] must be >= 1")
        ind_list.append(int_val)
    if len(set(ind_list)) != len(ind_list):
        raise _invalid("duplicate hunk index in selector")
    return tuple(sorted(ind_list))


def _normalize_selector(value: object) -> HunkSelector:
    if value == "all":
        return AllSelector()
    if _is_list(value):
        return IndicesSelector(
            _parse_indices_list(value, "hunk indices array must not be empty")
        )
    if _is_dict(value):
        obj = _mapping(value, "hunks selector")
        sel_type = obj.get("type") or obj.get("kind")
        if sel_type in ("indices", "index") or "indices" in obj:
            _ = _record(obj, "indices selector", frozenset({"indices", "type", "kind"}))
            return IndicesSelector(
                _parse_indices_list(
                    obj.get("indices"), "hunk indices must be a non-empty array"
                )
            )
        if "start" in obj or "end" in obj or sel_type == "lines":
            _ = _record(
                obj, "lines selector", frozenset({"start", "end", "type", "kind"})
            )
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
    _ = _record(obj, label, frozenset({"path", "hunks"}))
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
    _ = _record(
        obj, label, frozenset({"summary", "details", "changes", "dependencies"})
    )
    summary = _str(obj.get("summary"), f"{label}.summary", MAX_SUBJECT_LENGTH)
    raw_details = obj.get("details", [])
    details_list = _list(raw_details, f"{label}.details")
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
    changes = tuple(
        _normalize_change(item, f"{label}.changes[{i}]")
        for i, item in enumerate(changes_list)
    )
    dependencies = _normalize_dependencies(
        obj.get("dependencies", []), f"{label}.dependencies"
    )
    return CommitGroup(summary, details, changes, dependencies)


def _normalize_dependencies(raw: object, label: str) -> tuple[int, ...]:
    """Parse optional dependency indices, rejecting duplicates and negatives."""
    items = _list(raw, label)
    indices: list[int] = []
    for position, item in enumerate(items):
        value = _integer(item, f"{label}[{position}]")
        if value < 0:
            raise _invalid(f"{label}[{position}] must be >= 0")
        if value in indices:
            raise _invalid(f"{label}[{position}] duplicates index {value}")
        indices.append(value)
    return tuple(sorted(indices))


def _validate_dependencies(commits: tuple[CommitGroup, ...]) -> None:
    """Reject self-references and out-of-range dependency indices."""
    total = len(commits)
    for index, commit in enumerate(commits):
        for dependency in commit.dependencies:
            if dependency == index:
                raise _invalid(f"commits[{index}].dependencies cannot reference itself")
            if dependency >= total:
                raise _invalid(
                    f"commits[{index}].dependencies index {dependency} is out of range"
                )


def compute_apply_order(commits: tuple[CommitGroup, ...]) -> tuple[int, ...]:
    """Return a stable dependency order for the plan commits."""
    dependents: dict[int, list[int]] = {index: [] for index, _ in enumerate(commits)}
    pending = [len(commit.dependencies) for commit in commits]
    for index, commit in enumerate(commits):
        for dependency in commit.dependencies:
            dependents[dependency].append(index)
    ready = [index for index, count in enumerate(pending) if count == 0]
    order: list[int] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for dependent in dependents[current]:
            pending[dependent] -= 1
            if pending[dependent] == 0:
                ready.append(dependent)
        ready.sort()
    if len(order) != len(commits):
        raise _invalid("commits contain circular dependencies")
    return tuple(order)


def normalize_proposal(value: object) -> CommitProposal:
    """Validate and normalize an untrusted proposal JSON value."""
    obj = _mapping(value, "proposal")
    _ = _record(obj, "proposal", frozenset({"commits"}))
    raw_commits = obj.get("commits")
    if raw_commits is None:
        raise _invalid("proposal missing required field 'commits'")
    commits_list = _list(raw_commits, "proposal.commits")
    if not commits_list:
        raise _invalid("proposal.commits must not be empty")
    commits = tuple(_normalize_commit(item, i) for i, item in enumerate(commits_list))
    _validate_dependencies(commits)
    _ = compute_apply_order(commits)
    return CommitProposal(commits)


def normalize_atomicity_decision(value: object) -> AtomicityDecision:
    """Validate and normalize an untrusted critic decision JSON object."""
    if not _is_dict(value):
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
    if not _is_list(raw_concerns):
        raise _invalid_decision("concerns must be an array")
    concerns = tuple(
        _str(c, f"concerns[{i}]", MAX_CONCERN_LENGTH)
        for i, c in enumerate(raw_concerns)
    )
    raw_rationale = value.get("rationale", "")
    rationale = _str(raw_rationale, "rationale", MAX_RATIONALE_LENGTH)
    if raw_decision == "split" and not concerns:
        raise _invalid_decision("a 'split' decision must list at least one concern")
    if raw_decision == "accept" and concerns:
        raise _invalid_decision("an 'accept' decision must list no concerns")
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


def decode_git_path(value: str) -> str:
    """Decode a quoted path from Git's diff metadata."""
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
        for line in _diff_lines(content):
            if line.startswith("rename to "):
                return decode_git_path(line.removeprefix("rename to "))
    path_str = decode_git_path(second)
    return path_str.removeprefix("b/")


def _diff_lines(text: str) -> list[str]:
    """Split diff text on newlines only, as Git does.

    `str.splitlines()` also breaks on characters such as U+2028 and form feed, and
    drops the carriage return of CRLF lines, which corrupts rebuilt hunks.
    """
    return text.removesuffix("\n").split("\n")


def parse_file_diffs(diff_text: str) -> tuple[ParsedFile, ...]:
    """Parse file sections and assign 1-based hunk indices."""
    if not diff_text.strip():
        return ()
    parts = diff_text.split("\ndiff --git ")
    files: list[ParsedFile] = []
    for idx, part in enumerate(parts):
        chunk = part if idx == 0 else f"diff --git {part}"
        lines = _diff_lines(chunk)
        first_line = lines[0] if lines else ""
        filename = _diff_filename(first_line, chunk)
        is_binary = any(
            line.startswith("Binary files ") or line == "GIT binary patch"
            for line in lines
        )
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
    lines = _diff_lines(hunk.content)[1:]
    changed: list[int] = []
    line_num = hunk.new_start
    for line in lines:
        if line.startswith("+"):
            changed.append(line_num)
            line_num += 1
        elif line.startswith(" "):
            line_num += 1
    return tuple(changed) or (max(1, hunk.new_start),)


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
    zero_files: tuple[ParsedFile, ...] = (),
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
                    f"Overlapping hunk selections across commits: {filename} ({_describe_selector(left)} overlaps another selection); line ranges are inclusive and must be disjoint"
                )
                break
        if parsed is None:
            errors.append(f"No staged diff found for {filename}")
            continue
        if parsed.is_binary and any(
            not isinstance(item, AllSelector) for item in selections
        ):
            errors.append(f"Binary file cannot be partially selected: {filename}")
        if (
            "\nold mode " in parsed.content or "\ndeleted file mode " in parsed.content
        ) and any(not isinstance(item, AllSelector) for item in selections):
            errors.append(
                f"Mode changes and deletions require whole-file selection: {filename}"
            )
        if not parsed.hunks and any(
            not isinstance(item, AllSelector) for item in selections
        ):
            errors.append(
                f"Metadata-only file cannot be partially selected: {filename}"
            )
        coverage_file = (
            next((file for file in zero_files if file.filename == filename), parsed)
            if all(isinstance(item, LinesSelector) for item in selections)
            else parsed
        )
        for hunk in coverage_file.hunks:
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


def _is_rename(file: ParsedFile) -> bool:
    return "\nrename from " in file.content or file.content.startswith("rename from ")


def select_patch(file: ParsedFile, selector: HunkSelector) -> str:
    """Return a whole-file patch; partial selections must use blob staging."""
    if isinstance(selector, AllSelector):
        return file.content
    raise AutommitError(
        "invalid_plan", "Partial selections require exact blob staging."
    )


def build_commit_patch(
    changes: tuple[CommitChange, ...],
    staged_diff: str,
    zero_diff: str,
) -> str:
    """Build selected diff evidence; partial application uses exact blobs instead."""
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


def truncate_critic_diff(diff: str) -> tuple[str, bool]:
    """Bound the diff handed to the atomicity critic."""
    if len(diff) <= MAX_ATOMICITY_DIFF_CHARS:
        return diff, False
    return diff[:MAX_ATOMICITY_DIFF_CHARS], True


def requires_atomicity_review(proposal: CommitProposal, staged_diff: str) -> bool:
    """Match the narrow-proposal critic bypass.

    A commit of only pure renames is the deterministic move-only commit; it never
    counts toward the review, so the decision matches the planner, which judges
    the model's commits alone.
    """
    moves = {
        file.filename
        for file in parse_file_diffs(staged_diff)
        if _is_rename(file) and not file.hunks and not file.is_binary
    }
    commits = [
        commit
        for commit in proposal.commits
        if not commit.changes or any(c.path not in moves for c in commit.changes)
    ]
    if not commits:
        return not proposal.commits
    if len(proposal.commits) > 1:
        return False
    single = commits[0]
    narrow = (
        len(single.changes) == 1
        and isinstance(single.changes[0].hunks, AllSelector)
        and len(single.details) <= 1
        and changed_hunk_count(staged_diff) <= 1
    )
    return not narrow
