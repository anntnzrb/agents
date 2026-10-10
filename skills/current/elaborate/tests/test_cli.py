# Copyright (c) 2026
"""Public CLI integration, real-fixture ingestion, and deterministic builds."""

import os
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING
from zipfile import ZIP_STORED, ZipFile

import pytest

from lib.elaborate.config import load_config, section
from lib.elaborate.data import read_facts, read_manifest, table
from lib.elaborate.epub import linearize
from lib.elaborate.work import prompt

from .helpers import (
    ADAPTED_BODY,
    DIRECTIVES,
    ROOT,
    adapted,
    make_epub,
    rewrite_epub,
    run,
    run_subprocess,
)

if TYPE_CHECKING:
    from pathlib import Path

EXPECTED_USAGE = 2
MISSING_EXECUTABLE = 127
CHAPTER_COUNT = 13
TRATADO_COUNT = 7
SPLIT_LIMIT = 30


@pytest.mark.parametrize(
    "command", ["", "ingest", "check", "status", "prompt", "build"]
)
def test_help(command: str) -> None:
    """Every public help command exits successfully."""
    args = [command] if command else []
    result = run(*args, "--help") if command else run_subprocess("--help")
    assert result.returncode == 0
    assert "usage:" in result.stdout


@pytest.mark.parametrize(("nav", "single"), [(False, False), (True, True)])
def test_ingest_formats(tmp_path: Path, *, nav: bool, single: bool) -> None:
    """Resolve NCX documents and EPUB3 fragment cuts into the same units."""
    book = make_epub(tmp_path / "book.epub", nav=nav, single=single)
    work = tmp_path / "work"
    result = run_subprocess("ingest", str(book), "--work", str(work), "--json")
    assert result.returncode == 0, result.stderr
    manifest = read_manifest(work)
    assert [unit["title"] for unit in manifest["units"]] == ["One", "Two"]
    assert manifest["book"]["language"] == "en"
    assert manifest["book"]["authors"] == ["A Writer", "B Writer"]
    facts = read_facts(work / "protected" / "001.json")
    assert "Rome" in facts["proper_nouns"]
    assert facts["numbers"] == ["42"]
    first = {
        path.relative_to(work): path.read_bytes()
        for path in work.rglob("*")
        if path.is_file()
    }
    adapted(work, "001", "Unchanged model output.")
    assert run("ingest", str(book), "--work", str(work)).returncode == 0
    for path, content in first.items():
        assert (work / path).read_bytes() == content
    assert (work / "adapted" / "001.md").read_text(
        encoding="utf-8"
    ) == "Unchanged model output."


@pytest.mark.parametrize("drm", ["rights", "urn:drm:test"])
def test_drm_rejected(tmp_path: Path, drm: str) -> None:
    """Reject rights documents and non-font encryption with the input exit code."""
    book = make_epub(tmp_path / "book.epub", drm=drm)
    result = run("ingest", str(book), "--work", str(tmp_path / "work"), "--json")
    assert result.returncode == EXPECTED_USAGE
    assert "encrypted (DRM)" in result.stderr
    assert not result.stdout


@pytest.mark.parametrize(
    "algorithm",
    ["http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"],
)
def test_font_obfuscation_allowed(tmp_path: Path, algorithm: str) -> None:
    """Allow the two explicitly supported font-obfuscation methods."""
    book = make_epub(tmp_path / "book.epub", drm=algorithm)
    assert run("ingest", str(book), "--work", str(tmp_path / "work")).returncode == 0


