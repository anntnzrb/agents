# Copyright 2026 Vals-live contributors.
"""Exercise deterministic conditional transport and cache policy."""

import tempfile
import unittest
from urllib.error import URLError

import pytest

from fakes.transport import QueueOpener, Response
from vals_live import cache
from vals_live.cache import CacheError, CacheStore, fetch


class TransportTests(unittest.TestCase):
    """Verify validators, cache reuse, and explicit stale policy."""

    def test_200_then_304_reuses_exact_bytes_and_sends_both_validators(self) -> None:
        opener = QueueOpener(
            Response(
                b'{"catalog":[]}',
                200,
                {
                    "ETag": '"x"',
                    "Last-Modified": "Sat, 09 Aug 2026 00:00:00 GMT",
                    "Content-Type": "application/json",
                },
                "https://www.vals.ai/benchmarks",
            ),
            Response(b"", 304, {"ETag": '"x"'}, "https://www.vals.ai/benchmarks"),
        )
        original = cache.urlopen
        cache.urlopen = opener
        try:
            with tempfile.TemporaryDirectory() as directory:
                store = CacheStore(directory)
                first = fetch(
                    "https://www.vals.ai/benchmarks",
                    discovered_from="https://www.vals.ai/benchmarks",
                    cache=store,
                )
                second = fetch(
                    "https://www.vals.ai/benchmarks",
                    discovered_from="https://www.vals.ai/benchmarks",
                    cache=store,
                )
                assert first.body == second.body
                assert second.cache_reused
                headers = {
                    key.lower(): value
                    for key, value in opener.requests[1].headers.items()
                }
                assert headers.get("if-none-match") == '"x"'
                assert (
                    headers.get("if-modified-since") == "Sat, 09 Aug 2026 00:00:00 GMT"
                )
        finally:
            cache.urlopen = original

    def test_refresh_failure_is_not_implicit_stale(self) -> None:
        opener = QueueOpener(
            Response(
                b'{"catalog":[]}',
                200,
                {"ETag": '"x"'},
                "https://www.vals.ai/benchmarks",
            ),
            URLError("offline"),
            URLError("offline"),
        )
        original = cache.urlopen
        cache.urlopen = opener
        try:
            with tempfile.TemporaryDirectory() as directory:
                store = CacheStore(directory)
                _ = fetch(
                    "https://www.vals.ai/benchmarks",
                    discovered_from="fixture://vals",
                    cache=store,
                )
                with pytest.raises(CacheError) as context:
                    _ = fetch(
                        "https://www.vals.ai/benchmarks",
                        discovered_from="fixture://vals",
                        cache=store,
                    )
                assert context.value.code == "SOURCE_UNAVAILABLE"
                stale = fetch(
                    "https://www.vals.ai/benchmarks",
                    discovered_from="fixture://vals",
                    cache=store,
                    allow_stale=True,
                )
                assert stale.stale
        finally:
            cache.urlopen = original

    def test_304_without_cache_fails(self) -> None:
        original = cache.urlopen
        cache.urlopen = QueueOpener(Response(b"", 304, {"ETag": '"x"'}))
        try:
            with tempfile.TemporaryDirectory() as directory:
                with pytest.raises(CacheError) as context:
                    _ = fetch(
                        "https://www.vals.ai/benchmarks",
                        discovered_from="fixture://vals",
                        cache=CacheStore(directory),
                    )
                assert context.value.code == "CACHE_MISSING"
        finally:
            cache.urlopen = original


if __name__ == "__main__":
    _ = unittest.main()
