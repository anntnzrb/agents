"""Steam identity extraction and conservative title matching."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlsplit

STEAM_PATH_RE = re.compile(r"/(app|sub|bundle)/(\d+)(?:/|$)", re.IGNORECASE)
EDITION_WORDS = frozenset(
    {
        "edition",
        "deluxe",
        "ultimate",
        "complete",
        "collection",
        "goty",
        "game",
        "of",
        "the",
        "year",
    },
)
EDITION_MARKERS = frozenset(
    {
        "anniversary",
        "collection",
        "collector",
        "complete",
        "definitive",
        "deluxe",
        "enhanced",
        "gold",
        "goty",
        "premium",
        "remastered",
        "standard",
        "ultimate",
    },
)


def steam_identity(query: str) -> dict[str, str] | None:
    """Extract a Steam app/sub/bundle identity from a URL or typed prefix."""
    value = query.strip()
    typed = re.fullmatch(r"(?i)(app|sub|bundle)[:/\s]+(\d+)", value)
    if typed:
        return {"type": typed.group(1).lower(), "id": typed.group(2)}
    if value.isdigit():
        return {"type": "app", "id": value}
    match = STEAM_PATH_RE.search(urlsplit(value).path)
    if match:
        return {"type": match.group(1).lower(), "id": match.group(2)}
    return None


def normalized_title(value: str, *, drop_edition_words: bool = False) -> str:
    """Normalize punctuation and Unicode while preserving meaningful tokens."""
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    text = text.casefold().replace("&", " and ")
    tokens = re.findall(r"[a-z0-9]+", text)
    if drop_edition_words:
        tokens = [token for token in tokens if token not in EDITION_WORDS]
    return " ".join(tokens)


def title_score(query: str, candidate: str) -> float:
    """Return a 0..1 title score combining sequence and token agreement."""
    left = normalized_title(query)
    right = normalized_title(candidate)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence = SequenceMatcher(None, left, right).ratio()
    simplified_left = normalized_title(query, drop_edition_words=True)
    simplified_right = normalized_title(candidate, drop_edition_words=True)
    edition_score = SequenceMatcher(None, simplified_left, simplified_right).ratio()
    score = max(sequence * 0.65 + token_score * 0.35, edition_score * 0.94)
    if _edition_markers(left) != _edition_markers(right):
        score = min(score, 0.87)
    return round(score, 4)


def _edition_markers(normalized: str) -> set[str]:
    tokens = set(normalized.split())
    markers = tokens & EDITION_MARKERS
    if {"game", "of", "the", "year"} <= tokens:
        markers.add("goty")
    return markers


def choose_candidate(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    title_key: str = "title",
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Rank candidates and return a match only when confidence is usable."""
    scored = [
        {
            **candidate,
            "match_score": title_score(query, str(candidate.get(title_key, ""))),
        }
        for candidate in candidates
    ]
    scored.sort(key=lambda item: item["match_score"], reverse=True)
    best = scored[0] if scored and scored[0]["match_score"] >= 0.62 else None
    return best, scored
