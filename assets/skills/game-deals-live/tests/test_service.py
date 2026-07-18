"""Service contract tests for regions, failures, and checkout queues."""

from __future__ import annotations

import unittest

from game_deals.errors import ProviderError
from game_deals.http import JsonResponse
from game_deals.service import (
    GameDealsService,
    _envelope,
    _queue_offer_verification,
    _record_error,
    gg_region_for_country,
)


class ServiceContractTests(unittest.TestCase):
    def test_gg_region_uses_supported_value_or_us_proxy(self) -> None:
        self.assertEqual(gg_region_for_country("DE"), ("de", False))
        self.assertEqual(gg_region_for_country("EC"), ("us", True))
        self.assertEqual(gg_region_for_country("RU"), ("us", True))

    def test_verification_queue_is_five_strict_cheapest_checkout_targets(self) -> None:
        payload = _envelope("lookup", query="x", request={}, started="now")
        payload["offers"] = [
            {
                "provider": "fixture",
                "store": f"Store {value}",
                "url": f"https://example.test/{value}",
                "price": {"amount": float(value), "currency": "USD"},
                "acquisition_type": "direct_ownership",
                "evidence_status": "estimated",
            }
            for value in (6, 1, 5, 2, 4, 3)
        ]
        _queue_offer_verification(payload)
        self.assertEqual(len(payload["verification_queue"]), 5)
        indices = [item["details"]["offer_index"] for item in payload["verification_queue"]]
        self.assertEqual(indices, [1, 3, 5, 4, 2])
        fields = payload["verification_queue"][0]["details"]["checkout_fields"]
        self.assertIn("mandatory_fees", fields)
        self.assertIn("preselected_extras", fields)
        self.assertIn("claimed_region", fields)

    def test_provider_failures_are_explicit_and_snapshot_backed(self) -> None:
        payload = _envelope("stores", query=None, request={}, started="now")
        error = ProviderError(
            "fixture failed",
            provider="fixture",
            status=503,
            retry_after=3,
        )
        _record_error(payload, error, stage="read")
        self.assertEqual(len(payload["provider_failures"]), 1)
        self.assertEqual(payload["provider_snapshots"][0]["status"], "error")
        self.assertEqual(payload["provider_failures"][0]["retry_after"], 3)

    def test_failed_fx_marks_native_price_incomparable(self) -> None:
        class FailedFxClient:
            def get_json(self, *_args: object, **_kwargs: object) -> object:
                raise ProviderError("fx failed", provider="frankfurter", status=503)

        payload = _envelope("lookup", query="x", request={}, started="now")
        payload["offers"] = [
            {
                "price": {"amount": 1.0, "currency": "EUR"},
                "evidence_status": "estimated",
            },
        ]
        service = GameDealsService(env={}, client=FailedFxClient())  # type: ignore[arg-type]
        status = service._convert_offers(payload, "USD")  # noqa: SLF001
        self.assertEqual(status, 1)
        self.assertFalse(payload["offers"][0]["price_comparable"])
        self.assertEqual(payload["offers"][0]["evidence_status"], "blocked")

    def test_gg_partial_failure_keeps_finalized_price_and_exit_one(self) -> None:
        class PartialGgClient:
            def get_json(self, url: str, **_kwargs: object) -> JsonResponse:
                if "/bundles/" in url:
                    raise ProviderError("bundle failed", provider="gg", status=503)
                return JsonResponse(
                    {
                        "success": True,
                        "data": {
                            "220": {
                                "prices": {"currency": "USD", "currentRetail": 4.99},
                            },
                        },
                    },
                    200,
                    url,
                    {},
                )

        service = GameDealsService(
            env={"GG_DEALS_API_KEY": "fixture"},
            client=PartialGgClient(),  # type: ignore[arg-type]
        )
        result = service.provider_gg(steam_type="app", ids=["220"])
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(len(result.payload["offers"]), 1)
        self.assertEqual(result.payload["rankings"]["absolute_cheapest"]["offer_index"], 0)
        required = {
            "seller",
            "original_price",
            "regular_price",
            "price_comparable",
            "mandatory_fees",
        }
        self.assertTrue(required <= result.payload["offers"][0].keys())


if __name__ == "__main__":
    unittest.main()
