# Copyright (c) 2026
"""Real-file EPUB and CLI helpers for behavioral tests."""

import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.cli import main

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "cli.py"
PARAGRAPH = "The cat may sit by Rome and see 42 birds. " * 8
ADAPTED_BODY = PARAGRAPH.replace("birds. ", "birds.\n\n")
DIRECTIVES = (
    "@idea: The cat may sit.\n\n@question: What does it see?\n\n"
    "@why: We can look.\n\n@recap:\n- One\n- Two\n- Three\n\n"
    "@quiz:\n1. What?\n2. Why?\n\n@answers:\n1. Cat\n2. Birds\n\n"
)


def run(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Exercise the public CLI in process with isolated output and environment."""
    stdout, stderr = StringIO(), StringIO()
    with (
        redirect_stdout(stdout),
        redirect_stderr(stderr),
        pytest.MonkeyPatch.context() as monkeypatch,
    ):
        if env is not None:
            for key in os.environ.keys() - env.keys():
                monkeypatch.delenv(key)
            for key, value in env.items():
                monkeypatch.setenv(key, value)
        try:
            returncode = main(list(args))
        except SystemExit as error:
            returncode = (
                error.code
                if isinstance(error.code, int)
                else int(error.code is not None)
            )
            if isinstance(error.code, str):
                _ = stderr.write(error.code + "\n")
    return subprocess.CompletedProcess(
        args, returncode, stdout.getvalue(), stderr.getvalue()
    )


def run_subprocess(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the script at a real process boundary for each public command."""
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def make_epub(
    path: Path, *, nav: bool = False, drm: str = "", single: bool = False
) -> Path:
    """Create EPUB2 NCX or EPUB3 anchored navigation with real source files."""
    doc = '<html xmlns="http://www.w3.org/1999/xhtml"><body>{}</body></html>'
    first = '<h2 id="one">One</h2><p>' + PARAGRAPH + "</p>"
    second = '<h2 id="two">Two</h2><p>' + PARAGRAPH + "</p>"
    manifest = '<item id="one" href="one.xhtml" media-type="application/xhtml+xml" />'
    spine = '<itemref idref="one" />'
    if not single:
        manifest += (
            '<item id="two" href="two.xhtml" media-type="application/xhtml+xml" />'
        )
        spine += '<itemref idref="two" />'
    nav_path = "one.xhtml#two" if single else "two.xhtml#two"
    if nav:
        manifest += (
            '<item id="nav" href="nav.xhtml" properties="nav" '
            'media-type="application/xhtml+xml" />'
        )
    else:
        manifest += (
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml" />'
        )
    container = (
        '<container><rootfiles><rootfile full-path="OPS/book.opf" />'
        "</rootfiles></container>"
    )
    package = (
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:title>Test &amp; book</dc:title><dc:creator>A Writer</dc:creator>"
        "<dc:creator>B Writer</dc:creator><dc:language>en-US</dc:language>"
        "<dc:identifier>test</dc:identifier></metadata>"
        f'<manifest>{manifest}</manifest><spine toc="ncx">{spine}</spine></package>'
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/book.opf", package)
        archive.writestr(
            "OPS/one.xhtml", doc.format(first + second if single else first)
        )
        if not single:
            archive.writestr("OPS/two.xhtml", doc.format(second))
        if nav:
            navigation = (
                '<html xmlns:epub="http://www.idpf.org/2007/ops"><body>'
                '<nav epub:type="toc"><ol><li><a href="one.xhtml#one">One</a></li>'
                f'<li><a href="{nav_path}">Two</a></li></ol></nav></body></html>'
            )
            archive.writestr("OPS/nav.xhtml", navigation)
        else:
            navigation = (
                "<ncx><navMap><navPoint><navLabel><text>One</text></navLabel>"
                '<content src="one.xhtml#one" /></navPoint><navPoint><navLabel>'
                "<text>Two</text></navLabel>"
                f'<content src="{nav_path}" /></navPoint></navMap></ncx>'
            )
            archive.writestr("OPS/toc.ncx", navigation)
        if drm == "rights":
            archive.writestr("META-INF/rights.xml", "<rights />")
        elif drm:
            archive.writestr(
                "META-INF/encryption.xml",
                '<encryption><EncryptionMethod Algorithm="' + drm + '" /></encryption>',
            )
    return path


def adapted(work: Path, uid: str, text: str) -> None:
    """Write a model-owned adapted unit only from tests."""
    (work / "adapted").mkdir(exist_ok=True)
    _ = (work / "adapted" / f"{uid}.md").write_text(text, encoding="utf-8")


def rewrite_epub(path: Path, replacements: dict[str, bytes]) -> None:
    """Rewrite synthetic resources without duplicate ZIP entries."""
    with ZipFile(path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    files |= replacements
    with ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
