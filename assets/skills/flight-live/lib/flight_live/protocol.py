from __future__ import annotations

from collections.abc import Sequence
from statistics import mean
from typing import NotRequired, TypedDict

from .models import FlightLiveError, FlightOption, PlannerOffer, ResolvedPlace, SearchRequest
from .providers import fetch_kiwi_web_calendar, resolve_place
from .scoring import rank_options

PROTOCOL_VERSION = "1"
LLM_JSON_TYPE = "flight-live.search_results"
SCHEMA_TYPE = "flight-live.schema"
SCHEMA_NAME = "flight-live"


class ResolvedPlacePayload(TypedDict):
    query: str
    iata: str
    name: str | None
    resolved_via_autocomplete: bool


class SummaryPayload(TypedDict):
    planner_received: int
    after_filters: int
    returned: int


class InsightsPayload(TypedDict):
    weekend_avg_price: NotRequired[float]
    weekday_avg_price: NotRequired[float]
    weekend_premium_pct: NotRequired[float]
    cheapest_departure_weekday: NotRequired[str]


class DecisionPayload(TypedDict):
    recommendation: str
    actions: list[str]
    avoid: list[str]


class SearchPayload(TypedDict):
    type: str
    version: str
    ok: bool
    warnings: list[str]
    query: dict[str, object]
    resolved: dict[str, ResolvedPlacePayload]
    summary: SummaryPayload
    insights: InsightsPayload
    decision: DecisionPayload
    results: list[dict[str, object]]
    ranking: NotRequired[dict[str, object]]


def search_flights(request: SearchRequest) -> SearchPayload:
    if request.depart_end < request.depart_start:
        raise FlightLiveError("depart-end must be >= depart-start")

    resolved_origin = resolve_place(request.origin, locale=request.locale)
    resolved_destination = resolve_place(request.destination, locale=request.locale)
    planner_offers = fetch_kiwi_web_calendar(
        origin=resolved_origin.query,
        destination=resolved_destination.query,
        depart_start=request.depart_start,
        depart_end=request.depart_end,
        trip_type=request.trip_type,
        currency=request.currency,
        locale=request.locale,
        market=request.market,
        stay_min=request.stay_min,
        stay_max=request.stay_max,
    )

    filtered = _filter_planner_offers(planner_offers, request=request)
    ranked = rank_options(
        _to_options(filtered),
        max_budget=request.max_budget,
        prefer_nonstop=request.nonstop,
    )[: request.planner_limit]

    warnings: list[str] = []
    if not filtered:
        warnings.append(
            "No planner offers after filters. Widen date window, relax nonstop, or remove budget cap."
        )

    insights = _build_insights(filtered)
    decision = _build_decision(ranked=ranked, insights=insights)

    return build_llm_payload(
        request=request,
        resolved_origin=resolved_origin,
        resolved_destination=resolved_destination,
        planner_received=len(planner_offers),
        filtered_count=len(filtered),
        ranked=ranked,
        warnings=warnings,
        insights=insights,
        decision=decision,
    )


def build_llm_payload(
    *,
    request: SearchRequest,
    resolved_origin: ResolvedPlace,
    resolved_destination: ResolvedPlace,
    planner_received: int,
    filtered_count: int,
    ranked: Sequence[FlightOption],
    warnings: Sequence[str],
    insights: InsightsPayload,
    decision: DecisionPayload,
) -> SearchPayload:
    payload: SearchPayload = {
        "type": LLM_JSON_TYPE,
        "version": PROTOCOL_VERSION,
        "ok": True,
        "warnings": list(warnings),
        "query": {
            "origin": request.origin,
            "destination": request.destination,
            "depart_start": request.depart_start.isoformat(),
            "depart_end": request.depart_end.isoformat(),
            "trip_type": request.trip_type,
            "stay_min": request.stay_min,
            "stay_max": request.stay_max,
            "adults": request.adults,
            "children": request.children,
            "infants": request.infants,
            "cabin": request.cabin,
            "currency": request.currency,
            "locale": request.locale,
            "market": request.market,
            "nonstop": request.nonstop,
            "max_budget": request.max_budget,
            "planner_limit": request.planner_limit,
        },
        "resolved": {
            "origin": _resolved_payload(resolved_origin),
            "destination": _resolved_payload(resolved_destination),
        },
        "summary": {
            "planner_received": planner_received,
            "after_filters": filtered_count,
            "returned": len(ranked),
        },
        "insights": insights,
        "decision": decision,
        "results": [item.to_dict() for item in ranked],
        "ranking": {
            "mode": "agent_value",
            "weekend_penalty": True,
            "weekday_preference_hint": True,
        },
    }
    return payload


