#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.27,<1.0",
# ]
# ///
"""Ecuabet live market fetcher powered by Altenar widget endpoints."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

__all__: list[str] = []

EVENT_ID_PATTERN = re.compile(r"/deportes/partido/(\d+)")
ASCII_UPPER_BOUND = 128

DEFAULT_BASE_URL = "https://sb2frontend-altenar2.biahosted.com/api/widget"
DEFAULT_INTEGRATION = "ecuabet"
DEFAULT_COUNTRY_CODE = "EC"
DEFAULT_CULTURE = "es-ES"
DEFAULT_TIMEZONE_OFFSET = 300
DEFAULT_DEVICE_TYPE = 1
DEFAULT_NUM_FORMAT = "en-GB"

KEY_MARKETS = {
    "1x2",
    "doble oportunidad",
    "ambos equipos marcan",
    "total",
    "handicap",
    "1a mitad - 1x2",
    "1a mitad - total",
    "2a mitad - total",
    "primer gol",
    "ultimo gol",
    "marcador exacto",
}

INSIGHT_KEYWORDS = (
    "tarjeta",
    "corner",
    "tiro esquina",
    "falta",
    "offside",
    "fuera de juego",
    "penal",
    "saque",
    "tiro",
    "intercept",
    "atajada",
    "amarilla",
    "roja",
)

ODD_STATUS = {
    0: "open",
    1: "suspended",
    2: "closed",
    3: "settled",
}


@dataclass(frozen=True)
class FetchConfig:
    base_url: str
    integration: str
    country_code: str
    culture: str
    timezone_offset: int
    device_type: int
    num_format: str
    show_non_boosts: bool


def parse_event_id(value: str) -> int:
    value = value.strip()
    if value.isdigit():
        return int(value)

    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        match = EVENT_ID_PATTERN.search(parsed.path)
        if match:
            return int(match.group(1))

    match = EVENT_ID_PATTERN.search(value)
    if match:
        return int(match.group(1))

    msg = (
        "Could not parse event id. Pass a numeric id or a URL like "
        "'https://ecuabet.com/deportes/partido/<id>'."
    )
    raise ValueError(msg)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(ch for ch in normalized if ord(ch) < ASCII_UPPER_BOUND)
    return " ".join(ascii_text.lower().split())


def flatten_odd_ids(raw: object) -> list[int]:
    if not raw:
        return []
    out: list[int] = []
    for chunk in raw:
        if isinstance(chunk, list):
            out.extend(item for item in chunk if isinstance(item, int))
        elif isinstance(chunk, int):
            out.append(chunk)
    return out


def normalize_market_groups(details: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    market_group_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for group in details.get("marketGroups", []) or []:
        group_info = {
            "id": group.get("id"),
            "name": group.get("name"),
            "type": group.get("type"),
            "sortOrder": group.get("sortOrder"),
            "isBundle": group.get("isBundle"),
        }
        for market_id in group.get("marketIds", []) or []:
            if isinstance(market_id, int):
                market_group_map[market_id].append(group_info)
    return market_group_map


def normalize_markets(details: dict[str, Any]) -> list[dict[str, Any]]:
    odds_by_id = {odd.get("id"): odd for odd in details.get("odds", []) or []}
    market_groups = normalize_market_groups(details)
    normalized: list[dict[str, Any]] = []
    seen_market_ids: set[int] = set()

    for market in details.get("markets", []) or []:
        market_id = market.get("id")
        if not isinstance(market_id, int):
            continue
        if market_id in seen_market_ids:
            continue
        seen_market_ids.add(market_id)

        selections: list[dict[str, Any]] = []
        seen_selection: set[tuple[Any, ...]] = set()
        for odd_id in flatten_odd_ids(market.get("desktopOddIds")):
            odd = odds_by_id.get(odd_id)
            if not odd:
                continue
            odd_status = odd.get("oddStatus")
            selection = {
                "id": odd.get("id"),
                "name": odd.get("name"),
                "price": odd.get("price"),
                "statusCode": odd_status,
                "status": ODD_STATUS.get(odd_status, "unknown"),
                "competitorId": odd.get("competitorId"),
                "typeId": odd.get("typeId"),
            }
            selection_key = (
                selection["id"],
                selection["name"],
                selection["price"],
                selection["statusCode"],
                selection["competitorId"],
                selection["typeId"],
            )
            if selection_key in seen_selection:
                continue
            seen_selection.add(selection_key)
            selections.append(selection)

        normalized.append(
            {
                "id": market_id,
                "name": market.get("name"),
                "sportMarketId": market.get("sportMarketId"),
                "typeId": market.get("typeId"),
                "variant": market.get("variant"),
                "isBB": market.get("isBB"),
                "isMB": market.get("isMB"),
                "groups": market_groups.get(market_id, []),
                "selectionCount": len(selections),
                "selections": selections,
            },
        )

    return normalized


def extract_tracker_event(
    tracker: dict[str, Any],
    event_id: int,
) -> dict[str, Any] | None:
    events = tracker.get("events", []) or []
    for event in events:
        if event.get("id") == event_id:
            return event
    if events:
        return events[0]
    return None


def market_name_hits_insight(name: str) -> bool:
    lowered = normalize_text(name)
    return any(keyword in lowered for keyword in INSIGHT_KEYWORDS)


def as_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def selection_digest(
    markets: list[dict[str, Any]],
    odds_floor: float | None = None,
    odds_ceiling: float | None = None,
) -> dict[str, Any]:
    status_counts: Counter[str] = Counter()
    all_open: list[dict[str, Any]] = []

    for market in markets:
        market_name = market.get("name")
        market_id = market.get("id")
        for selection in market.get("selections") or []:
            status = selection.get("status") or "unknown"
            status_counts[status] += 1

            price = as_float(selection.get("price"))
            if status != "open" or price is None:
                continue

            implied = None
            if price > 0:
                implied = round(1 / price, 6)

            all_open.append(
                {
                    "marketId": market_id,
                    "marketName": market_name,
                    "selectionId": selection.get("id"),
                    "selectionName": selection.get("name"),
                    "price": price,
                    "impliedProbability": implied,
                },
            )

    all_open.sort(key=lambda x: (x["price"], str(x.get("marketName"))))

    filtered = all_open
    if odds_floor is not None:
        filtered = [
            x
            for x in filtered
            if (x.get("price") is not None and x["price"] >= odds_floor)
        ]
    if odds_ceiling is not None:
        filtered = [
            x
            for x in filtered
            if (x.get("price") is not None and x["price"] <= odds_ceiling)
        ]

    return {
        "statusCounts": dict(status_counts),
        "openSelectionCount": len(all_open),
        "openSelections": all_open,
        "appliedFilter": {
            "oddsFloor": odds_floor,
            "oddsCeiling": odds_ceiling,
        },
        "filteredSelectionCount": len(filtered),
        "filteredSelections": filtered,
    }


def key_market_digest(key_markets: list[dict[str, Any]]) -> dict[str, Any]:
    digest: dict[str, Any] = {}
    for market in key_markets:
        name = str(market.get("name") or "")
        digest[name] = {
            "marketId": market.get("id"),
            "selectionCount": market.get("selectionCount"),
            "selections": [
                {
                    "name": s.get("name"),
                    "price": s.get("price"),
                    "status": s.get("status"),
                }
                for s in (market.get("selections") or [])
            ],
        }
    return digest


def build_snapshot(  # noqa: PLR0913
    event_id: int,
    details: dict[str, Any],
    tracker: dict[str, Any],
    request_params: dict[str, Any],
    *,
    include_raw: bool,
    odds_floor: float | None = None,
    odds_ceiling: float | None = None,
) -> dict[str, Any]:
    tracker_event = extract_tracker_event(tracker, event_id) or {}
    competitors = details.get("competitors", []) or []
    markets = normalize_markets(details)
    key_markets = [
        m for m in markets if normalize_text(str(m.get("name") or "")) in KEY_MARKETS
    ]
    insight_markets = [
        m for m in markets if market_name_hits_insight(str(m.get("name") or ""))
    ]
    market_digest = selection_digest(
        markets=markets,
        odds_floor=odds_floor,
        odds_ceiling=odds_ceiling,
    )

    snapshot: dict[str, Any] = {
        "fetchedAtUtc": utc_now_iso(),
        "source": {
            "provider": "altenar-widget-api",
            "baseUrl": request_params["base_url"],
            "eventDetailsEndpoint": "GetEventDetails",
            "eventTrackerEndpoint": "GetEventTrackerInfo",
        },
        "request": {
            "eventId": event_id,
            "integration": request_params["integration"],
            "countryCode": request_params["countryCode"],
            "culture": request_params["culture"],
            "timezoneOffset": request_params["timezoneOffset"],
            "deviceType": request_params["deviceType"],
            "numFormat": request_params["numFormat"],
            "showNonBoosts": request_params["showNonBoosts"],
        },
        "match": {
            "id": details.get("id") or tracker_event.get("id"),
            "name": details.get("name") or tracker_event.get("name"),
            "startDate": details.get("startDate") or tracker_event.get("startDate"),
            "liveTime": details.get("liveTime") or tracker_event.get("liveTime"),
            "period": details.get("ls") or tracker_event.get("ls"),
            "lastUpdate": details.get("lst"),
            "score": tracker_event.get("score"),
            "statusCode": tracker_event.get("status"),
            "statusVariant": tracker_event.get("variant"),
            "redCardFlag": tracker_event.get("rc"),
            "hasStats": tracker_event.get("hasStats"),
            "trackerIds": {
                "lmt": (tracker_event.get("lmt") or {}).get("matchId"),
                "scoreBoard": (tracker_event.get("scoreBoard") or {}).get("matchId"),
            },
            "sport": details.get("sport"),
            "category": details.get("category"),
            "championship": details.get("champ"),
            "competitors": competitors,
        },
        "coverage": {
            "marketGroupCount": len(details.get("marketGroups", []) or []),
            "marketCount": len(markets),
            "oddCount": len(details.get("odds", []) or []),
            "keyMarketCount": len(key_markets),
            "insightMarketCount": len(insight_markets),
        },
        "marketDigest": market_digest,
        "keyMarketDigest": key_market_digest(key_markets),
        "keyMarkets": key_markets,
        "insightMarkets": insight_markets,
        "allMarkets": markets,
    }

    if include_raw:
        snapshot["raw"] = {
            "eventDetails": details,
            "eventTrackerInfo": tracker,
        }

    return snapshot


class EcuabetMatchClient:
    def __init__(self, config: FetchConfig, timeout: float) -> None:
        self._config = config
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "User-Agent": "ecuabet-match-fetch/1.0",
            },
        )

    def close(self) -> None:
        self._client.close()

    def _common_params(self, event_id: int) -> dict[str, Any]:
        return {
            "culture": self._config.culture,
            "timezoneOffset": self._config.timezone_offset,
            "integration": self._config.integration,
            "deviceType": self._config.device_type,
            "numFormat": self._config.num_format,
            "countryCode": self._config.country_code,
            "eventId": event_id,
        }

    def fetch_details(self, event_id: int) -> dict[str, Any]:
        params = self._common_params(event_id)
        params["showNonBoosts"] = str(self._config.show_non_boosts).lower()
        response = self._client.get(
            f"{self._config.base_url}/GetEventDetails",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    def fetch_tracker(self, event_id: int) -> dict[str, Any]:
        params = self._common_params(event_id)
        response = self._client.get(
            f"{self._config.base_url}/GetEventTrackerInfo",
            params=params,
        )
        response.raise_for_status()
        return response.json()


def write_snapshot(
    snapshot: dict[str, Any],
    output: Path,
    event_id: int,
    iteration: int,
    *,
    watch_mode: bool,
) -> Path:
    output = output.expanduser()
    if watch_mode:
        output.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = output / f"event_{event_id}_{ts}_{iteration:04d}.json"
    else:
        target = output
        target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch live Ecuabet sportsbook data for a match URL/id "
            "using Altenar widget endpoints."
        ),
    )
    parser.add_argument(
        "match",
        help="Ecuabet match URL (.../deportes/partido/<id>) or raw numeric id.",
    )
    parser.add_argument("--integration", default=DEFAULT_INTEGRATION)
    parser.add_argument("--country-code", default=DEFAULT_COUNTRY_CODE)
    parser.add_argument("--culture", default=DEFAULT_CULTURE)
    parser.add_argument("--timezone-offset", type=int, default=DEFAULT_TIMEZONE_OFFSET)
    parser.add_argument("--device-type", type=int, default=DEFAULT_DEVICE_TYPE)
    parser.add_argument("--num-format", default=DEFAULT_NUM_FORMAT)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--show-non-boosts",
        action="store_true",
        help="Request non-boost market variants when available.",
    )
    parser.add_argument(
        "--odds-floor",
        type=float,
        help=(
            "Optional minimum decimal odds filter for marketDigest.filteredSelections."
        ),
    )
    parser.add_argument(
        "--odds-ceiling",
        type=float,
        help=(
            "Optional maximum decimal odds filter for marketDigest.filteredSelections."
        ),
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--watch",
        type=float,
        default=0,
        help="Polling interval in seconds. 0 means single fetch.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=0,
        help="Used with --watch. 0 means infinite.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON output to file (single fetch) or directory (watch mode).",
    )
    parser.add_argument(
        "--no-raw",
        action="store_true",
        help="Do not include raw API payloads in output.",
    )
    parser.add_argument("--compact", action="store_true", help="Compact JSON output.")
    return parser.parse_args()


def main() -> int:  # noqa: C901,PLR0911,PLR0912
    args = parse_args()
    try:
        event_id = parse_event_id(args.match)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.watch < 0:
        print("error: --watch must be >= 0", file=sys.stderr)
        return 2
    if args.max_iterations < 0:
        print("error: --max-iterations must be >= 0", file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print("error: --timeout must be > 0", file=sys.stderr)
        return 2
    if (
        args.odds_floor is not None
        and args.odds_ceiling is not None
        and args.odds_floor > args.odds_ceiling
    ):
        print(
            "error: --odds-floor cannot be greater than --odds-ceiling",
            file=sys.stderr,
        )
        return 2

    config = FetchConfig(
        base_url=args.base_url.rstrip("/"),
        integration=args.integration,
        country_code=args.country_code,
        culture=args.culture,
        timezone_offset=args.timezone_offset,
        device_type=args.device_type,
        num_format=args.num_format,
        show_non_boosts=args.show_non_boosts,
    )
    request_params = {
        "base_url": config.base_url,
        "integration": config.integration,
        "countryCode": config.country_code,
        "culture": config.culture,
        "timezoneOffset": config.timezone_offset,
        "deviceType": config.device_type,
        "numFormat": config.num_format,
        "showNonBoosts": config.show_non_boosts,
    }

    client = EcuabetMatchClient(config=config, timeout=args.timeout)
    watch_mode = args.watch > 0
    iteration = 0

    try:
        while True:
            iteration += 1
            details = client.fetch_details(event_id)
            tracker = client.fetch_tracker(event_id)
            snapshot = build_snapshot(
                event_id=event_id,
                details=details,
                tracker=tracker,
                request_params=request_params,
                include_raw=not args.no_raw,
                odds_floor=args.odds_floor,
                odds_ceiling=args.odds_ceiling,
            )

            if args.output:
                path = write_snapshot(
                    snapshot=snapshot,
                    output=args.output,
                    event_id=event_id,
                    iteration=iteration,
                    watch_mode=watch_mode,
                )
                print(path)
            elif args.compact:
                print(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")))
            else:
                print(json.dumps(snapshot, ensure_ascii=False, indent=2))

            if not watch_mode:
                break
            if args.max_iterations and iteration >= args.max_iterations:
                break
            time.sleep(args.watch)
    except httpx.HTTPStatusError as exc:
        msg = (
            "error: upstream returned HTTP "
            f"{exc.response.status_code} for {exc.request.url}"
        )
        print(msg, file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"error: network error: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
