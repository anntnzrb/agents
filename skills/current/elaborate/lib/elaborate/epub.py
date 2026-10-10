# Copyright (c) 2026
"""Read EPUB metadata, navigation, and anchored XHTML blocks."""

import posixpath
import re
import sys
import xml.etree.ElementTree as ET
from copy import deepcopy, replace
from dataclasses import dataclass, field
from html.entities import name2codepoint
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from .data import Book, InputError, digest
from .images import MARKER, MEDIA, image_media

if TYPE_CHECKING:
    from zipfile import ZipFile

EPUB_NS = "http://www.idpf.org/2007/ops"
BLOCK_TAGS = frozenset(
    (
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "dl",
        "dt",
        "dd",
        "figure",
        "figcaption",
        "footer",
        "header",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "thead",
        "tr",
        "ul",
    )
)
MATTER_TYPES = frozenset(
    (
        "toc",
        "copyright-page",
        "dedication",
        "index",
        "acknowledgements",
        "acknowledgments",
        "colophon",
        "cover",
        "title-page",
        "titlepage",
        "bibliography",
        "frontmatter",
        "backmatter",
    )
)
BODY_TYPES = frozenset(("bodymatter", "chapter", "text"))


@dataclass(frozen=True, slots=True, kw_only=True)
class Block:
    """A source block carrying anchors and image counts."""

    kind: str
    text: str
    anchors: tuple[str, ...] = ()
    level: int = 0
    ordered: bool = False
    depth: int = 0
    images: int = 0
    semantic: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class Entry:
    """A navigation entry at its original nesting depth."""

    title: str
    anchor: str
    depth: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Publication:
    """Resolved publication data without an open archive."""

    book: Book
    blocks: list[Block]
    entries: list[Entry]
    documents: list[tuple[str, int]]
    cover_name: str | None
    cover_bytes: bytes | None
    images: dict[str, bytes] = field(default_factory=dict)
    non_linear: tuple[str, ...] = ()


def tag(element: ET.Element) -> str:
    """Strip an XML namespace."""
    return element.tag.rsplit("}", 1)[-1].lower()


def resolve(base: str, href: str) -> tuple[str, str]:
    """Resolve an archive-relative href and its optional fragment."""
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        raise InputError(f"External EPUB reference: {href}")
    document = (
        posixpath.normpath(
            posixpath.join(posixpath.dirname(base), unquote(parsed.path))
        )
        if parsed.path
        else base
    )
    if document.startswith(("../", "/")):
        raise InputError(f"Unsafe EPUB reference: {href}")
    return document, unquote(parsed.fragment)


def anchor_key(document: str, fragment: str = "") -> str:
    """Construct a unique document/fragment key."""
    return document + (f"#{fragment}" if fragment else "")


def xml(archive: ZipFile, path: str) -> ET.Element:
    """Read XML, reporting malformed or missing EPUB resources."""
    try:
        content = archive.read(path)
        if b"<!ENTITY" in content.upper():
            raise InputError(f"XML entities are not allowed: {path}")
        parser = ET.XMLParser()  # noqa: S314 - custom entities rejected above; XHTML names mapped below
        parser.entity.update({name: chr(code) for name, code in name2codepoint.items()})
        element = ET.fromstring(content, parser=parser)  # noqa: S314 - same guarded parser
    except (KeyError, ET.ParseError) as error:
        raise InputError(f"Invalid EPUB resource {path}: {error}") from error
    else:
        return element


def _image_name(document: str, href: str) -> tuple[str, str]:
    path, _ = resolve(document, href)
    _ = image_media(path)
    return path, f"images/{digest(path)[:16]}{posixpath.splitext(path)[1]}"


def _literal(text: str, *, preserve_lines: bool = False) -> str:
    if not preserve_lines:
        text = re.sub(r"\s+", " ", text)
    return text.replace("*", r"\*").replace("{", r"\{").replace("}", r"\}")


def _inline(
    element: ET.Element,
    document: str = "",
    *,
    blocks: str = "",
    preserve_lines: bool = False,
) -> str:
    kind = tag(element)
    preserve_lines = preserve_lines or kind == "pre"
    if kind == "img":
        _, name = _image_name(document, element.get("src", ""))
        alt = (
            " ".join(element.get("alt", "").split())
            .replace("{", r"\{")
            .replace("}", r"\}")
        )
        return f"\n\n{{image {name} | {alt}}}\n\n"
    if kind in ("script", "style"):
        return ""
    if kind == "br":
        return "\n"
    pieces = [_literal(element.text or "", preserve_lines=preserve_lines)]
    for child in element:
        separator = blocks if tag(child) in BLOCK_TAGS else ""
        if separator and not "".join(pieces).rstrip(" \t\r").endswith(separator):
            pieces.append(separator)
        pieces.extend(
            (
                _inline(child, document, blocks=blocks, preserve_lines=preserve_lines),
                separator,
                _literal(child.tail or "", preserve_lines=preserve_lines),
            )
        )
    value = "".join(pieces)
    if kind in ("em", "i", "cite"):
        return _wrap_emphasis(value, "*")
    if kind in ("strong", "b"):
        return _wrap_emphasis(value, "**")
    return value


