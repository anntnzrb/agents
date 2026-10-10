# Copyright (c) 2026
"""Round-six regressions for source retention and reader-visible fidelity."""

import re
import xml.etree.ElementTree as ET
from copy import replace
from typing import TYPE_CHECKING
from zipfile import ZipFile

import pytest

from lib.elaborate.adapted import parse, render_blocks
from lib.elaborate.config import load_config, section
from lib.elaborate.data import read_json, read_manifest, strings
from lib.elaborate.freq import supported
from lib.elaborate.gates import REGISTRY, evaluate
from lib.elaborate.text import plain, protect

from .helpers import ROOT, adapted, make_epub, rewrite_epub, run
from .test_gates import context

if TYPE_CHECKING:
    from pathlib import Path

XHTML = '<html xmlns="http://www.w3.org/1999/xhtml"><body>{}</body></html>'
TWO_ITEMS = 2
USAGE_ERROR = 2


def parsed_xml(content: str | bytes) -> ET.Element:
    """Parse test-authored XML or real builder output with the strict parser."""
    return ET.fromstring(content)  # noqa: S314 - trusted test or renderer output


def book_with_body(tmp_path: Path, body: str, *, nav: bool = False) -> Path:
    """Replace a synthetic chapter using the established archive helper."""
    book = make_epub(tmp_path / "book.epub", nav=nav)
    rewrite_epub(book, {"OPS/one.xhtml": XHTML.format(body).encode()})
    return book


def ingest_source(tmp_path: Path, book: Path) -> tuple[Path, str]:
    """Read the first source unit after a successful public ingest."""
    work = tmp_path / "work"
    result = run("ingest", str(book), "--work", str(work))
    assert result.returncode == 0, result.stderr
    return work, (work / "source/001.md").read_text(encoding="utf-8")


def test_xhtml_entities_keep_the_whole_document(tmp_path: Path) -> None:
    """Named XHTML entities must not stop parsing halfway through a chapter."""
    book = make_epub(tmp_path / "book.epub")
    doc = (
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" '
        '"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">'
    ) + XHTML.format(
        '<h2 id="one">One</h2><p>Before&nbsp;after &copy;.</p><p>Last.</p>'
    )
    rewrite_epub(book, {"OPS/one.xhtml": doc.encode()})
    _, source = ingest_source(tmp_path, book)
    assert "Before after ©." in source
    assert "Last." in source


def test_malformed_xhtml_exits_two_with_document(tmp_path: Path) -> None:
    """A late XML failure cannot return the already-parsed prefix."""
    book = book_with_body(
        tmp_path, '<h2 id="one">One</h2><p>Before &unknown; after.</p>'
    )
    result = run("ingest", str(book), "--work", str(tmp_path / "work"))
    assert result.returncode == USAGE_ERROR
    assert "OPS/one.xhtml" in result.stderr
    assert "undefined entity" in result.stderr


@pytest.mark.parametrize("previous", [False, True])
def test_short_body_never_becomes_matter(tmp_path: Path, *, previous: bool) -> None:
    """A lone short body stays body even when its only neighbour is matter."""
    book = make_epub(tmp_path / "book.epub")
    with ZipFile(book) as archive:
        toc = archive.read("OPS/toc.ncx").decode()
    toc = toc.replace(
        "<text>One</text>",
        "<text>Dedication</text>" if previous else "<text>One</text>",
    )
    toc = toc.replace(
        "<text>Two</text>",
        "<text>Two</text>" if previous else "<text>Dedication</text>",
    )
    rewrite_epub(
        book,
        {
            "OPS/toc.ncx": toc.encode(),
            "OPS/one.xhtml": XHTML.format(
                '<h2 id="one">One</h2><p>Kept first.</p>'
            ).encode(),
            "OPS/two.xhtml": XHTML.format(
                '<h2 id="two">Two</h2><p>Kept second.</p>'
            ).encode(),
        },
    )
    work, _ = ingest_source(tmp_path, book)
    manifest = read_manifest(work)
    assert [unit["kind"] for unit in manifest["units"]] == (
        ["matter", "body"] if previous else ["body", "matter"]
    )


