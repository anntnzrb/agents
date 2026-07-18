"""Provider adapters; no provider-specific data escapes without a snapshot."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from .errors import ConfigError, ProviderError
from .http import HttpClient, JsonResponse

GG_BASE = "https://api.gg.deals/v1"
STEAM_BASE = "https://store.steampowered.com/api"
CHEAPSHARK_BASE = "https://www.cheapshark.com/api/1.0"
ITAD_BASE = "https://api.isthereanydeal.com"
FRANKFURTER_BASE = "https://api.frankfurter.dev/v2"


def validate_gg_ids(values: list[str]) -> list[str]:
    """Validate, deduplicate, and retain at most 100 GG Deals identifiers."""
    unique: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        for value in raw_value.split(","):
            identifier = value.strip()
            if not identifier.isdigit() or int(identifier) <= 0:
                raise ConfigError(f"invalid GG Deals ID: {identifier or '<empty>'}")
            if identifier not in seen:
                unique.append(identifier)
                seen.add(identifier)
    if not unique:
        raise ConfigError("at least one GG Deals ID is required")
    if len(unique) > 100:
        raise ConfigError("GG Deals accepts at most 100 IDs per request")
    return unique


@dataclass
class GGDealsProvider:
    """Official GG Deals price and bundle-history API."""

    client: HttpClient
    api_key: str

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ConfigError("GG_DEALS_API_KEY is required for provider gg")

    def fetch(
        self,
        *,
        steam_type: str,
        ids: list[str],
        region: str,
        prices: bool = True,
        bundles: bool = True,
    ) -> Iterator[tuple[str, JsonResponse]]:
        """Yield each GG response immediately so later failures keep earlier evidence."""
        identifiers = validate_gg_ids(ids)
        if steam_type not in {"app", "sub", "bundle"}:
            raise ConfigError(f"unsupported Steam ID type: {steam_type}")
        if not prices and not bundles:
            raise ConfigError("at least one of prices or bundles must be requested")

        resources = [
            name for name, enabled in (("prices", prices), ("bundles", bundles)) if enabled
        ]
        for resource in resources:
            response = self.client.get_json(
                f"{GG_BASE}/{resource}/by-steam-{steam_type}-id/",
                provider="gg",
                params={
                    "ids": ",".join(identifiers),
                    "key": self.api_key,
                    "region": region,
                },
            )
            if not isinstance(response.data, dict) or response.data.get("success") is False:
                message = "GG Deals API rejected the request"
                if isinstance(response.data, dict):
                    details = response.data.get("data")
                    if isinstance(details, dict) and details.get("message"):
                        message = f"{message}: {details['message']}"
                raise ProviderError(message, provider="gg", status=response.status)
            yield resource, response


@dataclass
class SteamProvider:
    """Public Steam store search and app metadata endpoints."""

    client: HttpClient

    def search(self, title: str, *, country: str) -> JsonResponse:
        return self.client.get_json(
            f"{STEAM_BASE}/storesearch/",
            provider="steam",
            params={"term": title, "l": "english", "cc": country.upper()},
        )

    def app_details(self, app_id: str, *, country: str) -> JsonResponse:
        return self.client.get_json(
            f"{STEAM_BASE}/appdetails",
            provider="steam",
            params={"appids": app_id, "cc": country.upper(), "l": "english"},
        )


@dataclass
class CheapSharkProvider:
    """CheapShark game, deal, and store endpoints."""

    client: HttpClient

    def search(
        self,
        title: str,
        *,
        steam_app_id: str | None = None,
        limit: int = 10,
    ) -> JsonResponse:
        params: dict[str, Any] = {"limit": min(60, max(1, limit))}
        if steam_app_id:
            params["steamAppID"] = steam_app_id
        else:
            params["title"] = title
        return self.client.get_json(
            f"{CHEAPSHARK_BASE}/games",
            provider="cheapshark",
            params=params,
        )

    def game(self, game_id: str) -> JsonResponse:
        return self.client.get_json(
            f"{CHEAPSHARK_BASE}/games",
            provider="cheapshark",
            params={"id": game_id},
        )

    def stores(self) -> JsonResponse:
        return self.client.get_json(f"{CHEAPSHARK_BASE}/stores", provider="cheapshark")


@dataclass
class ITADProvider:
    """Optional IsThereAnyDeal v3 price adapter using header authentication."""

    client: HttpClient
    api_key: str

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ConfigError("ITAD_API_KEY is required when ITAD is enabled")

    @property
    def headers(self) -> dict[str, str]:
        return {"ITAD-API-Key": self.api_key}

    def search(self, title: str, *, limit: int = 10) -> JsonResponse:
        return self.client.get_json(
            f"{ITAD_BASE}/games/search/v1",
            provider="itad",
            params={"title": title, "results": min(100, max(1, limit))},
            headers=self.headers,
        )

    def prices(self, game_id: str, *, country: str) -> JsonResponse:
        return self.client.post_json(
            f"{ITAD_BASE}/games/prices/v3",
            provider="itad",
            params={"country": country.upper(), "vouchers": "true"},
            headers=self.headers,
            body=[game_id],
        )


@dataclass
class FrankfurterProvider:
    """Keyless currency conversion through Frankfurter v2."""

    client: HttpClient

    def rate(self, base: str, quote: str) -> JsonResponse:
        return self.client.get_json(
            f"{FRANKFURTER_BASE}/rates",
            provider="frankfurter",
            params={"base": base.upper(), "quotes": quote.upper()},
        )