def test_bad_epub_and_unknown_configuration(tmp_path: Path) -> None:
    """Map invalid archive and unknown dotted settings to input errors."""
    book = tmp_path / "bad.epub"
    _ = book.write_text("Not a zip", encoding="utf-8")
    assert (
        run("ingest", str(book), "--work", str(tmp_path)).returncode == EXPECTED_USAGE
    )
    with ZipFile(book, "w") as archive:
        archive.writestr("no-container", "missing")
    assert (
        run("ingest", str(book), "--work", str(tmp_path)).returncode == EXPECTED_USAGE
    )
    config = tmp_path / "bad.toml"
    _ = config.write_text("[ingest]\nunknown = 1\n", encoding="utf-8")
    result = run("ingest", str(book), "--work", str(tmp_path), "--config", str(config))
    assert result.returncode == EXPECTED_USAGE
    assert "ingest.unknown" in result.stderr


def test_splitting_and_adapted_warning(tmp_path: Path, synthetic_work: Path) -> None:
    """Split body parts at bounded word counts and warn if existing.

    Adaptations change.
    """
    work = synthetic_work
    book = make_epub(tmp_path / "book.epub")
    original_words = sum(unit["words"] for unit in read_manifest(work)["units"])
    adapted(work, "001", "Existing adaptation.")
    config = tmp_path / "small.toml"
    _ = config.write_text("[ingest]\nmax_unit_words = 30\n", encoding="utf-8")
    result = run(
        "ingest",
        str(book),
        "--work",
        str(work),
        "--config",
        str(config),
    )
    assert result.returncode == 0, result.stderr
    assert "adapted/001.md" in result.stderr
    manifest = read_manifest(work)
    assert sum(unit["words"] for unit in manifest["units"]) == original_words
    assert all(unit["words"] <= SPLIT_LIMIT for unit in manifest["units"])
    assert len({unit["chapter"] for unit in manifest["units"]}) == EXPECTED_USAGE
    assert all(unit["parts"] > 1 for unit in manifest["units"])
    assert "part 1/" in (work / "source" / "001.md").read_text(encoding="utf-8")


def test_check_pending_failure_cache_and_status(synthetic_work: Path) -> None:
    """Distinguish pending, failing, stale, and fresh cache states."""
    work = synthetic_work
    pending = run_subprocess("check", "--work", str(work), "--all", "--json")
    assert pending.returncode == 0
    assert '"pending"' in pending.stdout
    adapted(work, "001", "Bad {~ marker")
    failed = run("check", "--work", str(work), "001", "--json")
    assert failed.returncode == 1
    assert "K-format" in failed.stdout
    assert "line 1" in failed.stdout
    cache = work / "checks" / "001.json"
    original = cache.read_bytes()
    assert run("check", "--work", str(work), "001").returncode == 1
    assert cache.read_bytes() == original
    assert "fail" in run_subprocess("status", "--work", str(work)).stdout
    adapted(work, "001", DIRECTIVES + ADAPTED_BODY)
    assert "stale" in run("status", "--work", str(work)).stdout
    assert run("check", "--work", str(work), "001").returncode == 0
    assert cache.read_bytes() != original
    output = run("status", "--work", str(work), "--json")
    assert output.returncode == 0
    assert '"passing": 1' in output.stdout
    assert run("check", "--work", str(work), "999").returncode == EXPECTED_USAGE


def test_configuration_threshold_environment_and_languages(
    tmp_path: Path, synthetic_work: Path
) -> None:
    """Merge overrides, honor environment fallback, and reject unknown gate ids."""
    work = synthetic_work
    adapted(work, "001", DIRECTIVES + ADAPTED_BODY)
    config = tmp_path / "override.toml"
    _ = config.write_text("[gates.R-sentence-max]\nmax = 1\n", encoding="utf-8")
    result = run("check", "--work", str(work), "001", "--config", str(config))
    assert result.returncode == 1
    assert "R-sentence-max" in result.stdout
    assert "differs from ingest" in result.stderr
    env = dict(os.environ) | {"ELABORATE_CONFIG": str(config)}
    assert run("check", "--work", str(work), "001", env=env).returncode == 1
    _ = config.write_text("[gates.unknown]\nenabled = false\n", encoding="utf-8")
    result = run("check", "--work", str(work), "001", "--config", str(config))
    assert result.returncode == EXPECTED_USAGE
    assert "gates.unknown" in result.stderr
    _ = config.write_text('[lang.fr]\nhedges = ["peut"]\n', encoding="utf-8")
    merged = load_config(config)
    assert "fr" in section(merged, "lang")
    assert "labels" in table(section(merged, "lang")["fr"])