def serialize_results(payload: SearchPayload) -> list[dict[str, object]]:
    return payload["results"]


def get_schema_document() -> dict[str, object]:
    return {
        "type": SCHEMA_TYPE,
        "version": PROTOCOL_VERSION,
        "name": SCHEMA_NAME,
        "description": "Read-only agent-first flight search via Kiwi web scraping + public location resolver.",
        "capabilities": {
            "read_only": True,
            "modes": ["cli", "rpc"],
            "outputs": ["text", "json", "llm-json"],
            "providers": {
                "planner": "Kiwi web scrape via agent-browser (nix run wrapper)",
            },
            "credentials": {
                "required": [],
                "optional": [],
                "requires_credit_card": False,
            },
        },
        "cli": {
            "required_for_search": [
                "--origin",
                "--destination",
                "--depart-start",
                "--depart-end",
            ],
            "options": {
                "--trip-type": {"enum": ["oneway", "roundtrip"]},
                "--cabin": {
                    "enum": ["economy", "premium_economy", "business", "first"],
                },
                "--json": {"output": "results_array"},
                "--llm-json": {"output": "envelope"},
                "--mode rpc": {"output": "jsonl_rpc"},
            },
        },
        "rpc": {
            "pi_inspired": True,
            "full_pi_rpc": False,
            "transport": "jsonl",
            "request_command_field": "type",
            "legacy_request_command_field": "command",
            "commands": {
                "ping": {
                    "request": _rpc_request_schema(command="ping"),
                    "response_data": {
                        "type": "object",
                        "required": ["ok", "version"],
                    },
                },
                "get_schema": {
                    "request": _rpc_request_schema(command="get_schema"),
                    "response_data": {"$ref": "#"},
                },
                "search": {
                    "request": _rpc_request_schema(
                        command="search",
                        properties={
                            "origin": {"type": "string"},
                            "destination": {"type": "string"},
                            "departStart": {"type": "string", "format": "date"},
                            "departEnd": {"type": "string", "format": "date"},
                            "tripType": {"type": "string", "enum": ["oneway", "roundtrip"]},
                            "stayMin": {"type": ["integer", "null"], "minimum": 0},
                            "stayMax": {"type": ["integer", "null"], "minimum": 0},
                            "adults": {"type": ["integer", "null"], "minimum": 1},
                            "children": {"type": ["integer", "null"], "minimum": 0},
                            "infants": {"type": ["integer", "null"], "minimum": 0},
                            "cabin": {
                                "type": ["string", "null"],
                                "enum": [
                                    "economy",
                                    "premium_economy",
                                    "business",
                                    "first",
                                    None,
                                ],
                            },
                            "currency": {"type": ["string", "null"]},
                            "locale": {"type": ["string", "null"]},
                            "market": {"type": ["string", "null"]},
                            "nonstop": {"type": ["boolean", "null"]},
                            "maxBudget": {"type": ["number", "null"]},
                            "plannerLimit": {"type": ["integer", "null"], "minimum": 1},
                        },
                        required=["origin", "destination", "departStart", "departEnd"],
                    ),
                    "response_data": {
                        "type": "object",
                        "required": [
                            "type",
                            "version",
                            "ok",
                            "warnings",
                            "query",
                            "resolved",
                            "summary",
                            "insights",
                            "decision",
                            "results",
                        ],
                    },
                },
            },
        },
    }


