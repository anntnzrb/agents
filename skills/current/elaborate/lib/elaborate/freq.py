# Copyright (c) 2026
"""Contain the untyped wordfreq dependency at one typed boundary."""

import importlib
from functools import cache
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable


class _Frequency(Protocol):
    def __call__(self, word: str, lang: str) -> object: ...


@cache
def zipf(word: str, lang: str) -> float:
    """Return Zipf frequency; unsupported languages raise LookupError."""
    module = importlib.import_module("wordfreq")
    function = cast("_Frequency", module.zipf_frequency)
    try:
        result = function(word, lang)
    except (LookupError, ValueError) as error:
        raise LookupError(f"No wordfreq data for {lang}") from error
    if not isinstance(result, (float, int)):
        raise TypeError("wordfreq returned a non-numeric frequency")
    return float(result)


def supported(lang: str) -> bool:
    """Require exact wordfreq support, excluding nearest-language fallback."""
    module = importlib.import_module("wordfreq")
    available = cast("Callable[[], dict[str, str]]", module.available_languages)
    return lang in available()