def test_prompt_and_unknown_placeholder(tmp_path: Path, synthetic_work: Path) -> None:
    """Render all known variables and reject unknown ones without.

    Editing bundled templates.
    """
    work = synthetic_work
    result = run_subprocess("prompt", "--work", str(work), "001", "--kind", "rewrite")
    assert result.returncode == 0, result.stderr
    assert "{{" not in result.stdout
    assert "Test & book" in result.stdout
    assert "Protected" not in result.stdout or "Rome" in result.stdout
    assert "F-numbers" in result.stdout
    assert (
        run("prompt", "--work", str(work), "001", "--kind", "audit").returncode
        == EXPECTED_USAGE
    )
    adapted(work, "001", DIRECTIVES + ADAPTED_BODY)
    assert run("prompt", "--work", str(work), "001", "--kind", "audit").returncode == 0
    template = tmp_path / "rewrite.md"
    _ = template.write_text("{{unknown}}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown template placeholder"):
        _ = prompt(work, read_manifest(work), load_config(), "001", template)


def test_build_pending_failing_and_epubcheck_missing(
    tmp_path: Path, synthetic_work: Path
) -> None:
    """Refuse pending or invalid adaptations and report missing optional tooling."""
    work = synthetic_work
    out = tmp_path / "out.epub"
    assert run("build", "--work", str(work), "--out", str(out)).returncode == 1
    result = run("build", "--work", str(work), "--out", str(out), "--allow-pending")
    assert result.returncode == 0, result.stderr
    with ZipFile(out) as archive:
        chapter = archive.read("EPUB/chapter-001.xhtml").decode()
        assert "adaptation is pending" in chapter
    adapted(work, "001", "Bad {~ marker")
    failed = run("build", "--work", str(work), "--out", str(out), "--allow-pending")
    assert failed.returncode == 1
    assert "failing: 001" in failed.stderr
    adapted(work, "001", DIRECTIVES + ADAPTED_BODY)
    out.unlink()
    result = run(
        "build",
        "--work",
        str(work),
        "--out",
        str(out),
        "--allow-pending",
        "--epubcheck",
        env=dict(os.environ) | {"PATH": ""},
    )
    assert result.returncode == MISSING_EXECUTABLE
    assert out.is_file()


def test_build_checked_glossary_and_determinism(
    tmp_path: Path, synthetic_work: Path
) -> None:
    """Build valid navigation, progress, glossary, and identical EPUB bytes."""
    work = synthetic_work
    # The source has no rare tokens: this additional gloss tests EPUB presentation.
    for uid in ("001", "002"):
        adapted(
            work,
            uid,
            DIRECTIVES
            + "## Clear\n\n"
            + ADAPTED_BODY
            + "\n\nCat{= small pet} & bird < fish.\n",
        )
    first, second = tmp_path / "first.epub", tmp_path / "second.epub"
    result = run_subprocess("build", "--work", str(work), "--out", str(first))
    assert result.returncode == 0, result.stderr
    assert run("build", "--work", str(work), "--out", str(second)).returncode == 0
    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        names = archive.namelist()
        assert names[0] == "mimetype"
        assert archive.getinfo("mimetype").compress_type == ZIP_STORED
        assert {
            "EPUB/nav.xhtml",
            "EPUB/toc.ncx",
            "EPUB/package.opf",
            "EPUB/glossary.xhtml",
            "EPUB/chapter-001.xhtml",
            "EPUB/chapter-002.xhtml",
        }.issubset(names)
        for name in names:
            if name.endswith((".xhtml", ".opf", ".ncx", ".xml")):
                parser: ET.XMLPullParser[ET.Element] = ET.XMLPullParser(
                    events=("start",)
                )
                parser.feed(archive.read(name))
                parser.close()
        chapter = archive.read("EPUB/chapter-001.xhtml").decode()
        assert "1/2 · 50%" in chapter
        assert "&amp;" in chapter
        assert "&lt;" in chapter
        assert "The idea in one line" in chapter
        assert "Quick check" in chapter
        assert "Answers" in chapter
        glossary = archive.read("EPUB/glossary.xhtml").decode()
        assert "chapter-001.xhtml#unit-001" in glossary
        assert "small pet" in glossary
        assert "2000-01-01T00:00:00Z" in archive.read("EPUB/package.opf").decode()