def test_blockquote_keeps_text_children_and_tails(tmp_path: Path) -> None:
    """Quoted paragraphs cannot hide introductions, attribution, or tails."""
    book = book_with_body(
        tmp_path,
        (
            '<h2 id="one">One</h2><blockquote>Intro<p>Quoted.</p>Tail'
            "<footer>Footer <cite>Author</cite>.</footer>End</blockquote>"
        ),
    )
    _, source = ingest_source(tmp_path, book)
    assert (
        source.index("Intro")
        < source.index("Quoted.")
        < source.index("Tail")
        < source.index("Footer *Author*.")
        < source.index("End")
    )


@pytest.mark.parametrize("heading", [True, False])
def test_non_linear_spine_is_a_separate_unit(tmp_path: Path, *, heading: bool) -> None:
    """Supplementary notes survive as their own trailing unit, even when short."""
    book = make_epub(tmp_path / "book.epub")
    with ZipFile(book) as archive:
        opf = archive.read("OPS/book.opf").decode()
    opf = opf.replace('<itemref idref="two" />', '<itemref idref="two" linear="no" />')
    body = (
        '<h2 id="two">Endnotes</h2>' if heading else '<a id="two"/>'
    ) + "<p>Small note retained.</p>"
    rewrite_epub(
        book,
        {"OPS/book.opf": opf.encode(), "OPS/two.xhtml": XHTML.format(body).encode()},
    )
    work, _ = ingest_source(tmp_path, book)
    units = read_manifest(work)["units"]
    assert len(units) == TWO_ITEMS
    assert units[1]["title"] == ("Endnotes" if heading else "Two")
    assert "Small note retained." in (work / units[1]["source"]).read_text(
        encoding="utf-8"
    )


def test_ordered_list_renders_start_and_discontinuous_values() -> None:
    """Numbers in adapted list markers remain visible in the resulting EPUB."""
    rendered = render_blocks(parse("7. Seven\n8. Eight\n12. Twelve").blocks)
    root = parsed_xml(rendered)
    assert root.tag == "ol"
    assert root.get("start") == "7"
    assert root[2].get("value") == "12"
    assert (
        parse("7. Seven\n8. Eight\n12. Twelve").body_text
        == "7. Seven\n\n8. Eight\n\n12. Twelve"
    )


@pytest.mark.parametrize(
    "source", ["# Title\n\n## First\nSecond", "# Title\n\n- First\nSecond"]
)
def test_source_fallback_keeps_multiline_blocks(
    source: str, synthetic_work: Path, tmp_path: Path
) -> None:
    """Pending source headings and list items retain every line."""
    _ = (synthetic_work / "source/001.md").write_text(source, encoding="utf-8")
    out = tmp_path / "source.epub"
    result = run(
        "build", "--work", str(synthetic_work), "--out", str(out), "--allow-pending"
    )
    assert result.returncode == 0, result.stderr
    with ZipFile(out) as archive:
        assert "Second" in "".join(
            parsed_xml(archive.read("EPUB/chapter-001.xhtml")).itertext()
        )


