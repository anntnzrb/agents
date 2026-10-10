# Copyright (c) 2026
"""Render and package a deterministic EPUB3 with compatibility navigation."""

import html
import math
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from .adapted import BodyBlock, Parsed, Span, parse, render_blocks, render_inline
from .config import labels, section
from .data import InputError, Manifest, Table, Unit, integer, string
from .images import MARKER, image_media, image_path
from .text import unescape_braces, words
from .work import CheckError, check

if TYPE_CHECKING:
    from pathlib import Path

CONTAINER = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="EPUB/package.opf" '
    'media-type="application/oebps-package+xml" />'
    "</rootfiles></container>"
)
SOURCE_NOTE = (
    '<p class="pending">This section uses the original source text; '
    "adaptation is pending.</p>"
)

CSS = (
    "body { line-height: 1.5; } .progress { font-size: .9em; } "
    "blockquote { margin: 1em; } img { max-width: 100%; } "
    ".aside { font-style: italic; } "
    "p.aside { margin-left: 1em; padding-left: .75em; "
    "border-left: 1px solid currentColor; }\n"
)


class MissingExecutableError(RuntimeError):
    """An explicitly requested external validator is missing."""


def xhtml(title: str, body: str, lang: str) -> str:
    """Wrap escaped content in a valid EPUB XHTML document."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" '
        f'xml:lang="{html.escape(lang)}" lang="{html.escape(lang)}"><head>'
        f"<title>{html.escape(title)}</title>"
        '<link rel="stylesheet" type="text/css" href="style.css" />'
        f"</head><body>{body}</body></html>"
    )


def _source_blocks(source: str) -> list[BodyBlock]:
    blocks: list[BodyBlock] = []
    for paragraph in source.partition("\n")[2].strip().split("\n\n"):
        lines = paragraph.splitlines()
        if not lines:
            continue
        first = lines[0]
        if match := MARKER.fullmatch(paragraph):
            blocks.append(
                BodyBlock(
                    kind="image",
                    spans=[],
                    line=1,
                    image=image_path(match.group(1)),
                    alt=unescape_braces(match.group(2)),
                )
            )
            continue
        kind, level = "paragraph", 0
        content = paragraph
        if first.startswith("#"):
            kind, level = "heading", min(4, len(first) - len(first.lstrip("#")))
            content = "\n".join([first.lstrip("# "), *lines[1:]])
        elif first.startswith(">"):
            kind = "quote"
            content = "\n".join(
                line.removeprefix(">").removeprefix(" ") for line in lines
            )
        elif re.match(r"^(?:- |\d+\. )", first):
            kind = "list_item"
            content = "\n".join([first.partition(" ")[2], *lines[1:]])
        blocks.append(
            BodyBlock(
                kind=kind,
                spans=[Span(kind="text", text=unescape_braces(content))],
                line=1,
                level=level,
                ordered=kind == "list_item" and first[0].isdigit(),
                number=first.split(".", 1)[0]
                if kind == "list_item" and first[0].isdigit()
                else "",
            )
        )
    return blocks


def _directive(parsed: Parsed, name: str, local: dict[str, str], style: str) -> str:
    items = parsed.directives.get(name, [])
    if not items:
        return ""
    label = html.escape(local[name])
    if name in ("idea", "question", "why"):
        return f"<p><strong>{label}:</strong> {render_inline(items[0], style)}</p>"
    kind = "ul" if name == "recap" else "ol"
    content = "".join(f"<li>{render_inline(item, style)}</li>" for item in items)
    return f"<h2>{label}</h2><{kind}>{content}</{kind}>"


def _part_content(
    work: Path, unit: Unit, local: dict[str, str], config: Table
) -> tuple[str, list[tuple[str, str]], int]:
    path = work / "adapted" / f"{unit['id']}.md"
    if unit["kind"] == "matter" or not path.exists():
        note = SOURCE_NOTE if unit["kind"] == "body" else ""
        return (
            note
            + render_blocks(
                _source_blocks((work / unit["source"]).read_text(encoding="utf-8"))
            ),
            [],
            unit["words"],
        )
    parsed = parse(path.read_text(encoding="utf-8"))
    style = string(section(config, "build")["aside_style"])
    before = "".join(
        _directive(parsed, name, local, style) for name in ("idea", "question")
    )
    after = "".join(
        _directive(parsed, name, local, style)
        for name in ("why", "recap", "quiz", "answers")
    )
    return (
        before + render_blocks(parsed.blocks, style) + after,
        parsed.glosses,
        len(words(parsed.body_text)),
    )


def _modified() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch is None:
        return "2000-01-01T00:00:00Z"
    try:
        return datetime.fromtimestamp(int(epoch), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError, OSError) as error:
        raise InputError("Invalid SOURCE_DATE_EPOCH") from error


def _navpoint(index: int, path: str, label: str) -> str:
    return (
        f'<navPoint id="nav-{index}" playOrder="{index}"><navLabel>'
        f"<text>{html.escape(label)}</text></navLabel>"
        f'<content src="{html.escape(path)}" /></navPoint>'
    )


def _navigation(
    title: str, links: list[tuple[str, str]], identifier: str, lang: str
) -> tuple[str, str]:
    entries = "".join(
        f'<li><a href="{html.escape(path)}">{html.escape(label)}</a></li>'
        for path, label in links
    )
    body = (
        f'<nav epub:type="toc" id="toc"><h1>{html.escape(title)}</h1>'
        f"<ol>{entries}</ol></nav>"
    )
    nav = xhtml(title, body, lang)
    points = "".join(
        _navpoint(index, path, label) for index, (path, label) in enumerate(links, 1)
    )
    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        f'<head><meta name="dtb:uid" content="{identifier}" />'
        '<meta name="dtb:depth" content="1" />'
        '<meta name="dtb:totalPageCount" content="0" />'
        '<meta name="dtb:maxPageNumber" content="0" /></head>'
        f"<docTitle><text>{html.escape(title)}</text></docTitle><navMap>{points}</navMap></ncx>"
    )
    return nav, ncx


def _package(
    manifest: Manifest,
    title: str,
    identifier: str,
    resources: list[tuple[str, str, str, str]],
    spine: list[str],
) -> str:
    authors = "".join(
        f"<dc:creator>{html.escape(author)}</dc:creator>"
        for author in manifest["book"]["authors"]
    )
    items = "".join(
        f'<item id="{uid}" href="{html.escape(path)}" media-type="{media}"'
        + (f' properties="{properties}"' if properties else "")
        + " />"
        for uid, path, media, properties in resources
    )
    references = "".join(f'<itemref idref="{uid}" />' for uid in spine)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="book-id">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:identifier id="book-id">{identifier}</dc:identifier>'
        f"<dc:title>{html.escape(title)}</dc:title>"
        f"{authors}<dc:language>{html.escape(manifest['book']['language'])}</dc:language>"
        f'<meta property="dcterms:modified">{_modified()}</meta></metadata>'
        f'<manifest>{items}</manifest><spine toc="ncx">{references}</spine></package>'
    )


def _write_zip(out: Path, files: list[tuple[str, str | bytes]]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(out, "w") as archive:
        for name, content in files:
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_STORED if name == "mimetype" else ZIP_DEFLATED
            entry.create_system = 0
            entry.external_attr = 0x20
            archive.writestr(
                entry, content.encode("utf-8") if isinstance(content, str) else content
            )


def _chapters(
    work: Path, manifest: Manifest, config: Table
) -> tuple[
    list[tuple[str, str | bytes]],
    list[tuple[str, str]],
    dict[str, tuple[str, str, str]],
]:
    settings = section(config, "build")
    local = labels(config, manifest["book"]["language"])
    groups: dict[int, list[Unit]] = defaultdict(list)
    for unit in manifest["units"]:
        if unit["kind"] == "body" or settings["include_matter"]:
            groups[unit["chapter"]].append(unit)
    total = sum(units[0]["kind"] == "body" for units in groups.values())
    index = 0
    files: list[tuple[str, str | bytes]] = []
    links: list[tuple[str, str]] = []
    glossary: dict[str, tuple[str, str, str]] = {}
    for chapter, units in sorted(groups.items()):
        title = units[0]["title"]
        path = f"chapter-{chapter:03}.xhtml"
        sections: list[str] = []
        chapter_words = 0
        for unit in sorted(units, key=lambda item: item["part"]):
            content, terms, part_words = _part_content(work, unit, local, config)
            chapter_words += part_words
            label = (
                f"<h2>Part {unit['part']}/{unit['parts']}</h2>"
                if unit["parts"] > 1
                else ""
            )
            sections.append(
                f'<section id="unit-{unit["id"]}">{label}{content}</section>'
            )
            for term, gloss in terms:
                _ = glossary.setdefault(
                    term.casefold(), (term, gloss, f"{path}#unit-{unit['id']}")
                )
        progress = ""
        if units[0]["kind"] == "body":
            index += 1
            progress = (
                '<p class="progress">'
                + html.escape(
                    local["progress"].format(
                        index=index,
                        total=total,
                        percent=round(index / total * 100),
                        minutes=math.ceil(
                            chapter_words / integer(settings["words_per_minute"])
                        ),
                    )
                )
                + "</p>"
            )
        body = f"<h1>{html.escape(title)}</h1>{progress}{''.join(sections)}"
        files.append((f"EPUB/{path}", xhtml(title, body, manifest["book"]["language"])))
        links.append((path, title))
    return files, links, glossary


def _glossary_entry(term: str, gloss: str, path: str) -> str:
    return (
        f'<dt><a href="{html.escape(path)}">{html.escape(term)}</a></dt>'
        f"<dd>{html.escape(gloss)}</dd>"
    )


def build(
    work: Path,
    manifest: Manifest,
    config: Table,
    out: Path,
    *,
    allow_pending: bool = False,
) -> None:
    """Check every body unit, then build and optionally validate the EPUB."""
    reports, book = check(work, manifest, config, [], all_units=True)
    failing = [report["unit"] for report in reports if report["status"] == "fail"]
    pending = [report["unit"] for report in reports if report["status"] == "pending"]
    book_failures = [gate["id"] for gate in book if gate["status"] == "fail"]
    if failing or book_failures or (pending and not allow_pending):
        failures = ", ".join(failing + book_failures) or "none"
        waiting = ", ".join(pending) or "none"
        raise CheckError(f"Build refused; failing: {failures}; pending: {waiting}")
    title = string(section(config, "build")["title_template"]).format(
        title=manifest["book"]["title"]
    )
    identifier = f"urn:elaborate:{manifest['source']['sha256']}"
    lang = manifest["book"]["language"]
    files, links, glossary = _chapters(work, manifest, config)
    resources: list[tuple[str, str, str, str]] = [
        ("nav", "nav.xhtml", "application/xhtml+xml", "nav"),
        ("ncx", "toc.ncx", "application/x-dtbncx+xml", ""),
        ("style", "style.css", "text/css", ""),
    ]
    spine: list[str] = []
    cover = manifest["cover"]
    if cover is not None:
        files.insert(0, (f"EPUB/{cover}", (work / cover).read_bytes()))
        cover_body = (
            f'<section epub:type="cover"><img src="{html.escape(cover)}" '
            'alt="Cover" /></section>'
        )
        files.insert(1, ("EPUB/cover.xhtml", xhtml("Cover", cover_body, lang)))
        resources.extend(
            (
                ("cover-image", cover, image_media(cover), "cover-image"),
                ("cover", "cover.xhtml", "application/xhtml+xml", ""),
            )
        )
        spine.append("cover")
        links.insert(0, ("cover.xhtml", "Cover"))
    image_files = sorted(
        {
            image_path(element.get("src", ""))
            for _, content in files
            if isinstance(content, str)
            for element in ET.fromstring(content).iter()  # noqa: S314 - XML-escaped renderer output
            if element.tag.endswith("}img")
            and element.get("src", "").startswith("images/")
        }
    )
    for index, name in enumerate(image_files):
        files.append((f"EPUB/{name}", (work / name).read_bytes()))
        resources.append((f"image-{index}", name, image_media(name), ""))
    for index, (path, _) in enumerate(links):
        if path == "cover.xhtml":
            continue
        uid = f"chapter-{index}"
        resources.append((uid, path, "application/xhtml+xml", ""))
        spine.append(uid)
    if glossary:
        label = labels(config, lang)["glossary"]
        entries = "".join(_glossary_entry(*glossary[key]) for key in sorted(glossary))
        files.append(
            (
                "EPUB/glossary.xhtml",
                xhtml(label, f"<h1>{html.escape(label)}</h1><dl>{entries}</dl>", lang),
            )
        )
        resources.append(("glossary", "glossary.xhtml", "application/xhtml+xml", ""))
        spine.append("glossary")
        links.append(("glossary.xhtml", label))
    nav, ncx = _navigation(title, links, identifier, lang)
    _write_zip(
        out,
        [
            ("mimetype", "application/epub+zip"),
            ("META-INF/container.xml", CONTAINER),
            (
                "EPUB/package.opf",
                _package(manifest, title, identifier, resources, spine),
            ),
            ("EPUB/nav.xhtml", nav),
            ("EPUB/toc.ncx", ncx),
            ("EPUB/style.css", CSS),
            *files,
        ],
    )


def validate_epub(out: Path) -> None:
    """Run an explicitly requested external EPUB validator."""
    executable = shutil.which("epubcheck")
    if executable is None:
        raise MissingExecutableError("Required executable not found: epubcheck")
    completed = subprocess.run(
        [executable, str(out)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        shell=False,
    )
    if completed.returncode:
        raise CheckError(f"epubcheck failed:\n{completed.stdout}\n{completed.stderr}")