def test_linearizer_all_block_kinds_and_anchors() -> None:
    """Preserve source block kinds, nested inline formatting, and anchors."""
    content = (
        '<body><a name="before"/><h2 id="head">Heading</h2>'
        '<p>Text <em id="inside">italic</em> <strong>bold</strong>'
        '<img src="x.png"/><script>bad</script>.</p>'
        "<blockquote><p>Quote one</p><p>Quote two</p></blockquote>"
        "<ol><li>First<ul><li>Nested</li></ul></li><li>Second</li></ol>"
        "<table><tr><td>A</td><td>B</td></tr></table>"
        '<p class="poem">Line one<br/>Line two</p></body>'
    )
    parser: ET.XMLPullParser[ET.Element] = ET.XMLPullParser(events=("start",))
    parser.feed(content)
    parser.close()
    event = next(parser.read_events())
    root = event[1] if len(event) > 1 else None
    assert isinstance(root, ET.Element)
    blocks = linearize(root, "chapter.xhtml")
    assert "chapter.xhtml#before" in blocks[0].anchors
    assert "chapter.xhtml#inside" in blocks[1].anchors
    assert blocks[2].kind == "image"
    assert blocks[2].images == 1
    assert "{image images/" in blocks[2].text
    assert "*italic*" in blocks[1].text
    assert "**bold**" in blocks[1].text
    assert "bad" not in blocks[1].text
    assert any(block.kind == "quote" and "\n\n" in block.text for block in blocks)
    assert any(block.kind == "verse" and "\n" in block.text for block in blocks)
    assert any(block.text == "A | B" for block in blocks)
    assert [block.text for block in blocks if block.kind == "list_item"] == [
        "First",
        "Nested",
        "Second",
    ]


def test_real_art_of_war(art_of_war_ingested: Path) -> None:
    """Retain every chapter and cut Gutenberg's license inside the last document."""
    work = art_of_war_ingested
    manifest = read_manifest(work)
    chapters = {
        unit["chapter"]
        for unit in manifest["units"]
        if unit["title"].startswith("Chapter ") and unit["kind"] == "body"
    }
    assert len(chapters) == CHAPTER_COUNT
    assert all(
        unit["kind"] == "matter"
        for unit in manifest["units"]
        if unit["title"] == "Contents" or "LICENSE" in unit["title"]
    )
    last = [
        unit for unit in manifest["units"] if unit["title"].startswith("Chapter XIII.")
    ]
    assert last
    for unit in last:
        text = (work / unit["source"]).read_text(encoding="utf-8")
        assert "PROJECT GUTENBERG" not in text
        assert "full terms" not in text.lower()


def test_real_lazarillo_forward_merge(tmp_path: Path) -> None:
    """At depth two, merge near-empty Tratado anchors forward into their subsections."""
    config = tmp_path / "depth.toml"
    _ = config.write_text(
        "[ingest]\ntoc_depth = 2\nmax_unit_words = 20000\n", encoding="utf-8"
    )
    work = tmp_path / "lazarillo"
    result = run(
        "ingest",
        str(ROOT / "tests" / "fixtures" / "lazarillo.epub"),
        "--work",
        str(work),
        "--config",
        str(config),
    )
    assert result.returncode == 0, result.stderr
    manifest = read_manifest(work)
    tratados = [
        unit for unit in manifest["units"] if unit["title"].startswith("Tratado ")
    ]
    assert len(tratados) == TRATADO_COUNT
    assert all(unit["kind"] == "body" and ": " in unit["title"] for unit in tratados)
    assert any(
        "Prólogo" in unit["title"] and unit["kind"] == "body"
        for unit in manifest["units"]
    )
    assert manifest["book"]["language"] == "es"
    assert "PROJECT GUTENBERG" not in (work / tratados[-1]["source"]).read_text(
        encoding="utf-8"
    )


