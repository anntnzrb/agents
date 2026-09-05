# Copyright (c) 2026
from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
from tests._path import SKILL_DIR

from livebench.contracts import RawArtifact
from livebench.extraction import extract_artifact

FIXTURES = SKILL_DIR / "tests" / "fixtures" / "pages"


def artifact(path: Path, kind: str = "catalog") -> RawArtifact:
    body = path.read_bytes()

    digest = sha256(body).hexdigest()
    return RawArtifact(
        f"fixture:{digest}",
        "livebench",
        "fixture-release",
        kind,
        f"fixture://{path}",
        f"fixture://{path}",
        body,
        200,
        "text/html",
        {},
        "2026-08-09T00:00:00Z",
        "2026-08-09T00:00:00Z",
        digest,
        len(body),
        raw_bytes_ref=None,
        freshness_mode="snapshot",
        stale=False,
        historical=True,
        cache_reused=False,
        generated_at=None,
    )


def test_extraction_precedence_embedded_before_html_table() -> None:
    parsed, diagnostics = extract_artifact(artifact(FIXTURES / "embedded-json.html"))
    assert parsed is not None
    assert parsed.extraction_method == "embedded_json"
    assert not diagnostics


def test_rsc_and_table_fallbacks_are_source_pathed() -> None:
    rsc, _ = extract_artifact(artifact(FIXTURES / "rsc-next-frames.html"))
    table, _ = extract_artifact(artifact(FIXTURES / "table-fallback.html"))
    assert rsc is not None
    assert rsc.extraction_method == "rsc_frame"
    assert table is not None
    assert table.extraction_method == "html_table"
    assert rsc.source_paths[0].path.startswith("rsc-frame")
