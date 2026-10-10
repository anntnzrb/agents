# Copyright (c) 2026
"""Unicode tokens, sentence boundaries, readability, and protected facts."""

import re
import unicodedata
from collections import Counter

from .config import language, section
from .data import Facts, Table, integer, number, strings
from .freq import supported, zipf

ACRONYM_MIN_LENGTH = 2
NOMINAL_MIN_LENGTH = 6
OPENING_MARKS = " \n\t\r[(\"“«'\u2018¿¡"

WORDS = re.compile(r"[^\W\d_]+(?:['\u2019][^\W\d_]+)*|\d+(?:[.,]\d+)*", re.UNICODE)
NUMBERS = re.compile(r"(?<!\w)\d+(?:[.,]\d+)*(?!\w)")
ABBREVIATIONS = frozenset(
    ("mr", "mrs", "dr", "st", "vs", "e.g", "i.e", "etc", "sr", "sra")
)


def words(text: str) -> list[str]:
    """Tokenize alphabetic words and numeric tokens."""
    return WORDS.findall(unicodedata.normalize("NFC", text))


def plain(text: str, *, block_syntax: bool = True) -> str:
    """Remove the supported Markdown block and emphasis syntax."""
    if block_syntax:
        text = re.sub(r"(?m)^\s*(?:#{1,6}\s+|>\s?|[-*]\s+)", "", text)
    text = unescape_braces(text).replace(r"\.", ".")
    text = re.sub(r"(?<!\\)\*\*((?:\\\*|[^*])+)(?<!\\)\*\*", r"\1", text)
    return re.sub(r"(?<!\\)\*((?:\\\*|[^*])+)(?<!\\)\*", r"\1", text).replace(
        r"\*", "*"
    )


def unescape_braces(text: str) -> str:
    """Decode literal braces escaped to avoid adapted marker syntax."""
    return re.sub(r"\\([{}])", r"\1", text)


def normalize(text: str) -> str:
    """Normalize whitespace and typographic quotation variants."""
    return " ".join(
        text.translate(str.maketrans("“”\u2018\u2019«»", '""\'\'""')).split()
    ).strip('"')


def sentences(text: str) -> list[str]:
    """Split at block boundaries, retaining abbreviations and capital initials."""
    return [
        sentence
        for block in re.split(r"\n\s*\n", text)
        for sentence in _sentences(block)
    ]


def _sentences(text: str) -> list[str]:
    """Split one text block at sentence-ending punctuation."""
    result: list[str] = []
    start = 0
    for match in re.finditer(r"[.!?…]+[\"'”\u2019»\])]*(?=\s+|$)", text):
        end = match.end()
        remainder = text[end:].lstrip(OPENING_MARKS)
        if remainder and not (remainder[0].isupper() or remainder[0].isdigit()):
            continue
        token = (
            text[: match.start()].rsplit(maxsplit=1)[-1]
            if text[: match.start()].strip()
            else ""
        )
        token = token.strip("\"“«('")
        if match.group().startswith(".") and (
            token.lower() in ABBREVIATIONS
            or (len(token) == 1 and token.isupper())
            or text[: match.start()].strip().isdigit()
        ):
            continue
        segment = text[start:end].strip()
        if segment:
            result.append(segment)
        start = end
    tail = text[start:].strip()
    if tail:
        result.append(tail)
    return result


def syllables(word: str, lang: str) -> int:
    """Estimate syllables using language vowel groups."""
    value = word.lower()
    if lang == "en" and value.endswith("e") and not value.endswith("le"):
        value = value[:-1]
    if lang == "es" and value.endswith("y"):
        value = value[:-1] + "i"
    vowels = "aeiouy" if lang == "en" else "aeiouáéíóúü"
    return max(1, len(re.findall(f"[{vowels}]+", value)))


def readability(text: str, lang: str) -> float:
    """Compute Flesch-Kincaid grade or Fernández Huerta ease."""
    tokens = words(text)
    count = len(tokens)
    if not count:
        return 0.0
    sentence_count = max(1, len(sentences(text)))
    syllable_count = sum(syllables(token, lang) for token in tokens)
    if lang == "es":
        return 206.84 - 60 * syllable_count / count - 102 * sentence_count / count
    return 0.39 * count / sentence_count + 11.8 * syllable_count / count - 15.59