def test_real_cover_matter_and_split_chapters(
    tmp_path: Path, art_of_war_work: Path
) -> None:
    """Copy real cover bytes and concatenate split parts inside chapter sections."""
    work = art_of_war_work
    manifest = read_manifest(work)
    out = tmp_path / "book.epub"
    result = run("build", "--work", str(work), "--out", str(out), "--allow-pending")
    assert result.returncode == 0, result.stderr
    cover = manifest["cover"]
    assert cover is not None
    with ZipFile(out) as archive:
        assert archive.read(f"EPUB/{cover}") == (work / cover).read_bytes()
        assert "EPUB/cover.xhtml" in archive.namelist()
        assert 'properties="cover-image"' in archive.read("EPUB/package.opf").decode()
        contents = next(
            unit for unit in manifest["units"] if unit["title"] == "Contents"
        )
        matter_path = f"EPUB/chapter-{contents['chapter']:03}.xhtml"
        assert matter_path not in archive.namelist()
        split = next(unit for unit in manifest["units"] if unit["parts"] > 1)
        chapter = archive.read(f"EPUB/chapter-{split['chapter']:03}.xhtml").decode()
        assert f"Part 1/{split['parts']}" in chapter
        assert all(
            f'id="unit-{unit["id"]}"' in chapter
            for unit in manifest["units"]
            if unit["chapter"] == split["chapter"]
        )
    config = tmp_path / "matter.toml"
    _ = config.write_text("[build]\ninclude_matter = true\n", encoding="utf-8")
    result = run(
        "build",
        "--work",
        str(work),
        "--out",
        str(out),
        "--allow-pending",
        "--config",
        str(config),
    )
    assert result.returncode == 0, result.stderr
    with ZipFile(out) as archive:
        assert matter_path in archive.namelist()
        assert "Contents" in archive.read(matter_path).decode()


def test_build_reading_time_and_epoch(tmp_path: Path, synthetic_work: Path) -> None:
    """Use adapted body length for reading time and the reproducible-build epoch."""
    work = synthetic_work
    body = (
        DIRECTIVES
        + "## Clear\n\n"
        + ADAPTED_BODY
        + "\nCat{= small pet} & bird < fish.\n"
    )
    for uid in ("001", "002"):
        adapted(work, uid, body)
    config = tmp_path / "time.toml"
    _ = config.write_text("[build]\nwords_per_minute = 1\n", encoding="utf-8")
    out = tmp_path / "book.epub"
    result = run(
        "build",
        "--work",
        str(work),
        "--out",
        str(out),
        "--config",
        str(config),
        env=dict(os.environ) | {"SOURCE_DATE_EPOCH": "0"},
    )
    assert result.returncode == 0, result.stderr
    with ZipFile(out) as archive:
        assert "~86 min" in archive.read("EPUB/chapter-001.xhtml").decode()
        assert "1970-01-01T00:00:00Z" in archive.read("EPUB/package.opf").decode()


def test_invalid_work_json_and_disabled_format(
    tmp_path: Path, synthetic_work: Path
) -> None:
    """Treat malformed work files as input errors and keep format failures mandatory."""
    work = synthetic_work
    adapted(work, "001", "Malformed {~ aside")
    config = tmp_path / "format.toml"
    _ = config.write_text(
        '[gates.K-format]\nenabled = false\nseverity = "warn"\n', encoding="utf-8"
    )
    result = run("check", "--work", str(work), "001", "--config", str(config))
    assert result.returncode == 1
    assert "K-format fail" in result.stdout
    _ = (work / "manifest.json").write_text("bad JSON", encoding="utf-8")
    result = run("status", "--work", str(work), "--json")
    assert result.returncode == EXPECTED_USAGE
    assert "Invalid JSON" in result.stderr
    assert not result.stdout


