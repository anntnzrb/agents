# Copyright (c) 2026
"""Parse the adapted Markdown subset and its explicit inline markers."""

import html
import re
import unicodedata
import xml.etree.ElementTree as ET
from copy import replace
from dataclasses import dataclass, field

from .data import InputError
from .images import MARKER, image_path
from .text import plain, unescape_braces, words

MAX_HEADING_LEVEL = 4

INLINE = frozenset(("idea", "question", "why"))
LISTS = frozenset(("recap", "quiz", "answers"))
ITEM = re.compile(r"^(?:- |\d+\. )(.*)$")
BRACES = re.compile(r"(?<!\\)[{}]")


class ParseError(ValueError):
    """A malformed adapted unit with its exact source line."""

    def __init__(self, line: int, message: str) -> None:
        """Attach the original one-based line number."""
        self.line: int = line
        super().__init__(f"line {line}: {message}")


@dataclass(frozen=True, slots=True, kw_only=True)
class Span:
    """A text run, aside, or term with an attached gloss."""

    kind: str
    text: str
    gloss: str = ""
    emphasis: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class BodyBlock:
    """A parsed body block."""

    kind: str
    spans: list[Span]
    line: int
    level: int = 0
    ordered: bool = False
    analogy: bool = False
    number: str = ""
    image: str = ""
    alt: str = ""

    def text(self, *, asides: bool = False, glosses: bool = True) -> str:
        """Render plain text, optionally retaining asides."""
        if self.kind == "image":
            return ""
        spans = [
            replace(span, kind="text", gloss="")
            if span.kind == "gloss" and not glosses
            else span
            for span in self.spans
            if span.kind != "aside" or asides
        ]
        return rendered_text(render_blocks([replace(self, spans=spans)]))


@dataclass(frozen=True, slots=True, kw_only=True)
class Parsed:
    """An adapted unit and its gate-facing text views."""

    raw: str
    blocks: list[BodyBlock]
    directives: dict[str, list[list[Span]]]

    @property
    def body_text(self) -> str:
        """Body text including glosses and excluding asides."""
        return "\n\n".join(block.text() for block in self.blocks)

    @property
    def bare_body(self) -> str:
        """Body text without optional gloss definitions or asides."""
        return "\n\n".join(block.text(glosses=False) for block in self.blocks)

    @property
    def full_text(self) -> str:
        """All rendered content, including directives and asides."""
        return "\n\n".join(
            [
                *(block.text(asides=True) for block in self.blocks),
                *(
                    span_text(spans, asides=True)
                    for items in self.directives.values()
                    for spans in items
                ),
            ]
        )

    @property
    def aside_texts(self) -> list[str]:
        """Asides in body and directives."""
        return [
            span.text
            for spans in self.all_spans
            for span in spans
            if span.kind == "aside"
        ]

    @property
    def all_spans(self) -> list[list[Span]]:
        """All spans in deterministic content order."""
        return [
            *(block.spans for block in self.blocks),
            *(spans for items in self.directives.values() for spans in items),
        ]

    @property
    def glosses(self) -> list[tuple[str, str]]:
        """Body gloss terms and definitions in reading order."""
        return [
            (plain(span.text), span.gloss)
            for block in self.blocks
            for span in block.spans
            if span.kind == "gloss"
        ]

    @property
    def aside_positions(self) -> list[int]:
        """Body word positions at each aside."""
        positions: list[int] = []
        previous = 0
        for block in self.blocks:
            prefix: list[Span] = []
            for span in block.spans:
                if span.kind == "aside":
                    positions.append(previous + len(words(span_text(prefix))))
                prefix.append(span)
            previous += len(words(block.text()))
        return positions


def span_text(spans: list[Span], *, asides: bool = False, glosses: bool = True) -> str:
    """Render inline AST as plain text."""
    return plain(
        "".join(
            span.text
            if span.kind == "text" or (span.kind == "aside" and asides)
            else (f"{span.text} ({span.gloss})" if glosses else span.text)
            if span.kind == "gloss"
            else ""
            for span in spans
        )
    )


