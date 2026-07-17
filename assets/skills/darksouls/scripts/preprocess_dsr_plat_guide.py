# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pymupdf",
# ]
# ///
"""Stream a user-provided PSNProfiles DSR PDF into local guide chunks.

The PDF itself is never copied or tracked. Extraction is page-by-page and the
output is a compact, transformed JSONL corpus for local lookup only.
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

TITLE = "Dark Souls Remastered - Platinum Walkthrough"
FALLBACK_URL = "https://psnprofiles.com/guide/16645-dark-souls-remastered-platinum-walkthrough-guide"
DEFAULT_PDF = Path(
    "C:/Users/Nil/Downloads/Dark Souls Remastered - Platinum Walkthrough Guide • PSNProfiles.com.pdf",
)
DEFAULT_OUTDIR = (
    Path(__file__).resolve().parents[1] / "resources" / "guides" / "dsr_plat_guide"
)
ChunkKind = Literal[
    "overview",
    "mechanics",
    "build",
    "route",
    "boss",
    "weapon",
    "ring",
    "spell",
    "covenant",
    "achievement",
    "warning",
    "farming",
]


class GuideChunk(TypedDict):
    h: list[str]
    k: ChunkKind
    t: str


UNICODE_TRANSLATION = str.maketrans(
    {
        "\u00a0": " ",
        "\u2022": "-",
        "\u203a": ">",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\ufeff": "",
    },
)
KNOWN_HEADINGS = {
    "OVERVIEW",
    "INTRODUCTION",
    "GAMEPLAY MECHANICS",
    "CHARACTER BUILD",
    "BUILDS",
    "WALKTHROUGH",
    "ROADMAP",
    "TROPHY ROADMAP",
    "BOSS FIGHTS",
    "BOSSES",
    "BOSS STRATEGY",
    "WEAPONS",
    "RINGS",
    "SPELLS",
    "MIRACLES",
    "PYROMANCIES",
    "SORCERIES",
    "COVENANTS",
    "ACHIEVEMENTS",
    "TROPHIES",
    "ITEM CLEANUP",
    "RING CLEANUP",
    "SPELL CLEANUP",
    "FARMING",
    "GRINDING",
    "NEW GAME+",
    "NEW GAME++",
    "ENDINGS",
    "ONLINE PLAY",
    "OFFLINE PLAY",
    "DLC",
    "THE PAINTED WORLD OF ARIAMIS",
    "ARTORIAS OF THE ABYSS",
    "THE KILN OF THE FIRST FLAME",
    "KILN OF THE FIRST FLAME",
    "CHARACTER QUESTS",
}
NOT_HEADINGS = {
    "ITEM",
    "ITEMS",
    "DESCRIPTION",
    "LOCATION",
    "EFFECT",
    "EFFECTS",
    "NOTES",
    "TYPE",
    "REQUIREMENTS",
    "ICON",
    "NAME",
    "QUANTITY",
    "TROPHY",
}
CHROME_EXACT = {
    "GUIDE",
    "WALKTHROUGH",
    "USER FAVOURITES",
    "RATINGS",
    "VIEWS",
    "COMMENTS",
    "LOADING...",
    "HOME",
    "FORUMS",
    "GUIDES",
    "LEADERBOARD",
    "GAMES",
    "TROPHIES",
    "SESSIONS",
    "LOG IN",
    "CREATE ACCOUNT",
    "GUIDE CONTENTS",
    "RELATED GUIDES",
    "PS4",
    "PSNPROFILES.COM",
    "PSNProfiles is not affiliated with Sony or PlayStation in any way",
    "Contact Us - Terms & Conditions - Privacy Policy",
    "Advertising - Delete/Restore Profile - Cookie Settings",
}
CHROME_PATTERNS = [
    re.compile(
        r"^\s*Dark Souls Remastered\s*-\s*Platinum Walkthrough(?:\s*Guide)?(?:\s*-\s*PSNProfiles\.com)?\s*$",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*GUIDES\s*>.*DARK SOULS REMASTERED.*$", re.IGNORECASE),
    re.compile(
        r"^\s*https?://psnprofiles\.com/guide/[^ ]+\s+\d+\s*/\s*\d+\s*$",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*https?://psnprofiles\.com/guide/[^ ]+\s*$", re.IGNORECASE),
    re.compile(
        r"^\s*\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}\s*[AP]M\s*$",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*\d+\s*/\s*\d+\s*$"),
    re.compile(r"^\s*Page\s+\d+(?:\s+of\s+\d+)?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:\d+[,.]?\d*|\d+\s+RATINGS|\d+\s+COMMENTS)\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:A gameplay guide by|Published|Updated)\b.*$", re.IGNORECASE),
    re.compile(
        r"^\s*[A-Za-z][A-Za-z0-9_-]+\s+and\s+[A-Za-z][A-Za-z0-9_-]+\s*$",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*©\s*20\d{2}.*$", re.IGNORECASE),
    re.compile(r"^\s*No\s+\d+.*Troph(?:y|ies).*$", re.IGNORECASE),
    re.compile(
        r"^\s*(?:HOME|FORUMS|GUIDES|LEADERBOARD|GAMES|TROPHIES|SESSIONS|LOG IN|CREATE ACCOUNT)(?:\s+(?:HOME|FORUMS|GUIDES|LEADERBOARD|GAMES|TROPHIES|SESSIONS|LOG IN|CREATE ACCOUNT))+\s*$",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*(?:Part\s+\d+:[^:]+)\s+(?:Part\s+\d+:.*){1,}$", re.IGNORECASE),
    re.compile(
        r"^\s*\d+\s+Trophies\s+-\s+[\d,]+\s+Points.*RELATED GUIDES.*$",
        re.IGNORECASE,
    ),
]
INLINE_CHROME_PATTERNS = [
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}\s*[AP]M\b", re.IGNORECASE),
    re.compile(
        r"\bDark Souls Remastered\s*-\s*Platinum Walkthrough(?:\s*Guide)?\s*-\s*PSNProfiles\.com\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:HOME|FORUMS|GUIDES|LEADERBOARD|GAMES|TROPHIES|SESSIONS|LOG IN|CREATE ACCOUNT){2,}\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bGUIDE CONTENTS\b", re.IGNORECASE),
]


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(UNICODE_TRANSLATION)
    text = "".join(
        " " if unicodedata.category(char) in {"Co", "So", "Cf"} else char
        for char in text
    )
    text = re.sub(r"(?i)\b([a-z]{2,})\1\b", r"\1", text)
    text = re.sub(r"(?i)\b([a-z]{2,})(?:\s+\1){1,}\b", r"\1", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def clean_inline_chrome(line: str) -> str:
    for pattern in INLINE_CHROME_PATTERNS:
        line = pattern.sub(" ", line)
    return norm(line)


def is_boilerplate(line: str) -> bool:
    return (
        not line
        or line.casefold() in {item.casefold() for item in CHROME_EXACT}
        or len(re.findall(r"\bPart\s+\d+\s*:", line, flags=re.IGNORECASE)) >= 3
        or any(pattern.match(line) for pattern in CHROME_PATTERNS)
    )


def page_lines(page: fitz.Page) -> list[str]:
    """Extract text blocks so sidebars/header chrome do not merge into prose."""
    lines: list[str] = []
    for block in page.get_text("blocks", sort=True):
        if len(block) < 5 or (len(block) >= 7 and block[6] != 0):
            continue
        # PSNProfiles exports the navigation/contents sidebar as a right column.
        if float(block[0]) > 400:
            continue
        for raw_line in str(block[4]).splitlines():
            lines.append(clean_inline_chrome(norm(raw_line)))
        lines.append("")
    return lines


def is_heading(line: str) -> bool:
    candidate = line.strip().rstrip(":").strip()
    upper = candidate.upper()
    if upper in NOT_HEADINGS or len(candidate) < 4 or len(candidate) > 90:
        return False
    if upper in {item.upper() for item in KNOWN_HEADINGS}:
        return True
    if re.match(r"^PART\s+\d+\s*:", upper):
        return True
    letters = [char for char in candidate if char.isalpha()]
    if (
        len(letters) < 4
        or sum(char.isupper() for char in letters) / len(letters) < 0.86
    ):
        return False
    return any(
        token in upper
        for token in (
            "BOSS",
            "BUILD",
            "WALKTHROUGH",
            "ROADMAP",
            "WEAPON",
            "RING",
            "SPELL",
            "MIRACLE",
            "PYROMANC",
            "SORCER",
            "COVENANT",
            "TROPHY",
            "ACHIEV",
            "FARM",
            "GRIND",
            "ENDING",
            "NEW GAME",
            "DLC",
            "KILN",
            "PAINTED WORLD",
            "ARTORIAS",
            "MECHANIC",
            "INTRODUCTION",
            "OVERVIEW",
        )
    )


def heading_title(text: str) -> str:
    candidate = text.strip().rstrip(":").strip()
    if candidate.isupper():
        return candidate.title().replace("Ng+", "NG+").replace("Dlc", "DLC")
    return candidate


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
            paragraphs.append(line)
            current = ""
            continue
        starts_item = bool(re.match(r"^(?:[-*]|\d+[.)]|[A-Za-z][.)])\s+", line))
        if not current or starts_item:
            if current:
                paragraphs.append(current.strip())
            current = line
        elif current.endswith("-") and line[:1].islower():
            current += line
        elif (
            current.endswith((".", "!", "?", ":", ";", ")"))
            and line[:1].isupper()
            and len(current) > 90
        ):
            paragraphs.append(current.strip())
            current = line
        else:
            current += " " + line
    if current:
        paragraphs.append(current.strip())
    return paragraphs


def classify(heading: list[str], text: str) -> ChunkKind:
    heading_text = " ".join(heading).lower()
    haystack = f"{heading_text} {text.lower()}"
    if heading_text == "overview" or "introduction" in heading_text:
        return "overview"
    if re.match(r"part\s+\d+\s*:", heading_text) or "walkthrough" in heading_text:
        return "route"
    if "character build" in heading_text or "build" in heading_text:
        return "build"
    if "covenant" in heading_text:
        return "covenant"
    if "ring" in heading_text:
        return "ring"
    if any(
        token in heading_text for token in ("spell", "miracle", "pyromanc", "sorcer")
    ):
        return "spell"
    if "trophy" in heading_text or "achievement" in heading_text:
        return "achievement"
    if "boss" in heading_text:
        return "boss"
    if "weapon" in heading_text:
        return "weapon"
    if "farming" in heading_text or "grinding" in heading_text:
        return "farming"
    if "mechanic" in heading_text:
        return "mechanics"
    if "warning" in heading_text:
        return "warning"
    if "trophy" in haystack or "achievement" in haystack:
        return "achievement"
    if "boss" in haystack or "strategy" in haystack:
        return "boss"
    if "weapon" in haystack or "shield" in haystack or "upgrade" in haystack:
        return "weapon"
    if "ring" in haystack:
        return "ring"
    if any(token in haystack for token in ("spell", "miracle", "pyromanc", "sorcer")):
        return "spell"
    if "covenant" in haystack:
        return "covenant"
    if any(token in haystack for token in ("farm", "grind", "souls per", "drop rate")):
        return "farming"
    if "build" in haystack or "class" in haystack or "stat" in haystack:
        return "build"
    if "mechanic" in haystack or "combat" in haystack or "stamina" in haystack:
        return "mechanics"
    if (
        "warning" in haystack
        or "missable" in haystack
        or "do not" in haystack
        or "make sure" in haystack
    ):
        return "warning"
    return "route"


def split_long(text: str, target: int, maximum: int) -> list[str]:
    if len(text) <= maximum:
        return [text]
    parts: list[str] = []
    buffer = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if buffer and len(buffer) + len(sentence) + 1 > target:
            parts.append(buffer.strip())
            buffer = sentence
        elif len(sentence) > maximum and not buffer:
            parts.extend(
                sentence[start : start + target].strip()
                for start in range(0, len(sentence), target)
            )
        else:
            buffer = f"{buffer} {sentence}".strip()
    if buffer:
        parts.append(buffer)
    return [part for part in parts if part]


def stream_chunks(pdf_path: Path, chunks_path: Path) -> dict[str, object]:
    sha = hashlib.sha256()
    with pdf_path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            sha.update(block)
    counters: Counter[str] = Counter()
    chunk_count = total_chars = page_count = pages_with_text = removed_chrome = (
        extracted_chars
    ) = 0
    headings_seen: set[str] = set()
    url = FALLBACK_URL
    authors: list[str] = []
    heading_path = ["Overview"]
    current_heading: list[str] | None = None
    current_parts: list[str] = []
    current_len = 0
    target, maximum = 1800, 3200

    chunks_path.parent.mkdir(parents=True, exist_ok=True)
    with chunks_path.open("w", encoding="utf-8") as output, fitz.open(pdf_path) as doc:
        page_count = doc.page_count
        for page_index in range(page_count):
            page_text = "\n".join(page_lines(doc.load_page(page_index)))
            extracted_chars += len(page_text)
            pages_with_text += bool(page_text.strip())
            clean_lines: list[str] = []
            metadata_text = norm(page_text)
            if author_match := re.search(
                r"A gameplay guide by\s+(.+?)(?=\s*(?:-|•)\s*Published\b)",
                metadata_text,
                re.IGNORECASE,
            ):
                candidate = re.sub(
                    r"^(?:A gameplay guide by\s*)+",
                    "",
                    author_match.group(1).strip(),
                    flags=re.IGNORECASE,
                )
                for author in re.split(r"\s+and\s+", candidate, flags=re.IGNORECASE):
                    if author and author not in authors:
                        authors.append(author)
            previous = None
            pending_author = False
            for raw_line in page_text.splitlines():
                line = clean_inline_chrome(norm(raw_line))
                if re.search(r"A gameplay guide by", line, re.IGNORECASE):
                    pending_author = True
                if pending_author:
                    if re.search(r"\bPublished\b", line, re.IGNORECASE):
                        pending_author = False
                    removed_chrome += 1
                    continue
                if url_match := re.search(
                    r"https?://psnprofiles\.com/guide/[A-Za-z0-9_-]+",
                    line,
                    re.IGNORECASE,
                ):
                    url = url_match.group(0)
                if is_boilerplate(line):
                    removed_chrome += 1
                    continue
                if line == previous:
                    removed_chrome += 1
                    continue
                previous = line
                clean_lines.append(line)
            for paragraph in reflow(clean_lines):
                text = norm(paragraph)
                if not text or text.casefold() == TITLE.casefold():
                    continue
                if is_heading(text):
                    title = heading_title(text)
                    heading_path = (
                        [title] if title.casefold() != "overview" else ["Overview"]
                    )
                    headings_seen.add(title)
                    continue
                for piece in split_long(text, target, maximum):
                    if current_heading is None:
                        current_heading = list(heading_path)
                    if heading_path != current_heading or (
                        current_len and current_len + len(piece) + 2 > maximum
                    ):
                        if current_parts:
                            rendered = "\n\n".join(current_parts).strip()
                            if len(rendered) >= 80:
                                row: GuideChunk = {
                                    "h": current_heading or ["Overview"],
                                    "k": classify(
                                        current_heading or ["Overview"],
                                        rendered,
                                    ),
                                    "t": rendered,
                                }
                                output.write(
                                    json.dumps(
                                        row,
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                    )
                                    + "\n",
                                )
                                chunk_count += 1
                                counters[row["k"]] += 1
                                total_chars += len(rendered)
                        current_parts, current_len = [], 0
                        current_heading = list(heading_path)
                    current_parts.append(piece)
                    current_len += len(piece) + 2
                    if current_len >= target:
                        rendered = "\n\n".join(current_parts).strip()
                        if len(rendered) >= 80:
                            row = {
                                "h": current_heading or ["Overview"],
                                "k": classify(
                                    current_heading or ["Overview"],
                                    rendered,
                                ),
                                "t": rendered,
                            }
                            output.write(
                                json.dumps(
                                    row,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                )
                                + "\n",
                            )
                            chunk_count += 1
                            counters[row["k"]] += 1
                            total_chars += len(rendered)
                        current_parts, current_len, current_heading = [], 0, None
        if current_parts:
            rendered = "\n\n".join(current_parts).strip()
            if len(rendered) >= 80:
                row = {
                    "h": current_heading or ["Overview"],
                    "k": classify(current_heading or ["Overview"], rendered),
                    "t": rendered,
                }
                output.write(
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n",
                )
                chunk_count += 1
                counters[row["k"]] += 1
                total_chars += len(rendered)
    return {
        "sha256": sha.hexdigest(),
        "url": url,
        "authors": authors or ["Unknown (PDF metadata not explicit)"],
        "page_count": page_count,
        "pages_with_text": pages_with_text,
        "extracted_chars": extracted_chars,
        "removed_chrome_lines": removed_chrome,
        "heading_count": len(headings_seen),
        "chunk_count": chunk_count,
        "chunk_kind_counts": dict(sorted(counters.items())),
        "total_chunk_chars": total_chars,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the local DSR platinum guide corpus from a user-provided PDF.",
    )
    parser.add_argument("pdf", nargs="?", type=Path, default=DEFAULT_PDF)
    parser.add_argument("outdir", nargs="?", type=Path, default=DEFAULT_OUTDIR)
    args = parser.parse_args(argv)
    pdf_path = args.pdf.expanduser().resolve()
    if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
        parser.error(f"PDF not found or not a PDF: {pdf_path}")
    outdir = args.outdir.expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    chunks_path = outdir / "dsr-plat-guide.chunks.jsonl"
    stats = stream_chunks(pdf_path, chunks_path)
    manifest = {
        "title": TITLE,
        "authors": stats["authors"],
        "url": stats["url"],
        "format": "dsr-guide-chunks-v1",
        "chunk_count": stats["chunk_count"],
        "source_pdf_name": pdf_path.name,
        "source_pdf_sha256": stats["sha256"],
        "source_type": "user-provided PSNProfiles PDF export",
        "source_pdf_tracked": False,
        "tracked_artifact": True,
        "copyable": False,
        "usage": ["local guide lookup", "transformed, provenance-labeled answers only"],
        "constraints": [
            "non-authoritative walkthrough; verify mechanics against game data",
            "copyrighted source is not redistributed",
            "PDF is not copied or tracked",
            "spoiler-heavy source; caller must gate spoilers",
            "no save-file claims are inferred from this corpus",
        ],
        "provenance": {
            "boundary": "Only transformed/reflowed excerpts are stored; source PDF remains user-local and is not an output artifact.",
            "citation": "PSNProfiles guide URL and local chunk heading path; do not present chunks as official game documentation.",
        },
        "extraction": {
            "page_count": stats["page_count"],
            "pages_with_text": stats["pages_with_text"],
            "extracted_chars": stats["extracted_chars"],
            "removed_chrome_lines": stats["removed_chrome_lines"],
            "heading_count": stats["heading_count"],
            "chunk_kind_counts": stats["chunk_kind_counts"],
            "total_chunk_chars": stats["total_chunk_chars"],
            "min_chunk_chars": None,
            "max_chunk_chars": None,
            "quality": "page-block text extraction with Unicode normalization, browser/PDF chrome removal, duplicate-line suppression, heading inference, paragraph reflow, and bounded chunking",
        },
        "preprocessing": {
            "streamed_sha256": True,
            "page_by_page": True,
            "pdf_boilerplate_removed": True,
            "page_numbers_removed": True,
            "line_wraps_reflowed": True,
            "unicode_normalized": True,
            "section_chunked": True,
            "target_chunk_chars": 1800,
            "max_chunk_chars": 3200,
            "row_schema": {
                "h": "heading path",
                "k": "conservative kind",
                "t": "cleaned transformed content",
            },
        },
    }
    lengths: list[int] = []
    with chunks_path.open(encoding="utf-8") as rows:
        for line in rows:
            lengths.append(len(json.loads(line)["t"]))
    if lengths:
        manifest["extraction"]["min_chunk_chars"] = min(lengths)
        manifest["extraction"]["max_chunk_chars"] = max(lengths)
    (outdir / "dsr-plat-guide.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    sys.stdout.write(
        json.dumps(
            {
                "chunks": stats["chunk_count"],
                "pages": stats["page_count"],
                "sha256": stats["sha256"],
                "url": stats["url"],
                "authors": stats["authors"],
            },
            ensure_ascii=False,
        )
        + "\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