@pytest.mark.parametrize(
    ("extension", "media"),
    [
        ("jpg", "image/jpeg"),
        ("png", "image/png"),
        ("gif", "image/gif"),
        ("svg", "image/svg+xml"),
        ("webp", "image/webp"),
    ],
)
def test_images_survive_ingest_check_and_build(
    tmp_path: Path, extension: str, media: str
) -> None:
    """All core image resources, alt text, and repeated uses survive the pipeline."""
    book = book_with_body(
        tmp_path,
        "".join(
            (
                f'<h2 id="one">One</h2><p>Before <img src="figure.{extension}" ',
                f'alt="A &amp; B"/> after.</p><img src="figure.{extension}"/>',
            )
        ),
    )
    with ZipFile(book) as archive:
        opf = archive.read("OPS/book.opf").decode()
    opf = opf.replace(
        "</manifest>",
        "".join(
            (
                f'<item id="figure" href="figure.{extension}" ',
                f'media-type="{media}"/></manifest>',
            )
        ),
    )
    payload = b"synthetic resource"
    rewrite_epub(
        book, {"OPS/book.opf": opf.encode(), f"OPS/figure.{extension}": payload}
    )
    work, source = ingest_source(tmp_path, book)
    markers = [
        (match.group(1), match.group(2))
        for match in re.finditer(r"\{image (images/[^ ]+) \| ([^}]*)\}", source)
    ]
    assert len(markers) == TWO_ITEMS, source
    image = markers[0][0]
    assert image.endswith(f".{extension}")
    assert markers == [(image, "A & B"), (image, "")]
    assert (work / image).read_bytes() == payload
    assert strings(read_json(work / "protected/001.json")["images"]) == [image, image]
    parsed = parse("\n\n".join(f"{{image {file} | {alt}}}" for file, alt in markers))
    assert len(parsed.blocks) == TWO_ITEMS
    out = tmp_path / "out.epub"
    result = run("build", "--work", str(work), "--out", str(out), "--allow-pending")
    assert result.returncode == 0, result.stdout + result.stderr
    with ZipFile(out) as archive:
        assert archive.read(f"EPUB/{image}") == payload
        package = parsed_xml(archive.read("EPUB/package.opf"))
        assert any(
            element.get("href") == image and element.get("media-type") == media
            for element in package.iter()
        )
        chapter = parsed_xml(archive.read("EPUB/chapter-001.xhtml"))
        pictures = [
            element for element in chapter.iter() if element.tag.endswith("}img")
        ]
        assert [
            (element.get("src"), element.get("alt")) for element in pictures
        ] == markers


@pytest.mark.parametrize(
    "body",
    [
        "{image images/b.png | B}\n\n{image images/a.png | A}",
        "{image images/a.png | A}",
    ],
)
def test_image_gate_rejects_loss_and_reordering(body: str) -> None:
    """Source image order and duplicate occurrences are protected facts."""
    ctx = context("Plain.")
    ctx = replace(ctx, source="{image images/a.png | A}\n\n{image images/b.png | B}")
    settings = section(section(ctx.config, "gates"), "F-images")
    good = replace(ctx, parsed=parse(ctx.source))
    outcome = REGISTRY["F-images"](good, settings)
    assert outcome is not None
    assert outcome[0]
    outcome = REGISTRY["F-images"](replace(ctx, parsed=parse(body)), settings)
    assert outcome is not None
    assert not outcome[0]


def test_verse_separates_block_children(tmp_path: Path) -> None:
    """Verse child paragraphs have line boundaries instead of joined words."""
    book = book_with_body(
        tmp_path,
        (
            '<h2 id="one">One</h2><div class="verse"><p>Stars bright</p>'
            "<p>In night</p><span>Soft</span><span> winds</span></div>"
        ),
    )
    _, source = ingest_source(tmp_path, book)
    assert "Stars bright  \nIn night" in source
    assert "Soft winds" in source
    assert "brightIn" not in source


def test_div_inline_run_retains_emphasis_and_one_paragraph(tmp_path: Path) -> None:
    """Inline child nodes share their surrounding paragraph and emphasis."""
    book = book_with_body(
        tmp_path,
        (
            '<h2 id="one">One</h2><div>Before <em>bold</em> middle '
            "<span>normal</span> end.</div>"
        ),
    )
    _, source = ingest_source(tmp_path, book)
    assert "Before *bold* middle normal end." in source


def test_straight_quotes_never_pair_across_paragraphs() -> None:
    """Unbalanced paragraph quotes cannot swallow narration or the next quote."""
    text = (
        'He said "unfinished words here.\n\nNarration stays outside quotes.\n\n'
        '"The actual quoted words are right here."'
    )
    facts = protect(text, [], [], "en", load_config())
    assert facts["quotes"] == ["The actual quoted words are right here."]