def test_no_usable_toc_and_non_linear_spine(tmp_path: Path) -> None:
    """Fall back to spine documents and honor non-linear spine flags."""
    book = make_epub(tmp_path / "fallback.epub")
    rewrite_epub(book, {"OPS/toc.ncx": b"<ncx><navMap /></ncx>"})
    work = tmp_path / "fallback"
    result = run("ingest", str(book), "--work", str(work))
    assert result.returncode == 0, result.stderr
    assert [unit["title"] for unit in read_manifest(work)["units"]] == ["One", "Two"]
    with ZipFile(book) as archive:
        opf = archive.read("OPS/book.opf").replace(
            b'<itemref idref="two" />', b'<itemref idref="two" linear="no" />'
        )
    rewrite_epub(book, {"OPS/book.opf": opf})
    result = run("ingest", str(book), "--work", str(work))
    assert result.returncode == 0, result.stderr
    assert [unit["title"] for unit in read_manifest(work)["units"]] == ["One", "Two"]
    assert "42 birds" in (work / "source/002.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("version", ["2", "3"])
def test_cover_metadata_versions(tmp_path: Path, version: str) -> None:
    """Find covers via either EPUB2 metadata or EPUB3 manifest properties."""
    book = make_epub(tmp_path / "cover.epub", nav=version == "3")
    image = b"GIF89a"  # Ingest copies image bytes without decoding them.
    with ZipFile(book) as archive:
        opf = archive.read("OPS/book.opf").decode()
    properties = ' properties="cover-image"' if version == "3" else ""
    cover_item = (
        f'<item id="cover" href="cover.gif" media-type="image/gif"{properties} />'
        "</manifest>"
    )
    opf = opf.replace("</manifest>", cover_item)
    if version == "2":
        opf = opf.replace(
            "</metadata>", '<meta name="cover" content="cover" /></metadata>'
        )
    rewrite_epub(book, {"OPS/book.opf": opf.encode(), "OPS/cover.gif": image})
    work = tmp_path / "work"
    assert run("ingest", str(book), "--work", str(work)).returncode == 0
    assert read_manifest(work)["cover"] == "cover.gif"
    assert (work / "cover.gif").read_bytes() == image


def test_trailing_short_unit_and_unknown_language_labels(tmp_path: Path) -> None:
    """Merge a trailing short unit backward and fall back to English labels."""
    book = make_epub(tmp_path / "short.epub")
    with ZipFile(book) as archive:
        opf = archive.read("OPS/book.opf").replace(b"en-US", b"zz")
    rewrite_epub(
        book,
        {
            "OPS/book.opf": opf,
            "OPS/two.xhtml": (
                b'<html><body><h2 id="two">Two</h2><p>Short end.</p></body></html>'
            ),
        },
    )
    work = tmp_path / "work"
    result = run("ingest", str(book), "--work", str(work))
    assert result.returncode == 0, result.stderr
    units = read_manifest(work)["units"]
    assert [unit["title"] for unit in units] == ["One"]
    assert "Short end." in (work / units[0]["source"]).read_text(encoding="utf-8")
    result = run("prompt", "--work", str(work), "001", "--kind", "rewrite")
    assert result.returncode == 0
    assert "The idea in one line" in result.stdout
    out = tmp_path / "out.epub"
    assert (
        run(
            "build", "--work", str(work), "--out", str(out), "--allow-pending"
        ).returncode
        == 0
    )
    with ZipFile(out) as archive:
        assert "1/1 · 100%" in archive.read("EPUB/chapter-001.xhtml").decode()
