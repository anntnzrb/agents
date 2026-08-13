# Copyright 2026 Vals-live contributors.
"""Layered extraction for official Vals JSON, HTML, Astro and table payloads."""

from __future__ import annotations

import csv
import io
import json
import re
from html import unescape
from html.parser import HTMLParser

from .contracts import ParsedDocument, RawArtifact
from .diagnostics import make

_ASTRO_ATTR = re.compile(
    r"(?:^|\s)props\s*=\s*(['\"])(.*?)\1", re.DOTALL | re.IGNORECASE
)
_RSC_PUSH = re.compile(
    r"(?:self\.__next_f\.push|__next_f\.push)\s*\(\s*\[\s*\d+\s*,\s*(\"(?:\\.|[^\"\\])*\")\s*\]\s*\)",
    re.DOTALL,
)

_ASTRO_PAIR_LENGTH = 2
_MIN_TABLE_ROWS = 2
_MIN_CSV_LINES = 2


class ExtractionError(RuntimeError):
    """Represent structured extraction failure details."""

    def __init__(
        self, code: str, message: str, details: dict[str, object] | None = None
    ) -> None:
        """Initialize an extraction code, message, and details."""
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _decode_astro(value: object) -> object:
    if isinstance(value, list):
        if len(value) == _ASTRO_PAIR_LENGTH and isinstance(value[0], int):
            return _decode_astro(value[1])
        return [_decode_astro(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _decode_astro(item) for key, item in value.items()}
    return value


def _parse_json(text: str) -> object | None:
    try:
        return _decode_astro(json.loads(text))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


class _HTMLPayloadParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[tuple[dict[str, str], str]] = []
        self.islands: list[tuple[dict[str, str], str]] = []
        self.data_attributes: list[tuple[str, str]] = []
        self.tables: list[list[list[str]]] = []
        self._script_attrs: dict[str, str] | None = None
        self._script_text: list[str] = []
        self._island_attrs: dict[str, str] | None = None
        self._table_rows: list[list[str]] | None = None
        self._table_row: list[str] | None = None
        self._cell_text: list[str] | None = None
        self._cell_tag: str | None = None
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): value or "" for key, value in attrs}
        for key, value in attrs_map.items():
            if key.startswith("data-"):
                self.data_attributes.append((key, value))
        lowered = tag.lower()
        if lowered == "script":
            self._script_attrs = attrs_map
            self._script_text = []
        elif lowered == "astro-island":
            self._island_attrs = attrs_map
            self._script_text = []
        elif lowered == "table":
            self._table_rows = []
        elif lowered == "tr" and self._table_rows is not None:
            self._table_row = []
        elif lowered in {"th", "td"} and self._table_row is not None:
            self._cell_tag = lowered
            self._cell_text = []
        if lowered not in {"script", "style"}:
            self.text_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "script" and self._script_attrs is not None:
            self.scripts.append((self._script_attrs, "".join(self._script_text)))
            self._script_attrs = None
            self._script_text = []
        elif lowered == "astro-island" and self._island_attrs is not None:
            self.islands.append((self._island_attrs, "".join(self._script_text)))
            self._island_attrs = None
            self._script_text = []
        elif (
            lowered in {"th", "td"}
            and self._cell_text is not None
            and self._table_row is not None
        ):
            self._table_row.append(" ".join("".join(self._cell_text).split()))
            self._cell_text = None
            self._cell_tag = None
        elif (
            lowered == "tr"
            and self._table_row is not None
            and self._table_rows is not None
        ):
            if self._table_row:
                self._table_rows.append(self._table_row)
            self._table_row = None
        elif lowered == "table" and self._table_rows is not None:
            if self._table_rows:
                self.tables.append(self._table_rows)
            self._table_rows = None

    def handle_data(self, data: str) -> None:
        if self._script_attrs is not None or self._island_attrs is not None:
            self._script_text.append(data)
        elif self._cell_text is not None:
            self._cell_text.append(data)
        else:
            self.text_parts.append(data)


def _table_rows_to_dict(rows: list[list[str]]) -> list[dict[str, str]]:
    if len(rows) < _MIN_TABLE_ROWS:
        return []
    headers = [item.strip() or f"column_{index}" for index, item in enumerate(rows[0])]
    result: list[dict[str, str]] = []
    for row in rows[1:]:
        if not any(item.strip() for item in row):
            continue
        result.append(
            {
                headers[index]: row[index].strip() if index < len(row) else ""
                for index in range(len(headers))
            }
        )
    return result