def parse_inline(text: str, line: int) -> list[Span]:
    """Parse balanced markers, accepting escaped braces as literal text."""
    text = unicodedata.normalize("NFC", text)
    spans: list[Span] = []
    position = 0
    while position < len(text):
        match = BRACES.search(text, position)
        if match is None:
            spans.append(Span(kind="text", text=unescape_braces(text[position:])))
            break
        opening = match.start()
        if match.group() == "}":
            raise ParseError(line + text[:opening].count("\n"), "unbalanced marker")
        prefix = text[position:opening]
        if prefix:
            spans.append(Span(kind="text", text=unescape_braces(prefix)))
        current_line = line + text[:opening].count("\n")
        if text.startswith("{~", opening):
            span, position = _aside(text, opening, current_line)
            spans.append(span)
            continue
        closing_match = BRACES.search(text, opening + 1)
        if closing_match is None or closing_match.group() != "}":
            raise ParseError(current_line, "unbalanced marker")
        closing = closing_match.start()
        marker = text[opening + 1 : closing]
        term, gloss, position, emphasis = _gloss(
            text, marker, closing, spans, current_line
        )
        if not gloss or BRACES.search(gloss):
            raise ParseError(current_line, "empty or malformed gloss")
        spans.append(
            Span(
                kind="gloss",
                text=unescape_braces(term),
                gloss=unescape_braces(gloss),
                emphasis=emphasis,
            )
        )
    return spans


def _aside(text: str, opening: int, line: int) -> tuple[Span, int]:
    closing = text.find("~}", opening + 2)
    if closing == -1:
        raise ParseError(line, "unbalanced aside")
    value = text[opening + 2 : closing].strip()
    if not value or BRACES.search(value):
        raise ParseError(line, "malformed aside")
    return Span(kind="aside", text=unescape_braces(value)), closing + 2


def _gloss(
    text: str, marker: str, closing: int, spans: list[Span], line: int
) -> tuple[str, str, int, str]:
    emphasis = ""
    if marker.startswith("="):
        if not spans or spans[-1].kind != "text":
            raise ParseError(line, "gloss has no immediately preceding word")
        previous = spans.pop()
        word = r"[^\W\d_]+(?:['\u2019][^\W\d_]+)*"
        match = re.search(rf"(\*{{1,2}})({word})\1$|({word})$", previous.text)
        if match is None:
            raise ParseError(line, "gloss must attach directly to a word")
        term = match.group(2) or match.group(3)
        emphasis = match.group(1) or ""
        prefix = previous.text[: match.start()]
        gloss = marker[1:].strip()
        position = closing + 1
        opening_emphasis = re.search(r"(?<!\\)(\*{1,2})$", prefix)
        if (
            not emphasis
            and opening_emphasis
            and text[position:].startswith(opening_emphasis.group())
        ):
            emphasis = opening_emphasis.group()
            prefix = prefix[: -len(emphasis)]
            position += len(emphasis)
        if prefix:
            spans.append(Span(kind="text", text=prefix))
    else:
        term = marker.strip()
        emphasized = re.fullmatch(r"(\*{1,2})([^*]+)\1", term)
        if emphasized:
            emphasis, term = emphasized.groups()
        attachment = re.match(r"\{=((?:\\[{}]|[^{}])+)\}", text[closing + 1 :])
        if not term or BRACES.search(marker) or attachment is None:
            raise ParseError(line, "unknown or malformed marker")
        gloss = attachment.group(1).strip()
        position = closing + 1 + attachment.end()
    return term, gloss, position, emphasis


