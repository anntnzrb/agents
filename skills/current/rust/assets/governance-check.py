# Copyright (c) 2026 anntnzrb
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Reject changes that weaken human-owned Rust quality gates."""

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import cast

DIFF_FLAGS = (
    "--text",
    "--no-textconv",
    "--no-ext-diff",
    "--no-renames",
    "--src-prefix=a/",
    "--dst-prefix=b/",
)
PROTECTED = re.compile(
    r"""(?x)^(?:
    \.github/|\.gate/|\.cargo/|\.config/|deny\.toml$|mutants\.toml$|
    \.?clippy\.toml$|\.?rustfmt\.toml$|rust-toolchain(?:\.toml)?$|
    scripts/governance-check\.(?:py|sh)$)
    """
)
LEXICAL = re.compile(
    r"""//[^\n]*|/\*|\b(?:br|cr|r)(?P<hashes>\#*)"|"|'(?:\\.|[^'\\\n])' """, re.VERBOSE
)
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class Options(argparse.Namespace):
    """Typed command line arguments."""

    base: str = ""
    inventory: bool = False
    doctests: bool = False


@dataclass(frozen=True)
class Attribute:
    """A complete Rust attribute bound to its source offsets."""

    start: int
    end: int
    body: str
    names: frozenset[str]


