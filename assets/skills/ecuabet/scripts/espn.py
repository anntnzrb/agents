#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.27,<1.0",
# ]
# ///
"""ESPN site API live event snapshot CLI."""

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
from urllib.parse import parse_qs, urlparse

import httpx

__all__: list[str] = []

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"
GAME_ID_PATTERN = re.compile(r"gameId/(\d+)")
EVENT_PARAM_PATTERN = re.compile(r"event=(\d+)")
TWO_TEAMS = 2


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_event_id(value: str) -> int | None:
    value = value.strip()
    if value.isdigit():
        return int(value)

    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        match = GAME_ID_PATTERN.search(parsed.path)
        if match:
            return int(match.group(1))
        query = parse_qs(parsed.query)
        if "event" in query and query["event"] and query["event"][0].isdigit():
            return int(query["event"][0])

    match = GAME_ID_PATTERN.search(value)
    if match:
        return int(match.group(1))
    match = EVENT_PARAM_PATTERN.search(value)
    if match:
        return int(match.group(1))
    return None


def normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def resolve_event_by_query(
    client: httpx.Client,
    query: str,
    sport: str,
    league: str,
    date: str | None,
) -> tuple[int, list[dict[str, Any]]]:
    params: dict[str, Any] = {}
    if date:
        params["dates"] = date

    url = f"{BASE_URL}/{sport}/{league}/scoreboard"
    response = client.get(url, params=params)
    response.raise_for_status()
    payload = response.json()

    terms = [t for t in normalize_text(query).split(" ") if t]
    candidates: list[dict[str, Any]] = []

    for event in payload.get("events") or []:
        name = event.get("name") or ""
        short_name = event.get("shortName") or ""
        text = normalize_text(f"{name} {short_name}")
        score = sum(1 for term in terms if term in text)
        if score == 0:
            continue
        status = ((event.get("status") or {}).get("type") or {}).get("state", "")
        priority = {"in": 0, "pre": 1, "post": 2}.get(status, 3)
        candidates.append(
            {
                "id": int(event["id"]),
                "name": name,
                "date": event.get("date"),
                "state": status,
                "matchScore": score,
                "priority": priority,
            }
        )

    if not candidates:
        msg = f"No ESPN event found for query: {query}"
        raise ValueError(msg)

    candidates.sort(key=lambda x: (x["priority"], -x["matchScore"], x["date"] or ""))
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


