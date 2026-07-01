#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pymupdf",
# ]
# ///
# ruff: noqa: C901, D103, PLR0911, PLR0912, PLR0915, PLR2004
"""Generate the local DS3 platinum guide agent corpus.

Input is the user-provided PDF export of:
https://psnprofiles.com/guide/18822-dark-souls-iii-platinum-walkthrough

Output schema is intentionally minimal JSONL for agent lookup:
  {"h": [heading_path], "k": kind, "t": cleaned_text}

This script is kept beside the generated corpus so cleanup rules and parameters
are auditable/regenerable if extraction bugs show up.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Literal, TypedDict

import fitz

TITLE = "Dark Souls III - Platinum Walkthrough"
URL = "https://psnprofiles.com/guide/18822-dark-souls-iii-platinum-walkthrough"
AUTHOR = "Xillynoc"
PUBLISHED = "2024-05-19"
UPDATED = "2026-06-24"
ChunkKind = Literal[
    "overview",
    "mechanics",
    "build",
    "covenant",
    "ending",
    "route",
    "spell",
    "dlc",
    "boss",
    "ring",
    "warning",
]


class GuideChunk(TypedDict):
    """Minimal agent lookup chunk schema."""

    h: list[str]
    k: ChunkKind
    t: str


UNICODE_TRANSLATION = str.maketrans(
    {
        "\u00a0": " ",
        "\u203a": ">",
        "\u2022": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
    },
)

FOOTER_PATTERNS = [
    re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2},\s*\d{1,2}:\d{2}\s*[AP]M\s*$"),
    re.compile(r"^\s*Dark Souls III - Platinum Walkthrough - PSNProfiles\.com\s*$"),
    re.compile(
        r"^\s*https://psnprofiles\.com/guide/18822-dark-souls-iii-platinum-walkthrough\s+\d+/200\s*$",
    ),
    re.compile(r"^\s*Loading\.\.\.\s*$"),
    re.compile(r"^\s*$"),
]
RESIDUAL_PATTERNS = [
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2},\s*\d{1,2}:\d{2}\s*[AP]M\b"),
    re.compile(r"Dark Souls III - Platinum Walkthrough - PSNProfiles\.com"),
    re.compile(
        r"https://psnprofiles\.com/guide/18822-dark-souls-iii-platinum-walkthrough\s*\d*/?200?",
    ),
    re.compile(
        r"\bNo 1 3 13 26 43 Trophies - 1,350 Points "
        r"PS4 RELATED GUIDES\b[\s\S]*?HOME FORUMS GUIDES LEADERBOARD "
        r"GAMES TROPHIES SESSIONS LOG IN CREATE ACCOUNT",
    ),
    re.compile(
        r"\bNo 1 3 13 26 43 Trophies - 1,350 Points "
        r"PS4 RELATED GUIDES\b[\s\S]*?(?=Shields |Item Type Description Trophied|$)",
    ),
    re.compile(r"\b2026 Gaming Profiles Ltd\b[\s\S]*?Cookie Settings"),
    re.compile(r"^New Game\+\+ \(The Usurpation of Fire\)\s+"),
]
CHROME_EXACT = {
    "GUIDES > DARK SOULS III - PLATINUM WALKTHROUGH",
    "GUIDE",
    "58 COMMENTS",
    "USER FAVOURITES",
    "RATINGS",
    "VIEWS",
    "A gameplay guide by",
    "A gameplay guide by Xillynoc",
    "Xillynoc",
    "Xillynoc - Published 19th May 2024",
    "Published 19th May 2024",
    "Published 19th May 2024 - Updated 24th June 2026",
    "Updated 24th June 2026",
    "78",
    "31 RATINGS",
    "75,152",
    "PSNProfiles is not affiliated with Sony or PlayStation in any way",
    "© 2026 Gaming Profiles Ltd",
    "Contact Us • Terms & Conditions • Privacy Policy",
    "Advertising • Delete/Restore Profile • Cookie Settings",
}
KNOWN_HEADINGS = {
    "OVERVIEW",
    "GAMEPLAY MECHANICS",
    "CHARACTER BUILD",
    "CEMETERY OF ASH",
    "FIRELINK SHRINE",
    "HIGH WALL OF LOTHRIC",
    "UNDEAD SETTLEMENT",
    "ROAD OF SACRIFICES",
    "CATHEDRAL OF THE DEEP",
    "FARRON KEEP",
    "CATACOMBS OF CARTHUS",
    "SMOULDERING LAKE",
    "IRITHYLL OF THE BOREAL VALLEY",
    "ANOR LONDO",
    "IRITHYLL DUNGEON",
    "PROFANED CAPITAL",
    "CONSUMED KING'S GARDEN",
    "UNTENDED GRAVES",
    "LOTHRIC CASTLE",
    "GRAND ARCHIVES",
    "ARCHDRAGON PEAK",
    "SPELL + RING CLEANUP/GRINDING",
    "ASHES OF ARIANDEL (DLC)",
    "THE RINGED CITY (DLC)",
    "KILN OF THE FIRST FLAME",
    "NEW GAME+ (THE END OF FIRE)",
    "NEW GAME++ (THE USURPATION OF FIRE)",
    "STRATEGY VIDEO",
    "BOSS FIGHT",
    "OFFLINE PLAYERS",
    "ONLINE PLAYERS",
}
NOT_HEADINGS = {
    "ITEM TYPE",
    "DESCRIPTION",
    "TROPHIED",
    "ATTRIBUTE",
    "ICON",
    "EFFECTS",
    "SOFT CAP(S)",
    "BUTTON",
    "ACTION",
}


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(UNICODE_TRANSLATION)
    text = "".join(
        " " if unicodedata.category(char) in {"Co", "So"} else char for char in text
    )
    return re.sub(r"[ \t]+", " ", text).strip()


def is_boilerplate(line: str) -> bool:
    return (
        (not line)
        or line in CHROME_EXACT
        or any(pattern.match(line) for pattern in FOOTER_PATTERNS)
    )


def is_heading(line: str) -> bool:
    candidate = line.strip().rstrip(":")
    if candidate in NOT_HEADINGS:
        return False
    if candidate in KNOWN_HEADINGS:
        return True
    if len(candidate) < 4 or len(candidate) > 80:
        return False
    letters = [char for char in candidate if char.isalpha()]
    if len(letters) < 3:
        return False
    if sum(char.isupper() for char in letters) / len(letters) < 0.85:
        return False
    return any(
        token in candidate
        for token in (
            "FIRELINK",
            "BONFIRE",
            "COVENANT",
            "NG+",
            "NEW GAME",
            "DLC",
            "CLEANUP",
            "ASHES",
            "RINGED",
            "KILN",
            "CASTLE",
            "KEEP",
            "SETTLEMENT",
            "CATHEDRAL",
            "CATACOMBS",
            "IRITHYLL",
            "ANOR",
            "DUNGEON",
            "CAPITAL",
            "GRAVES",
            "ARCHIVES",
            "PEAK",
            "OVERVIEW",
            "MECHANICS",
            "BUILD",
        )
    )


def reflow(lines: list[str]) -> list[str]:
    paragraphs: list[str] = []
    current = ""
    for line in lines:
        if not line:
            if current:
                paragraphs.append(current.strip())
                current = ""
            continue
        if is_heading(line):
            if current:
                paragraphs.append(current.strip())
                current = ""
            paragraphs.append(line)
            continue
        if not current:
            current = line
        elif re.match(
            r"^(Online Players|Offline Players|Note|Credit and thanks|\d+\.|"
            r"[A-Z][A-Za-z ]{1,30}:)\b",
            line,
        ):
            paragraphs.append(current.strip())
            current = line
        elif current.endswith("-") and line[:1].islower():
            current += line
        elif (
            current.endswith((".", "!", "?", ":", ";", ")"))
            and line[:1].isupper()
            and len(current) > 80
        ):
            paragraphs.append(current.strip())
            current = line
        else:
            current += " " + line
    if current:
        paragraphs.append(current.strip())
    return paragraphs


def classify(heading_path: list[str], text: str) -> ChunkKind:
    haystack = (" ".join(heading_path) + " " + text).lower()
    if "overview" in haystack:
        return "overview"
    if "mechanics" in haystack:
        return "mechanics"
    if (
        "sellsword" in haystack
        or "character build" in haystack
        or ("dex" in haystack and "build" in haystack)
    ):
        return "build"
    if (
        "covenant" in haystack
        or "proof of a concord" in haystack
        or "vertebra" in haystack
        or "sunlight medal" in haystack
        or "wolf's blood" in haystack
        or "human dregs" in haystack
    ):
        return "covenant"
    if (
        "ending" in haystack
        or "usurpation" in haystack
        or "link the fire" in haystack
        or "end of fire" in haystack
    ):
        return "ending"
    if "new game" in haystack or "journey 2" in haystack or "journey 3" in haystack:
        return "route"
    if (
        "miracle" in haystack
        or "sorcer" in haystack
        or "pyromanc" in haystack
        or "spell" in haystack
    ):
        return "spell"
    if (
        "dlc" in haystack
        or "ashes of ariandel" in haystack
        or "ringed city" in haystack
    ):
        return "dlc"
    if "boss" in haystack or "strategy video" in haystack:
        return "boss"
    if "ring" in haystack:
        return "ring"
    if "missable" in haystack or "do not" in haystack or "make sure" in haystack:
        return "warning"
    return "route"


def heading_title(text: str) -> str:
    return (
        text.title()
        .replace("Ng+", "NG+")
        .replace("Dlc", "DLC")
        .replace("King'S", "King's")
    )


def parse_pdf(pdf_path: Path) -> list[GuideChunk]:
    paragraphs: list[tuple[list[str], str]] = []
    heading_path = ["Overview"]
    with fitz.open(pdf_path) as doc:
        for page_index in range(doc.page_count):
            page_text = doc.load_page(page_index).get_text("text") or ""
            clean_lines: list[str] = []
            previous = None
            in_overview = page_index != 0
            for raw_line in page_text.splitlines():
                line = norm(raw_line)
                if line == "OVERVIEW":
                    in_overview = True
                if page_index == 0 and not in_overview:
                    continue
                if is_boilerplate(line):
                    continue
                if line == previous:
                    continue
                previous = line
                clean_lines.append(line)
            for paragraph in reflow(clean_lines):
                text = norm(paragraph)
                if not text or text == TITLE:
                    continue
                if is_heading(text):
                    if text in {"ONLINE PLAYERS", "OFFLINE PLAYERS", "STRATEGY VIDEO"}:
                        heading_path = [*heading_path[:1], heading_title(text)]
                    else:
                        heading_path = [heading_title(text)]
                else:
                    paragraphs.append((list(heading_path), text))
    return chunk_paragraphs(paragraphs)


def chunk_paragraphs(
    paragraphs: list[tuple[list[str], str]],
) -> list[GuideChunk]:
    chunks: list[GuideChunk] = []
    current_heading: list[str] | None = None
    current_parts: list[str] = []
    current_len = 0
    target = 1800
    maximum = 3200
    minimum = 250

    def flush() -> None:
        nonlocal current_heading, current_parts, current_len
        if current_parts:
            text = "\n\n".join(current_parts).strip()
            if text:
                heading = current_heading or ["Guide"]
                chunks.append({"h": heading, "k": classify(heading, text), "t": text})
        current_parts = []
        current_len = 0

    for heading, paragraph in paragraphs:
        paragraph_len = len(paragraph)
        if current_heading is None:
            current_heading = heading
        if heading != current_heading or (
            current_len and current_len + paragraph_len > maximum
        ):
            flush()
            current_heading = heading
        if paragraph_len > maximum:
            flush()
            current_heading = heading
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            buffer: list[str] = []
            buffer_len = 0
            for sentence in sentences:
                if buffer_len and buffer_len + len(sentence) > target:
                    text = " ".join(buffer).strip()
                    chunks.append(
                        {"h": heading, "k": classify(heading, text), "t": text},
                    )
                    buffer = [sentence]
                    buffer_len = len(sentence)
                else:
                    buffer.append(sentence)
                    buffer_len += len(sentence) + 1
            if buffer:
                text = " ".join(buffer).strip()
                chunks.append({"h": heading, "k": classify(heading, text), "t": text})
            current_heading = None
            continue
        current_parts.append(paragraph)
        current_len += paragraph_len + 2
        if current_len >= target:
            flush()
            current_heading = None
    flush()

    merged: list[GuideChunk] = []
    for chunk in chunks:
        if (
            merged
            and chunk["h"] == merged[-1]["h"]
            and len(chunk["t"]) < minimum
            and len(merged[-1]["t"]) + len(chunk["t"]) < maximum
        ):
            merged[-1]["t"] = merged[-1]["t"] + "\n\n" + chunk["t"]
            merged[-1]["k"] = classify(merged[-1]["h"], merged[-1]["t"])
        else:
            merged.append(chunk)
    for chunk in merged:
        text = chunk["t"]
        for pattern in RESIDUAL_PATTERNS:
            text = pattern.sub(" ", text)
        if chunk["h"] == ["Overview"]:
            text = re.sub(r"\bfor Anor Londo Firelink Shrine \(10\)[\s\S]*$", " ", text)
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r" *\n *", "\n", text).strip()
        chunk["t"] = text
    return [chunk for chunk in merged if len(chunk["t"]) >= 80]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the local DS3 platinum guide agent corpus.",
    )
    parser.add_argument("pdf", type=Path, help="Path to the PSNProfiles PDF export.")
    parser.add_argument(
        "outdir",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "resources"
        / "guides"
        / "ds3_plat_guide",
        help=(
            "Output directory for ds3-plat-guide.manifest.json and "
            "ds3-plat-guide.chunks.jsonl."
        ),
    )
    args = parser.parse_args(argv)
    pdf_path = args.pdf.expanduser().resolve()
    if not pdf_path.is_file():
        parser.error(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        parser.error(f"Input must be a PDF: {pdf_path}")
    outdir = args.outdir.expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    chunks = parse_pdf(pdf_path)
    chunks_path = outdir / "ds3-plat-guide.chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(
                json.dumps(chunk, ensure_ascii=False, separators=(",", ":")) + "\n",
            )
    manifest = {
        "title": TITLE,
        "author": AUTHOR,
        "url": URL,
        "published": PUBLISHED,
        "updated": UPDATED,
        "format": "ds3-guide-chunks-v1",
        "chunk_count": len(chunks),
        "source_pdf_name": pdf_path.name,
        "source_pdf_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "source_type": "user-provided PDF export",
        "copyable": False,
        "tracked_artifact": True,
        "source_pdf_tracked": False,
        "usage": [
            "local lookup",
            "transformed cited answers",
        ],
        "constraints": [
            "non-authoritative",
            "non-save-backed",
            "spoiler-heavy",
            "not relicensable",
        ],
        "preprocessing": {
            "pdf_boilerplate_removed": True,
            "page_numbers_removed": True,
            "line_wraps_reflowed": True,
            "unicode_normalized": True,
            "section_chunked": True,
            "row_schema": {"h": "heading path", "k": "kind", "t": "cleaned content"},
        },
    }
    (outdir / "ds3-plat-guide.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    sys.stdout.write(
        json.dumps(
            {"chunks": len(chunks), "kinds": Counter(chunk["k"] for chunk in chunks)},
            ensure_ascii=False,
            default=dict,
        )
        + "\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