def _rpc_request_schema(
    *,
    command: str,
    properties: dict[str, object] | None = None,
    required: Sequence[str] | None = None,
) -> dict[str, object]:
    request_properties: dict[str, object] = {
        "id": {"type": ["string", "number", "null"]},
        "type": {"type": "string"},
        "command": {"type": "string"},
    }
    if properties is not None:
        request_properties.update(properties)

    required_fields = list(required or ())
    return {
        "type": "object",
        "properties": request_properties,
        "anyOf": [
            {
                "required": ["type", *required_fields],
                "properties": {"type": {"const": command}},
            },
            {
                "required": ["command", *required_fields],
                "properties": {"command": {"const": command}},
            },
        ],
    }


def _resolved_payload(value: ResolvedPlace) -> ResolvedPlacePayload:
    return {
        "query": value.query,
        "iata": value.iata,
        "name": value.name,
        "resolved_via_autocomplete": value.resolved_via_autocomplete,
    }


def _filter_planner_offers(
    offers: Sequence[PlannerOffer],
    *,
    request: SearchRequest,
) -> list[PlannerOffer]:
    filtered: list[PlannerOffer] = []
    for offer in offers:
        if offer.depart_date < request.depart_start or offer.depart_date > request.depart_end:
            continue
        if request.nonstop and not offer.nonstop:
            continue
        if request.max_budget is not None and offer.price > request.max_budget:
            continue
        if request.trip_type == "roundtrip" and offer.return_date is not None:
            stay = (offer.return_date - offer.depart_date).days
            if request.stay_min is not None and stay < request.stay_min:
                continue
            if request.stay_max is not None and stay > request.stay_max:
                continue
        filtered.append(offer)
    return filtered


def _to_options(offers: Sequence[PlannerOffer]) -> list[FlightOption]:
    return [
        FlightOption(
            origin=offer.origin,
            destination=offer.destination,
            depart_date=offer.depart_date,
            return_date=offer.return_date,
            price=offer.price,
            currency=offer.currency,
            transfers=offer.transfers,
            airline=offer.airline,
            source=offer.source,
        )
        for offer in offers
    ]


def _build_insights(offers: Sequence[PlannerOffer]) -> InsightsPayload:
    insights: InsightsPayload = {}
    if not offers:
        return insights

    weekend_prices = [offer.price for offer in offers if offer.depart_date.weekday() in (4, 5, 6)]
    weekday_prices = [offer.price for offer in offers if offer.depart_date.weekday() in (0, 1, 2, 3)]

    if weekend_prices:
        insights["weekend_avg_price"] = round(mean(weekend_prices), 2)
    if weekday_prices:
        insights["weekday_avg_price"] = round(mean(weekday_prices), 2)

    if weekend_prices and weekday_prices:
        weekday_avg = mean(weekday_prices)
        if weekday_avg > 0:
            weekend_avg = mean(weekend_prices)
            premium_pct = ((weekend_avg - weekday_avg) / weekday_avg) * 100
            insights["weekend_premium_pct"] = round(premium_pct, 2)

    cheapest = min(offers, key=lambda offer: offer.price)
    insights["cheapest_departure_weekday"] = cheapest.depart_date.strftime("%A")
    return insights


def _build_decision(*, ranked: Sequence[FlightOption], insights: InsightsPayload) -> DecisionPayload:
    if not ranked:
        return {
            "recommendation": "No viable options after filters.",
            "actions": [
                "Widen departure window by at least 2 weeks.",
                "Disable nonstop-only mode.",
                "Remove or raise max budget.",
            ],
            "avoid": ["Over-constrained searches"],
        }

    best = ranked[0]
    actions = [
        f"Target departures near {best.depart_date.isoformat()} for lowest score-adjusted fare.",
        "Probe ±2 days around top option to check for lower local minima.",
    ]

    avoid = ["Friday/Saturday/Sunday departures unless they remain cheapest."]

    premium = insights.get("weekend_premium_pct")
    if isinstance(premium, float) and premium > 8:
        actions.append("Prefer Tuesday-Thursday departures; observed weekend premium is high.")

    recommendation = (
        f"Best current candidate: {best.origin}->{best.destination} on {best.depart_date.isoformat()}"
        f" at ~{best.effective_price:.2f} {best.currency}."
    )

    return {
        "recommendation": recommendation,
        "actions": actions,
        "avoid": avoid,
    }
