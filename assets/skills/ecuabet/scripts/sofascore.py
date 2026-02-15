#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.27,<1.0",
# ]
# ///
"""CLI client for SofaScore match snapshots and live event context."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

__all__: list[str] = []

BASE_URL = "https://api.sofascore.com/api/v1"
EVENT_PATH_PATTERN = re.compile(r"/event/[^/]+/(\d+)$")
TAIL_DIGITS_PATTERN = re.compile(r"(\d{6,})$")

STAT_KEYS = {
    "ballPossession",
    "expectedGoals",
    "bigChanceCreated",
    "totalShotsOnGoal",
    "shotsOnGoal",
    "cornerKicks",
    "fouls",
    "yellowCards",
    "redCards",
    "offsides",
    "goalkeeperSaves",
    "passes",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_event_id(value: str) -> int | None:
    value = value.strip()
    if value.isdigit():
        return int(value)

    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        match = EVENT_PATH_PATTERN.search(parsed.path)
        if match:
            return int(match.group(1))
        tail = TAIL_DIGITS_PATTERN.search(parsed.path)
        if tail:
            return int(tail.group(1))

    tail = TAIL_DIGITS_PATTERN.search(value)
    if tail:
        return int(tail.group(1))

    return None


def ensure_timestamp(value: object) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def fractional_to_decimal(value: str | None) -> float | None:
    if not value or "/" not in value:
        return None
    left, right = value.split("/", maxsplit=1)
    try:
        n = float(left)
        d = float(right)
    except ValueError:
        return None
    if d == 0:
        return None
    return round(1 + (n / d), 4)


def extract_event_candidates(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in results:
        if row.get("type") != "event":
            continue
        entity = row.get("entity") or {}
        event_id = entity.get("id")
        if not isinstance(event_id, int):
            continue
        status_type = ((entity.get("status") or {}).get("type") or "").lower()
        priority = {
            "inprogress": 0,
            "notstarted": 1,
            "finished": 2,
        }.get(status_type, 3)
        out.append(
            {
                "id": event_id,
                "name": entity.get("name"),
                "startTimestamp": entity.get("startTimestamp"),
                "statusType": status_type,
                "priority": priority,
                "score": row.get("score", 0),
            }
        )
    out.sort(
        key=lambda x: (
            x["priority"],
            -(x.get("startTimestamp") or 0),
            -(x.get("score") or 0),
        )
    )
    return out


def resolve_event_id(
    client: httpx.Client, query: str
) -> tuple[int, list[dict[str, Any]]]:
    response = client.get(f"{BASE_URL}/search/all", params={"q": query})
    response.raise_for_status()
    payload = response.json()
    candidates = extract_event_candidates(payload.get("results") or [])
    if not candidates:
        msg = f"No SofaScore event found for query: {query}"
        raise ValueError(msg)
    return candidates[0]["id"], candidates


def safe_get_json(
    client: httpx.Client, url: str, params: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 410):
            return None
        raise


def collect_stats(
    statistics_payload: dict[str, Any] | None,
) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    if not statistics_payload:
        return result

    for period in statistics_payload.get("statistics") or []:
        period_name = period.get("period") or "UNKNOWN"
        period_stats: dict[str, dict[str, Any]] = {}
        for group in period.get("groups") or []:
            for item in group.get("statisticsItems") or []:
                key = item.get("key") or item.get("name")
                if key not in STAT_KEYS:
                    continue
                period_stats[key] = {
                    "name": item.get("name"),
                    "home": item.get("home"),
                    "away": item.get("away"),
                    "homeValue": item.get("homeValue"),
                    "awayValue": item.get("awayValue"),
                    "group": group.get("groupName"),
                }
        result[period_name] = period_stats
    return result


def collect_incidents(
    incidents_payload: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    incidents = (incidents_payload or {}).get("incidents") or []
    type_counts = Counter((x.get("incidentType") or "unknown") for x in incidents)

    recent = [
        {
            "time": incident.get("time"),
            "addedTime": incident.get("addedTime"),
            "type": incident.get("incidentType"),
            "isHome": incident.get("isHome"),
            "text": incident.get("text"),
            "reason": incident.get("reason"),
            "player": ((incident.get("player") or {}).get("name")),
            "playerIn": ((incident.get("playerIn") or {}).get("name")),
            "playerOut": ((incident.get("playerOut") or {}).get("name")),
            "homeScore": incident.get("homeScore"),
            "awayScore": incident.get("awayScore"),
        }
        for incident in incidents[:40]
    ]

    summary = {
        "incidentCount": len(incidents),
        "incidentTypeCounts": dict(type_counts),
        "goalCount": type_counts.get("goal", 0),
        "cardCount": type_counts.get("card", 0),
        "substitutionCount": type_counts.get("substitution", 0),
    }
    return summary, recent


def collect_lineups(lineups_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not lineups_payload:
        return {}

    home = lineups_payload.get("home") or {}
    away = lineups_payload.get("away") or {}

    return {
        "confirmed": lineups_payload.get("confirmed"),
        "home": {
            "formation": home.get("formation"),
            "playerCount": len(home.get("players") or []),
            "missingCount": len(home.get("missingPlayers") or []),
            "manager": (home.get("manager") or {}).get("name"),
        },
        "away": {
            "formation": away.get("formation"),
            "playerCount": len(away.get("players") or []),
            "missingCount": len(away.get("missingPlayers") or []),
            "manager": (away.get("manager") or {}).get("name"),
        },
    }


def collect_odds(odds_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not odds_payload:
        return []

    markets: list[dict[str, Any]] = []
    for market in odds_payload.get("markets") or []:
        picks: list[dict[str, Any]] = []
        for choice in market.get("choices") or []:
            frac = choice.get("fractionalValue")
            picks.append(
                {
                    "name": choice.get("name"),
                    "fractional": frac,
                    "decimal": fractional_to_decimal(frac),
                    "change": choice.get("change"),
                    "sourceId": choice.get("sourceId"),
                    "winning": choice.get("winning"),
                }
            )

        markets.append(
            {
                "id": market.get("id"),
                "marketId": market.get("marketId"),
                "name": market.get("marketName"),
                "group": market.get("marketGroup"),
                "period": market.get("marketPeriod"),
                "isLive": market.get("isLive"),
                "suspended": market.get("suspended"),
                "selectionCount": len(picks),
                "selections": picks,
            }
        )

    return markets


def build_snapshot(  # noqa: PLR0913
    event_id: int,
    event_payload: dict[str, Any],
    incidents_payload: dict[str, Any] | None,
    statistics_payload: dict[str, Any] | None,
    lineups_payload: dict[str, Any] | None,
    odds_payload: dict[str, Any] | None,
    *,
    include_raw: bool,
    resolved_candidates: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    event = event_payload.get("event") or {}

    incident_summary, recent_incidents = collect_incidents(incidents_payload)
    lineup_summary = collect_lineups(lineups_payload)
    stats = collect_stats(statistics_payload)
    odds_markets = collect_odds(odds_payload)

    snapshot: dict[str, Any] = {
        "fetchedAtUtc": utc_now_iso(),
        "source": {
            "provider": "sofascore-public-api",
            "baseUrl": BASE_URL,
        },
        "request": {
            "eventId": event_id,
        },
        "match": {
            "id": event.get("id"),
            "slug": event.get("slug"),
            "name": (
                f"{(event.get('homeTeam') or {}).get('name')} vs "
                f"{(event.get('awayTeam') or {}).get('name')}"
            ),
            "status": event.get("status"),
            "startTimestamp": event.get("startTimestamp"),
            "startTimeUtc": ensure_timestamp(event.get("startTimestamp")),
            "homeTeam": event.get("homeTeam"),
            "awayTeam": event.get("awayTeam"),
            "homeScore": event.get("homeScore"),
            "awayScore": event.get("awayScore"),
            "tournament": event.get("tournament"),
            "roundInfo": event.get("roundInfo"),
            "venue": event.get("venue"),
            "referee": event.get("referee"),
            "hasXg": event.get("xg") is not None,
            "xg": event.get("xg"),
        },
        "coverage": {
            "hasIncidents": incidents_payload is not None,
            "hasStatistics": statistics_payload is not None,
            "hasLineups": lineups_payload is not None,
            "hasOdds": odds_payload is not None,
            "oddsMarketCount": len(odds_markets),
            "statsPeriods": list(stats.keys()),
        },
        "incidentsSummary": incident_summary,
        "recentIncidents": recent_incidents,
        "statistics": stats,
        "lineups": lineup_summary,
        "oddsMarkets": odds_markets,
    }

    if resolved_candidates:
        snapshot["resolution"] = {
            "resolvedBy": "search",
            "candidates": resolved_candidates[:10],
        }

    if include_raw:
        snapshot["raw"] = {
            "event": event_payload,
            "incidents": incidents_payload,
            "statistics": statistics_payload,
            "lineups": lineups_payload,
            "odds": odds_payload,
        }

    return snapshot


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
        target = output / f"sofascore_{event_id}_{ts}_{iteration:04d}.json"
    else:
        target = output
        target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch SofaScore match snapshot by event id/url/query."
    )
    parser.add_argument(
        "match",
        help="SofaScore event id, URL, or search query.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--watch", type=float, default=0)
    parser.add_argument("--max-iterations", type=int, default=0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-raw", action="store_true")
    parser.add_argument("--compact", action="store_true")
    return parser.parse_args()


def main() -> int:  # noqa: C901,PLR0911,PLR0912
    args = parse_args()
    if args.watch < 0:
        print("error: --watch must be >= 0", file=sys.stderr)
        return 2
    if args.max_iterations < 0:
        print("error: --max-iterations must be >= 0", file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print("error: --timeout must be > 0", file=sys.stderr)
        return 2

    event_id = parse_event_id(args.match)
    resolved_candidates: list[dict[str, Any]] | None = None

    client = httpx.Client(
        timeout=args.timeout,
        headers={"Accept": "application/json", "User-Agent": "sofascore-cli/1.0"},
    )

    try:
        if event_id is None:
            event_id, resolved_candidates = resolve_event_id(client, args.match)

        watch_mode = args.watch > 0
        iteration = 0

        while True:
            iteration += 1
            event_payload = safe_get_json(client, f"{BASE_URL}/event/{event_id}")
            if not event_payload:
                print(f"error: event {event_id} not found", file=sys.stderr)
                return 1

            incidents_payload = safe_get_json(
                client, f"{BASE_URL}/event/{event_id}/incidents"
            )
            statistics_payload = safe_get_json(
                client, f"{BASE_URL}/event/{event_id}/statistics"
            )
            lineups_payload = safe_get_json(
                client, f"{BASE_URL}/event/{event_id}/lineups"
            )
            odds_payload = safe_get_json(
                client, f"{BASE_URL}/event/{event_id}/odds/1/all"
            )

            snapshot = build_snapshot(
                event_id=event_id,
                event_payload=event_payload,
                incidents_payload=incidents_payload,
                statistics_payload=statistics_payload,
                lineups_payload=lineups_payload,
                odds_payload=odds_payload,
                include_raw=not args.no_raw,
                resolved_candidates=resolved_candidates,
            )

            if args.output:
                path = write_snapshot(
                    snapshot,
                    args.output,
                    event_id,
                    iteration,
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

        return 0  # noqa: TRY300
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
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