def collect_team_stats(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    boxscore = summary.get("boxscore") or {}
    teams = boxscore.get("teams") or []
    out: dict[str, dict[str, Any]] = {}

    for team_row in teams:
        team_name = (team_row.get("team") or {}).get("displayName") or "Unknown"
        stats = {}
        for stat in team_row.get("statistics") or []:
            name = stat.get("name")
            if not name:
                continue
            stats[name] = {
                "label": stat.get("label"),
                "value": stat.get("value"),
                "displayValue": stat.get("displayValue"),
            }
        out[team_name] = stats

    return out


def collect_key_events(
    summary: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    events = summary.get("keyEvents") or []
    type_counts = Counter(
        ((x.get("type") or {}).get("type") or "unknown") for x in events
    )

    recent: list[dict[str, Any]] = []
    for event in events[-40:]:
        etype = event.get("type") or {}
        recent.append(
            {
                "id": event.get("id"),
                "type": etype.get("type"),
                "typeText": etype.get("text"),
                "clock": (event.get("clock") or {}).get("displayValue"),
                "period": (event.get("period") or {}).get("number"),
                "text": event.get("text"),
                "shortText": event.get("shortText"),
                "team": (event.get("team") or {}).get("displayName"),
                "scoringPlay": event.get("scoringPlay"),
                "wallclock": event.get("wallclock"),
            }
        )

    summary_counts = {
        "eventCount": len(events),
        "typeCounts": dict(type_counts),
        "goals": type_counts.get("goal", 0),
        "yellowCards": type_counts.get("yellow-card", 0),
        "redCards": type_counts.get("red-card", 0),
        "offsides": type_counts.get("offside", 0),
        "fouls": type_counts.get("foul", 0),
    }
    return summary_counts, recent


def collect_commentary(summary: dict[str, Any]) -> list[dict[str, Any]]:
    commentary = summary.get("commentary") or []
    return [
        {
            "sequence": item.get("sequence"),
            "clock": ((item.get("time") or {}).get("displayValue")),
            "text": item.get("text"),
            "playType": (((item.get("play") or {}).get("type") or {}).get("type")),
        }
        for item in commentary[-40:]
    ]


def collect_competitors(summary: dict[str, Any]) -> list[dict[str, Any]]:
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    out = []
    for c in competitors:
        team = c.get("team") or {}
        out.append(
            {
                "id": team.get("id"),
                "name": team.get("displayName"),
                "abbreviation": team.get("abbreviation"),
                "homeAway": c.get("homeAway"),
                "score": c.get("score"),
                "winner": c.get("winner"),
                "record": c.get("records"),
            }
        )
    return out


def build_snapshot(  # noqa: PLR0913
    event_id: int,
    summary: dict[str, Any],
    *,
    include_raw: bool,
    sport: str,
    league: str,
    resolved_candidates: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    header = summary.get("header") or {}
    competition = (header.get("competitions") or [{}])[0]
    status = competition.get("status") or {}
    status_type = status.get("type") or {}

    key_event_counts, recent_key_events = collect_key_events(summary)
    team_stats = collect_team_stats(summary)

    competitors = collect_competitors(summary)
    match_name = competition.get("name")
    if not match_name and len(competitors) == TWO_TEAMS:
        match_name = f"{competitors[0]['name']} vs {competitors[1]['name']}"

    snapshot: dict[str, Any] = {
        "fetchedAtUtc": utc_now_iso(),
        "source": {
            "provider": "espn-site-api",
            "baseUrl": BASE_URL,
        },
        "request": {
            "eventId": event_id,
            "sport": sport,
            "league": league,
        },
        "match": {
            "id": competition.get("id") or str(event_id),
            "name": match_name,
            "shortName": competition.get("shortName"),
            "date": competition.get("date"),
            "status": {
                "state": status_type.get("state"),
                "description": status_type.get("description"),
                "detail": status_type.get("detail"),
                "shortDetail": status_type.get("shortDetail"),
                "period": status.get("period"),
                "clock": status.get("displayClock"),
            },
            "competitors": competitors,
            "venue": (competition.get("venue") or {}),
            "attendance": competition.get("attendance"),
            "broadcasts": summary.get("broadcasts") or [],
        },
        "coverage": {
            "commentaryCount": len(summary.get("commentary") or []),
            "keyEventCount": key_event_counts["eventCount"],
            "injuryCount": len(summary.get("injuries") or []),
            "hasOdds": bool(summary.get("hasOdds")),
            "pickcenterCount": len(summary.get("pickcenter") or []),
            "newsCount": len(summary.get("news") or []),
        },
        "keyEventSummary": key_event_counts,
        "recentKeyEvents": recent_key_events,
        "teamStatistics": team_stats,
        "recentCommentary": collect_commentary(summary),
        "injuries": summary.get("injuries") or [],
        "odds": {
            "odds": summary.get("odds") or [],
            "pickcenter": summary.get("pickcenter") or [],
        },
    }

    if resolved_candidates:
        snapshot["resolution"] = {
            "resolvedBy": "scoreboard-search",
            "candidates": resolved_candidates[:10],
        }

    if include_raw:
        snapshot["raw"] = {
            "summary": summary,
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
        target = output / f"espn_{event_id}_{ts}_{iteration:04d}.json"
    else:
        target = output
        target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch ESPN soccer event summary by id/url/query."
    )
    parser.add_argument(
        "match",
        help="ESPN event id, ESPN URL, or search query.",
    )
    parser.add_argument("--sport", default="soccer")
    parser.add_argument("--league", default="esp.1")
    parser.add_argument(
        "--date",
        help=(
            "Optional date for scoreboard search (YYYYMMDD). Used for query resolution."
        ),
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
        headers={"Accept": "application/json", "User-Agent": "espn-cli/1.0"},
    )

    try:
        if event_id is None:
            event_id, resolved_candidates = resolve_event_by_query(
                client=client,
                query=args.match,
                sport=args.sport,
                league=args.league,
                date=args.date,
            )

        watch_mode = args.watch > 0
        iteration = 0

        while True:
            iteration += 1
            url = f"{BASE_URL}/{args.sport}/{args.league}/summary"
            summary = safe_get_json(client, url, params={"event": event_id})
            if not summary:
                print(f"error: ESPN event {event_id} not found", file=sys.stderr)
                return 1

            snapshot = build_snapshot(
                event_id=event_id,
                summary=summary,
                include_raw=not args.no_raw,
                sport=args.sport,
                league=args.league,
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
