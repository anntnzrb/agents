# Copyright (c) 2026
"""Cut anchored source blocks into deterministic working units."""

import re
import sys
from copy import replace
from dataclasses import dataclass
from typing import TYPE_CHECKING
from zipfile import BadZipFile, ZipFile

from .config import fingerprint, section
from .data import (
    InputError,
    Manifest,
    Table,
    Unit,
    digest,
    integer,
    read_manifest,
    strings,
    write_json,
)
from .epub import Block, Publication, read_publication
from .images import MARKER
from .text import plain, protect, words

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True, kw_only=True)
class Draft:
    """A source unit before numbering and persistence."""

    title: str
    blocks: list[Block]
    kind: str = "body"
    separate: bool = False


def _title(blocks: list[Block]) -> str:
    return next(
        (plain(block.text) for block in blocks if block.kind == "heading"),
        "Front matter",
    )


def _count(blocks: list[Block]) -> int:
    return sum(len(words(plain(block.text))) for block in blocks)


def _cut(publication: Publication, depth: int) -> list[Draft]:
    positions = {
        anchor: index
        for index, block in enumerate(publication.blocks)
        for anchor in block.anchors
    }
    cuts: dict[int, str] = {}
    for entry in publication.entries:
        if (
            entry.depth <= depth
            and entry.anchor in positions
            and entry.anchor.split("#", 1)[0] not in publication.non_linear
        ):
            _ = cuts.setdefault(positions[entry.anchor], entry.title)
    if not cuts:
        cuts = {
            start: _title(publication.blocks[start:next_start])
            for (_, start), next_start in zip(
                publication.documents,
                [
                    *(start for _, start in publication.documents[1:]),
                    len(publication.blocks),
                ],
                strict=True,
            )
        }
    for (document, start), end in zip(
        publication.documents,
        [*(offset for _, offset in publication.documents[1:]), len(publication.blocks)],
        strict=True,
    ):
        if document in publication.non_linear and start < end:
            title = next(
                (
                    plain(block.text)
                    for block in publication.blocks[start:end]
                    if block.kind == "heading"
                ),
                next(
                    (
                        entry.title
                        for entry in publication.entries
                        if entry.anchor.split("#", 1)[0] == document
                    ),
                    "Notes",
                ),
            )
            cuts[start] = title
    for index, block in enumerate(publication.blocks):
        if (block.semantic and index == 0) or (
            index > 0 and block.semantic != publication.blocks[index - 1].semantic
        ):
            _ = cuts.setdefault(index, _title(publication.blocks[index:]))
    if not cuts:
        return []
    _ = cuts.setdefault(0, _title(publication.blocks[: min(cuts)]))
    starts = sorted(cuts)
    return [
        Draft(
            title=cuts[start],
            blocks=publication.blocks[start:end],
            separate=any(
                document in publication.non_linear and offset == start
                for document, offset in publication.documents
            ),
        )
        for start, end in zip(
            starts, [*starts[1:], len(publication.blocks)], strict=True
        )
    ]


def _strip(drafts: list[Draft]) -> list[Draft]:
    all_blocks = [block for draft in drafts for block in draft.blocks]
    start = next(
        (
            index + 1
            for index, block in enumerate(all_blocks)
            if "*** START OF" in plain(block.text).upper()
        ),
        0,
    )
    end = next(
        (
            index
            for index, block in enumerate(all_blocks)
            if "*** END OF" in plain(block.text).upper()
        ),
        len(all_blocks),
    )
    result: list[Draft] = []
    offset = 0
    for draft in drafts:
        kept = (
            draft.blocks
            if draft.separate
            else draft.blocks[
                max(0, start - offset) : max(0, min(len(draft.blocks), end - offset))
            ]
        )
        offset += len(draft.blocks)
        if any(block.text.strip() or block.images for block in kept):
            result.append(replace(draft, blocks=kept))
    return result