def _wrap_emphasis(value: str, marker: str) -> str:
    parts: list[str] = []
    start = 0
    for match in MARKER.finditer(value):
        if prefix := value[start : match.start()].strip():
            parts.append(f"{marker}{prefix}{marker}")
        parts.append(match.group())
        start = match.end()
    if tail := value[start:].strip():
        parts.append(f"{marker}{tail}{marker}")
    return (
        "\n\n".join(parts)
        if MARKER.search(value)
        else f"{marker}{value.strip()}{marker}"
    )


def _semantic(value: str) -> str:
    types = set(value.split())
    return "body" if types & BODY_TYPES else "matter" if types & MATTER_TYPES else ""


def _clean(text: str) -> str:
    return "\n".join(" ".join(line.split()) for line in text.split("\n")).strip()


@dataclass(slots=True, kw_only=True)
class _Linearizer:
    document: str
    blocks: list[Block] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    semantic: str = ""

    def anchors(self, element: ET.Element) -> None:
        for name in (
            element.get("id"),
            element.get("name") if tag(element) == "a" else None,
        ):
            if name:
                self.pending.append(anchor_key(self.document, name))

    def emit(
        self, element: ET.Element, kind: str, *, depth: int = 0, ordered: bool = False
    ) -> None:
        for child in element.iter():
            if child is not element:
                self.anchors(child)
        if tag(element) == "tr":
            text = " | ".join(
                _clean(_inline(child, self.document))
                for child in element
                if tag(child) in ("td", "th")
            )
        else:
            text = _clean(
                _inline(
                    element,
                    self.document,
                    blocks={"quote": "\n\n", "verse": "\n"}.get(kind, ""),
                    preserve_lines=kind == "verse",
                )
            )
        if text:
            anchors = tuple(dict.fromkeys(self.pending))
            self.pending.clear()
            start = 0
            pieces: list[tuple[str, str]] = []
            for match in MARKER.finditer(text):
                if prefix := text[start : match.start()].strip():
                    pieces.append((kind, prefix))
                pieces.append(("image", match.group()))
                start = match.end()
            if tail := text[start:].strip():
                pieces.append((kind, tail))
            for index, (piece_kind, piece_text) in enumerate(pieces):
                self.blocks.append(
                    Block(
                        kind=piece_kind,
                        text=piece_text,
                        anchors=anchors if index == 0 else (),
                        level=int(tag(element)[1]) if piece_kind == "heading" else 0,
                        depth=depth,
                        ordered=ordered,
                        images=int(piece_kind == "image"),
                        semantic=self.semantic,
                    )
                )

    def walk(
        self, element: ET.Element, *, depth: int = 0, ordered: bool = False
    ) -> None:
        previous = self.semantic
        self.semantic = _semantic(element.get(f"{{{EPUB_NS}}}type", "")) or previous
        self._walk(element, depth=depth, ordered=ordered)
        self.semantic = previous

    def _walk(
        self, element: ET.Element, *, depth: int = 0, ordered: bool = False
    ) -> None:
        self.anchors(element)
        kind = tag(element)
        if kind in ("script", "style", "head"):
            return
        if kind == "img":
            self.emit(element, "image")
            return
        if re.search(
            r"poem|verse|stanza|poetry", element.get("class", ""), re.IGNORECASE
        ):
            self.emit(element, "verse")
        elif kind in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.emit(element, "heading")
        elif kind == "blockquote":
            self.emit(element, "quote")
        elif kind in ("p", "tr", "pre"):
            self.emit(element, "paragraph")
        else:
            self.children(element, depth=depth, ordered=ordered)

    def children(self, element: ET.Element, *, depth: int, ordered: bool) -> None:
        if tag(element) == "li":
            # Keep nested list items separate rather than duplicating their text.
            shallow = ET.Element("li", element.attrib)
            shallow.text = element.text
            for child in element:
                if tag(child) not in ("ul", "ol"):
                    shallow.append(child)
            self.emit(shallow, "list_item", depth=depth, ordered=ordered)
            for child in element:
                if tag(child) in ("ul", "ol"):
                    self.walk(child, depth=depth, ordered=ordered)
        else:
            run = ET.Element("p")
            run.text = element.text
            for child in element:
                if tag(child) not in BLOCK_TAGS:
                    run.append(deepcopy(child))
                    continue
                self.emit(run, "paragraph")
                run = ET.Element("p")
                self.walk(
                    child,
                    depth=depth + (tag(element) in ("ul", "ol")),
                    ordered=tag(element) == "ol"
                    if tag(element) in ("ul", "ol")
                    else ordered,
                )
                run.text = child.tail
            self.emit(run, "paragraph")