@pytest.mark.parametrize("gid", ["F-length", "F-coverage"])
def test_gloss_definitions_cannot_replace_body(gid: str) -> None:
    """Removed claims inserted in a gloss cannot satisfy fidelity gates."""
    source = "Zebras lanterns orchards glaciers submarines mountains forests flowers."
    ctx = replace(context("Cat{= " + source + "}"), source=source)
    settings = section(section(ctx.config, "gates"), gid)
    outcome = REGISTRY[gid](ctx, settings)
    assert outcome is not None
    assert not outcome[0]


@pytest.mark.parametrize(
    ("gid", "source", "body"),
    [
        ("F-numbers", "We saw 42. We saw 42.", "We saw 42."),
        ("F-names", "We saw Rome. We saw Rome.", "We saw Rome."),
    ],
)
def test_fidelity_counts_repeated_claim_facts(gid: str, source: str, body: str) -> None:
    """Keeping one copy of a name or number cannot cover two source claims."""
    ctx = replace(context(body), source=source)
    settings = section(section(ctx.config, "gates"), gid)
    outcome = REGISTRY[gid](ctx, settings)
    assert outcome is not None
    assert not outcome[0]
    outcome = REGISTRY[gid](replace(ctx, parsed=parse(source)), settings)
    assert outcome is not None
    assert outcome[0]


def test_paragraph_gate_names_a_deleted_claim() -> None:
    """A lost paragraph fails even if overall vocabulary survives elsewhere."""
    first = (
        "Zebras roam through forests beside mountains where lanterns illuminate "
        "orchards beneath glaciers and flowers, meadows, canyons, volcanoes, "
        "waterfalls, rainbows, valleys, and deserts."
    )
    second = (
        "Submarines cross rivers beside sailors who explore islands beneath "
        "storms and waves with courage."
    )
    ctx = replace(context(second), source=first + "\n\n" + second)
    settings = section(section(ctx.config, "gates"), "F-paragraphs")
    outcome = REGISTRY["F-paragraphs"](ctx, settings)
    assert outcome is not None
    assert not outcome[0]
    assert any("Zebras roam through forests" in detail for detail in outcome[2])
    outcome = REGISTRY["F-paragraphs"](replace(ctx, parsed=parse(ctx.source)), settings)
    assert outcome is not None
    assert outcome[0]


@pytest.mark.parametrize("gid", ["F-coverage", "L-rare-kept", "L-gloss", "S-grounded"])
def test_wordfreq_languages_without_config_still_run(gid: str) -> None:
    """French frequency data enables vocabulary gates without language lists."""
    ctx = replace(
        context("Parsimony is wise.\n\n@idea: Robots submarines.", "S-grounded"),
        lang="fr",
    )
    settings = section(section(ctx.config, "gates"), gid)
    outcome = REGISTRY[gid](ctx, settings)
    assert outcome is not None, gid
    assert REGISTRY[gid](replace(ctx, lang="la"), settings) is None


def test_wordfreq_nearest_language_fallback_is_not_support() -> None:
    """Latin must never acquire Italian frequency data through nearest matching."""
    assert supported("fr")
    assert not supported("la")


def test_dedication_substring_is_a_real_body_title(tmp_path: Path) -> None:
    """Temple dedication chapters are not the book's dedication page."""
    book = make_epub(tmp_path / "book.epub")
    with ZipFile(book) as archive:
        toc = archive.read("OPS/toc.ncx").replace(
            b"<text>One</text>", b"<text>The Dedication of the Temple</text>"
        )
    rewrite_epub(book, {"OPS/toc.ncx": toc})
    work, _ = ingest_source(tmp_path, book)
    assert read_manifest(work)["units"][0]["kind"] == "body"