def _classify(drafts: list[Draft], patterns: list[str]) -> list[Draft]:
    result: list[Draft] = []
    for draft in drafts:
        text = " ".join(block.text for block in draft.blocks)
        license_text = re.search(
            r"project gutenberg", text, re.IGNORECASE
        ) and re.search(r"license|full terms|redistribut", text, re.IGNORECASE)
        semantic = next(
            (block.semantic for block in draft.blocks if block.semantic), ""
        )
        matter = (
            semantic == "matter"
            if semantic
            else (
                any(
                    re.search(pattern, draft.title, re.IGNORECASE)
                    for pattern in patterns
                )
                or license_text
            )
        )
        result.append(replace(draft, kind="matter" if matter else "body"))
    return result


def _merge_short(drafts: list[Draft], minimum: int) -> list[Draft]:
    result = list(drafts)
    index = 0
    while index < len(result):
        current = result[index]
        if (
            current.kind != "body"
            or current.separate
            or _count(current.blocks) >= minimum
            or len(result) == 1
        ):
            index += 1
            continue
        following_index = next(
            (
                offset
                for offset in range(index + 1, len(result))
                if result[offset].kind == "body" and not result[offset].separate
            ),
            None,
        )
        previous_index = next(
            (
                offset
                for offset in range(index - 1, -1, -1)
                if result[offset].kind == "body" and not result[offset].separate
            ),
            None,
        )
        if following_index is not None:
            following = result[following_index]
            result[following_index] = replace(
                following,
                title=f"{current.title}: {following.title}",
                blocks=current.blocks + following.blocks,
            )
            del result[index]
        elif previous_index is not None:
            previous = result[previous_index]
            result[previous_index] = replace(
                previous, blocks=previous.blocks + current.blocks
            )
            del result[index]
            index = previous_index
        else:
            index += 1
    return result


def _split_large_blocks(blocks: list[Block], maximum: int) -> list[Block]:
    result: list[Block] = []
    for block in blocks:
        tokens = list(re.finditer(r"\S+", block.text))
        if len(words(plain(block.text))) <= maximum:
            result.append(block)
            continue
        # A single oversized paragraph cannot be split at a paragraph boundary.
        # Preserve all text by inserting deterministic word boundaries.
        chunks: list[str] = []
        start = 0
        for token in tokens:
            if (
                len(words(plain(block.text[start : token.end()]))) > maximum
                and token.start() > start
            ):
                chunks.append(block.text[start : token.start()].strip())
                start = token.start()
        chunks.append(block.text[start:].strip())
        result.extend(
            replace(
                block,
                text=chunk,
                anchors=block.anchors if index == 0 else (),
                images=block.images if index == 0 else 0,
            )
            for index, chunk in enumerate(chunks)
        )
    return result


def split_blocks(blocks: list[Block], maximum: int) -> list[list[Block]]:
    """Split at headings or balanced block boundaries without dropping text."""
    blocks = _split_large_blocks(blocks, maximum)
    parts: list[list[Block]] = []
    while _count(blocks) > maximum:
        total = _count(blocks)
        part_count = (total + maximum - 1) // maximum
        target = total / part_count
        cumulative = 0
        candidates: list[tuple[int, int, bool]] = []
        for index, block in enumerate(blocks[:-1], 1):
            cumulative += _count([block])
            if cumulative > maximum:
                break
            if cumulative:
                candidates.append((index, cumulative, blocks[index].kind == "heading"))
        headings = [
            candidate
            for candidate in candidates
            if candidate[2] and candidate[1] >= target / 2
        ]
        eligible = headings or candidates
        if not eligible:
            raise InputError("Cannot split source block")
        cut, _, _ = min(eligible, key=lambda item: (abs(item[1] - target), item[0]))
        parts.append(blocks[:cut])
        blocks = blocks[cut:]
    if blocks:
        parts.append(blocks)
    return parts


