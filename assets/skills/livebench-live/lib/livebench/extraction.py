# Copyright (c) 2026
"""Ordered extraction helpers for official JSON/CSV/HTML/RSC fallback sources."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contracts import Diagnostic, RawArtifact

from .diagnostics import make_diagnostic


@dataclass(frozen=True)
class SourcePath:
    """Represent SourcePath in the LiveBench adapter."""

    field: str
    path: str
    raw: object


@dataclass
class ParsedDocument:
    """Represent ParsedDocument in the LiveBench adapter."""

    document_kind: str
    extraction_method: str
    root: object
    raw_artifact_id: str
    source_paths: list[SourcePath] = field(default_factory=list)
    unknown_fields: dict[str, object] = field(default_factory=dict)
    parser: str = "livebench.extraction"
    parser_version: str = "1"


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        """Initialize this instance."""
        super().__init__()
        self.rows: list[list[str]] = []
        self._current: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        """Handle starttag for the LiveBench adapter."""
        if tag.lower() == "tr":
            self._current = []
        elif tag.lower() in {"th", "td"} and self._current is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        """Handle data for the LiveBench adapter."""
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        """Handle endtag for the LiveBench adapter."""
        lowered = tag.lower()
        if (
            lowered in {"th", "td"}
            and self._current is not None
            and self._cell is not None
        ):
            self._current.append("".join(self._cell).strip())
            self._cell = None
        elif lowered == "tr" and self._current is not None:
            if self._current:
                self.rows.append(self._current)
            self._current = None


def extract_artifact(  # noqa: C901, PLR0911, PLR0912
    artifact: RawArtifact,
) -> tuple[ParsedDocument | None, list[Diagnostic]]:
    """Apply the required extraction precedence and preserve the selected path."""
    body = artifact.body
    content_type = (artifact.content_type or "").casefold()
    diagnostics: list[Diagnostic] = []
    if (
        artifact.artifact_kind in {"category_map", "releases", "catalog"}
        or "json" in content_type
    ):
        try:
            root = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            root = None
        if root is not None:
            return ParsedDocument(
                "json", "official_json", root, artifact.artifact_id
            ), diagnostics
    if artifact.artifact_kind in {"score_table", "cost_table"} or "csv" in content_type:
        try:
            rows = _csv_rows(body)
        except (UnicodeDecodeError, csv.Error) as exc:
            diagnostics.append(
                make_diagnostic(
                    "MALFORMED_PAYLOAD",
                    "CSV payload could not be parsed strictly.",
                    severity="error",
                    stage="parse",
                    artifact=artifact.artifact_id,
                    details={"error": str(exc)},
                )
            )
            return None, diagnostics
        if rows:
            return ParsedDocument(
                "csv", "official_csv", rows, artifact.artifact_id
            ), diagnostics

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        diagnostics.append(
            make_diagnostic(
                "MALFORMED_PAYLOAD",
                "Source bytes are not UTF-8.",
                severity="error",
                stage="parse",
                artifact=artifact.artifact_id,
                details={"error": str(exc)},
            )
        )
        return None, diagnostics

    if parsed := _embedded_json(text):
        return ParsedDocument(
            "json",
            "embedded_json",
            parsed[0],
            artifact.artifact_id,
            [SourcePath("embedded", parsed[1], parsed[0])],
        ), diagnostics
    if parsed := _rsc_frames(text):
        return ParsedDocument(
            "rsc",
            "rsc_frame",
            parsed[0],
            artifact.artifact_id,
            [SourcePath("frame", parsed[1], parsed[0])],
        ), diagnostics
    if parsed := _json_ld(text):
        return ParsedDocument(
            "json",
            "json_ld",
            parsed[0],
            artifact.artifact_id,
            [SourcePath("json_ld", parsed[1], parsed[0])],
        ), diagnostics
    if table := _html_table(text):
        return ParsedDocument(
            "html", "html_table", table, artifact.artifact_id
        ), diagnostics

    if _looks_like_js_shell(text):
        diagnostics.append(
            make_diagnostic(
                "REQUIRES_RENDERED_SOURCE",
                "The source is a JavaScript shell without an official data asset.",
                severity="error",
                stage="extract",
                artifact=artifact.artifact_id,
                details={
                    "attempted_url": artifact.source_url,
                    "delivery": "empty_root_js_shell",
                },
            )
        )
        return None, diagnostics

    stripped = text.strip()
    if stripped:
        # Plain text is last and never promoted to numeric chart truth.
        diagnostics.append(
            make_diagnostic(
                "PARTIAL_EXTRACTION",
                (
                    "Only unstructured source text was available; no table or "
                    "JSON payload was selected."
                ),
                severity="warning",
                stage="extract",
                artifact=artifact.artifact_id,
                details={"attempted_url": artifact.source_url},
            )
        )
        return ParsedDocument(
            "text", "plaintext", {"text": stripped}, artifact.artifact_id
        ), diagnostics
    diagnostics.append(
        make_diagnostic(
            "MALFORMED_PAYLOAD",
            "Source payload was empty.",
            severity="error",
            stage="extract",
            artifact=artifact.artifact_id,
        )
    )
    return None, diagnostics


def _csv_rows(body: bytes) -> list[dict[str, object]]:
    text = body.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    if not reader.fieldnames:
        message = "CSV has no header"
        raise csv.Error(message)
    fields = [field.strip() if field is not None else "" for field in reader.fieldnames]
    if any(not field for field in fields):
        message = "CSV contains an empty header"
        raise csv.Error(message)
    rows: list[dict[str, object]] = []
    for row in reader:
        if None in row:
            message = "CSV row has more fields than its header"
            raise csv.Error(message)
        rows.append({field: row.get(field, "") for field in fields})
    return rows


def _embedded_json(text: str) -> tuple[object, str] | None:
    pattern = re.compile(
        r"<script[^>]+type=[\"']application/json[\"'][^>]*>(.*?)</script>",
        re.IGNORECASE | re.DOTALL,
    )
    for index, match in enumerate(pattern.finditer(text)):
        payload = match.group(1).strip()
        try:
            return json.loads(payload), f"script[type=application/json][{index}]"
        except json.JSONDecodeError:
            continue
    return None


def _rsc_frames(text: str) -> tuple[object, str] | None:
    patterns = [
        re.compile(
            r"self\.__next_f\.push\(\s*(\[\s*\d+\s*,\s*(\"(?:\\.|[^\"])*\")\s*\])\s*\)",
            re.DOTALL,
        ),
        re.compile(
            r"(?:\bRSC_FRAME\b|\bdata-rsc\b)\s*[:=]\s*(\"(?:\\.|[^\"])*\")", re.DOTALL
        ),
    ]
    for pattern in patterns:
        for index, match in enumerate(pattern.finditer(text)):
            encoded = match.group(1)
            try:
                decoded = json.loads(encoded)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, list) and len(decoded) == 2:  # noqa: PLR2004
                decoded = decoded[1]
            if isinstance(decoded, str):
                candidate = decoded.strip()
                start = min(
                    (
                        pos
                        for pos in (candidate.find("{"), candidate.find("["))
                        if pos >= 0
                    ),
                    default=-1,
                )
                if start >= 0:
                    try:
                        return json.loads(candidate[start:]), f"rsc-frame[{index}]"
                    except json.JSONDecodeError:
                        continue
            elif isinstance(decoded, (dict, list)):
                return decoded, f"rsc-frame[{index}]"
    return None


def _json_ld(text: str) -> tuple[object, str] | None:
    pattern = re.compile(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        re.IGNORECASE | re.DOTALL,
    )
    for index, match in enumerate(pattern.finditer(text)):
        try:
            return json.loads(
                match.group(1).strip()
            ), f"script[type=application/ld+json][{index}]"
        except json.JSONDecodeError:
            continue
    return None


def _html_table(text: str) -> list[dict[str, str]] | None:
    parser = _TableParser()
    parser.feed(text)
    if len(parser.rows) < 2:  # noqa: PLR2004
        return None
    headers = parser.rows[0]
    if not headers or any(not header for header in headers):
        return None
    rows: list[dict[str, str]] = []
    for values in parser.rows[1:]:
        if len(values) != len(headers):
            continue
        rows.append(dict(zip(headers, values, strict=True)))
    return rows or None


def _looks_like_js_shell(text: str) -> bool:
    return bool(
        re.search(r"<div[^>]+id=[\"']root[\"'][^>]*>\s*</div>", text, re.IGNORECASE)
    ) and bool(
        re.search(
            r"(?:enable JavaScript|javascript is required|noscript)",
            text,
            re.IGNORECASE,
        )
    )