@dataclass(slots=True, kw_only=True)
class _Parser:
    lines: list[str]
    blocks: list[BodyBlock] = field(default_factory=list)
    directives: dict[str, list[list[Span]]] = field(default_factory=dict)
    position: int = 0

    def directive(self, match: re.Match[str]) -> None:
        name, rest = match.groups()
        line = self.position + 1
        if name not in INLINE | LISTS:
            raise ParseError(line, f"unknown directive @{name}")
        if name in self.directives:
            raise ParseError(line, f"duplicate directive @{name}")
        self.position += 1
        items: list[list[Span]] = []
        if name in INLINE:
            pieces = [rest.strip()]
            while (
                self.position < len(self.lines)
                and self.lines[self.position].strip()
                and not self.lines[self.position].startswith("@")
            ):
                pieces.append(self.lines[self.position])
                self.position += 1
            items.append(parse_inline("\n".join(pieces).strip(), line))
        else:
            if rest.strip():
                raise ParseError(
                    line, "list directive content must be on following lines"
                )
            while (
                self.position < len(self.lines)
                and self.lines[self.position].strip()
                and not self.lines[self.position].startswith("@")
            ):
                item = ITEM.match(self.lines[self.position])
                if item is None:
                    raise ParseError(
                        self.position + 1, "expected a list directive item"
                    )
                items.append(parse_inline(item.group(1), self.position + 1))
                self.position += 1
        self.directives[name] = items

    def body(self) -> None:
        line = self.position + 1
        current = self.lines[self.position]
        if current.startswith("{image "):
            self.image(current, line)
            return
        heading = re.match(r"^(#{1,6})\s+(.*)$", current)
        item = ITEM.match(current)
        kind, level, ordered = "paragraph", 0, False
        if heading:
            level = len(heading.group(1))
            kind, current = "heading", heading.group(2)
            if level > MAX_HEADING_LEVEL:
                raise ParseError(line, "adapted headings must have levels 2 through 4")
        elif current.startswith(">"):
            kind, current = "quote", current.removeprefix(">").removeprefix(" ")
        elif item:
            kind, current = "list_item", item.group(1)
            ordered = self.lines[self.position][0].isdigit()
        analogy = current.startswith("{analogy} ")
        if analogy:
            if kind != "paragraph":
                raise ParseError(line, "analogy marker must start a paragraph")
            current = current.removeprefix("{analogy} ")
        pieces = [current]
        self.position += 1
        if kind in ("paragraph", "quote"):
            self.continue_body(kind, pieces)
        self.blocks.append(
            BodyBlock(
                kind=kind,
                spans=parse_inline("\n".join(pieces), line),
                line=line,
                level=level,
                ordered=ordered,
                analogy=analogy,
                number=self.lines[line - 1].split(".", 1)[0] if ordered else "",
            )
        )

    def image(self, current: str, line: int) -> None:
        match = MARKER.fullmatch(current)
        if match is None:
            raise ParseError(line, "malformed image marker")
        try:
            image = image_path(match.group(1))
        except InputError as error:
            raise ParseError(line, str(error)) from error
        self.blocks.append(
            BodyBlock(
                kind="image",
                spans=[],
                line=line,
                image=image,
                alt=unescape_braces(match.group(2)),
            )
        )
        self.position += 1

    def continue_body(self, kind: str, pieces: list[str]) -> None:
        while self.position < len(self.lines):
            following = self.lines[self.position]
            if (
                not following.strip()
                or following.startswith(("@", "#", "{analogy} ", "{image "))
                or ITEM.match(following)
            ):
                break
            if kind == "quote":
                if not following.startswith(">"):
                    break
                following = following.removeprefix(">").removeprefix(" ")
            elif following.startswith(">"):
                break
            pieces.append(following)
            self.position += 1


def parse(text: str) -> Parsed:
    """Parse an adapted unit, preserving line numbers for errors."""
    parser = _Parser(lines=text.splitlines())
    while parser.position < len(parser.lines):
        line = parser.lines[parser.position]
        if not line.strip():
            parser.position += 1
        elif match := re.match(r"^@([^:]+):(.*)$", line):
            parser.directive(match)
        elif line.startswith("@"):
            raise ParseError(parser.position + 1, "malformed directive")
        else:
            parser.body()
    return Parsed(raw=text, blocks=parser.blocks, directives=parser.directives)


