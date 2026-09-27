"""Parse OMP terminal output into structured fields."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import SearchSource

ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
OSC_RE = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")
HEADER_RE = re.compile(r"Web Search:\s*(?P<provider>.+?)\s+(?P<count>\d+)\s+sources?\b")
SECTION_RE = re.compile(
    r"[-─]{3,}\s*(?P<name>Answer|Sources|Metadata)\b", re.IGNORECASE
)
SOURCE_RE = re.compile(
    r"^(?:[+*-]|[├└─]+\s*)\s*(?P<title>.+?)\s+"
    r"\((?P<domain>[^();·]+?)(?:[;·]\s*(?P<ageIn>[^()]+?))?\)"
    r"(?:\s*[·;]\s*(?P<ageOut>.+?))?$"
)
MORE_LINES_RE = re.compile(r"(?:…|\.\.\.)\s*\d+\s+more\s+lines")
SECRET_RE = re.compile(r"\bsk-[a-z0-9_-]{8,}\b", re.IGNORECASE)
ASSIGNMENT_SECRET_RE = re.compile(
    r"(\b[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET)\b\s*[=:]\s*)\S+", re.IGNORECASE
)
AUTH_SECRET_RE = re.compile(r"(\bAuthorization\s*:\s*Bearer\s+)\S+", re.IGNORECASE)


def strip_terminal_controls(value: str) -> str:
    """Remove ANSI/OSC escape sequences and normalize newlines."""
    cleaned = OSC_RE.sub("", value)
    cleaned = ANSI_RE.sub("", cleaned)
    return cleaned.replace("\r\n", "\n").replace("\r", "\n")


def redact(value: str) -> str:
    """Mask API keys, token assignments, and bearer credentials."""
    cleaned = SECRET_RE.sub("<redacted>", value)
    cleaned = ASSIGNMENT_SECRET_RE.sub(r"\1<redacted>", cleaned)
    return AUTH_SECRET_RE.sub(r"\1<redacted>", cleaned)


def frame_content(line: str) -> str:
    """Strip box-drawing frame borders and trailing whitespace."""
    content = line
    if "│" in content:
        first_idx = content.index("│")
        content = content[first_idx + 1 :]
        if "│" in content:
            last_idx = content.rindex("│")
            content = content[:last_idx]
    return content.rstrip()


@dataclass(frozen=True)
class ParsedSearchOutput:
    """Structured fields extracted from one OMP search transcript."""

    query: str
    provider: str
    answer: str
    sources: list[SearchSource]
    truncated: bool
    parsed: bool
    cleaned_raw: str


def parse_search_output(raw: str, fallback_query: str) -> ParsedSearchOutput:
    """Parse OMP search output into query, provider, answer, and sources."""
    cleaned = strip_terminal_controls(raw)
    lines = cleaned.split("\n")
    provider: str | None = None
    actual_query = fallback_query
    answer_lines: list[str] = []
    sources: list[SearchSource] = []
    section: str | None = None
    started = False

    for line in lines:
        if not started:
            header_match = HEADER_RE.search(line)
            provider_group = header_match.group("provider") if header_match else None
            if provider_group:
                provider = provider_group.strip()
                started = True
                continue

        if "---" in line or "───" in line:
            section_match = SECTION_RE.search(line)
            name_group = section_match.group("name") if section_match else None
            if name_group:
                section = name_group.lower()
                started = True
                continue
            if section is not None:
                break

        content = frame_content(line)
        trimmed = content.strip()

        if re.match(r"^query:\s*", trimmed, re.IGNORECASE):
            actual_query = (
                re.sub(r"^query:\s*", "", trimmed, flags=re.IGNORECASE).strip()
                or fallback_query
            )
            continue

        if section == "answer":
            answer_lines.append(content)
        elif section == "sources":
            match = SOURCE_RE.match(trimmed)
            title = match.group("title") if match else None
            domain = match.group("domain") if match else None
            age_in = match.group("ageIn") if match else None
            age_out = match.group("ageOut") if match else None
            age = age_in or age_out
            if title and domain:
                sources.append(
                    {
                        "title": title.strip(),
                        "domain": domain.strip(),
                        "age": age.strip() if age else None,
                    }
                )
        elif section == "metadata" and re.match(
            r"^provider:\s*", trimmed, re.IGNORECASE
        ):
            provider = (
                re.sub(r"^provider:\s*", "", trimmed, flags=re.IGNORECASE).strip()
                or provider
            )

    while answer_lines and not answer_lines[0]:
        answer_lines.pop(0)
    while answer_lines and not answer_lines[-1]:
        answer_lines.pop()

    answer = "\n".join(answer_lines)
    truncated = bool(MORE_LINES_RE.search(cleaned))
    parsed = bool(provider or answer or len(sources) > 0)

    return ParsedSearchOutput(
        query=actual_query,
        provider=provider or "unknown",
        answer=answer,
        sources=sources,
        truncated=truncated,
        parsed=parsed,
        cleaned_raw=cleaned,
    )
