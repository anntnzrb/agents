"""Command-level orchestration with partial-result evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import ConfigError, ProviderError
from .http import HttpClient, JsonResponse
from .identity import choose_candidate, steam_identity
from .normalize import (
    apply_fx,
    extract_fx_rate,
    finalize_offers,
    normalize_cheapshark_game,
    normalize_gg_bundle_history,
    normalize_gg_prices,
    normalize_itad_prices,
    normalize_steam_app,
    rank_offers,
    utc_now,
)
from .providers import (
    CheapSharkProvider,
    FrankfurterProvider,
    GGDealsProvider,
    ITADProvider,
    SteamProvider,
    validate_gg_ids,
)
from .schema import SCHEMA_VERSION


@dataclass(frozen=True)
class ServiceResult:
    """Structured result plus process exit status."""

    payload: dict[str, Any]
    exit_code: int = 0


class GameDealsService:
    """Reusable lookup engine independent from argparse and rendering."""

    def __init__(
        self,
        *,
        env: dict[str, str],
        client: HttpClient | None = None,
    ) -> None:
        self.env = env
        self.client = client or HttpClient()

    def lookup(
        self,
        query: str | None,
        *,
        country: str = "US",
        currency: str = "USD",
        top: int = 5,
        include_itad: bool = False,
        explicit_steam: dict[str, str] | None = None,
    ) -> ServiceResult:
        """Resolve identity, acquire provider evidence, normalize, and rank."""
        if query is not None and not query.strip():
            query = None
        if query is None and explicit_steam is None:
            raise ConfigError("lookup requires a query or an explicit Steam ID option")
        if explicit_steam is not None:
            if explicit_steam.get("type") not in {"app", "sub", "bundle"}:
                raise ConfigError("invalid explicit Steam ID type")
            identifier = str(explicit_steam.get("id", ""))
            if not identifier.isdigit() or int(identifier) <= 0:
                raise ConfigError("explicit Steam ID must be a positive integer")
            explicit_steam = {"type": explicit_steam["type"], "id": identifier}
        if query is not None and explicit_steam is not None:
            raise ConfigError(
                "use either a query or an explicit Steam ID option, not both",
            )
        if len(country) != 2 or not country.isalpha():
            raise ConfigError("country must be a two-letter code")
        if len(currency) != 3 or not currency.isalpha():
            raise ConfigError("currency must be a three-letter code")
        if not 1 <= top <= 50:
            raise ConfigError("top must be between 1 and 50")
        if include_itad and not self.env.get("ITAD_API_KEY"):
            raise ConfigError("--include-itad requires ITAD_API_KEY")

        country = country.upper()
        currency = currency.upper()
        if query is not None:
            display_query = query
        else:
            if explicit_steam is None:  # Defensive; validated above.
                raise ConfigError("lookup requires a query or explicit Steam ID")
            display_query = f"{explicit_steam['type']}:{explicit_steam['id']}"
        gg_region, gg_is_proxy = gg_region_for_country(country)
        started = utc_now()
        payload = _envelope(
            "lookup",
            query=display_query,
            request={
                "country": country,
                "currency": currency,
                "top": top,
                "provider_regions": {"gg": gg_region},
                "gg_region_is_proxy": gg_is_proxy,
            },
            started=started,
        )
        payload["warnings"].append(
            _warning(
                "region.activation_unverified",
                f"Activation and region eligibility for {country} require merchant-page verification",
            ),
        )
        if country == "US":
            payload["warnings"].append(
                _warning(
                    "pricing.sales_tax_unknown",
                    "US checkout tax is unknown without state and ZIP code",
                ),
            )
        if gg_is_proxy:
            payload["warnings"].append(
                _warning(
                    "provider.gg.region_proxy",
                    f"GG Deals does not expose region {country}; using US discovery prices as a proxy",
                    "gg",
                ),
            )
        identity = {
            "canonical_title": None,
            "match_status": "unresolved",
            "confidence": 0.0,
            "steam": explicit_steam or steam_identity(query or ""),
            "cheapshark_game_id": None,
            "itad_id": None,
            "candidates": [],
        }
        payload["identity"] = identity
        exit_code = 0

        steam = SteamProvider(self.client)
        if identity["steam"] is None and query is not None:
            try:
                search = steam.search(query, country=country)
                payload["provider_snapshots"].append(
                    _snapshot(
                        "steam",
                        "search",
                        search,
                        {"query": query, "country": country.upper()},
                    ),
                )
                raw_items = search.data.get("items", []) if isinstance(search.data, dict) else []
                candidates = [
                    {
                        "provider": "steam",
                        "id": str(item.get("id")),
                        "title": item.get("name"),
                    }
                    for item in raw_items
                    if isinstance(item, dict) and item.get("id") is not None
                ]
                match, scored = choose_candidate(query, candidates)
                identity["candidates"].extend(scored[:5])
                if match:
                    identity["steam"] = {"type": "app", "id": match["id"]}
                    identity["canonical_title"] = match["title"]
                    identity["confidence"] = match["match_score"]
                    identity["match_status"] = (
                        "matched" if match["match_score"] >= 0.88 else "needs_verification"
                    )
                    if identity["match_status"] == "needs_verification":
                        payload["critical_verification_items"].append(
                            _verification(
                                "identity.ambiguous",
                                "warning",
                                "Steam title match needs human verification",
                                "steam",
                                {"candidate": match},
                            ),
                        )
            except ProviderError as error:
                exit_code = 1
                _record_error(payload, error, stage="search")

        steam_id = identity["steam"]
        if steam_id and steam_id["type"] == "app":
            try:
                details = steam.app_details(steam_id["id"], country=country)
                observed = utc_now()
                payload["provider_snapshots"].append(
                    _snapshot(
                        "steam",
                        "app_details",
                        details,
                        {
                            "steam_type": "app",
                            "id": steam_id["id"],
                            "country": country.upper(),
                        },
                    ),
                )
                app_record = (
                    details.data.get(steam_id["id"], {}) if isinstance(details.data, dict) else {}
                )
                app_data = app_record.get("data", {}) if isinstance(app_record, dict) else {}
                if app_data.get("name"):
                    identity["canonical_title"] = app_data["name"]
                    if identity["match_status"] == "unresolved":
                        identity["match_status"] = "id_exact"
                        identity["confidence"] = 1.0
                payload["offers"].extend(
                    normalize_steam_app(
                        details.data,
                        steam_id["id"],
                        observed_at=observed,
                    ),
                )
            except ProviderError as error:
                exit_code = 1
                _record_error(payload, error, stage="app_details")
        elif steam_id:
            identity["match_status"] = "id_exact"
            identity["confidence"] = 1.0

        cheapshark_query = identity["canonical_title"] or query
        cheapshark_app_id = steam_id["id"] if steam_id and steam_id["type"] == "app" else None
        if cheapshark_query is not None or cheapshark_app_id is not None:
            cheapshark = CheapSharkProvider(self.client)
            store_names: dict[str, str] = {}
            try:
                store_response = cheapshark.stores()
                payload["provider_snapshots"].append(
                    _snapshot("cheapshark", "stores", store_response, {}),
                )
                store_names = (
                    {
                        str(item.get("storeID")): str(item.get("storeName"))
                        for item in store_response.data
                        if isinstance(item, dict)
                    }
                    if isinstance(store_response.data, list)
                    else {}
                )
            except ProviderError as error:
                exit_code = 1
                _record_error(payload, error, stage="stores")

            try:
                cs_search = cheapshark.search(
                    cheapshark_query or "",
                    steam_app_id=cheapshark_app_id,
                    limit=10,
                )
                payload["provider_snapshots"].append(
                    _snapshot(
                        "cheapshark",
                        "search",
                        cs_search,
                        {"query": cheapshark_query, "steam_app_id": cheapshark_app_id},
                    ),
                )
                candidates = (
                    [
                        {
                            "provider": "cheapshark",
                            "gameID": str(item.get("gameID")),
                            "title": item.get("external"),
                            "steamAppID": (
                                str(item.get("steamAppID")) if item.get("steamAppID") else None
                            ),
                        }
                        for item in cs_search.data
                        if isinstance(item, dict) and item.get("gameID")
                    ]
                    if isinstance(cs_search.data, list)
                    else []
                )
                cs_match, cs_scored = choose_candidate(
                    cheapshark_query or display_query,
                    candidates,
                )
                identity["candidates"].extend(cs_scored[:5])
                if cs_match:
                    identity["cheapshark_game_id"] = cs_match["gameID"]
                    cs_game = cheapshark.game(cs_match["gameID"])
                    observed = utc_now()
                    payload["provider_snapshots"].append(
                        _snapshot(
                            "cheapshark",
                            "game",
                            cs_game,
                            {"game_id": cs_match["gameID"]},
                        ),
                    )
                    payload["offers"].extend(
                        normalize_cheapshark_game(
                            cs_game.data,
                            stores=store_names,
                            title=identity["canonical_title"],
                            observed_at=observed,
                        ),
                    )
            except ProviderError as error:
                exit_code = 1
                _record_error(payload, error, stage="game_lookup")

        gg_key = self.env.get("GG_DEALS_API_KEY")
        if gg_key and steam_id:
            gg = GGDealsProvider(self.client, gg_key)
            try:
                for resource, response in gg.fetch(
                    steam_type=steam_id["type"],
                    ids=[steam_id["id"]],
                    region=gg_region,
                ):
                    observed = utc_now()
                    payload["provider_snapshots"].append(
                        _snapshot(
                            "gg",
                            resource,
                            response,
                            {
                                "steam_type": steam_id["type"],
                                "ids": [steam_id["id"]],
                                "region": gg_region,
                                "requested_country": country,
                                "region_is_proxy": gg_is_proxy,
                            },
                        ),
                    )
                    if resource == "prices":
                        payload["offers"].extend(
                            normalize_gg_prices(response.data, observed_at=observed),
                        )
                    else:
                        payload["bundle_history"].extend(
                            normalize_gg_bundle_history(
                                response.data,
                                observed_at=observed,
                            ),
                        )
            except ProviderError as error:
                exit_code = 1
                _record_error(payload, error, stage="prices_and_bundles")
        elif not gg_key:
            payload["warnings"].append(
                _warning(
                    "provider.gg.not_configured",
                    "GG Deals skipped because GG_DEALS_API_KEY is not set",
                    "gg",
                ),
            )

        if include_itad:
            itad: ITADProvider | None = None
            itad_search: JsonResponse | None = None
            itad_query = identity["canonical_title"] or query
            if itad_query is None:
                payload["warnings"].append(
                    _warning(
                        "provider.itad.title_required",
                        "ITAD skipped because this explicit Steam ID has no resolved title",
                        "itad",
                    ),
                )
            else:
                itad = ITADProvider(self.client, self.env["ITAD_API_KEY"])
                try:
                    itad_search = itad.search(itad_query, limit=10)
                except ProviderError as error:
                    exit_code = 1
                    _record_error(payload, error, stage="search")
                    itad_search = None
            if itad_query is not None and itad is not None and itad_search is not None:
                payload["provider_snapshots"].append(
                    _snapshot(
                        "itad",
                        "search",
                        itad_search,
                        {"query": itad_query},
                    ),
                )
                candidates = (
                    [
                        {
                            "provider": "itad",
                            "id": item.get("id"),
                            "title": item.get("title"),
                        }
                        for item in itad_search.data
                        if isinstance(item, dict) and item.get("id")
                    ]
                    if isinstance(itad_search.data, list)
                    else []
                )
                itad_match, itad_scored = choose_candidate(
                    itad_query,
                    candidates,
                )
                identity["candidates"].extend(itad_scored[:5])
                if itad_match:
                    identity["itad_id"] = itad_match["id"]
                    try:
                        itad_prices = itad.prices(itad_match["id"], country=country)
                    except ProviderError as error:
                        exit_code = 1
                        _record_error(payload, error, stage="prices")
                    else:
                        observed = utc_now()
                        payload["provider_snapshots"].append(
                            _snapshot(
                                "itad",
                                "prices",
                                itad_prices,
                                {"game_id": itad_match["id"], "country": country},
                            ),
                        )
                        payload["offers"].extend(
                            normalize_itad_prices(
                                itad_prices.data,
                                title=identity["canonical_title"],
                                observed_at=observed,
                            ),
                        )

        finalize_offers(payload["offers"])
        exit_code = max(exit_code, self._convert_offers(payload, currency))
        for offer in payload["offers"]:
            offer["requested_country"] = country
            offer["region_status"] = "unverified"
        if identity["match_status"] in {"matched", "id_exact"}:
            payload["rankings"] = rank_offers(payload["offers"], top=top)
            _queue_offer_verification(payload)
        else:
            payload["warnings"].append(
                _warning(
                    "identity.unresolved",
                    "Rankings and checkout verification are suppressed until product identity is resolved",
                ),
            )
        payload["timestamps"]["completed_at"] = utc_now()
        return ServiceResult(payload, exit_code)

    def provider_gg(
        self,
        *,
        steam_type: str,
        ids: list[str],
        region: str = "us",
        prices: bool = True,
        bundles: bool = True,
        top: int = 5,
    ) -> ServiceResult:
        """Return raw and normalized GG Deals data for explicit Steam IDs."""
        if not 1 <= top <= 50:
            raise ConfigError("top must be between 1 and 50")
        identifiers = validate_gg_ids(ids)
        started = utc_now()
        payload = _envelope(
            "provider.gg",
            query=None,
            request={
                "steam_type": steam_type,
                "ids": identifiers,
                "region": region.casefold(),
                "prices": prices,
                "bundles": bundles,
            },
            started=started,
        )
        gg = GGDealsProvider(self.client, self.env.get("GG_DEALS_API_KEY", ""))
        try:
            for resource, response in gg.fetch(
                steam_type=steam_type,
                ids=identifiers,
                region=region.casefold(),
                prices=prices,
                bundles=bundles,
            ):
                observed = utc_now()
                payload["provider_snapshots"].append(
                    _snapshot(
                        "gg",
                        resource,
                        response,
                        {
                            "steam_type": steam_type,
                            "ids": identifiers,
                            "region": region.casefold(),
                        },
                    ),
                )
                if resource == "prices":
                    payload["offers"].extend(
                        normalize_gg_prices(response.data, observed_at=observed),
                    )
                else:
                    payload["bundle_history"].extend(
                        normalize_gg_bundle_history(response.data, observed_at=observed),
                    )
        except ProviderError as error:
            _record_error(payload, error, stage="provider_command")
            exit_code = 1
        else:
            exit_code = 0
        finalize_offers(payload["offers"])
        payload["rankings"] = rank_offers(payload["offers"], top=top)
        _queue_offer_verification(payload)
        payload["timestamps"]["completed_at"] = utc_now()
        return ServiceResult(payload, exit_code)

    def stores(self) -> ServiceResult:
        """List CheapShark stores with absolute asset URLs."""
        started = utc_now()
        payload = _envelope("stores", query=None, request={}, started=started)
        try:
            response = CheapSharkProvider(self.client).stores()
        except ProviderError as error:
            _record_error(payload, error, stage="stores")
            payload["timestamps"]["completed_at"] = utc_now()
            return ServiceResult(payload, 1)
        payload["provider_snapshots"].append(
            _snapshot("cheapshark", "stores", response, {}),
        )
        payload["stores"] = (
            [_normalize_store(item) for item in response.data if isinstance(item, dict)]
            if isinstance(response.data, list)
            else []
        )
        payload["timestamps"]["completed_at"] = utc_now()
        return ServiceResult(payload)

    def _convert_offers(self, payload: dict[str, Any], target: str) -> int:
        for offer in payload["offers"]:
            price = offer.get("price")
            if isinstance(price, dict):
                offer["price_comparable"] = str(price.get("currency", "")).upper() == target
        pairs = {
            str(offer["price"]["currency"]).upper()
            for offer in payload["offers"]
            if isinstance(offer.get("price"), dict)
            and str(offer["price"].get("currency", "")).upper() != target
        }
        status = 0
        fx = FrankfurterProvider(self.client)
        for base in sorted(pairs):
            try:
                response = fx.rate(base, target)
                rate, as_of = extract_fx_rate(response.data, base, target)
                payload["provider_snapshots"].append(
                    _snapshot(
                        "frankfurter",
                        "rate",
                        response,
                        {"base": base, "quote": target},
                    ),
                )
                for offer in payload["offers"]:
                    price = offer.get("price")
                    if isinstance(price, dict) and price.get("currency") == base:
                        apply_fx(offer, target=target, rate=rate, as_of=as_of)
                        offer["price_comparable"] = True
                if as_of:
                    payload["timestamps"]["fx_as_of"] = as_of
            except (ProviderError, ValueError) as error:
                status = 1
                for offer in payload["offers"]:
                    price = offer.get("price")
                    if isinstance(price, dict) and price.get("currency") == base:
                        offer["price_comparable"] = False
                        offer["evidence_status"] = "blocked"
                if isinstance(error, ProviderError):
                    _record_error(payload, error, stage="fx")
                else:
                    payload["warnings"].append(
                        _warning("fx.invalid_response", str(error), "frankfurter"),
                    )
        return status


def _envelope(
    command: str,
    *,
    query: str | None,
    request: dict[str, Any],
    started: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "query": query,
        "request": request,
        "identity": None,
        "provider_snapshots": [],
        "provider_failures": [],
        "offers": [],
        "bundle_history": [],
        "verification_queue": [],
        "critical_verification_items": [],
        "rankings": {
            "overall": [],
            "absolute_cheapest": None,
            "cheapest_ownership": None,
            "cheapest_verified": None,
        },
        "warnings": [],
        "timestamps": {"started_at": started, "completed_at": None, "fx_as_of": None},
    }


def _snapshot(
    provider: str,
    operation: str,
    response: JsonResponse,
    request: dict[str, Any],
) -> dict[str, Any]:
    return {
        "provider": provider,
        "operation": operation,
        "status": "ok",
        "http_status": response.status,
        "fetched_at": utc_now(),
        "request": request,
        "source_url": response.safe_url,
        "data": response.data,
    }


def _record_error(payload: dict[str, Any], error: ProviderError, *, stage: str) -> None:
    failure = {
        "provider": error.provider,
        "operation": stage,
        "status": "error",
        "http_status": error.status,
        "fetched_at": utc_now(),
        "request": {},
        "error": str(error),
        "retry_after": error.retry_after,
    }
    payload["provider_snapshots"].append(dict(failure))
    payload["provider_failures"].append(failure)
    payload["warnings"].append(_warning("provider.error", str(error), error.provider))


def _warning(code: str, message: str, provider: str | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "warning",
        "message": message,
        "provider": provider,
        "details": {},
    }


def _verification(
    code: str,
    severity: str,
    message: str,
    provider: str | None,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "provider": provider,
        "details": details,
    }


def _queue_offer_verification(payload: dict[str, Any]) -> None:
    payload["verification_queue"] = []
    priced = [
        (index, offer)
        for index, offer in enumerate(payload["offers"])
        if isinstance(offer.get("price"), dict) and offer["price"].get("amount") is not None
        if offer.get("price_comparable", True)
    ]
    priced.sort(key=lambda item: (float(item[1]["price"]["amount"]), item[0]))
    for rank, (index, offer) in enumerate(priced[:5], start=1):
        acquisition = offer.get("acquisition_type")
        if acquisition in {"account", "subscription_access", "unknown"}:
            payload["critical_verification_items"].append(
                _verification(
                    "offer.acquisition_review",
                    "warning" if acquisition != "account" else "critical",
                    f"Verify acquisition type before purchase: {acquisition}",
                    offer.get("provider"),
                    {"offer_index": index, "acquisition_type": acquisition},
                ),
            )
        payload["verification_queue"].append(
            _verification(
                "offer.checkout_required",
                "warning",
                "Open the merchant page and verify the final payable offer",
                offer.get("provider"),
                {
                    "rank": rank,
                    "offer_index": index,
                    "merchant": offer.get("store"),
                    "offer_url": offer.get("url"),
                    "acquisition_type": acquisition,
                    "evidence_status": offer.get("evidence_status"),
                    "checkout_fields": [
                        "merchant_identity",
                        "seller",
                        "final_price",
                        "original_price",
                        "currency",
                        "tax",
                        "fees",
                        "mandatory_fees",
                        "coupon",
                        "preselected_extras",
                        "subscription_period",
                        "exclusions",
                        "stock",
                        "region_lock",
                        "claimed_region",
                        "activation_type",
                    ],
                },
            ),
        )


GG_REGIONS = frozenset(
    {
        "us",
        "eu",
        "gb",
        "ca",
        "au",
        "br",
        "pl",
        "fr",
        "de",
        "es",
        "it",
        "ch",
        "nl",
        "se",
        "no",
        "dk",
        "fi",
        "ie",
        "be",
    },
)


def gg_region_for_country(country: str) -> tuple[str, bool]:
    """Map a requested country to a supported GG region or the US proxy."""
    region = country.casefold()
    if region in GG_REGIONS:
        return region, False
    return "us", True


def _normalize_store(item: dict[str, Any]) -> dict[str, Any]:
    raw_images = item.get("images")
    images: dict[str, Any] = raw_images if isinstance(raw_images, dict) else {}
    return {
        "id": str(item.get("storeID")),
        "name": item.get("storeName"),
        "active": str(item.get("isActive", "0")) == "1",
        "images": {
            key: f"https://www.cheapshark.com{value}"
            if isinstance(value, str) and value.startswith("/")
            else value
            for key, value in images.items()
        },
    }