@pytest.mark.parametrize("semantics", ["guide", "landmark", "section"])
@pytest.mark.parametrize(
    ("value", "title", "kind"),
    [("dedication", "One", "matter"), ("bodymatter", "Dedication", "body")],
)
def test_epub_semantics_override_title_patterns(
    tmp_path: Path, semantics: str, value: str, title: str, kind: str
) -> None:
    """Publisher semantics take priority over ambiguous human-readable titles."""
    book = make_epub(tmp_path / "book.epub", nav=semantics == "landmark")
    with ZipFile(book) as archive:
        opf = archive.read("OPS/book.opf").decode()
        resource = "OPS/nav.xhtml" if semantics == "landmark" else "OPS/toc.ncx"
        toc = archive.read(resource).decode().replace(">One<", f">{title}<")
        first = archive.read("OPS/one.xhtml").decode()
    if semantics == "guide":
        guide_type = "text" if value == "bodymatter" else value
        opf = opf.replace(
            "</package>",
            "".join(
                (
                    f'<guide><reference type="{guide_type}" ',
                    'href="one.xhtml"/></guide></package>',
                )
            ),
        )
    elif semantics == "landmark":
        toc = toc.replace(
            "</body>",
            "".join(
                (
                    f'<nav epub:type="landmarks"><ol><li><a epub:type="{value}" ',
                    'href="one.xhtml">Landmark</a></li></ol></nav></body>',
                )
            ),
        )
    else:
        first = first.replace(
            "<body>",
            "".join(
                (
                    '<body><section xmlns:epub="http://www.idpf.org/2007/ops" ',
                    f'epub:type="{value}">',
                )
            ),
        ).replace("</body>", "</section></body>")
    rewrite_epub(
        book,
        {
            "OPS/book.opf": opf.encode(),
            resource: toc.encode(),
            "OPS/one.xhtml": first.encode(),
        },
    )
    work, _ = ingest_source(tmp_path, book)
    assert read_manifest(work)["units"][0]["kind"] == kind


def test_emphasis_never_crosses_aside_html() -> None:
    """Unpaired asterisks on each side of an aside cannot produce crossing tags."""
    rendered = render_blocks(
        parse("5 * 3 means fifteen {~ Grim * indeed. ~}").blocks, "italic"
    )
    root = parsed_xml(f"<div>{rendered}</div>")
    assert "".join(root.itertext()) == "5 * 3 means fifteen Grim * indeed."


def test_ingest_and_build_escape_literal_asterisks(tmp_path: Path) -> None:
    """Literal source arithmetic stays literal while actual emphasis survives."""
    book = book_with_body(
        tmp_path, '<h2 id="one">One</h2><p>5 * 3 and * literal <em>real</em>.</p>'
    )
    work, source = ingest_source(tmp_path, book)
    assert r"5 \* 3 and \* literal *real*." in source
    assert plain(r"5 \* 3 and \* literal *real*.") == "5 * 3 and * literal real."
    out = tmp_path / "out.epub"
    result = run("build", "--work", str(work), "--out", str(out), "--allow-pending")
    assert result.returncode == 0, result.stderr
    with ZipFile(out) as archive:
        chapters = [name for name in archive.namelist() if "/chapter-" in name]
        for name in chapters:
            _ = parsed_xml(archive.read(name))
        chapter = parsed_xml(archive.read(chapters[0]))
        assert any(
            element.text == "real"
            for element in chapter.iter()
            if element.tag.endswith("}em")
        )
        assert "5 * 3 and * literal real." in "".join(chapter.itertext())


def test_emoji_gate_allows_typography_and_source_characters() -> None:
    """Typography and original symbols survive, while newly added emoji fail."""
    ctx = replace(context("♯ ♭ ♔ ♀ ☞ © 😀"), source="Original 😀.")
    gate = next(gate for gate in evaluate(ctx) if gate["id"] == "K-no-emoji")
    assert gate["status"] == "pass", gate
    gate = next(
        gate
        for gate in evaluate(replace(ctx, parsed=parse("New ☀️ 😀 🦊")))
        if gate["id"] == "K-no-emoji"
    )
    assert gate["status"] == "fail"
    assert "🦊" in gate["details"]


