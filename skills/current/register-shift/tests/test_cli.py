# Copyright (c) 2026
# ruff: noqa: INP001 - standalone skill tests, no package required
# ruff: noqa: PLR2004 - literal expected values document the public contract
# ruff: noqa: RUF001 - fixtures intentionally exercise Unicode terminators
"""Verify complexity arithmetic and the public JSON CLI using real inputs."""

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import cli

LOAD_JSON: Callable[[str], object] = json.loads
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"
ENGLISH = "Simple words communicate ideas. Cats run."
ENGLISH_METRICS = {
    "words": 6,
    "sentences": 2,
    "long_words": 1,
    "words_per_sentence": 3.0,
    "long_word_pct": 16.67,
    "lix": 19.67,
    "rix": 0.5,
    "unsegmented_script": False,
}


def run_cli(*paths: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    """Run the actual entrypoint with the gate's interpreter and UTF-8 streams."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *paths],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=10,
    )


def test_hand_calculated_english() -> None:
    """Six words, two sentences, one long word give LIX 3 + 100/6."""
    assert cli.score(ENGLISH) == ENGLISH_METRICS


def test_real_file_json(tmp_path: Path) -> None:
    """A UTF-8 file produces just the ordered metrics JSON on stdout."""
    source = tmp_path / "original.txt"
    _ = source.write_text(ENGLISH, encoding="utf-8")
    result = run_cli(str(source))
    assert result.returncode == 0
    assert result.stderr == ""
    assert (
        result.stdout
        == json.dumps(ENGLISH_METRICS, ensure_ascii=False, indent=2) + "\n"
    )


def test_spanish_accents(tmp_path: Path) -> None:
    """Accented letters remain in words, including seven-character canción."""
    source = tmp_path / "español.txt"
    _ = source.write_text("La canción inspira alegría.", encoding="utf-8")
    result = run_cli(str(source))
    assert result.returncode == 0
    assert LOAD_JSON(result.stdout) == {
        "words": 4,
        "sentences": 1,
        "long_words": 3,
        "words_per_sentence": 4.0,
        "long_word_pct": 75.0,
        "lix": 79.0,
        "rix": 3.0,
        "unsegmented_script": False,
    }


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_blank_lines(newline: str) -> None:
    """Whitespace-only lines split sentences; ordinary line wraps do not."""
    text = f"One{newline}two{newline} \t{newline}{newline}Three four"
    metrics = cli.score(text)
    assert metrics["words"] == 4
    assert metrics["sentences"] == 2
    assert metrics["lix"] == 2.0


def test_no_terminator() -> None:
    """A nonempty fragment is one sentence without requiring punctuation."""
    metrics = cli.score("one two three")
    assert metrics["sentences"] == 1
    assert metrics["lix"] == 3.0


@pytest.mark.parametrize("terminator", list(".!?…;:。！？؟।॥"))
def test_sentence_terminators(terminator: str) -> None:
    """Every documented terminator splits, and empty segments never count."""
    metrics = cli.score(f"{terminator}One{terminator * 3}Two{terminator}")
    assert metrics["sentences"] == 2
    assert metrics["words"] == 2


def test_word_boundaries_and_marks() -> None:
    """Apostrophes, hyphens, and underscores split; combining marks stay."""
    assert cli.words_in("don't re-write a_b cafe\u0301 123") == [
        "don",
        "t",
        "re",
        "write",
        "a",
        "b",
        "cafe\u0301",
        "123",
    ]
    metrics = cli.score("abcdef abcdefg")
    assert metrics["long_words"] == 1
    assert metrics["lix"] == 52.0


def test_japanese_nulls() -> None:
    """Unsegmented text retains counts but suppresses misleading scores."""
    assert cli.score("猫が眠る。犬が走る！") == {
        "words": 2,
        "sentences": 2,
        "long_words": None,
        "words_per_sentence": None,
        "long_word_pct": None,
        "lix": None,
        "rix": None,
        "unsegmented_script": True,
    }


@pytest.mark.parametrize("text", ["漢", "あ", "ア", "ก", "ກ", "ក", "က", "ཀ", "𠀀"])
def test_script_detection(text: str) -> None:
    """All eight specified scripts and supplementary Han are recognized."""
    assert cli.has_unsegmented_script(text) is True


def test_script_threshold_uses_letters_only() -> None:
    """Exactly 20% triggers the flag, while digits never dilute the ratio."""
    assert cli.has_unsegmented_script("漢abcd 123456789 !!!") is True
    assert cli.has_unsegmented_script("漢abcde") is False
    assert cli.has_unsegmented_script("123456") is False


@pytest.mark.parametrize("rewrite", ["Cats run.", "猫が眠る。犬が走る！"])
def test_comparison(tmp_path: Path, rewrite: str) -> None:
    """Two real files return rewrite-minus-original deltas, including nulls."""
    original_path = tmp_path / "original.txt"
    rewrite_path = tmp_path / "rewrite.txt"
    _ = original_path.write_text(ENGLISH, encoding="utf-8")
    _ = rewrite_path.write_text(rewrite, encoding="utf-8")
    result = run_cli(str(original_path), str(rewrite_path))
    assert result.returncode == 0
    assert result.stderr == ""
    payload: object = LOAD_JSON(result.stdout)
    assert isinstance(payload, dict)
    assert payload["original"] == ENGLISH_METRICS
    if rewrite == "Cats run.":
        assert payload["rewrite"] == {
            "words": 2,
            "sentences": 1,
            "long_words": 0,
            "words_per_sentence": 2.0,
            "long_word_pct": 0.0,
            "lix": 2.0,
            "rix": 0.0,
            "unsegmented_script": False,
        }
        assert payload["delta"] == {
            "words": -4,
            "sentences": -1,
            "long_words": -1,
            "words_per_sentence": -1.0,
            "long_word_pct": -16.67,
            "lix": -17.67,
            "rix": -0.5,
        }
    else:
        assert payload["rewrite"] == cli.score(rewrite)
        assert payload["delta"] == {
            "words": -4,
            "sentences": 0,
            "long_words": None,
            "words_per_sentence": None,
            "long_word_pct": None,
            "lix": None,
            "rix": None,
        }


def test_null_propagation_from_original() -> None:
    """An unavailable original score also makes each derived delta null."""
    delta = cli.compare(cli.score("猫。"), cli.score("Cats run."))["delta"]
    assert delta == {
        "words": 1,
        "sentences": 0,
        "long_words": None,
        "words_per_sentence": None,
        "long_word_pct": None,
        "lix": None,
        "rix": None,
    }


def test_stdin() -> None:
    """A single dash consumes UTF-8 stdin."""
    result = run_cli("-", stdin=ENGLISH)
    assert result.returncode == 0
    assert LOAD_JSON(result.stdout) == ENGLISH_METRICS


@pytest.mark.parametrize("stdin_first", [True, False])
def test_stdin_comparison(tmp_path: Path, *, stdin_first: bool) -> None:
    """Stdin may supply either side of a comparison."""
    source = tmp_path / "text.txt"
    _ = source.write_text("Cats run.", encoding="utf-8")
    paths = ("-", str(source)) if stdin_first else (str(source), "-")
    result = run_cli(*paths, stdin="Cats run.")
    assert result.returncode == 0
    payload: object = LOAD_JSON(result.stdout)
    assert isinstance(payload, dict)
    assert payload["delta"] == {
        "words": 0,
        "sentences": 0,
        "long_words": 0,
        "words_per_sentence": 0.0,
        "long_word_pct": 0.0,
        "lix": 0.0,
        "rix": 0.0,
    }


@pytest.mark.parametrize("text", ["", " \t\n", "...!?…。؛"])
def test_zero_words(tmp_path: Path, text: str) -> None:
    """Empty or punctuation-only files are input errors with no JSON output."""
    source = tmp_path / "empty.txt"
    _ = source.write_text(text, encoding="utf-8")
    result = run_cli(str(source))
    assert result.returncode == 2
    assert result.stdout == ""
    assert "zero words" in result.stderr
    with pytest.raises(ValueError, match="zero words"):
        _ = cli.score(text)


def test_missing_file(tmp_path: Path) -> None:
    """A missing file reports its path and returns the input-error status."""
    missing = tmp_path / "missing.txt"
    result = run_cli(str(missing))
    assert result.returncode == 2
    assert result.stdout == ""
    assert "missing.txt" in result.stderr


@pytest.mark.parametrize("paths", [(), ("-", "-"), ("a", "b", "c")])
def test_usage_errors(paths: tuple[str, ...]) -> None:
    """Missing arguments, duplicate stdin, and excess arguments exit two."""
    result = run_cli(*paths)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "error:" in result.stderr


def test_invalid_utf8(tmp_path: Path) -> None:
    """Malformed UTF-8 is a clean input error, rather than a traceback."""
    source = tmp_path / "invalid.txt"
    _ = source.write_bytes(b"\xff")
    result = run_cli(str(source))
    assert result.returncode == 2
    assert result.stdout == ""
    assert "utf-8" in result.stderr
    assert "Traceback" not in result.stderr
