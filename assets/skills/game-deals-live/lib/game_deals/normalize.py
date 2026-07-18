"""Provider normalization, acquisition classification, FX, and ranking."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def money(amount: Any, currency: str) -> dict[str, Any] | None:
    """Build a stable money object or return None for missing values."""
    if amount in (None, ""):
        return None
    try:
        decimal = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    return {"amount": float(decimal), "currency": currency.upper()}


def classify_acquisition(*values: Any) -> str:
    """Classify explicit provider language conservatively."""
    text = " ".join(str(value or "") for value in values).casefold()
    if "account" in text:
        return "account"
    if any(token in text for token in ("subscription", "game pass", "ea play", "ubisoft+")):
        return "subscription_access"
    if any(token in text for token in ("bundle", "package")):
        return "bundle"
    if "gift" in text:
        return "gift"
    if any(token in text for token in ("steam key", "key", "drm")):
        return "ownership_key"
    if any(token in text for token in ("steam", "gog", "epic", "microsoft store")):
        return "direct_ownership"
    return "unknown"


def evidence(source: str, kind: str, value: Any, observed_at: str) -> dict[str, Any]:
    return {"source": source, "kind": kind, "value": value, "observed_at": observed_at}


def normalize_steam_app(
    data: Any,
    app_id: str,
    *,
    observed_at: str,
) -> list[dict[str, Any]]:
    item = data.get(app_id, {}) if isinstance(data, dict) else {}
    if not isinstance(item, dict) or not item.get("success"):
        return []
    details = item.get("data") or {}
    overview = details.get("price_overview")
    if not isinstance(overview, dict):
        return []
    currency = str(overview.get("currency", "USD"))
    final = money(Decimal(str(overview.get("final", 0))) / 100, currency)
    regular = money(Decimal(str(overview.get("initial", 0))) / 100, currency)
    return [
        {
            "provider": "steam",
            "provider_offer_id": app_id,
            "store": "Steam",
            "title": details.get("name"),
            "url": f"https://store.steampowered.com/app/{app_id}/",
            "price": final,
            "regular_price": regular,
            "discount_percent": int(overview.get("discount_percent", 0)),
            "drm": ["Steam"],
            "official": True,
            "historical_low": None,
            "acquisition_type": "direct_ownership",
            "evidence_status": "estimated",
            "evidence": [evidence("steam", "store_app_metadata", app_id, observed_at)],
            "observed_at": observed_at,
        },
    ]


def normalize_cheapshark_game(
    data: Any,
    *,
    stores: dict[str, str],
    title: str | None,
    observed_at: str,
) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    raw_info = data.get("info")
    info: dict[str, Any] = raw_info if isinstance(raw_info, dict) else {}
    result: list[dict[str, Any]] = []
    for deal in data.get("deals", []):
        if not isinstance(deal, dict):
            continue
        store_id = str(deal.get("storeID", ""))
        store = stores.get(store_id, f"CheapShark store {store_id}")
        deal_id = str(deal.get("dealID", ""))
        sale = money(deal.get("price"), "USD")
        regular = money(deal.get("retailPrice"), "USD")
        if sale is None:
            continue
        steam_app_id = deal.get("steamAppID") or info.get("steamAppID")
        acquisition = (
            "direct_ownership"
            if store.casefold() == "steam"
            else classify_acquisition(
                store,
                steam_app_id,
                "Steam key" if steam_app_id else "",
            )
        )
        result.append(
            {
                "provider": "cheapshark",
                "provider_offer_id": deal_id or None,
                "store": store,
                "title": title or info.get("title"),
                "url": f"https://www.cheapshark.com/redirect?dealID={deal_id}" if deal_id else None,
                "price": sale,
                "regular_price": regular,
                "discount_percent": _discount(sale, regular),
                "drm": ["Steam"] if steam_app_id else [],
                "official": True,
                "historical_low": None,
                "acquisition_type": acquisition,
                "evidence_status": "estimated",
                "evidence": [evidence("cheapshark", "deal", deal_id, observed_at)],
                "observed_at": observed_at,
            },
        )
    return result


def normalize_gg_prices(data: Any, *, observed_at: str) -> list[dict[str, Any]]:
    records = data.get("data", {}) if isinstance(data, dict) else {}
    if not isinstance(records, dict):
        return []
    result: list[dict[str, Any]] = []
    for steam_id, record in records.items():
        if not isinstance(record, dict):
            continue
        prices = record.get("prices") or {}
        currency = str(prices.get("currency") or record.get("currency") or "USD")
        for key, store, official, history_key in (
            ("currentRetail", "GG Deals: official stores", True, "historicalRetail"),
            ("currentKeyshops", "GG Deals: keyshops", False, "historicalKeyshops"),
        ):
            price = money(prices.get(key), currency)
            if price is None:
                continue
            result.append(
                {
                    "provider": "gg",
                    "provider_offer_id": f"{steam_id}:{key}",
                    "store": store,
                    "title": record.get("title") or record.get("name"),
                    "url": record.get("url"),
                    "price": price,
                    "regular_price": None,
                    "discount_percent": None,
                    "drm": [],
                    "official": official,
                    "historical_low": money(prices.get(history_key), currency),
                    "acquisition_type": "unknown",
                    "evidence_status": "headline",
                    "evidence": [evidence("gg", "aggregate_low", key, observed_at)],
                    "observed_at": observed_at,
                },
            )
    return result


def normalize_gg_bundle_history(data: Any, *, observed_at: str) -> list[dict[str, Any]]:
    """Expose GG bundle tiers as history, never as current standalone offers."""
    records = data.get("data", {}) if isinstance(data, dict) else {}
    result: list[dict[str, Any]] = []
    for steam_id, raw in records.items() if isinstance(records, dict) else []:
        bundle_items = (
            raw
            if isinstance(raw, list)
            else raw.get("bundles", [])
            if isinstance(raw, dict)
            else []
        )
        for index, bundle in enumerate(bundle_items):
            if not isinstance(bundle, dict):
                continue
            bundle_id = str(bundle.get("id") or f"{steam_id}:{index}")
            tiers: list[dict[str, Any]] = []
            for tier_index, tier in enumerate(bundle.get("tiers", [])):
                if not isinstance(tier, dict):
                    continue
                price_value = tier.get("price")
                currency = tier.get("currency", bundle.get("currency", "USD"))
                if isinstance(price_value, dict):
                    currency = price_value.get("currency", currency)
                    price_value = price_value.get("amount")
                tiers.append(
                    {
                        "tier": tier_index + 1,
                        "price": money(price_value, str(currency)),
                        "games_count": tier.get("gamesCount"),
                        "games": tier.get("games", []),
                    },
                )
            result.append(
                {
                    "provider": "gg",
                    "steam_id": str(steam_id),
                    "bundle_id": bundle_id,
                    "title": bundle.get("title") or bundle.get("name"),
                    "url": bundle.get("url"),
                    "date_from": bundle.get("dateFrom"),
                    "date_to": bundle.get("dateTo"),
                    "tiers": tiers,
                    "evidence": [
                        evidence("gg", "bundle_history", bundle_id, observed_at),
                    ],
                    "observed_at": observed_at,
                },
            )
    return result


def normalize_itad_prices(
    data: Any,
    *,
    title: str | None,
    observed_at: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    records = data if isinstance(data, list) else []
    for record in records:
        if not isinstance(record, dict):
            continue
        history = (record.get("historyLow") or {}).get("all")
        for deal in record.get("deals", []):
            if not isinstance(deal, dict):
                continue
            shop = deal.get("shop") or {}
            price_data = deal.get("price") or {}
            regular_data = deal.get("regular") or {}
            price = money(price_data.get("amount"), price_data.get("currency", "USD"))
            regular = money(
                regular_data.get("amount"),
                regular_data.get("currency", "USD"),
            )
            if price is None:
                continue
            drm_names = [
                str(item.get("name")) for item in deal.get("drm", []) if isinstance(item, dict)
            ]
            store = str(shop.get("name") or "IsThereAnyDeal shop")
            result.append(
                {
                    "provider": "itad",
                    "provider_offer_id": None,
                    "store": store,
                    "title": title,
                    "url": deal.get("url"),
                    "price": price,
                    "regular_price": regular,
                    "discount_percent": deal.get("cut"),
                    "coupon": deal.get("voucher"),
                    "drm": drm_names,
                    "official": True,
                    "historical_low": money(
                        history.get("amount") if isinstance(history, dict) else None,
                        history.get("currency", "USD") if isinstance(history, dict) else "USD",
                    ),
                    "acquisition_type": (
                        "direct_ownership"
                        if store.casefold() in {"steam", "gog", "epic games store"}
                        else classify_acquisition(
                            store,
                            *drm_names,
                            "key" if drm_names else "",
                        )
                    ),
                    "evidence_status": "estimated",
                    "evidence": [
                        evidence("itad", "deal", deal.get("url"), observed_at),
                    ],
                    "observed_at": deal.get("timestamp") or observed_at,
                },
            )
    return result


def finalize_offers(offers: list[dict[str, Any]]) -> None:
    """Make purchase-risk fields explicit and preserve provider-native money."""
    defaults: dict[str, Any] = {
        "claimed_region": None,
        "exclusions": [],
        "coupon": None,
        "mandatory_fees": None,
        "tax": None,
        "subscription_period": None,
        "preselected_extras": None,
        "price_comparable": True,
    }
    for offer in offers:
        offer.setdefault("seller", offer.get("store"))
        for key, value in defaults.items():
            offer.setdefault(key, list(value) if isinstance(value, list) else value)
        price = offer.get("price")
        if isinstance(price, dict):
            offer.setdefault("original_price", dict(price.get("converted_from", price)))


def extract_fx_rate(data: Any, base: str, quote: str) -> tuple[float, str | None]:
    """Accept Frankfurter v2 list responses and legacy-compatible objects."""
    if base.upper() == quote.upper():
        return 1.0, None
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and str(item.get("quote", "")).upper() == quote.upper():
                return float(item["rate"]), item.get("date")
    if isinstance(data, dict):
        rate = (data.get("rates") or {}).get(quote.upper())
        if rate is not None:
            return float(rate), data.get("date")
    raise ValueError(f"FX response has no {base.upper()}/{quote.upper()} rate")


def apply_fx(
    offer: dict[str, Any],
    *,
    target: str,
    rate: float,
    as_of: str | None,
) -> None:
    price = offer.get("price")
    if not isinstance(price, dict) or price.get("currency") == target.upper():
        return
    original = dict(price)
    offer.setdefault("original_price", dict(original))
    converted = money(Decimal(str(price["amount"])) * Decimal(str(rate)), target)
    if converted:
        converted["converted_from"] = original
        converted["fx_rate"] = rate
        converted["fx_as_of"] = as_of
        offer["price"] = converted


def rank_offers(offers: list[dict[str, Any]], *, top: int) -> dict[str, Any]:
    """Sort payable price first; expose risk without allowing it to reorder."""
    priced = [
        (index, offer)
        for index, offer in enumerate(offers)
        if isinstance(offer.get("price"), dict) and offer["price"].get("amount") is not None
        if offer.get("price_comparable", True)
    ]
    if not priced:
        return _empty_rankings()
    lowest = min(float(offer["price"]["amount"]) for _, offer in priced)
    ranked: list[tuple[float, int, float, list[str], list[str]]] = []
    for index, offer in priced:
        amount = float(offer["price"]["amount"])
        score = 100.0 if amount == 0 else 100.0 * (lowest / amount)
        reasons = [f"price {amount:.2f} {offer['price']['currency']}"]
        acquisition = str(offer.get("acquisition_type", "unknown"))
        risk_labels: list[str] = []
        if acquisition in {"account", "subscription_access", "unknown"}:
            risk_labels.append(acquisition)
        status = offer.get("evidence_status")
        if status != "verified":
            risk_labels.append(f"evidence:{status or 'unknown'}")
        if offer.get("official") is True:
            reasons.append("official store")
        ranked.append((amount, index, round(score, 3), reasons, risk_labels))
    ranked.sort(key=lambda item: (item[0], item[1]))
    overall = [
        {
            "rank": rank,
            "offer_index": index,
            "score": score,
            "reasons": reasons,
            "risk_labels": risk_labels,
        }
        for rank, (_, index, score, reasons, risk_labels) in enumerate(
            ranked[:top],
            start=1,
        )
    ]
    ownership_types = {"ownership_key", "direct_ownership", "gift"}
    return {
        "overall": overall,
        "absolute_cheapest": _cheapest(priced),
        "cheapest_ownership": _cheapest(
            [
                (index, offer)
                for index, offer in priced
                if offer.get("acquisition_type") in ownership_types
            ],
        ),
        "cheapest_verified": _cheapest(
            [
                (index, offer)
                for index, offer in priced
                if offer.get("evidence_status") == "verified"
            ],
        ),
    }


def _empty_rankings() -> dict[str, Any]:
    return {
        "overall": [],
        "absolute_cheapest": None,
        "cheapest_ownership": None,
        "cheapest_verified": None,
    }


def _cheapest(
    indexed_offers: list[tuple[int, dict[str, Any]]],
) -> dict[str, Any] | None:
    if not indexed_offers:
        return None
    index, offer = min(
        indexed_offers,
        key=lambda item: (float(item[1]["price"]["amount"]), item[0]),
    )
    return {"offer_index": index, "price": dict(offer["price"])}


def _discount(
    price: dict[str, Any] | None,
    regular: dict[str, Any] | None,
) -> int | None:
    if not price or not regular or not regular["amount"]:
        return None
    return round((1 - price["amount"] / regular["amount"]) * 100)