@pytest.mark.parametrize(
    ("extension", "media", "accepted"),
    [("webp", "image/webp", True), ("xhtml", "application/xhtml+xml", False)],
)
def test_cover_validated_during_ingest(
    tmp_path: Path, extension: str, media: str, *, accepted: bool
) -> None:
    """Unsupported covers warn early; WebP covers remain buildable."""
    book = make_epub(tmp_path / "book.epub")
    with ZipFile(book) as archive:
        opf = archive.read("OPS/book.opf").decode()
    opf = opf.replace(
        "</manifest>",
        "".join(
            (
                f'<item id="cover" href="cover.{extension}" properties="cover-image" ',
                f'media-type="{media}"/></manifest>',
            )
        ),
    )
    rewrite_epub(
        book, {"OPS/book.opf": opf.encode(), f"OPS/cover.{extension}": b"cover"}
    )
    work = tmp_path / "work"
    result = run("ingest", str(book), "--work", str(work))
    assert result.returncode == 0, result.stderr
    assert read_manifest(work)["cover"] == (f"cover.{extension}" if accepted else None)
    if not accepted:
        assert "Warning" in result.stderr
        assert f"cover.{extension}" in result.stderr
    result = run(
        "build",
        "--work",
        str(work),
        "--out",
        str(tmp_path / "out.epub"),
        "--allow-pending",
    )
    assert result.returncode == 0, result.stderr


def test_external_nav_entry_warns_and_keeps_local_chapters(tmp_path: Path) -> None:
    """External TOC entries are skipped without aborting usable spine content."""
    book = make_epub(tmp_path / "book.epub", nav=True)
    with ZipFile(book) as archive:
        nav = archive.read("OPS/nav.xhtml").decode()
    nav = nav.replace(
        "</ol>", '<li><a href="https://example.org/extra">External</a></li></ol>'
    )
    rewrite_epub(book, {"OPS/nav.xhtml": nav.encode()})
    work = tmp_path / "work"
    result = run("ingest", str(book), "--work", str(work))
    assert result.returncode == 0, result.stderr
    assert "Warning" in result.stderr
    assert "https://example.org/extra" in result.stderr
    assert len(read_manifest(work)["units"]) == TWO_ITEMS


@pytest.mark.parametrize("deletion", ["first_claim", "factors", "conclusion"])
def test_art_golden_claim_deletions_fail(art_of_war_work: Path, deletion: str) -> None:
    """Independent deletion probes must trip an error gate under defaults."""
    text = (ROOT / "cookbook/art-of-war-ch01.adapted.txt").read_text(encoding="utf-8")
    patterns = {
        "first_claim": r"\*\*1\.\*\* Sun Tzŭ said:.*?\n\n",
        "factors": r"- \(1\) The Moral Law\n.*?- \(5\) Method and discipline\n",
        "conclusion": r"The general who loses a battle.*?win or lose\.",
    }
    changed, count = re.subn(patterns[deletion], "", text, count=1, flags=re.DOTALL)
    assert count == 1
    adapted(art_of_war_work, "013", changed)
    result = run("check", "013", "--work", str(art_of_war_work))
    assert result.returncode == 1, result.stdout


def test_lazarillo_golden_plinio_deletion_fails(tmp_path: Path) -> None:
    """The Plinio claim cannot vanish while the named person remains in recap."""
    work = tmp_path / "work"
    result = run(
        "ingest", str(ROOT / "tests/fixtures/lazarillo.epub"), "--work", str(work)
    )
    assert result.returncode == 0, result.stderr
    text = (ROOT / "cookbook/lazarillo-prologo.adapted.txt").read_text(encoding="utf-8")
    changed, count = re.subn(
        r"A este propósito dice Plinio.*?buena\.\n\n", "", text, count=1
    )
    assert count == 1
    adapted(work, "001", changed)
    result = run("check", "001", "--work", str(work))
    assert result.returncode == 1, result.stdout


def test_literal_image_marker_is_source_text(tmp_path: Path) -> None:
    """Image-like prose must not create a resource reference or drop braces."""
    book = book_with_body(
        tmp_path, '<h2 id="one">One</h2><p>{image images/a.png | literal}</p>'
    )
    work, source = ingest_source(tmp_path, book)
    assert r"\{image images/a.png | literal\}" in source
    assert read_manifest(work)["units"][0]["images"] == 0
    out = tmp_path / "literal.epub"
    result = run("build", "--work", str(work), "--out", str(out), "--allow-pending")
    assert result.returncode == 0, result.stderr
    with ZipFile(out) as archive:
        visible = "".join(parsed_xml(archive.read("EPUB/chapter-001.xhtml")).itertext())
    assert "{image images/a.png | literal}" in visible
    assert r"\{image" not in visible