def linearize(root: ET.Element, document: str, semantic: str = "") -> list[Block]:
    """Convert a document body into ordered blocks with fragment anchors."""
    body = next((element for element in root.iter() if tag(element) == "body"), root)
    reader = _Linearizer(document=document, pending=[document], semantic=semantic)
    reader.walk(body)
    return reader.blocks


def _toc_target(base: str, href: str) -> tuple[str, str] | None:
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        _ = sys.stderr.write(f"Warning: skipping external TOC entry: {href}\n")
        return None
    return resolve(base, href)


def _nav_entries(root: ET.Element, base: str) -> list[Entry]:
    nav = next(
        (
            element
            for element in root.iter()
            if tag(element) == "nav"
            and "toc" in element.get(f"{{{EPUB_NS}}}type", "").split()
        ),
        None,
    )
    entries: list[Entry] = []
    if nav is None:
        return entries

    def visit(element: ET.Element, depth: int) -> None:
        if tag(element) == "a" and element.get("href"):
            target = _toc_target(base, element.get("href", ""))
            if target is None:
                return
            document, fragment = target
            entries.append(
                Entry(
                    title=" ".join(element.itertext()).strip(),
                    anchor=anchor_key(document, fragment),
                    depth=depth,
                )
            )
        for child in element:
            visit(child, depth + (tag(child) == "ol"))

    visit(nav, 0)
    return entries


def _ncx_entries(root: ET.Element, base: str) -> list[Entry]:
    entries: list[Entry] = []

    def visit(element: ET.Element, depth: int) -> None:
        if tag(element) == "navpoint":
            label = next((child for child in element if tag(child) == "navlabel"), None)
            content = next(
                (child for child in element if tag(child) == "content"), None
            )
            if label is not None and content is not None:
                target = _toc_target(base, content.get("src", ""))
                if target is not None:
                    document, fragment = target
                    entries.append(
                        Entry(
                            title=" ".join(label.itertext()).strip(),
                            anchor=anchor_key(document, fragment),
                            depth=depth,
                        )
                    )
        for child in element:
            visit(child, depth + (tag(child) == "navpoint"))

    visit(root, 0)
    return entries


def _check_drm(archive: ZipFile) -> None:
    if "META-INF/rights.xml" in archive.namelist():
        raise InputError("EPUB is encrypted (DRM)")
    if "META-INF/encryption.xml" in archive.namelist():
        for element in xml(archive, "META-INF/encryption.xml").iter():
            if tag(element) == "encryptionmethod" and element.get("Algorithm") not in (
                "http://www.idpf.org/2008/embedding",
                "http://ns.adobe.com/pdf/enc#RC",
            ):
                raise InputError("EPUB is encrypted (DRM)")


def _ncx_item(items: dict[str, ET.Element], spine: ET.Element) -> ET.Element | None:
    referenced = items.get(spine.get("toc", ""))
    if referenced is not None:
        return referenced
    return next(
        (
            element
            for element in items.values()
            if element.get("media-type") == "application/x-dtbncx+xml"
        ),
        None,
    )


def _guide_semantics(root: ET.Element, base: str) -> dict[str, str]:
    semantics: dict[str, str] = {}
    for element in root.iter():
        if tag(element) == "reference" and (kind := _semantic(element.get("type", ""))):
            semantics[anchor_key(*resolve(base, element.get("href", "")))] = kind
    return semantics


def _landmark_semantics(root: ET.Element, base: str) -> dict[str, str]:
    semantics: dict[str, str] = {}
    for landmark in root.iter():
        if (
            tag(landmark) != "nav"
            or "landmarks" not in landmark.get(f"{{{EPUB_NS}}}type", "").split()
        ):
            continue
        for element in landmark.iter():
            kind = _semantic(element.get(f"{{{EPUB_NS}}}type", ""))
            if tag(element) == "a" and kind:
                target = _toc_target(base, element.get("href", ""))
                if target is not None:
                    semantics[anchor_key(*target)] = kind
    return semantics