def markdown(title: str, blocks: list[Block], part: int, total: int) -> str:
    """Render source Markdown without duplicating the unit title."""
    heading = title + (f" (part {part}/{total})" if total > 1 else "")
    pieces = [f"# {heading}".replace("{", r"\{").replace("}", r"\}")]
    minimum = min(
        (block.level for block in blocks if block.kind == "heading"), default=1
    )
    for block in blocks:
        text = block.text
        if not text:
            continue
        if block.kind == "image":
            pieces.append(text)
            continue
        if block.kind == "heading":
            if plain(text).casefold() == title.casefold():
                continue
            text = "#" * min(6, block.level - minimum + 2) + " " + text
        elif block.kind == "quote":
            text = "\n".join("> " + line if line else ">" for line in text.splitlines())
        elif block.kind == "list_item":
            text = (
                "  " * max(0, block.depth - 1)
                + ("1. " if block.ordered else "- ")
                + text
            )
        elif block.kind == "verse":
            text = "\n".join(line + "  " for line in text.splitlines())
        elif block.kind == "paragraph":
            text = re.sub(r"(?m)^(\d+)\. ", r"\1\\. ", text)
        pieces.append(re.sub(r"(?<!\\)([{}])", r"\\\1", text))
    return "\n\n".join(pieces).rstrip("\n") + "\n"


def ingest(book_path: Path, work: Path, config: Table) -> Manifest:
    """Ingest a publication and leave all adapted files untouched."""
    try:
        source_bytes = book_path.read_bytes()
        with ZipFile(book_path) as archive:
            publication = read_publication(archive)
    except (BadZipFile, KeyError) as error:
        raise InputError(f"Invalid EPUB: {error}") from error
    settings = section(config, "ingest")
    drafts = _cut(publication, integer(settings["toc_depth"]))
    if settings["strip_gutenberg"]:
        drafts = _strip(drafts)
    drafts = _merge_short(
        _classify(drafts, strings(settings["matter_patterns"])),
        integer(settings["min_unit_words"]),
    )
    old = read_manifest(work) if (work / "manifest.json").exists() else None
    old_hashes = {unit["id"]: unit["sha256"] for unit in old["units"]} if old else {}
    units: list[Unit] = []
    work.mkdir(parents=True, exist_ok=True)
    (work / "source").mkdir(exist_ok=True)
    if publication.images:
        (work / "images").mkdir(exist_ok=True)
        for name, content in sorted(publication.images.items()):
            _ = (work / name).write_bytes(content)
    for chapter, draft in enumerate(drafts, 1):
        parts = (
            split_blocks(draft.blocks, integer(settings["max_unit_words"]))
            if draft.kind == "body"
            else [draft.blocks]
        )
        for part, blocks in enumerate(parts, 1):
            uid = f"{len(units) + 1:03}"
            source = markdown(draft.title, blocks, part, len(parts))
            sha = digest(source)
            if (
                uid in old_hashes
                and old_hashes[uid] != sha
                and (work / "adapted" / f"{uid}.md").exists()
            ):
                _ = sys.stderr.write(f"Warning: source changed for adapted/{uid}.md\n")
            _ = (work / "source" / f"{uid}.md").write_text(source, encoding="utf-8")
            body = "\n\n".join(
                plain(block.text, block_syntax=False)
                for block in blocks
                if block.kind != "image"
            )
            facts = protect(
                body,
                [plain(block.text) for block in blocks if block.kind == "quote"],
                [plain(block.text) for block in blocks if block.kind == "heading"],
                publication.book["language"],
                config,
            )
            facts["images"] = [
                match.group(1)
                for block in blocks
                if block.kind == "image"
                for match in MARKER.finditer(block.text)
            ]
            write_json(work / "protected" / f"{uid}.json", facts)
            units.append(
                Unit(
                    id=uid,
                    chapter=chapter,
                    part=part,
                    parts=len(parts),
                    title=draft.title,
                    kind=draft.kind,
                    words=facts["words"],
                    images=sum(block.images for block in blocks),
                    source=f"source/{uid}.md",
                    sha256=sha,
                )
            )
    manifest = Manifest(
        schema=1,
        source={"file": book_path.name, "sha256": digest(source_bytes)},
        book=publication.book,
        config_sha256=fingerprint(config),
        cover=publication.cover_name,
        units=units,
    )
    if publication.cover_name and publication.cover_bytes:
        _ = (work / publication.cover_name).write_bytes(publication.cover_bytes)
    write_json(work / "manifest.json", manifest)
    return manifest