def occurrences(
    text: str, term: str, *, insensitive: bool = False
) -> list[re.Match[str]]:
    """Find boundary-delimited words or multiword phrases."""
    expression = r"\s+".join(re.escape(part) for part in term.split())
    return list(
        re.finditer(
            rf"(?<!\w){expression}(?!\w)", text, re.IGNORECASE if insensitive else 0
        )
    )


def hedge_counts(text: str, phrases: list[str]) -> dict[str, int]:
    """Count each configured hedge phrase independently."""
    return {
        phrase: count
        for phrase in phrases
        if (count := len(occurrences(text, phrase, insensitive=True)))
    }


def name_token(token: str) -> str:
    """Normalize possessive endings while retaining a name's internal apostrophes."""
    return re.sub(r"['\u2019]s$", "", token)


def proper_nouns(text: str) -> list[str]:
    """Protect capitalized tokens seen beyond a sentence's first token."""
    tokens = [name_token(token) for token in words(text)]
    lowercase = {token for token in tokens if token.islower()}
    candidates: set[str] = set()
    for sentence in sentences(text):
        for match in WORDS.finditer(sentence):
            token = name_token(match.group())
            prefix = re.sub(r"^\s*\d+(?:,\s*\d+)*\.\s+", "", sentence[: match.start()])
            if not prefix.strip(OPENING_MARKS) or re.search(
                r"(?:^|[\s:(])[\"“«'\u2018][\s[(¿¡]*$", prefix
            ):
                continue
            if (
                token[0].isupper()
                and token.lower() not in lowercase
                and (not token.isupper() or len(token) >= ACRONYM_MIN_LENGTH)
            ):
                candidates.add(token)
    return list(dict.fromkeys(token for token in tokens if token in candidates))


def protect(
    text: str, quotes: list[str], headings: list[str], lang: str, config: Table
) -> Facts:
    """Extract deterministic facts from source plain text."""
    settings = section(config, "protect")
    inline = [
        normalize(match.group(1))
        for paragraph in text.split("\n\n")
        for match in re.finditer(r"[“\"]([^“”\"\n]+)[”\"]", paragraph)
        if match.group(1) is not None
        and len(words(match.group(1))) >= integer(settings["min_quote_words"])
    ]
    inline.extend(
        normalize(match.group(1))
        for paragraph in text.split("\n\n")
        for match in re.finditer(r"«([^»\n]+)»", paragraph)
        if len(words(match.group(1))) >= integer(settings["min_quote_words"])
    )
    name_body = "\n\n".join(
        block for block in text.split("\n\n") if block not in headings
    )
    names = proper_nouns(name_body)
    body_tokens = words(name_body)
    excluded = {name.lower() for name in names} | {
        token.lower() for token in body_tokens if token[0].isupper()
    }
    tokens = words(text)
    has_data = supported(lang)
    rare = list(
        dict.fromkeys(
            token.lower()
            for token in body_tokens
            if token.isalpha()
            and len(token) >= integer(settings["rare_min_length"])
            and token.lower() not in excluded
            and has_data
            and zipf(token.lower(), lang) < number(settings["rare_zipf"])
        )
    )
    rules = language(config, lang)
    return Facts(
        quotes=list(dict.fromkeys([*(normalize(quote) for quote in quotes), *inline])),
        numbers=list(dict.fromkeys(NUMBERS.findall(text))),
        proper_nouns=names,
        hedges=hedge_counts(text, strings(rules["hedges"]))
        if rules and "hedges" in rules
        else {},
        rare_words=rare,
        headings=headings,
        words=len(tokens),
    )


def nominal_ratio(text: str, suffixes: list[str]) -> float:
    """Return the nominalized share of all tokens."""
    tokens = words(text)
    counts = Counter(token.lower() for token in tokens)
    return sum(
        count
        for token, count in counts.items()
        if len(token) >= NOMINAL_MIN_LENGTH and token.endswith(tuple(suffixes))
    ) / max(1, len(tokens))
