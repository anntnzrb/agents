"""Secret redaction and Retry-After behavior tests."""

from __future__ import annotations

import io
import unittest
from urllib.error import HTTPError

from game_deals.errors import ProviderError
from game_deals.http import HttpClient, redact_data, redact_url


class HttpTests(unittest.TestCase):
    def test_redacts_all_secret_query_names(self) -> None:
        safe = redact_url(
            "https://example.test/x?key=abc&ids=1&access_token=def#fragment",
        )
        self.assertNotIn("abc", safe)
        self.assertNotIn("def", safe)
        self.assertNotIn("fragment", safe)
        self.assertIn("ids=1", safe)

    def test_redacts_echoed_urls_and_secret_fields_in_payloads(self) -> None:
        redacted = redact_data(
            {
                "key": "super-secret",
                "echo": "https://api.test/x?ids=1&key=super-secret&region=us",
            },
        )
        self.assertEqual(redacted["key"], "[REDACTED]")
        self.assertNotIn("super-secret", redacted["echo"])

    def test_honors_retry_after_then_raises_safe_error(self) -> None:
        sleeps: list[float] = []

        def opener(request: object, *, timeout: float) -> object:
            del request, timeout
            raise HTTPError(
                "https://example.test/?key=super-secret",
                429,
                "rate limited",
                {"Retry-After": "2"},
                io.BytesIO(b"rate limited: super-secret"),
            )

        client = HttpClient(opener=opener, sleep=sleeps.append, max_retries=1)
        with self.assertRaises(ProviderError) as caught:
            client.get_json(
                "https://example.test/",
                provider="fixture",
                params={"key": "super-secret"},
            )
        self.assertEqual(sleeps, [2.0])
        self.assertNotIn("super-secret", str(caught.exception))
        self.assertEqual(caught.exception.retry_after, 2.0)


if __name__ == "__main__":
    unittest.main()