def _rsc_payloads(text: str) -> list[tuple[str, object]]:
    result: list[tuple[str, object]] = []
    for index, match in enumerate(_RSC_PUSH.finditer(text)):
        raw = match.group(1)
        try:
            decoded = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            decoded = raw[1:-1].replace('\\"', '"').replace("\\n", "\n")
        parsed = (
            _parse_json(decoded) if isinstance(decoded, str) else _decode_astro(decoded)
        )
        if parsed is not None:
            result.append((f"$._next_f[{index}]", parsed))
    return result


def _looks_like_csv(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < _MIN_CSV_LINES:
        return False
    return "," in lines[0] and "," in lines[1]


def _annotate(
    document: ParsedDocument,
    diagnostics: list[dict[str, object]],
    candidates: list[dict[str, object]],
) -> ParsedDocument:
    if diagnostics:
        document.diagnostics.extend(diagnostics)
        document.unknown_fields.setdefault("malformed_candidates", []).extend(
            candidates
        )
        document.unknown_fields.setdefault("extraction_diagnostics", []).extend(
            diagnostics
        )
    return document


def _malformed_json(
    artifact: RawArtifact, text: str
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    candidate = {"field": "$", "path": "$", "raw": text}
    diagnostic = make(
        "MALFORMED_PAYLOAD",
        (
            "A top-level JSON candidate could not be decoded; lower-precedence "
            "representations were attempted."
        ),
        severity="warning",
        stage="extract",
        source_path="$",
        details={
            "source_url": artifact.source_url,
            "content_type": artifact.content_type,
            "candidate": candidate,
        },
    )
    return [diagnostic], [candidate]


def _primary_document(
    artifact: RawArtifact,
    text: str,
    content_type: str,
    stripped: str,
) -> tuple[
    ParsedDocument | None,
    list[dict[str, object]],
    list[dict[str, object]],
]:
    diagnostics: list[dict[str, object]] = []
    malformed_candidates: list[dict[str, object]] = []
    if "json" in content_type or stripped.startswith(("{", "[")):
        parsed = _parse_json(text)
        if parsed is not None:
            return (
                ParsedDocument(
                    parsed,
                    "json",
                    "official_json",
                    [{"field": "$", "path": "$", "raw": text}],
                    artifact,
                ),
                diagnostics,
                malformed_candidates,
            )
        diagnostics, malformed_candidates = _malformed_json(artifact, text)
    if "csv" in content_type or _looks_like_csv(text):
        try:
            rows = list(csv.DictReader(io.StringIO(text)))
        except (csv.Error, UnicodeError) as exc:
            msg = "MALFORMED_PAYLOAD"
            raise ExtractionError(
                msg,
                "CSV payload could not be parsed.",
                {"source_url": artifact.source_url},
            ) from exc
        if rows and ("model" in rows[0] or "benchmark" in rows[0] or len(rows[0]) > 1):
            return (
                ParsedDocument(
                    rows,
                    "csv",
                    "official_csv",
                    [
                        {"field": key, "path": f"csv[column={key}]", "raw": None}
                        for key in rows[0]
                    ],
                    artifact,
                ),
                diagnostics,
                malformed_candidates,
            )
        if "csv" in content_type:
            msg = "MALFORMED_PAYLOAD"
            raise ExtractionError(
                msg,
                "CSV payload contained no usable rows.",
                {"source_url": artifact.source_url},
            )
    return None, diagnostics, malformed_candidates


def _embedded_documents(
    parser: _HTMLPayloadParser, artifact: RawArtifact
) -> tuple[list[ParsedDocument], list[ParsedDocument]]:
    embedded_candidates: list[ParsedDocument] = []
    jsonld_candidates: list[ParsedDocument] = []
    for index, (attrs, script_text) in enumerate(parser.scripts):
        script_type = attrs.get("type", "").lower()
        is_json = script_type in {"application/json", "application/ld+json"}
        is_next_data = attrs.get("id", "").lower() in {"__next_data__", "data"}
        if not (is_json or is_next_data):
            continue
        parsed = _parse_json(unescape(script_text.strip()))
        if parsed is None:
            continue
        candidate = ParsedDocument(
            parsed,
            "json",
            "json_ld" if "ld+json" in script_type else "embedded_json",
            [{"field": "$", "path": f"script[{index}]", "raw": script_text}],
            artifact,
        )
        (jsonld_candidates if "ld+json" in script_type else embedded_candidates).append(
            candidate
        )
    for index, (attrs, script_text) in enumerate(parser.islands):
        props = attrs.get("props", "")
        parsed = _parse_json(unescape(props))
        if parsed is None:
            parsed = _parse_json(unescape(script_text.strip()))
        if parsed is not None:
            embedded_candidates.append(
                ParsedDocument(
                    parsed,
                    "html",
                    "embedded_json",
                    [
                        {
                            "field": "props",
                            "path": f"astro-island[{index}].props",
                            "raw": props,
                        }
                    ],
                    artifact,
                )
            )
    return embedded_candidates, jsonld_candidates


def _html_fallback(
    parser: _HTMLPayloadParser,
    text: str,
    artifact: RawArtifact,
    diagnostics: list[dict[str, object]],
    malformed_candidates: list[dict[str, object]],
) -> ParsedDocument:
    rsc = _rsc_payloads(text)
    if rsc:
        root: object = {"frames": [value for _, value in rsc]}
        paths = [{"field": "frame", "path": path, "raw": value} for path, value in rsc]
        return _annotate(
            ParsedDocument(root, "rsc", "rsc", paths, artifact),
            diagnostics,
            malformed_candidates,
        )
    for index, rows in enumerate(parser.tables):
        mapped = _table_rows_to_dict(rows)
        if mapped:
            document = ParsedDocument(
                mapped,
                "html",
                "html_table",
                [
                    {"field": key, "path": f"table[{index}].{key}", "raw": None}
                    for key in mapped[0]
                ],
                artifact,
            )
            return _annotate(document, diagnostics, malformed_candidates)
    data_attrs = [
        {"field": key, "value": value} for key, value in parser.data_attributes
    ]
    if data_attrs:
        document = ParsedDocument(
            {"data_attributes": data_attrs},
            "html",
            "data_attribute",
            [
                {
                    "field": item["field"],
                    "path": f"@{item['field']}",
                    "raw": item["value"],
                }
                for item in data_attrs
            ],
            artifact,
        )
        return _annotate(document, diagnostics, malformed_candidates)
    plain = " ".join("".join(parser.text_parts).split())
    if plain:
        requires_rendered = (
            bool(parser.scripts)
            or "noscript" in text.lower()
            or 'id="root"' in text.lower()
            or "id='root'" in text.lower()
        )
        if requires_rendered:
            msg = "REQUIRES_RENDERED_SOURCE"
            raise ExtractionError(
                msg,
                (
                    "The official page contains no usable static data and "
                    "requires a rendered source."
                ),
                {
                    "attempted_url": artifact.source_url,
                    "content_type": artifact.content_type,
                },
            )
        values = [
            match.group(0)
            for match in re.finditer(
                r"(?<![A-Za-z])(?:\d+(?:\.\d+)?%?|N/A|—|-)(?![A-Za-z])", plain
            )
        ]
        return _annotate(
            ParsedDocument(
                {"text": plain, "values": values},
                "text",
                "plaintext",
                [{"field": "text", "path": "text", "raw": plain}],
                artifact,
            ),
            diagnostics,
            malformed_candidates,
        )
    details: dict[str, object] = {"attempted_url": artifact.source_url}
    if malformed_candidates:
        details["malformed_candidates"] = malformed_candidates
    msg = "MALFORMED_PAYLOAD"
    raise ExtractionError(
        msg,
        "The source contained no parseable representation.",
        details,
    )


def extract_document(artifact: RawArtifact) -> ParsedDocument:
    """Extract the highest-precedence usable source representation."""
    body = artifact.body
    content_type = (artifact.content_type or "").lower()
    text = body.decode("utf-8", errors="replace")
    stripped = text.lstrip("\ufeff \t\r\n")
    primary, diagnostics, malformed_candidates = _primary_document(
        artifact, text, content_type, stripped
    )
    if primary is not None:
        return _annotate(primary, diagnostics, malformed_candidates)

    parser = _HTMLPayloadParser()
    try:
        parser.feed(text)
        parser.close()
    except (ValueError, AssertionError) as exc:
        msg = "MALFORMED_PAYLOAD"
        raise ExtractionError(
            msg,
            "HTML payload could not be parsed.",
            {"source_url": artifact.source_url},
        ) from exc

    embedded_candidates, jsonld_candidates = _embedded_documents(parser, artifact)
    for candidates in (embedded_candidates, jsonld_candidates):
        if candidates:
            return _annotate(candidates[0], diagnostics, malformed_candidates)
    return _html_fallback(parser, text, artifact, diagnostics, malformed_candidates)


def extraction_diagnostic(exc: ExtractionError) -> dict[str, object]:
    """Convert an extraction exception into a public diagnostic."""
    return make(
        exc.code, str(exc), severity="error", stage="parse", details=exc.details
    )
