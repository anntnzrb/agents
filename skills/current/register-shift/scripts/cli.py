#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
# Copyright (c) 2026
"""Measure text complexity with LIX and RIX, or compare two texts."""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import TypedDict

# Inclusive Unicode block ranges; only letter characters count toward the flag.
UNSEGMENTED_RANGES: tuple[tuple[int, int], ...] = (
    (0x0E00, 0x0E7F),  # Thai
    (0x0E80, 0x0EFF),  # Lao
    (0x0F00, 0x0FFF),  # Tibetan
    (0x1000, 0x109F),  # Myanmar
    (0x1780, 0x17FF),  # Khmer
    (0x3005, 0x3007),  # Han iteration and ideographic marks
    (0x303B, 0x303B),  # Han vertical iteration mark
    (0x3040, 0x309F),  # Hiragana
    (0x30A0, 0x30FF),  # Katakana
    (0x31F0, 0x31FF),  # Katakana Phonetic Extensions
    (0x3400, 0x4DBF),  # Han: CJK Extension A
    (0x4E00, 0x9FFF),  # Han: CJK Unified Ideographs
    (0xA9E0, 0xA9FF),  # Myanmar Extended-B
    (0xAA60, 0xAA7F),  # Myanmar Extended-A
    (0xF900, 0xFAFF),  # Han: CJK Compatibility Ideographs
    (0xFF66, 0xFF9D),  # Halfwidth Katakana
    (0x116D0, 0x116FF),  # Myanmar Extended-C
    (0x16FE3, 0x16FE3),  # Han: Old Chinese iteration mark
    (0x1AFF0, 0x1AFFF),  # Kana Extended-B
    (0x1B000, 0x1B0FF),  # Kana Supplement
    (0x1B100, 0x1B12F),  # Kana Extended-A
    (0x1B130, 0x1B16F),  # Small Kana Extension
    (0x20000, 0x2EE5F),  # Han: CJK Extensions B through F and I
    (0x2F800, 0x2FA1F),  # Han: CJK Compatibility Ideographs Supplement
    (0x30000, 0x3347F),  # Han: CJK Extensions G, H and J
)
LONG_WORD_LENGTH = 6
SENTENCE_BOUNDARY = re.compile(
    r"[.!?…;:。！？؟।॥]+|\r?\n[^\S\r\n]*\r?\n"  # noqa: RUF001 - specified Unicode terminators
)


class NumericMetrics(TypedDict):
    """Numeric metrics shared by scores and comparison deltas."""

    words: int
    sentences: int
    long_words: int | None
    words_per_sentence: float | None
    long_word_pct: float | None
    lix: float | None
    rix: float | None


class Metrics(NumericMetrics):
    """A score, with an explicit warning for unreliable word segmentation."""

    unsegmented_script: bool


class Comparison(TypedDict):
    """Scores for both inputs and their numeric differences."""

    original: Metrics
    rewrite: Metrics
    delta: NumericMetrics


class _Args(argparse.Namespace):
    original: str = ""
    rewrite: str | None = None


def arguments() -> _Args:
    """Parse one or two paths, allowing stdin for at most one input."""
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("original", metavar="ORIGINAL", help="UTF-8 file, or -")
    _ = parser.add_argument(
        "rewrite", nargs="?", metavar="REWRITE", help="UTF-8 file, or -"
    )
    args = parser.parse_args(namespace=_Args())
    if args.original == "-" and args.rewrite == "-":
        parser.error("at most one input may be - (stdin)")
    return args


def words_in(text: str) -> list[str]:
    """Find maximal runs of Unicode letters, marks, and digits."""
    characters = (
        char if unicodedata.category(char)[0] in "LMN" else " " for char in text
    )
    return "".join(characters).split()


def has_unsegmented_script(text: str) -> bool:
    """Flag texts where at least one fifth of letters use unsegmented scripts."""
    letters = [char for char in text if unicodedata.category(char).startswith("L")]
    count = sum(
        any(start <= ord(char) <= end for start, end in UNSEGMENTED_RANGES)
        for char in letters
    )
    return bool(letters) and count * 5 >= len(letters)


def score(text: str) -> Metrics:
    """Calculate rounded metrics, rejecting input with no words."""
    words = words_in(text)
    if not words:
        raise ValueError("text has zero words")
    sentences = sum(bool(words_in(part)) for part in SENTENCE_BOUNDARY.split(text))
    unsegmented = has_unsegmented_script(text)
    long_words = sum(len(word) > LONG_WORD_LENGTH for word in words)
    words_per_sentence = len(words) / sentences
    long_word_pct = 100 * long_words / len(words)
    return {
        "words": len(words),
        "sentences": sentences,
        "long_words": None if unsegmented else long_words,
        "words_per_sentence": None if unsegmented else round(words_per_sentence, 2),
        "long_word_pct": None if unsegmented else round(long_word_pct, 2),
        "lix": None if unsegmented else round(words_per_sentence + long_word_pct, 2),
        "rix": None if unsegmented else round(long_words / sentences, 2),
        "unsegmented_script": unsegmented,
    }


def difference(original: float | None, rewrite: float | None) -> float | None:
    """Subtract numeric values, propagating unavailable metrics."""
    if original is None or rewrite is None:
        return None
    return round(rewrite - original, 2)


def compare(original: Metrics, rewrite: Metrics) -> Comparison:
    """Compare already rounded scores without including the boolean flag."""
    return {
        "original": original,
        "rewrite": rewrite,
        "delta": {
            "words": rewrite["words"] - original["words"],
            "sentences": rewrite["sentences"] - original["sentences"],
            "long_words": (
                None
                if original["long_words"] is None or rewrite["long_words"] is None
                else rewrite["long_words"] - original["long_words"]
            ),
            "words_per_sentence": difference(
                original["words_per_sentence"], rewrite["words_per_sentence"]
            ),
            "long_word_pct": difference(
                original["long_word_pct"], rewrite["long_word_pct"]
            ),
            "lix": difference(original["lix"], rewrite["lix"]),
            "rix": difference(original["rix"], rewrite["rix"]),
        },
    }


def read_input(path: str) -> str:
    """Read UTF-8 from a file or stdin."""
    if path == "-":
        return sys.stdin.buffer.read().decode("utf-8")
    return Path(path).read_text(encoding="utf-8")


def main() -> int:
    """Print one JSON document, returning two for invalid input."""
    args = arguments()
    try:
        original = score(read_input(args.original))
        result = (
            original
            if args.rewrite is None
            else compare(original, score(read_input(args.rewrite)))
        )
    except (OSError, UnicodeError, ValueError) as exc:
        _ = sys.stderr.write(f"register-shift: {exc}\n")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