def git(*args: str, different: bool = False) -> str:
    """Read git output, accepting exit one only for a no-index difference."""
    result = subprocess.run(
        ["git", *args], check=False, capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode not in ((0, 1) if different else (0,)):
        raise subprocess.CalledProcessError(
            result.returncode, ["git", *args], result.stdout, result.stderr
        )
    return result.stdout


def paths_from(output: str) -> list[str]:
    """Decode NUL-delimited filenames without Git patch-header quoting."""
    return [path for path in output.split("\0") if path]


def show_or_empty(ref: str, path: str) -> str:
    """Read an optional tracked file at a revision."""
    exists = git("ls-tree", "--name-only", "-z", ref, "--", path)
    return git("show", f"{ref}:{path}") if exists else ""


def content_at(path: str) -> str:
    """Read current file content while treating deleted files as empty."""
    file = Path(path)
    return file.read_text(encoding="utf-8") if file.exists() else ""


def table(document: dict[str, object], key: str) -> dict[str, object]:
    """Narrow a TOML table at the parser boundary, rejecting invalid shapes."""
    value = document.get(key, {})
    if not isinstance(value, dict):
        raise TypeError(f"invalid TOML gate table: {key}")
    return cast("dict[str, object]", value)


def manifest_findings(ancestor: str, paths: list[str]) -> list[str]:
    """Compare lint and profile TOML values, including alternative spellings."""
    errors: list[str] = []
    for path in paths:
        if Path(path).name != "Cargo.toml" or Path(path).is_symlink():
            continue
        before_text = show_or_empty(ancestor, path)
        try:
            before = cast("dict[str, object]", tomllib.loads(before_text))
            after = cast("dict[str, object]", tomllib.loads(content_at(path)))
        except tomllib.TOMLDecodeError as error:
            errors.append(f"invalid TOML in {path}: {error}")
            continue
        previous = table(before, "lints")
        current = table(after, "lints")
        if not before_text and "package" in after:
            if current != {"workspace": True}:
                errors.append(f"new member must inherit workspace lints in {path}")
            # Inheritance is the only permitted new package lint declaration.
            previous = {"workspace": True}
        if (
            previous != current
            or table(table(before, "workspace"), "lints")
            != table(table(after, "workspace"), "lints")
            or table(before, "profile") != table(after, "profile")
        ):
            errors.append(f"[lints] or [profile] changed in {path}")
    return errors


def comment_end(source: str, start: int) -> int:
    """Find the end of a possibly nested Rust block comment."""
    depth = 1
    position = start + 2
    while depth:
        match = re.search(r"/\*|\*/", source[position:])
        if match is None:
            raise ValueError("unterminated Rust block comment")
        depth += 1 if match[0] == "/*" else -1
        position += match.end()
    return position


def lexical_end(source: str, match: re.Match[str]) -> int:
    """Find the end of a comment or literal matched by the Rust lexer."""
    if match[0] == "/*":
        return comment_end(source, match.start())
    if match.group("hashes") is not None:
        closing = '"' + match.group("hashes")
        found = source.find(closing, match.end())
        if found < 0:
            raise ValueError("unterminated Rust raw string")
        return found + len(closing)
    if match[0] == '"':
        string = re.match(r'"(?:\\.|[^"\\])*"', source[match.start() :], re.DOTALL)
        if string is None:
            raise ValueError("unterminated Rust string")
        return match.start() + string.end()
    return match.end()


def fenced_code(text: str) -> str:
    """Blank doc prose and fence delimiters, retaining hidden doctest lines."""
    fence = ""
    result: list[str] = []
    for line in text.splitlines(keepends=True):
        marker = re.match(r"[ \t]*(`{3,}|~{3,})(.*?)[\r\n]*$", line)
        if marker and not fence:
            fence = marker[1]
        elif (
            marker
            and marker[1][0] == fence[0]
            and len(marker[1]) >= len(fence)
            and not marker[2].strip()
        ):
            fence = ""
        elif fence:
            # Rustdoc compiles hidden lines after removing their '# ' prefix.
            hidden = re.match(r"[ \t]*#(?: |(?=\r?$))", line)
            result.append(" " * hidden.end() + line[hidden.end() :] if hidden else line)
            continue
        result.append("".join("\n" if c == "\n" else " " for c in line))
    return "".join(result)


def doc_string(source: str, start: int, end: int) -> tuple[str, list[int]]:
    """Decode Rust doc strings into contiguous slots inside their source literal."""
    opening = source.index('"', start)
    raw = source[start:opening].startswith("r")
    closing = end - (opening - start if raw else 0) - 1
    text: list[str] = []
    position = opening + 1
    while position < closing:
        character = source[position]
        position += 1
        if character == "\\" and not raw:
            escape = source[position]
            position += 1
            if escape in "\n\r":
                while position < closing and source[position].isspace():
                    position += 1
                continue
            if escape == "u":
                finish = source.index("}", position)
                character = chr(int(source[position + 1 : finish].replace("_", ""), 16))
                position = finish + 1
            elif escape == "x":
                character = chr(int(source[position : position + 2], 16))
                position += 2
            else:
                character = {
                    "n": "\n",
                    "r": "\r",
                    "t": "\t",
                    "0": "\0",
                    '"': '"',
                    "'": "'",
                    "\\": "\\",
                }[escape]
        text.append(character)
    return "".join(text), list(range(opening + 1, opening + 1 + len(text)))


def comment_documentation(
    source: str, match: re.Match[str], end: int
) -> tuple[int, str, list[int]]:
    """Collect one documentation comment block and its source offsets."""
    start = match.start()
    text = ""
    offsets: list[int] = []
    if match[0].startswith(("///", "//!")) and not match[0].startswith("////"):
        lines = re.match(
            r"(?:(?:///|//!)(?!/)[^\n]*(?:\n[ \t]*(?=///(?!/)|//!)|$|\n)) +",
            source[start:],
            re.VERBOSE,
        )
        if lines is None:
            raise ValueError("unparseable Rust doc comment")
        end = start + lines.end()
        for line in re.finditer(r"(?:///|//!)(?!/) ?([^\n]*)(\n|$)", source[start:end]):
            text += line[1] + line[2]
            offsets.extend(range(start + line.start(1), start + line.end()))
    elif source.startswith(("/**", "/*!"), start) and not source.startswith(
        ("/***", "/**/"), start
    ):
        body_start = start + 3
        body = source[body_start : end - 2]
        for line in re.finditer(r"[^\n]*\n|[^\n]+$", body):
            prefix = re.match(r"[ \t]*\* ?", line[0])
            skip = prefix.end() if prefix else 0
            text += line[0][skip:]
            offsets.extend(
                range(body_start + line.start() + skip, body_start + line.end())
            )
    return end, text, offsets


def documented_source(source: str, *, literals: bool = True, code: bool = True) -> str:
    """Replace documentation with fenced Rust at the original source offsets."""
    result = list(source)
    position = 0
    while match := LEXICAL.search(source, position):
        start = match.start()
        end = lexical_end(source, match)
        end, text, offsets = comment_documentation(source, match, end)
        if match[0] == '"' or match.group("hashes") is not None:
            attribute = re.search(r"#\s*!?\s*\[\s*doc\s*=\s*$", source[:start])
            if attribute and re.match(r"\s*\]", source[end:]):
                text, offsets = doc_string(source, start, end)
                start = attribute.start()
                closing = re.match(r"\s*\]", source[end:])
                if closing is not None:
                    end += closing.end()
        if offsets:
            result[start:end] = ["\n" if c == "\n" else " " for c in source[start:end]]
            if code:
                doctest = masked_source(fenced_code(text), literals=literals)
                for offset, character in zip(offsets, doctest, strict=True):
                    result[offset] = character
        position = end
    return "".join(result)


def masked_source(source: str, *, literals: bool = True) -> str:
    """Blank comments and literals while retaining fenced documentation code."""
    source = documented_source(source, literals=literals)
    result = list(source)
    position = 0
    while match := LEXICAL.search(source, position):
        start = match.start()
        end = lexical_end(source, match)
        if literals or match[0].startswith(("//", "/*")):
            result[start:end] = ["\n" if c == "\n" else " " for c in source[start:end]]
        position = end
    return "".join(result)


def comma_parts(body: str) -> list[str]:
    """Split an attribute argument list only at its outermost commas."""
    depth = 0
    start = 0
    parts: list[str] = []
    for index, character in enumerate(body):
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif character == "," and depth == 0:
            parts.append(body[start:index])
            start = index + 1
    parts.append(body[start:])
    return parts


def meta_counts(body: str, *, templates: bool = False) -> Counter[str]:
    """Count attribute names recursively without expanding macro placeholders."""
    head = re.match(r"\s*((?:r#)?\w+(?:::(?:r#)?\w+)*)", body)
    if head is None:
        if templates and body.lstrip().startswith("$"):
            return Counter()
        raise ValueError("unparseable Rust attribute")
    name = head[1].split("::")[-1].removeprefix("r#")
    names = Counter({name: 1})
    if name == "cfg_attr":
        arguments = body[head.end() :].strip()
        if not arguments.startswith("(") or not arguments.endswith(")"):
            raise ValueError("unparseable cfg_attr")
        for nested in comma_parts(arguments[1:-1])[1:]:
            if nested.strip():
                names.update(meta_counts(nested, templates=templates))
    return names


def attributes(mask: str, *, templates: bool = False) -> list[Attribute]:
    """Locate complete bracket-balanced attributes in masked Rust source."""
    result: list[Attribute] = []
    position = 0
    while match := re.search(r"#\s*!?\s*\[", mask[position:]):
        start = position + match.start()
        body_start = position + match.end()
        end = body_start
        depth = 1
        while depth and end < len(mask):
            depth += (mask[end] == "[") - (mask[end] == "]")
            end += 1
        if depth:
            raise ValueError("unterminated Rust attribute")
        body = mask[body_start : end - 1]
        result.append(
            Attribute(
                start, end, body, frozenset(meta_counts(body, templates=templates))
            )
        )
        position = end
    return result


def canonical_attribute(source: str) -> str:
    """Ignore comments and whitespace while retaining literal condition values."""
    return re.sub(r"\s+", "", source)


def module_spans(mask: str) -> list[tuple[str, int, int]]:
    """Keep existing module-qualified early-error test identities."""
    stack: list[int] = []
    closing: dict[int, int] = {}
    for position, character in enumerate(mask):
        if character == "{":
            stack.append(position)
        elif character == "}" and stack:
            closing[stack.pop()] = position
    return [
        (match[1], match.end() - 1, closing[match.end() - 1])
        for match in re.finditer(r"\bmod\s+(\w+)\s*\{", mask)
        if match.end() - 1 in closing
    ]


def item_attributes(
    source: str, mask: str, attrs: list[Attribute]
) -> dict[tuple[str, str], list[Attribute]]:
    """Bind adjacent outer attributes explicitly to their following item."""
    result: dict[tuple[str, str], list[Attribute]] = {}
    modules = module_spans(mask)
    group: list[Attribute] = []
    for index, attr in enumerate(attrs):
        if not group or mask[group[-1].end : attr.start].strip():
            group = []
        group.append(attr)
        end = attrs[index + 1].start if index + 1 < len(attrs) else len(mask)
        following = mask[attr.end : end]
        item = re.match(
            r"\s*(?:pub(?:\([^)]*\))?\s+)?(?:(?:async|const|unsafe)\s+)*(fn|mod)\s+(\w+)",
            following,
        )
        if item and not source[attr.start : attr.end].lstrip().startswith("#!"):
            parents = [name for name, start, end in modules if start < attr.start < end]
            result.setdefault((item[1], "::".join([*parents, item[2]])), []).extend(
                group
            )
    return result


def miri_only(body: str) -> bool:
    """Recognize conditions whose effects apply exclusively to Miri builds."""
    return bool(
        re.match(r"\s*(?:r#)?cfg_attr\s*\(\s*(?:r#)?miri\s*,", body)
        or re.fullmatch(
            r"\s*(?:r#)?cfg\s*\(\s*(?:r#)?miri\s*\)\s*",
            body,
        )
        or re.fullmatch(
            r"\s*(?:r#)?cfg\s*\(\s*(?:r#)?not\s*\(\s*(?:r#)?miri\s*\)\s*\)\s*",
            body,
        )
    )


def test_conditions(
    before: str,
    after: str,
    attrs: list[Attribute],
    changed: set[int],
    *,
    allowed: bool,
) -> list[str]:
    """Reject new cfg conditions on existing test functions and test modules."""
    old_mask, _ = macro_policy(
        masked_source(before), set(), allowed=True, source=before
    )
    old_items = item_attributes(before, old_mask, attributes(old_mask))
    new_mask, _ = macro_policy(masked_source(after), set(), allowed=True, source=after)
    new_items = item_attributes(after, new_mask, attrs)
    errors: list[str] = []
    for identity, old in old_items.items():
        is_test = (
            any("test" in attr.names for attr in old)
            if identity[0] == "fn"
            else any(re.search(r"\bcfg\s*\(\s*test\s*\)", attr.body) for attr in old)
        )
        if not is_test:
            continue
        previous = {canonical_attribute(before[attr.start : attr.end]) for attr in old}
        for attr in new_items.get(identity, []):
            if (
                attr.names & {"cfg", "cfg_attr"}
                and not (allowed and miri_only(attr.body))
                and touched(after, attr, changed)
                and canonical_attribute(after[attr.start : attr.end]) not in previous
            ):
                errors.append(f"test condition added or changed on {identity[1]}")
    return errors


def touched(source: str, attribute: Attribute, changed: set[int]) -> bool:
    """Check whether any added line intersects the entire post-change attribute."""
    first = source.count("\n", 0, attribute.start) + 1
    last = source.count("\n", 0, attribute.end) + 1
    return any(first <= line <= last for line in changed)


def changed_lines(patch: str) -> tuple[set[int], list[str], list[str]]:
    """Parse textual hunk positions; never derive authorization from headers."""
    changed: set[int] = set()
    added: list[str] = []
    removed: list[str] = []
    number = 0
    old_left = 0
    new_left = 0
    for line in patch.splitlines():
        if line.startswith("@@"):
            header = HUNK.match(line)
            if header is None:
                raise ValueError("unparseable diff hunk header")
            number = int(header[3])
            old_left = int(header[2] or "1")
            new_left = int(header[4] or "1")
        elif old_left or new_left:
            if line.startswith("+"):
                changed.add(number)
                added.append(line[1:])
                number += 1
                new_left -= 1
            elif line.startswith("-"):
                removed.append(line[1:])
                old_left -= 1
            elif line.startswith(" "):
                number += 1
                old_left -= 1
                new_left -= 1
            elif not line.startswith("\\"):
                raise ValueError("unparseable diff hunk content")
    if old_left or new_left:
        raise ValueError("incomplete diff hunk")
    return changed, added, removed


def ignore_findings(source: str, mask: str, *, miri: bool = False) -> list[str]:
    """Allow only reasoned ignore attributes conditional on a Miri build."""
    head = re.match(r"\s*(?:r#)?(\w+)", mask)
    if head is None:
        raise ValueError("unparseable Rust attribute")
    if head[1] == "ignore":
        if not miri:
            return ["#[ignore] added"]
        reason = re.fullmatch(
            r"""(?x)\s*(?:r\#)?ignore\s*=\s*
            (?:"(?P<quoted>(?:\\.|[^"\\])*)"|
            r(?P<hashes>\#*)"(?P<raw>.*?)"(?P=hashes))\s*""",
            source,
            re.DOTALL,
        )
        if reason is None or not (reason["quoted"] or reason["raw"] or "").strip():
            return ["Miri ignore requires a non-empty reason"]
    if head[1] != "cfg_attr":
        return []
    opening = mask.index("(", head.end())
    parts = comma_parts(mask[opening + 1 : mask.rfind(")")])
    conditional = miri or bool(re.fullmatch(r"\s*(?:r#)?miri\s*", parts[0]))
    offset = opening + 1 + len(parts[0]) + 1
    errors: list[str] = []
    for part in parts[1:]:
        if part.strip():
            errors.extend(
                ignore_findings(
                    source[offset : offset + len(part)], part, miri=conditional
                )
            )
        offset += len(part) + 1
    return errors


def attribute_findings(
    path: str, source: str, attr: Attribute, *, allowed: bool
) -> list[str]:
    """Govern suppressions, Miri exclusions, and panic test attributes."""
    errors: list[str] = []
    counts = meta_counts(attr.body, templates=True)
    if "allow" in attr.names:
        errors.extend([f"allow attribute added in {path}"] * counts["allow"])
    if "ignore" in attr.names:
        body_start = attr.end - 1 - len(attr.body)
        errors.extend(
            f"{message} in {path}"
            for message in ignore_findings(
                source[body_start : attr.end - 1],
                attr.body,
            )
        )
    if "should_panic" in attr.names:
        policy = "zero-panic policy requires tests to assert Result/Option values"
        errors.extend(
            [f"#[should_panic] added in {path}: {policy}"] * counts["should_panic"]
        )
    if not allowed:
        if attr.names & {"cfg", "cfg_attr"} and re.search(r"\bmiri\b", attr.body):
            errors.extend(
                [f"escape hatch outside allowlist in {path}: Miri"]
                * len(re.findall(r"\bmiri\b", attr.body))
            )
        skips = re.findall(r"\bmutants\s*::\s*(?:r#)?skip\b", attr.body)
        errors.extend(
            [f"escape hatch outside allowlist in {path}: mutants::skip"] * len(skips)
        )
        if "path" in attr.names:
            errors.extend(
                [f"escape hatch outside allowlist in {path}: path"] * counts["path"]
            )
    if "expect" in attr.names and not allowed:
        errors.extend(
            [f"escape hatch outside allowlist in {path}: expect"] * counts["expect"]
        )
    return errors


def policy_occurrences(
    path: str, source: str, *, allowed: bool
) -> list[tuple[Attribute, str]]:
    """Locate active policy occurrences before masking macro definitions."""
    source = documented_source(source, literals=False)
    mask = masked_source(source)
    occurrences = [
        (attr, message)
        for attr in attributes(mask, templates=True)
        for message in attribute_findings(path, source, attr, allowed=allowed)
    ]
    if allowed:
        return occurrences
    rules = {
        "unsafe": r"\bunsafe\b",
    }
    occurrences.extend(
        (
            Attribute(match.start(), match.end(), "", frozenset()),
            f"escape hatch outside allowlist in {path}: {kind}",
        )
        for kind, pattern in rules.items()
        for match in re.finditer(pattern, mask)
    )
    for match in re.finditer(r"\b(cfg|include)\s*!\s*[(\[{]", mask):
        end = bounded_tokens(mask, match.end() - 1)
        kind = "include!" if match[1] == "include" else "cfg!(miri)"
        if match[1] == "include" or re.search(r"\bmiri\b", mask[match.end() : end - 1]):
            occurrences.append(
                (
                    Attribute(match.start(), end, "", frozenset()),
                    f"escape hatch outside allowlist in {path}: {kind}",
                )
            )
    return occurrences


def source_findings(
    path: str,
    ancestor: str,
    changed: set[int],
    *,
    allowed: bool,
) -> list[str]:
    """Check each source file independently, including complete attributes."""
    after = content_at(path)
    before = show_or_empty(ancestor, path)
    current = policy_occurrences(path, after, allowed=allowed)
    old_source = documented_source(before, literals=False)
    new_source = documented_source(after, literals=False)
    old_counts = Counter(
        (message, " ".join(old_source[attr.start : attr.end].split()))
        for attr, message in policy_occurrences(path, before, allowed=allowed)
    )
    new_counts = Counter(
        (message, " ".join(new_source[attr.start : attr.end].split()))
        for attr, message in current
    )
    errors = [
        message
        for (message, _), count in (new_counts - old_counts).items()
        for _ in range(count)
    ]
    if not allowed and any(
        number in changed and re.search(r"\bunsafe\b", line)
        for number, line in enumerate(
            documented_source(after, code=False).splitlines(), 1
        )
    ):
        errors.append(f"escape hatch outside allowlist in {path}: unsafe")
    mask, macro_errors = macro_policy(
        masked_source(after), changed, allowed=allowed, source=after
    )
    errors.extend(f"{message} in {path}" for message in macro_errors)
    attrs = attributes(mask)
    errors.extend(
        f"{message} in {path}"
        for message in test_conditions(before, after, attrs, changed, allowed=allowed)
    )
    return errors


def count_findings(added: list[str], removed: list[str]) -> list[str]:
    """Retain the aggregate removed-test and assertion heuristics."""
    errors: list[str] = []
    for pattern, message in [
        (r"#\s*\[\s*(?:tokio::)?test\b", "net loss of #[test] functions"),
        (r"\bassert(?:_eq|_ne)?!", "net loss of assertions"),
    ]:
        if sum(bool(re.search(pattern, line)) for line in removed) > sum(
            bool(re.search(pattern, line)) for line in added
        ):
            errors.append(message)
    return errors


def symlink_findings(patterns: list[str]) -> list[str]:
    """Reject every proposed symlink lacking a trusted exact-path/glob approval."""
    errors: list[str] = []
    for folder, directories, files in os.walk(".", followlinks=False):
        directories[:] = [name for name in directories if name != ".git"]
        for name in [*directories, *files]:
            path = Path(folder) / name
            relative = path.as_posix().removeprefix("./")
            if path.is_symlink() and not any(
                fnmatch.fnmatchcase(relative, pattern) for pattern in patterns
            ):
                errors.append(f"symlink outside allowlist in {relative}")
    return errors


def proc_macro_findings(
    ancestor: str, paths: list[str], patterns: list[str]
) -> list[str]:
    """Require approval for every change belonging to a proc-macro package."""
    manifests = paths_from(git("ls-files", "-z"))
    manifests.extend(
        paths_from(git("ls-files", "--others", "--exclude-standard", "-z"))
    )
    manifests.extend(path for path in paths if Path(path).name == "Cargo.toml")
    packages: set[Path] = set()
    for name in set(manifests):
        if Path(name).name != "Cargo.toml" or Path(name).is_symlink():
            continue
        for content in (show_or_empty(ancestor, name), content_at(name)):
            try:
                document = cast("dict[str, object]", tomllib.loads(content))
            except tomllib.TOMLDecodeError as error:
                raise ValueError(f"invalid TOML in {name}: {error}") from error
            if table(document, "lib").get("proc-macro") is True:
                packages.add(Path(name).parent)
    return [
        f"proc-macro package change outside allowlist in {path}"
        for path in paths
        if any(Path(path).is_relative_to(package) for package in packages)
        and not any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
    ]


def build_script_findings(
    paths: list[str], patterns: list[str], custom: set[str] | None = None
) -> list[str]:
    """Require trusted approval for all changed build-script entry points."""
    return [
        f"build script change outside allowlist in {path}"
        for path in paths
        if (Path(path).name == "build.rs" or path in (custom or set()))
        and not any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
    ]


def findings(base: str) -> list[str]:
    """Check tracked and non-ignored untracked files without modifying the index."""
    ancestor = git("merge-base", base, "HEAD").strip()
    untracked = set(paths_from(git("ls-files", "--others", "--exclude-standard", "-z")))
    paths = sorted(
        set(paths_from(git("diff", "--no-renames", "--name-only", "-z", ancestor)))
        | untracked
    )
    errors = [
        f"protected gate file changed: {path}"
        for path in paths
        if PROTECTED.match(path) or Path(path).name in {".gitattributes", ".gitmodules"}
    ]
    errors.extend(manifest_findings(ancestor, paths))
    deleted = paths_from(
        git("diff", *DIFF_FLAGS, "--name-only", "-z", "--diff-filter=D", ancestor)
    )
    errors.extend(
        f"test file deleted: {path}"
        for path in deleted
        if path.startswith("tests/") or "/tests/" in path
    )
    patterns = [
        line.strip()
        for line in show_or_empty(ancestor, ".gate/escape-hatch-paths").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    errors.extend(build_script_findings(paths, patterns))
    errors.extend(symlink_findings(patterns))
    errors.extend(proc_macro_findings(ancestor, paths, patterns))
    all_added: list[str] = []
    all_removed: list[str] = []
    for path in paths:
        allowed = any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
        if Path(path).is_symlink():
            continue
        if not path.endswith(".rs"):
            continue
        patch = (
            git(
                "diff",
                *DIFF_FLAGS,
                "-U0",
                "--no-index",
                "--",
                "/dev/null",
                path,
                different=True,
            )
            if path in untracked
            else git("diff", *DIFF_FLAGS, "-U0", ancestor, "--", path)
        )
        changed, added, removed = changed_lines(patch)
        all_added.extend(added)
        all_removed.extend(removed)
        allowed = any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
        errors.extend(
            source_findings(
                path,
                ancestor,
                changed,
                allowed=allowed,
            )
        )
    return errors + count_findings(all_added, all_removed)


def bounded_tokens(mask: str, opening: int) -> int:
    """Bound a Rust token tree with all three delimiter types; fail on mismatch."""
    closing = {"{": "}", "(": ")", "[": "]"}
    stack = [closing[mask[opening]]]
    for position in range(opening + 1, len(mask)):
        character = mask[position]
        if character in closing:
            stack.append(closing[character])
        elif character in "})]":
            if character != stack.pop():
                raise ValueError("unbounded or mismatched macro token tree")
            if not stack:
                return position + 1
    raise ValueError("unterminated macro body")


def macro_policy(
    mask: str, changed: set[int], *, allowed: bool, source: str
) -> tuple[str, list[str]]:
    """Govern hash-bearing definitions and bare hash tokens in macro input."""
    ranges: list[tuple[int, int]] = []
    errors: list[str] = []
    for definition in re.finditer(r"\bmacro_rules\s*!", mask):
        head = re.match(r"\s*(?:r#)?\w+\s*([({\[])", mask[definition.end() :])
        if head is None:
            raise ValueError("cannot bound macro definition")
        opening = definition.end() + head.end() - 1
        end = bounded_tokens(mask, opening)
        body = mask[opening + 1 : end - 1]
        hash_tokens = bool(re.search(r"(?<!\w)#|\$\w+\s*(?:!|\[)", body))
        if (
            hash_tokens
            and touched(
                source, Attribute(definition.start(), end, "", frozenset()), changed
            )
            and not allowed
        ):
            errors.append("attribute-producing macro outside allowlist")
        ranges.append((opening, end))
    if not allowed:
        for token in re.finditer(r"(?<!\w)#", mask):
            if not re.match(r"#\s*!?\s*\[", mask[token.start() :]):
                errors.append("bare hash token outside allowlist")
    result = list(mask)
    for start, end in ranges:
        result[start:end] = ["\n" if c == "\n" else " " for c in mask[start:end]]
    return "".join(result), errors


def json_object(value: object) -> dict[str, object]:
    """Require a JSON object at an untrusted tool-output boundary."""
    if not isinstance(value, dict):
        raise TypeError("invalid inventory JSON object")
    return cast("dict[str, object]", value)


def nextest_inventory(output: str) -> dict[str, bool]:
    """Normalize recorded Nextest JSON into stable identities and ignored states."""
    document = json_object(cast("object", json.loads(output)))
    suites = json_object(document["rust-suites"])
    result: dict[str, bool] = {}
    for suite_value in suites.values():
        suite = json_object(suite_value)
        if suite.get("status", "listed") != "listed":
            raise ValueError("Nextest suite was not listed")
        package, binary = suite["package-name"], suite["binary-id"]
        if not isinstance(package, str) or not isinstance(binary, str):
            raise TypeError("invalid Nextest package or binary identity")
        for name, test_value in json_object(suite["testcases"]).items():
            ignored = json_object(test_value)["ignored"]
            if not isinstance(ignored, bool):
                raise TypeError("invalid Nextest ignored state")
            result[f"nextest:{package}:{binary}:{name}"] = ignored
    return result


def doctest_inventory(output: str, ignored_output: str = "") -> dict[str, bool]:
    """Read stable crate/item identities from rustdoc listings."""
    crate = ""
    ignored_lines = set(ignored_output.splitlines())
    result: dict[str, bool] = {}
    groups: dict[str, list[bool]] = {}
    for line in output.splitlines():
        heading = re.search(r"Doc-tests\s+(\S+)", line)
        if heading:
            crate = heading[1]
        elif line.endswith((": test", ": test (ignored)")):
            if not crate:
                raise ValueError("doctest listing without a crate identity")
            item = re.sub(r" \(line \d+\)", "", line.split(": test")[0])
            stem = f"doctest:{crate}:{item}"
            groups.setdefault(stem, []).append(
                line.endswith("(ignored)") or line in ignored_lines
            )
    for stem, states in groups.items():
        for index, ignored in enumerate(sorted(states), 1):
            result[f"{stem}:{index}"] = ignored
    return result


def compare_inventories(
    before: dict[str, bool], after: dict[str, bool], approved: set[str]
) -> list[str]:
    """Reject lost or newly ignored tests without exact trusted approvals."""
    errors: list[str] = []
    for identity, ignored in before.items():
        if identity in approved:
            continue
        if identity not in after or (not ignored and after[identity]):
            errors.append(
                "".join(
                    [
                        f"test inventory lost or newly ignored: {identity}; ",
                        "a human must approve removals/renames in trusted ",
                        ".gate/test-inventory-allowlist.toml",
                    ]
                )
            )
    return errors


def command_output(
    command: list[str], root: Path, *, combined: bool = False, target: str | None = None
) -> str:
    """Run inventory tooling with strict UTF-8 and retain useful failure output."""
    environment = {**os.environ, "CARGO_TERM_COLOR": "never"}
    if target is not None:
        if os.name == "nt":
            raise RuntimeError("inventory mode requires a POSIX host")
        wrapper = Path(target) / "cap-lints-rustc"
        _ = wrapper.write_text(
            f"""#!{sys.executable}
import os
import sys
os.execvp(sys.argv[1], [sys.argv[1], *sys.argv[2:], "--cap-lints=warn"])
""",
            encoding="utf-8",
        )
        wrapper.chmod(0o700)
        environment |= {
            "CARGO_TARGET_DIR": target,
            "RUSTC_WORKSPACE_WRAPPER": str(wrapper),
        }
    result = subprocess.run(
        command,
        cwd=root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if combined else subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=environment,
    )
    if result.returncode:
        raise ValueError(
            "\n".join(
                [
                    f"inventory command failed: {command}",
                    result.stdout,
                    result.stderr or "",
                ]
            )
        )
    return result.stdout


def workspace_packages(root: Path) -> list[dict[str, object]]:
    """Resolve workspace package metadata, including target kinds and membership."""
    output = command_output(
        ["cargo", "metadata", "--no-deps", "--format-version", "1", "--locked"], root
    )
    metadata = json_object(cast("object", json.loads(output)))
    members, packages = metadata["workspace_members"], metadata["packages"]
    if not isinstance(members, list) or not isinstance(packages, list):
        raise TypeError("invalid cargo metadata packages/members")
    ids = {
        member for member in cast("list[object]", members) if isinstance(member, str)
    }
    result = [
        json_object(value)
        for value in cast("list[object]", packages)
        if json_object(value)["id"] in ids
    ]
    if len(result) != len(ids):
        raise ValueError("cargo metadata omitted a workspace member")
    return result


def workspace_members(root: Path, base: str = "HEAD") -> list[str]:
    """Validate target ownership and require approval for custom build scripts."""
    manifests: list[str] = []
    custom: set[str] = set()
    for package in workspace_packages(root):
        manifest, targets = package.get("manifest_path"), package.get("targets")
        if not isinstance(manifest, str) or not isinstance(targets, list):
            raise TypeError("invalid cargo metadata manifest path/targets")
        directory = Path(manifest).resolve().parent
        for value in cast("list[object]", targets):
            target = json_object(value)
            source, kinds = target.get("src_path"), target.get("kind")
            if not isinstance(source, str) or not isinstance(kinds, list):
                raise TypeError("invalid cargo metadata target source/kind")
            file = Path(source).resolve()
            if not source.endswith(".rs") or not file.is_relative_to(directory):
                raise ValueError(
                    f"workspace target must be a .rs file inside its package: {source}"
                )
            if "custom-build" in kinds:
                custom.add(file.relative_to(root.resolve()).as_posix())
        manifests.append(manifest)
    if custom:
        ancestor = git("merge-base", base, "HEAD").strip()
        paths = sorted(
            set(paths_from(git("diff", "--no-renames", "--name-only", "-z", ancestor)))
            | set(paths_from(git("ls-files", "--others", "--exclude-standard", "-z")))
        )
        patterns = [
            line.strip()
            for line in show_or_empty(ancestor, ".gate/escape-hatch-paths").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        errors = build_script_findings(paths, patterns, custom)
        if errors:
            raise ValueError("; ".join(errors))
    return manifests


def library_names(root: Path) -> list[str]:
    """Select only workspace packages with a Cargo library target."""
    names: list[str] = []
    for package in workspace_packages(root):
        targets = package["targets"]
        name = package["name"]
        if not isinstance(targets, list) or not isinstance(name, str):
            raise TypeError("invalid cargo target metadata")
        for value in cast("list[object]", targets):
            kinds = json_object(value)["kind"]
            if not isinstance(kinds, list):
                raise TypeError("invalid cargo target kind")
            if any(
                kind in {"lib", "rlib", "dylib", "cdylib", "staticlib", "proc-macro"}
                for kind in cast("list[object]", kinds)
                if isinstance(kind, str)
            ):
                names.append(name)
                break
    return names


def doctest_command(root: Path) -> list[str] | None:
    """Build an applicable doctest command; binary-only workspaces have none."""
    names = library_names(root)
    if not names:
        return None
    return [
        "cargo",
        "test",
        "--doc",
        "--all-features",
        "--locked",
        *[argument for name in names for argument in ("--package", name)],
    ]


def member_findings(root: Path, base: str = "HEAD") -> list[str]:
    """Require inheritance in every resolved proposed workspace member manifest."""
    errors: list[str] = []
    for manifest in workspace_members(root, base):
        document = cast(
            "dict[str, object]",
            tomllib.loads(Path(manifest).read_text(encoding="utf-8")),
        )
        if table(document, "lints") != {"workspace": True}:
            errors.append(f"workspace member must inherit workspace lints: {manifest}")
    return errors


def has_packages(revision: str, checkout: Path) -> bool:
    """Require inventory unless the tree and checkout establish an empty base."""
    output = git("ls-tree", "-r", "-z", "--full-tree", revision)
    if output and not output.endswith("\0"):
        raise ValueError("unterminated git tree record")
    root_manifest = False
    uncertain = False
    for record in output.split("\0")[:-1]:
        match = re.fullmatch(
            r"([0-7]{6}) (blob|tree|commit) ([0-9a-f]{40}|[0-9a-f]{64})\t(.+)",
            record,
            flags=re.DOTALL,
        )
        if match is None:
            raise ValueError("malformed git tree record")
        mode, kind, _, path = match.groups()
        if mode == "120000" or kind == "commit":
            uncertain = True
        # Case-insensitive filesystems load any casing as the manifest.
        if path.casefold() == "cargo.toml":
            root_manifest = True
        elif path.rsplit("/", 1)[-1].casefold() == "cargo.toml":
            uncertain = True
    if uncertain:
        return True
    if not root_manifest:
        return False
    document = tomllib.loads((checkout / "Cargo.toml").read_text(encoding="utf-8"))
    return not set(document).issubset({"workspace", "profile"})


def collect_inventory(root: Path) -> dict[str, bool]:
    """Build each inventory with fresh outputs isolated from shared Cargo caches."""
    with tempfile.TemporaryDirectory(prefix="rust-inventory-target-") as target:
        return collect_with_target(root, target)


def collect_with_target(root: Path, target: str) -> dict[str, bool]:
    """List compiled Nextest tests and rustdoc tests, including ignored doctests."""
    common = ["--workspace", "--all-features", "--locked"]
    result = nextest_inventory(
        command_output(
            ["cargo", "nextest", "list", *common, "--message-format", "json"],
            root,
            target=target,
        )
    )
    applicable = doctest_command(root)
    if applicable is None:
        return result
    docs_command = [*applicable, "--", "--list"]
    docs_output = command_output(docs_command, root, combined=True, target=target)
    ignored_output = command_output(
        [*docs_command, "--ignored"], root, combined=True, target=target
    )
    docs = doctest_inventory(docs_output, ignored_output)
    return {**result, **docs}


def inventory_findings(base: str) -> list[str]:
    """Compare compiled test inventories and always remove the worktree."""
    root = Path.cwd()
    ancestor = git("merge-base", base, "HEAD").strip()
    errors = member_findings(root, base)
    trusted_text = show_or_empty(ancestor, ".gate/test-inventory-allowlist.toml")
    document = cast("dict[str, object]", tomllib.loads(trusted_text))
    entries = table(document, "removed-or-renamed").get("identities", [])
    if not isinstance(entries, list) or not all(
        isinstance(item, str) for item in cast("list[object]", entries)
    ):
        raise TypeError("invalid trusted test inventory allowlist")
    approved = set(cast("list[str]", entries))
    with tempfile.TemporaryDirectory(prefix="rust-inventory-") as temporary:
        baseline = Path(temporary) / "base"
        _ = git("worktree", "add", "--quiet", "--detach", str(baseline), ancestor)
        try:
            # A trusted base without packages has no tests to lose.
            before = (
                collect_inventory(baseline) if has_packages(ancestor, baseline) else {}
            )
            after = collect_inventory(root)
            errors.extend(compare_inventories(before, after, approved))
        finally:
            _ = git("worktree", "remove", "--force", str(baseline))
    return errors


def main() -> int:
    """Run the standalone governance check from the repository root."""
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "base", nargs="?", default="origin/main", help="Trusted base revision"
    )
    _ = parser.add_argument(
        "--inventory",
        action="store_true",
        help="Compare compiled tests and resolve workspace members",
    )
    _ = parser.add_argument(
        "--doctests", action="store_true", help="Run doctests for library packages only"
    )
    args = parser.parse_args(namespace=Options())
    try:
        if args.doctests:
            command = doctest_command(Path.cwd())
            if command is not None:
                _ = sys.stdout.write(command_output(command, Path.cwd(), combined=True))
            return 0
        errors = findings(args.base)
        if args.inventory:
            errors.extend(inventory_findings(args.base))
        else:
            skipped = "compiled test inventory, member resolution, doctest comparison"
            _ = sys.stderr.write(
                f"governance: {skipped} skipped; CI runs them with --inventory\n"
            )
    except FileNotFoundError as error:
        _ = sys.stderr.write(f"governance: missing executable: {error}\n")
        return 127
    except (
        subprocess.CalledProcessError,
        OSError,
        ValueError,
        TypeError,
        UnicodeError,
    ) as error:
        _ = sys.stderr.write(
            f"governance: invalid governed content or command failure: {error}\n"
        )
        return 1
    for error in errors:
        _ = sys.stderr.write(
            f"governance: invalid governed content or command failure: {error}\n"
        )
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