def test_external_ncx_parent_keeps_local_child(tmp_path: Path) -> None:
    """Skipping a remote parent entry must preserve its usable nested entry."""
    book = make_epub(tmp_path / "book.epub")
    toc = (
        "<ncx><navMap><navPoint><navLabel><text>External</text></navLabel>"
        '<content src="https://example.org/extra"/><navPoint><navLabel>'
        '<text>Local child</text></navLabel><content src="one.xhtml#one"/>'
        "</navPoint></navPoint><navPoint><navLabel><text>Two</text></navLabel>"
        '<content src="two.xhtml#two"/></navPoint></navMap></ncx>'
    )
    rewrite_epub(book, {"OPS/toc.ncx": toc.encode()})
    work = tmp_path / "work"
    config = tmp_path / "config.toml"
    _ = config.write_text("[ingest]\ntoc_depth = 2\n", encoding="utf-8")
    result = run("ingest", str(book), "--work", str(work), "--config", str(config))
    assert result.returncode == 0, result.stderr
    assert "https://example.org/extra" in result.stderr
    assert read_manifest(work)["units"][0]["title"] == "Local child"


def test_escaped_asterisk_cannot_close_emphasis() -> None:
    """An escaped delimiter remains visible instead of closing an emphasis run."""
    rendered = render_blocks(parse(r"*unclosed \*").blocks)
    assert "".join(parsed_xml(rendered).itertext()) == "*unclosed *"
    assert plain(r"*unclosed \*") == "*unclosed *"


def test_fragment_matter_semantics_end_at_next_chapter(tmp_path: Path) -> None:
    """A dedication landmark must not classify the following chapter as matter."""
    book = make_epub(tmp_path / "book.epub", single=True)
    with ZipFile(book) as archive:
        opf = archive.read("OPS/book.opf").decode()
    opf = opf.replace(
        "</package>",
        '<guide><reference type="dedication" href="one.xhtml#one"/></guide></package>',
    )
    rewrite_epub(book, {"OPS/book.opf": opf.encode()})
    work, _ = ingest_source(tmp_path, book)
    assert [unit["kind"] for unit in read_manifest(work)["units"]] == ["matter", "body"]


def test_section_matter_semantics_end_with_section(tmp_path: Path) -> None:
    """Unmarked body after a matter section needs its own unit."""
    book = book_with_body(
        tmp_path,
        (
            '<section xmlns:epub="http://www.idpf.org/2007/ops" '
            'epub:type="dedication"><h2 id="one">One</h2><p>To my family.</p>'
            "</section><h2>Story</h2><p>Body survives.</p>"
        ),
    )
    work, _ = ingest_source(tmp_path, book)
    units = read_manifest(work)["units"]
    assert units[0]["kind"] == "matter"
    assert units[1]["kind"] == "body"
    assert "Body survives." in (work / units[1]["source"]).read_text(encoding="utf-8")


def test_full_art_of_war_build_has_parseable_chapters(
    art_of_war_work: Path, tmp_path: Path
) -> None:
    """The full fixture, including the unedited golden, emits valid chapter XML."""
    adapted(
        art_of_war_work,
        "013",
        (ROOT / "cookbook/art-of-war-ch01.adapted.txt").read_text(encoding="utf-8"),
    )
    out = tmp_path / "full-art.epub"
    result = run(
        "build", "--work", str(art_of_war_work), "--out", str(out), "--allow-pending"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    expected = {
        unit["chapter"]
        for unit in read_manifest(art_of_war_work)["units"]
        if unit["kind"] == "body"
    }
    with ZipFile(out) as archive:
        chapters = [name for name in archive.namelist() if "/chapter-" in name]
        assert len(chapters) == len(expected)
        for name in chapters:
            assert (
                parsed_xml(archive.read(name)).tag
                == "{http://www.w3.org/1999/xhtml}html"
            )