def _read_spine(
    archive: ZipFile,
    spine: ET.Element,
    items: dict[str, ET.Element],
    opf: str,
    *,
    semantics: dict[str, str],
) -> tuple[list[Block], list[tuple[str, int]], dict[str, bytes], tuple[str, ...]]:
    blocks: list[Block] = []
    documents: list[tuple[str, int]] = []
    images: dict[str, bytes] = {}
    non_linear: list[str] = []
    references = [element for element in spine if tag(element) == "itemref"]
    for reference in sorted(
        references, key=lambda element: element.get("linear") == "no"
    ):
        item = items.get(reference.get("idref", ""))
        if item is None:
            raise InputError("Spine references missing manifest item")
        document, _ = resolve(opf, item.get("href", ""))
        documents.append((document, len(blocks)))
        if reference.get("linear") == "no":
            non_linear.append(document)
        root = xml(archive, document)
        for element in root.iter():
            if tag(element) == "img":
                path, name = _image_name(document, element.get("src", ""))
                images[name] = archive.read(path)
        semantic = semantics.get(document, "")
        for block in linearize(root, document):
            semantic = next(
                (semantics[anchor] for anchor in block.anchors if anchor in semantics),
                semantic,
            )
            blocks.append(replace(block, semantic=block.semantic or semantic))
    return blocks, documents, images, tuple(non_linear)


def read_publication(archive: ZipFile) -> Publication:
    """Resolve an EPUB2 or EPUB3 publication, rejecting DRM."""
    _check_drm(archive)
    container = xml(archive, "META-INF/container.xml")
    opf = next(
        (
            element.get("full-path")
            for element in container.iter()
            if tag(element) == "rootfile"
        ),
        None,
    )
    if not opf:
        raise InputError("Missing OPF rootfile")
    root = xml(archive, opf)
    metadata = next((element for element in root if tag(element) == "metadata"), None)
    spine = next((element for element in root if tag(element) == "spine"), None)
    if metadata is None or spine is None:
        raise InputError("Missing EPUB metadata or spine")
    fields: dict[str, list[str]] = {}
    for element in metadata:
        fields.setdefault(tag(element), []).append(" ".join(element.itertext()).strip())
    book = Book(
        title=next(iter(fields.get("title", [])), "Untitled"),
        authors=fields.get("creator", []),
        language=next(iter(fields.get("language", [])), "und").lower().split("-")[0],
        identifier=next(iter(fields.get("identifier", [])), ""),
    )
    items = {
        element.get("id", ""): element
        for element in root.iter()
        if tag(element) == "item"
    }
    cover_id = next(
        (
            element.get("content")
            for element in metadata
            if tag(element) == "meta" and element.get("name") == "cover"
        ),
        None,
    )
    cover = next(
        (
            element
            for key, element in items.items()
            if "cover-image" in element.get("properties", "").split() or key == cover_id
        ),
        None,
    )
    nav = next(
        (
            element
            for element in items.values()
            if "nav" in element.get("properties", "").split()
        ),
        None,
    )
    ncx = _ncx_item(items, spine)
    entries: list[Entry] = []
    semantics = _guide_semantics(root, opf)
    if nav is not None:
        nav_path, _ = resolve(opf, nav.get("href", ""))
        nav_root = xml(archive, nav_path)
        entries = _nav_entries(nav_root, nav_path)
        semantics.update(_landmark_semantics(nav_root, nav_path))
    if not entries and ncx is not None:
        ncx_path, _ = resolve(opf, ncx.get("href", ""))
        entries = _ncx_entries(xml(archive, ncx_path), ncx_path)
    # A fragment's scope ends at the next TOC entry unless a section says otherwise.
    semantics = {
        entry.anchor: semantics.get(
            entry.anchor, semantics.get(entry.anchor.split("#", 1)[0], "")
        )
        for entry in entries
    } | semantics
    blocks, documents, images, non_linear = _read_spine(
        archive, spine, items, opf, semantics=semantics
    )
    cover_name: str | None = None
    cover_bytes: bytes | None = None
    if cover is not None:
        path, _ = resolve(opf, cover.get("href", ""))
        suffix = posixpath.splitext(path)[1].lower()
        if suffix in MEDIA and cover.get("media-type") in set(MEDIA.values()):
            cover_name = f"cover{suffix}"
            cover_bytes = archive.read(path)
        else:
            media = cover.get("media-type", "")
            _ = sys.stderr.write(
                f"Warning: skipping unsupported cover: {path} ({media})\n"
            )
    return Publication(
        book=book,
        blocks=blocks,
        entries=entries,
        documents=documents,
        cover_name=cover_name,
        cover_bytes=cover_bytes,
        images=images,
        non_linear=tuple(non_linear),
    )
