"""Provider request constraints and optional authentication tests."""

from __future__ import annotations

import unittest
from typing import Any

from game_deals.errors import ConfigError, ProviderError
from game_deals.http import JsonResponse
from game_deals.providers import GGDealsProvider, ITADProvider, validate_gg_ids


class RecordingClient:
    def __init__(self, data: Any) -> None:
        self.data = data
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_json(self, url: str, **kwargs: Any) -> JsonResponse:
        self.calls.append((url, kwargs))
        return JsonResponse(self.data, 200, url, {})

    def post_json(self, url: str, **kwargs: Any) -> JsonResponse:
        self.calls.append((url, kwargs))
        return JsonResponse(self.data, 200, url, {})


class ProviderTests(unittest.TestCase):
    def test_gg_ids_deduplicate_and_cap_at_100(self) -> None:
        self.assertEqual(validate_gg_ids(["1,2", "2", "3"]), ["1", "2", "3"])
        with self.assertRaises(ConfigError):
            validate_gg_ids([str(value) for value in range(1, 102)])
        with self.assertRaises(ConfigError):
            validate_gg_ids(["-1"])

    def test_gg_fetches_price_and_bundle_endpoints(self) -> None:
        client = RecordingClient({"success": True, "data": {}})
        provider = GGDealsProvider(client, "test-key")  # type: ignore[arg-type]
        responses = list(provider.fetch(steam_type="sub", ids=["10"], region="us"))
        self.assertEqual([name for name, _ in responses], ["prices", "bundles"])
        self.assertIn("prices/by-steam-sub-id", client.calls[0][0])
        self.assertEqual(client.calls[0][1]["params"]["key"], "test-key")

    def test_gg_surfaces_api_level_failure(self) -> None:
        client = RecordingClient({"success": False, "data": {"message": "bad region"}})
        provider = GGDealsProvider(client, "test-key")  # type: ignore[arg-type]
        with self.assertRaises(ProviderError) as caught:
            list(provider.fetch(steam_type="app", ids=["220"], region="xx"))
        self.assertIn("bad region", str(caught.exception))

    def test_gg_yields_price_evidence_before_later_bundle_failure(self) -> None:
        class PartialClient(RecordingClient):
            def get_json(self, url: str, **kwargs: Any) -> JsonResponse:
                if "/bundles/" in url:
                    raise ProviderError("bundle failed", provider="gg", status=503)
                return super().get_json(url, **kwargs)

        provider = GGDealsProvider(
            PartialClient({"success": True, "data": {}}),
            "test-key",
        )  # type: ignore[arg-type]
        responses = provider.fetch(steam_type="app", ids=["220"], region="us")
        name, _ = next(responses)
        self.assertEqual(name, "prices")
        with self.assertRaises(ProviderError):
            next(responses)

    def test_itad_is_optional_and_uses_header_not_query_key(self) -> None:
        with self.assertRaises(ConfigError):
            ITADProvider(RecordingClient([]), "")  # type: ignore[arg-type]
        client = RecordingClient([])
        provider = ITADProvider(client, "itad-secret")  # type: ignore[arg-type]
        provider.search("Half-Life 2")
        _, kwargs = client.calls[0]
        self.assertEqual(kwargs["headers"]["ITAD-API-Key"], "itad-secret")
        self.assertNotIn("key", kwargs["params"])


if __name__ == "__main__":
    unittest.main()