def _emphasis(escaped: str) -> str:
    escaped = re.sub(
        r"(?<!\\)\*\*((?:\\\*|[^*])+)(?<!\\)\*\*", r"<strong>\1</strong>", escaped
    )
    escaped = re.sub(r"(?<!\\)\*((?:\\\*|[^*])+)(?<!\\)\*", r"<em>\1</em>", escaped)
    return escaped.replace(r"\*", "*")


def _render_aside(span: Span, aside_style: str) -> str:
    content = _emphasis(html.escape(span.text)).replace("\n", "<br />")
    return f"<em>{content}</em>" if aside_style == "italic" else content


def render_inline(spans: list[Span], aside_style: str = "plain") -> str:
    """Render the inline subset with XML-escaped text."""
    result: list[str] = []
    for span in spans:
        if span.kind == "gloss":
            result.append(
                _emphasis(
                    span.emphasis
                    + html.escape(f"{span.text} ({span.gloss})")
                    + span.emphasis
                )
            )
        elif span.kind == "aside":
            result.append(
                f'<span class="aside">{_render_aside(span, aside_style)}</span>'
            )
        else:
            result.append(_emphasis(html.escape(span.text)))
    return "".join(result).replace(r"\.", ".").replace("\n", "<br />")


def render_blocks(blocks: list[BodyBlock], aside_style: str = "plain") -> str:
    """Render block structure as valid XHTML."""
    rendered: list[str] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if block.kind == "image":
            image, alt = html.escape(block.image), html.escape(block.alt)
            rendered.append(
                f'<div class="figure"><img src="{image}" alt="{alt}" /></div>'
            )
            index += 1
            continue
        if (
            block.kind == "paragraph"
            and len(block.spans) == 1
            and block.spans[0].kind == "aside"
        ):
            rendered.append(
                f'<p class="aside">{_render_aside(block.spans[0], aside_style)}</p>'
            )
            index += 1
            continue
        if block.kind == "list_item":
            kind = "ol" if block.ordered else "ul"
            start = int(block.number or "1")
            expected = start
            items: list[str] = []
            while (
                index < len(blocks)
                and blocks[index].kind == "list_item"
                and blocks[index].ordered == block.ordered
            ):
                current = blocks[index]
                value = int(current.number or str(expected))
                attribute = (
                    f' value="{value}"' if block.ordered and value != expected else ""
                )
                items.append(
                    f"<li{attribute}>{render_inline(current.spans, aside_style)}</li>"
                )
                expected = value + 1
                index += 1
            attribute = f' start="{start}"' if block.ordered and start != 1 else ""
            rendered.append(f"<{kind}{attribute}>{''.join(items)}</{kind}>")
            continue
        content = render_inline(block.spans, aside_style)
        if block.kind == "heading":
            rendered.append(
                f"<h{max(2, block.level)}>{content}</h{max(2, block.level)}>"
            )
        elif block.kind == "quote":
            rendered.append(f"<blockquote><p>{content}</p></blockquote>")
        else:
            rendered.append(f"<p>{content}</p>")
        index += 1
    return "\n".join(rendered)


def rendered_text(markup: str) -> str:
    """Read visible XHTML text, including list counters and line breaks."""
    root = ET.fromstring(f"<div>{markup}</div>")  # noqa: S314 - XML-escaped renderer output

    def visit(element: ET.Element) -> str:
        if element.tag == "br":
            return "\n"
        pieces = [element.text or ""]
        counter = int(element.get("start", "1")) if element.tag == "ol" else 0
        for child in element:
            if element.tag == "ol" and child.tag == "li":
                counter = int(child.get("value", str(counter)))
                pieces.append(f"{counter}. ")
                counter += 1
            pieces.extend((visit(child), child.tail or ""))
            if child.tag in ("p", "li", "div", "blockquote", "h2", "h3", "h4"):
                pieces.append("\n\n")
        return "".join(pieces)

    return visit(root).strip()
