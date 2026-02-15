#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "httpx>=0.27,<1.0",
#   "understatapi>=0.6.1,<1.0",
# ]
# ///
"""Unified live football feed collector for betting-decision workflows."""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from understatapi import UnderstatClient

import ecuabet
import espn
import open_meteo
import recommendations
import sofascore
import understat

__all__: list[str] = []

LINE_RE = re.compile(r"-?\d+(?:\.\d+)?")
ASCII_UPPER_BOUND = 128
TWO_TEAMS = 2
DEFAULT_ESPN_LEAGUE = "esp.1"
DEFAULT_UNDERSTAT_LEAGUE: str | None = None
UNDERSTAT_LEAGUE_HINTS = (
    ("la liga", "La_Liga"),
    ("premier league", "EPL"),
    ("bundesliga", "Bundesliga"),
    ("serie a", "Serie_A"),
    ("ligue 1", "Ligue_1"),
    ("russian premier league", "RFPL"),
    ("premier liga", "RFPL"),
)
ESPN_LEAGUE_HINTS = (
    ("la liga", "esp.1"),
    ("premier league", "eng.1"),
    ("bundesliga", "ger.1"),
    ("serie a", "ita.1"),
    ("ligue 1", "fra.1"),
    ("primeira liga", "por.1"),
    ("liga portugal", "por.1"),
    ("portugal", "por.1"),
    ("russian premier league", "rus.1"),
    ("premier liga", "rus.1"),
)
MIN_HISTORY_LIMIT = 2


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def date_yyyymmdd_from_timestamp(ts: object) -> str | None:
    if not isinstance(ts, (int, float)):
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%d")


def date_yyyymmdd_from_iso(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value.strip())
    if not match:
        return None
    return "".join(match.groups())


def team_names_from_ecuabet_details(
    details: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    if not isinstance(details, dict):
        return None, None
    competitors = details.get("competitors") or []
    names = [c.get("name") for c in competitors if isinstance(c, dict)]
    names = [name for name in names if isinstance(name, str) and name]
    if len(names) >= TWO_TEAMS:
        return names[0], names[1]
    return None, None


def infer_league_hints(  # noqa: C901
    sofa_event: dict[str, Any] | None,
    ecuabet_details: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    candidates: list[str] = []
    if isinstance(sofa_event, dict):
        tournament = sofa_event.get("tournament") or {}
        unique_tournament = tournament.get("uniqueTournament") or {}
        category = tournament.get("category") or {}
        for value in (
            tournament.get("name"),
            unique_tournament.get("name"),
            category.get("name"),
        ):
            normalized = normalize_text(value if isinstance(value, str) else None)
            if normalized:
                candidates.append(normalized)
    if isinstance(ecuabet_details, dict):
        championship = ecuabet_details.get("champ") or {}
        category = ecuabet_details.get("category") or {}
        for value in (
            championship.get("name"),
            category.get("name"),
        ):
            normalized = normalize_text(value if isinstance(value, str) else None)
            if normalized:
                candidates.append(normalized)

    understat_league = None
    espn_league = None
    for text in candidates:
        if understat_league is None:
            understat_league = next(
                (value for key, value in UNDERSTAT_LEAGUE_HINTS if key in text), None
            )
        if espn_league is None:
            espn_league = next(
                (value for key, value in ESPN_LEAGUE_HINTS if key in text), None
            )
        if understat_league and espn_league:
            break
    return understat_league, espn_league


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(ch for ch in text if ord(ch) < ASCII_UPPER_BOUND)
    return " ".join(ascii_text.lower().split())


def as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def write_snapshot(
    snapshot: dict[str, Any], output: Path, iteration: int, *, watch_mode: bool
) -> Path:
    output = output.expanduser()
    if watch_mode:
        output.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = output / f"main_{ts}_{iteration:04d}.json"
    else:
        target = output
        target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch Ecuabet + SofaScore + ESPN + Open-Meteo + Understat in one "
            "decision-ready snapshot."
        )
    )
    parser.add_argument(
        "match",
        help=(
            "Primary match input. Supports Ecuabet id/url, "
            "SofaScore id/url, or team query text."
        ),
    )
    parser.add_argument(
        "--sofascore",
        help="Optional explicit SofaScore event id/url/query override.",
    )

    parser.add_argument(
        "--ecuabet",
        help="Ecuabet match URL/id. Recommended for full market coverage.",
    )
    parser.add_argument("--require-ecuabet", action="store_true")
    parser.add_argument("--ecuabet-integration", default=ecuabet.DEFAULT_INTEGRATION)
    parser.add_argument("--ecuabet-country-code", default=ecuabet.DEFAULT_COUNTRY_CODE)
    parser.add_argument("--ecuabet-culture", default=ecuabet.DEFAULT_CULTURE)
    parser.add_argument(
        "--ecuabet-timezone-offset", type=int, default=ecuabet.DEFAULT_TIMEZONE_OFFSET
    )
    parser.add_argument(
        "--ecuabet-device-type", type=int, default=ecuabet.DEFAULT_DEVICE_TYPE
    )
    parser.add_argument("--ecuabet-num-format", default=ecuabet.DEFAULT_NUM_FORMAT)
    parser.add_argument("--ecuabet-base-url", default=ecuabet.DEFAULT_BASE_URL)
    parser.add_argument("--ecuabet-show-non-boosts", action="store_true")

    parser.add_argument(
        "--espn",
        help=(
            "Optional ESPN event id/url/query. "
            "If omitted, auto-resolve from team names."
        ),
    )
    parser.add_argument("--espn-sport", default="soccer")
    parser.add_argument(
        "--espn-league",
        help=(
            "Optional ESPN league code override (auto-inferred when possible). "
            "Example: ger.1."
        ),
    )

    parser.add_argument(
        "--weather-location",
        help=(
            "Optional weather location (city or lat,lon). "
            "If omitted, use SofaScore venue coords."
        ),
    )
    parser.add_argument("--weather-country-code")

    parser.add_argument(
        "--understat-league",
        help=(
            "Optional Understat league override (auto-inferred when possible). "
            "Examples: La_Liga, Bundesliga."
        ),
    )
    parser.add_argument("--understat-season", default=understat.default_season())
    parser.add_argument("--top-players", type=int, default=12)

    parser.add_argument(
        "--odds-floor",
        type=float,
        help="Optional minimum decimal odds filter for Ecuabet filteredSelections.",
    )
    parser.add_argument(
        "--odds-ceiling",
        type=float,
        help="Optional maximum decimal odds filter for Ecuabet filteredSelections.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--watch", type=float, default=0)
    parser.add_argument("--max-iterations", type=int, default=0)
    parser.add_argument(
        "--recommend",
        action="store_true",
        help=(
            "Compatibility flag. Recommendations are always computed and included "
            "in unified output."
        ),
    )
    parser.add_argument(
        "--recommend-top",
        type=int,
        default=8,
        help="Number of ranked recommendations to return.",
    )
    parser.add_argument(
        "--recommend-min-odds",
        type=float,
        default=1.01,
        help="Minimum decimal odds allowed in recommendation shortlist.",
    )
    parser.add_argument(
        "--recommend-max-odds",
        type=float,
        help="Optional maximum decimal odds allowed in recommendation shortlist.",
    )
    parser.add_argument(
        "--recommend-min-confidence",
        type=float,
        default=0.0,
        help="Minimum global confidence [0..1] to keep recommendations.",
    )
    parser.add_argument(
        "--recommend-include-high-risk",
        action="store_true",
        help="Include high-risk selections in shortlist ranking.",
    )
    parser.add_argument(
        "--stale-threshold-seconds",
        type=float,
        default=180.0,
        help="Max acceptable feed age before confidence starts decaying.",
    )
    parser.add_argument(
        "--line-history-limit",
        type=int,
        default=120,
        help="Per-selection price history points retained in --watch mode.",
    )
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-raw", action="store_true")
    parser.add_argument("--compact", action="store_true")
    return parser.parse_args()


def market_lookup(ecuabet_snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for market in ecuabet_snapshot.get("keyMarkets") or []:
        lookup[normalize_text(market.get("name"))] = market
    return lookup


def market_open_selections(
    market: dict[str, Any], limit: int = 40
) -> list[dict[str, Any]]:
    rows = []
    for sel in market.get("selections") or []:
        price = as_float(sel.get("price"))
        if sel.get("status") != "open" or price is None:
            continue
        implied = round(1 / price, 6) if price > 0 else None
        implied_pct = round(implied * 100, 2) if isinstance(implied, float) else None
        rows.append(
            {
                "name": sel.get("name"),
                "price": price,
                "impliedProbability": implied,
                "impliedProbabilityPct": implied_pct,
            }
        )
    rows.sort(key=lambda x: (x["price"], x["name"] or ""))
    return rows[:limit]


def parse_total_line(selection_name: str | None) -> tuple[str | None, float | None]:
    n = normalize_text(selection_name)
    side: str | None = None
    if n.startswith("mas de"):
        side = "over"
    elif n.startswith("menos de"):
        side = "under"

    match = LINE_RE.search(n)
    if not side or not match:
        return None, None

    try:
        line = float(match.group(0))
    except ValueError:
        return None, None
    return side, line


def totals_ladder(market: dict[str, Any]) -> list[dict[str, Any]]:
    lines: dict[float, dict[str, Any]] = {}
    for sel in market.get("selections") or []:
        if sel.get("status") != "open":
            continue
        side, line = parse_total_line(sel.get("name"))
        price = as_float(sel.get("price"))
        if side is None or line is None or price is None:
            continue

        line_row = lines.setdefault(line, {"line": line, "over": None, "under": None})
        line_row[side] = {
            "name": sel.get("name"),
            "price": price,
            "impliedProbability": round(1 / price, 6) if price > 0 else None,
            "impliedProbabilityPct": round((1 / price) * 100, 2) if price > 0 else None,
        }

    return [lines[k] for k in sorted(lines.keys())]


def pick_team_stats(
    espn_stats: dict[str, Any], team_name: str | None
) -> dict[str, Any]:
    if not team_name:
        return {}
    target = normalize_text(team_name)

    for key, value in espn_stats.items():
        key_n = normalize_text(key)
        if key_n == target or target in key_n or key_n in target:
            return value

    return {}


def metric_from_stats(stats: dict[str, Any], key: str) -> object | None:
    row = stats.get(key) if isinstance(stats, dict) else None
    if not isinstance(row, dict):
        return None
    return row.get("displayValue") or row.get("value")


def extract_espn_score(espn_snapshot: dict[str, Any]) -> dict[str, Any]:
    out = {"home": None, "away": None}
    for comp in espn_snapshot.get("match", {}).get("competitors") or []:
        side = comp.get("homeAway")
        if side == "home":
            out["home"] = comp.get("score")
        elif side == "away":
            out["away"] = comp.get("score")
    return out


def score_consensus(
    sofa: dict[str, Any] | None,
    espn_snap: dict[str, Any] | None,
    ecuabet_snap: dict[str, Any] | None,
) -> dict[str, Any]:
    sources: dict[str, list[int] | None] = {}

    if sofa:
        home = ((sofa.get("match") or {}).get("homeScore") or {}).get("current")
        away = ((sofa.get("match") or {}).get("awayScore") or {}).get("current")
        if isinstance(home, int) and isinstance(away, int):
            sources["sofascore"] = [home, away]

    if espn_snap:
        e = extract_espn_score(espn_snap)
        try:
            home = int(float(e["home"])) if e["home"] is not None else None
            away = int(float(e["away"])) if e["away"] is not None else None
        except (TypeError, ValueError):
            home, away = None, None
        if isinstance(home, int) and isinstance(away, int):
            sources["espn"] = [home, away]

    if ecuabet_snap:
        sc = (ecuabet_snap.get("match") or {}).get("score")
        if (
            isinstance(sc, list)
            and len(sc) == TWO_TEAMS
            and all(isinstance(x, int) for x in sc)
        ):
            sources["ecuabet"] = [sc[0], sc[1]]

    unique = {tuple(v) for v in sources.values()}
    return {
        "sources": sources,
        "consistent": len(unique) <= 1,
        "consensusScore": list(next(iter(unique))) if len(unique) == 1 else None,
    }


def derive_decision_summary(
    sofa: dict[str, Any] | None,
    espn_snap: dict[str, Any] | None,
    weather: dict[str, Any] | None,
    understat_snap: dict[str, Any] | None,
    ecuabet_snap: dict[str, Any] | None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {}

    summary["scoreConsensus"] = score_consensus(sofa, espn_snap, ecuabet_snap)

    status_board = {
        "sofascore": {
            "status": (((sofa or {}).get("match") or {}).get("status") or {}).get(
                "description"
            ),
            "time": (((sofa or {}).get("match") or {}).get("status") or {}).get(
                "description"
            )
            if sofa
            else None,
        },
        "espn": {
            "status": (((espn_snap or {}).get("match") or {}).get("status") or {}).get(
                "detail"
            ),
            "clock": (((espn_snap or {}).get("match") or {}).get("status") or {}).get(
                "clock"
            ),
        },
        "ecuabet": {
            "statusCode": ((ecuabet_snap or {}).get("match") or {}).get("statusCode"),
            "period": ((ecuabet_snap or {}).get("match") or {}).get("period"),
            "liveTime": ((ecuabet_snap or {}).get("match") or {}).get("liveTime"),
        },
    }
    summary["statusBoard"] = status_board

    sofa_stats = ((sofa or {}).get("statistics") or {}).get("ALL") or {}
    home_name = ((sofa or {}).get("match") or {}).get("homeTeam", {}).get("name")
    away_name = ((sofa or {}).get("match") or {}).get("awayTeam", {}).get("name")

    espn_team_stats = (espn_snap or {}).get("teamStatistics") or {}
    espn_home = pick_team_stats(espn_team_stats, home_name)
    espn_away = pick_team_stats(espn_team_stats, away_name)

    summary["liveMetrics"] = {
        "sofascore": {
            "expectedGoals": sofa_stats.get("expectedGoals"),
            "possession": sofa_stats.get("ballPossession"),
            "totalShots": sofa_stats.get("totalShotsOnGoal"),
            "shotsOnTarget": sofa_stats.get("shotsOnGoal"),
            "corners": sofa_stats.get("cornerKicks"),
            "fouls": sofa_stats.get("fouls"),
            "offsides": sofa_stats.get("offsides"),
            "yellowCards": sofa_stats.get("yellowCards"),
            "redCards": sofa_stats.get("redCards"),
            "saves": sofa_stats.get("goalkeeperSaves"),
        },
        "espn": {
            "home": {
                "team": home_name,
                "fouls": metric_from_stats(espn_home, "foulsCommitted"),
                "yellowCards": metric_from_stats(espn_home, "yellowCards"),
                "redCards": metric_from_stats(espn_home, "redCards"),
                "offsides": metric_from_stats(espn_home, "offsides"),
                "corners": metric_from_stats(espn_home, "wonCorners"),
                "shots": metric_from_stats(espn_home, "totalShots"),
                "shotsOnTarget": metric_from_stats(espn_home, "shotsOnTarget"),
                "possession": metric_from_stats(espn_home, "possessionPct"),
                "saves": metric_from_stats(espn_home, "saves"),
            },
            "away": {
                "team": away_name,
                "fouls": metric_from_stats(espn_away, "foulsCommitted"),
                "yellowCards": metric_from_stats(espn_away, "yellowCards"),
                "redCards": metric_from_stats(espn_away, "redCards"),
                "offsides": metric_from_stats(espn_away, "offsides"),
                "corners": metric_from_stats(espn_away, "wonCorners"),
                "shots": metric_from_stats(espn_away, "totalShots"),
                "shotsOnTarget": metric_from_stats(espn_away, "shotsOnTarget"),
                "possession": metric_from_stats(espn_away, "possessionPct"),
                "saves": metric_from_stats(espn_away, "saves"),
            },
        },
    }

    summary["weather"] = {
        "current": ((weather or {}).get("current")),
        "comfort": (((weather or {}).get("computed") or {}).get("comfort")),
        "atKickoff": (((weather or {}).get("atTime") or {}).get("nearestHourly")),
    }

    understat_forms = [
        {
            "team": team.get("title"),
            "seasonTotals": team.get("seasonTotals"),
            "form": team.get("form"),
            "topPlayersByXG": team.get("topPlayersByXG", [])[:6],
        }
        for team in (understat_snap or {}).get("teams") or []
    ]
    league_table = (understat_snap or {}).get("leagueTableSignals") or []
    team_names = {
        normalize_text(x.get("team")) for x in understat_forms if isinstance(x, dict)
    }
    understat_positions = [
        row for row in league_table if normalize_text(row.get("team")) in team_names
    ]
    summary["understatForm"] = {
        "headToHead": (understat_snap or {}).get("headToHead") or [],
        "leaguePositionSignals": understat_positions,
        "teams": understat_forms,
    }

    if ecuabet_snap:
        lookup = market_lookup(ecuabet_snap)
        total_market = lookup.get("total")
        total_1h = lookup.get("1a mitad - total")
        total_2h = lookup.get("2a mitad - total")

        key_pack = {
            "1x2": market_open_selections(lookup.get("1x2") or {}),
            "doubleChance": market_open_selections(
                lookup.get("doble oportunidad") or {}
            ),
            "btts": market_open_selections(lookup.get("ambos equipos marcan") or {}),
            "handicap": market_open_selections(lookup.get("handicap") or {}, limit=80),
            "firstGoal": market_open_selections(lookup.get("primer gol") or {}),
            "lastGoal": market_open_selections(lookup.get("ultimo gol") or {}),
            "correctScore": market_open_selections(
                lookup.get("marcador exacto") or {}, limit=80
            ),
            "totals": totals_ladder(total_market or {}),
            "totals_1st_half": totals_ladder(total_1h or {}),
            "totals_2nd_half": totals_ladder(total_2h or {}),
        }

        digest = ecuabet_snap.get("marketDigest") or {}
        open_selections = digest.get("openSelections") or []
        open_selections.sort(
            key=lambda x: (x.get("price") or 9999, x.get("marketName") or "")
        )
        filtered = digest.get("filteredSelections") or []
        filtered.sort(key=lambda x: (x.get("price") or 9999, x.get("marketName") or ""))

        summary["ecuabetMarkets"] = {
            "coverage": (ecuabet_snap.get("coverage") or {}),
            "statusCounts": digest.get("statusCounts"),
            "keyLines": key_pack,
            "openSelections": open_selections,
            "filteredSelections": filtered,
            "appliedFilter": digest.get("appliedFilter"),
        }
    else:
        summary["ecuabetMarkets"] = {"error": "ecuabet feed unavailable"}

    timeline = [
        {
            "source": "sofascore",
            "time": row.get("time"),
            "addedTime": row.get("addedTime"),
            "type": row.get("type"),
            "text": row.get("text"),
            "player": row.get("player"),
            "isHome": row.get("isHome"),
        }
        for row in (sofa or {}).get("recentIncidents") or []
    ]
    timeline.extend(
        {
            "source": "espn",
            "clock": row.get("clock"),
            "type": row.get("type"),
            "typeText": row.get("typeText"),
            "text": row.get("text"),
            "team": row.get("team"),
        }
        for row in (espn_snap or {}).get("recentKeyEvents") or []
    )
    summary["timeline"] = timeline

    return summary


def main() -> int:  # noqa: C901,PLR0911,PLR0912,PLR0915
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
    if (
        args.odds_floor is not None
        and args.odds_ceiling is not None
        and args.odds_floor > args.odds_ceiling
    ):
        print(
            "error: --odds-floor cannot be greater than --odds-ceiling", file=sys.stderr
        )
        return 2
    if args.recommend_top <= 0:
        print("error: --recommend-top must be > 0", file=sys.stderr)
        return 2
    if args.recommend_min_odds <= 0:
        print("error: --recommend-min-odds must be > 0", file=sys.stderr)
        return 2
    if (
        args.recommend_max_odds is not None
        and args.recommend_max_odds < args.recommend_min_odds
    ):
        print(
            "error: --recommend-max-odds cannot be lower than --recommend-min-odds",
            file=sys.stderr,
        )
        return 2
    if not 0 <= args.recommend_min_confidence <= 1:
        print("error: --recommend-min-confidence must be in [0, 1]", file=sys.stderr)
        return 2
    if args.stale_threshold_seconds <= 0:
        print("error: --stale-threshold-seconds must be > 0", file=sys.stderr)
        return 2
    if args.line_history_limit < MIN_HISTORY_LIMIT:
        print(
            f"error: --line-history-limit must be >= {MIN_HISTORY_LIMIT}",
            file=sys.stderr,
        )
        return 2

    client = httpx.Client(
        timeout=args.timeout,
        headers={"Accept": "application/json", "User-Agent": "all-feeds-cli/2.0"},
    )
    socket.setdefaulttimeout(args.timeout)
    understat_client = UnderstatClient()

    match_value = args.match.strip()
    match_is_numeric = match_value.isdigit()
    numeric_match_id = int(match_value) if match_is_numeric else None

    sofa_seed = args.sofascore or (None if match_is_numeric else args.match)
    sofa_event_id = sofascore.parse_event_id(sofa_seed) if sofa_seed else None
    sofa_candidates = None

    espn_event_id = espn.parse_event_id(args.espn) if args.espn else None
    espn_candidates = None
    espn_league_in_use = args.espn_league or DEFAULT_ESPN_LEAGUE
    understat_league_in_use = args.understat_league or DEFAULT_UNDERSTAT_LEAGUE

    ecuabet_event_id = None
    if args.ecuabet:
        try:
            ecuabet_event_id = ecuabet.parse_event_id(args.ecuabet)
        except ValueError as exc:
            if args.require_ecuabet:
                print(f"error: {exc}", file=sys.stderr)
                return 2
    else:
        try:
            ecuabet_event_id = ecuabet.parse_event_id(args.match)
        except ValueError:
            ecuabet_event_id = None

    if args.require_ecuabet and ecuabet_event_id is None:
        print(
            "error: could not resolve ecuabet event id; pass --ecuabet https://ecuabet.com/deportes/partido/<id>",
            file=sys.stderr,
        )
        return 2

    ecuabet_client: ecuabet.EcuabetMatchClient | None = None
    if ecuabet_event_id is not None:
        ecu_cfg = ecuabet.FetchConfig(
            base_url=args.ecuabet_base_url.rstrip("/"),
            integration=args.ecuabet_integration,
            country_code=args.ecuabet_country_code,
            culture=args.ecuabet_culture,
            timezone_offset=args.ecuabet_timezone_offset,
            device_type=args.ecuabet_device_type,
            num_format=args.ecuabet_num_format,
            show_non_boosts=args.ecuabet_show_non_boosts,
        )
        ecuabet_client = ecuabet.EcuabetMatchClient(
            config=ecu_cfg, timeout=args.timeout
        )
        ecu_request_params = {
            "base_url": ecu_cfg.base_url,
            "integration": ecu_cfg.integration,
            "countryCode": ecu_cfg.country_code,
            "culture": ecu_cfg.culture,
            "timezoneOffset": ecu_cfg.timezone_offset,
            "deviceType": ecu_cfg.device_type,
            "numFormat": ecu_cfg.num_format,
            "showNonBoosts": ecu_cfg.show_non_boosts,
        }
    else:
        ecu_request_params = {}

    try:
        preloaded_ecuabet_details: dict[str, Any] | None = None
        seed_home_name: str | None = None
        seed_away_name: str | None = None
        seed_match_date: str | None = None
        if ecuabet_client and ecuabet_event_id is not None:
            try:
                preloaded_ecuabet_details = ecuabet_client.fetch_details(
                    ecuabet_event_id
                )
                seed_home_name, seed_away_name = team_names_from_ecuabet_details(
                    preloaded_ecuabet_details
                )
                seed_match_date = date_yyyymmdd_from_iso(
                    preloaded_ecuabet_details.get("startDate")
                )
                inferred_understat, inferred_espn = infer_league_hints(
                    sofa_event=None, ecuabet_details=preloaded_ecuabet_details
                )
                if args.understat_league is None and inferred_understat:
                    understat_league_in_use = inferred_understat
                if args.espn_league is None and inferred_espn:
                    espn_league_in_use = inferred_espn
            except httpx.HTTPError:
                preloaded_ecuabet_details = None

        if sofa_event_id is None:
            sofa_query = args.match if not match_is_numeric else None
            if not sofa_query and seed_home_name and seed_away_name:
                sofa_query = f"{seed_home_name} {seed_away_name}"
            if sofa_query:
                sofa_event_id, sofa_candidates = sofascore.resolve_event_id(
                    client, sofa_query
                )
            elif numeric_match_id is not None:
                sofa_event_id = numeric_match_id

        if sofa_event_id is None:
            print(
                (
                    "error: could not resolve SofaScore event. "
                    "Pass --sofascore <id/url/query>."
                ),
                file=sys.stderr,
            )
            return 2

        watch_mode = args.watch > 0
        iteration = 0
        recommendation_cfg = recommendations.RecommendationConfig(
            top_n=args.recommend_top,
            min_odds=args.recommend_min_odds,
            max_odds=args.recommend_max_odds,
            min_confidence=args.recommend_min_confidence,
            stale_threshold_seconds=args.stale_threshold_seconds,
            history_limit=args.line_history_limit,
            include_high_risk=args.recommend_include_high_risk,
        )
        line_history: dict[str, list[dict[str, object]]] = {}
        last_success_feed_epoch: dict[str, float] = {}

        while True:
            iteration += 1
            feed_errors: dict[str, str] = {}

            sofa_snapshot = None
            espn_snapshot = None
            weather_snapshot = None
            understat_snapshot = None
            ecuabet_snapshot = None

            event = {}
            home_name = seed_home_name
            away_name = seed_away_name

            try:
                sofa_event_payload = sofascore.safe_get_json(
                    client, f"{sofascore.BASE_URL}/event/{sofa_event_id}"
                )
                if not sofa_event_payload:
                    msg = f"SofaScore event {sofa_event_id} not found"
                    raise ValueError(msg)  # noqa: TRY301

                sofa_incidents = sofascore.safe_get_json(
                    client, f"{sofascore.BASE_URL}/event/{sofa_event_id}/incidents"
                )
                sofa_statistics = sofascore.safe_get_json(
                    client, f"{sofascore.BASE_URL}/event/{sofa_event_id}/statistics"
                )
                sofa_lineups = sofascore.safe_get_json(
                    client, f"{sofascore.BASE_URL}/event/{sofa_event_id}/lineups"
                )
                sofa_odds = sofascore.safe_get_json(
                    client, f"{sofascore.BASE_URL}/event/{sofa_event_id}/odds/1/all"
                )

                sofa_snapshot = sofascore.build_snapshot(
                    event_id=sofa_event_id,
                    event_payload=sofa_event_payload,
                    incidents_payload=sofa_incidents,
                    statistics_payload=sofa_statistics,
                    lineups_payload=sofa_lineups,
                    odds_payload=sofa_odds,
                    include_raw=not args.no_raw,
                    resolved_candidates=sofa_candidates,
                )

                event = sofa_event_payload.get("event") or {}
                home_name = (event.get("homeTeam") or {}).get("name")
                away_name = (event.get("awayTeam") or {}).get("name")
                inferred_understat, inferred_espn = infer_league_hints(
                    sofa_event=event, ecuabet_details=preloaded_ecuabet_details
                )
                if args.understat_league is None and inferred_understat:
                    understat_league_in_use = inferred_understat
                if args.espn_league is None and inferred_espn:
                    espn_league_in_use = inferred_espn
            except Exception as exc:
                feed_errors["sofascore"] = str(exc)
                if args.fail_fast:
                    raise

            try:
                if home_name and away_name and espn_event_id is None:
                    query = args.espn or f"{home_name} {away_name}"
                    auto_date = (
                        date_yyyymmdd_from_timestamp(event.get("startTimestamp"))
                        or seed_match_date
                    )
                    espn_event_id, espn_candidates = espn.resolve_event_by_query(
                        client=client,
                        query=query,
                        sport=args.espn_sport,
                        league=espn_league_in_use,
                        date=auto_date,
                    )

                if espn_event_id is not None:
                    espn_summary = espn.safe_get_json(
                        client,
                        f"{espn.BASE_URL}/{args.espn_sport}/{espn_league_in_use}/summary",
                        params={"event": espn_event_id},
                    )
                    if not espn_summary:
                        msg = f"ESPN event {espn_event_id} not found"
                        raise ValueError(msg)  # noqa: TRY301

                    espn_snapshot = espn.build_snapshot(
                        event_id=espn_event_id,
                        summary=espn_summary,
                        include_raw=not args.no_raw,
                        sport=args.espn_sport,
                        league=espn_league_in_use,
                        resolved_candidates=espn_candidates,
                    )
            except Exception as exc:
                feed_errors["espn"] = str(exc)
                if args.fail_fast:
                    raise

            try:
                if ecuabet_client and ecuabet_event_id is not None:
                    if preloaded_ecuabet_details is not None and iteration == 1:
                        ecu_details = preloaded_ecuabet_details
                    else:
                        ecu_details = ecuabet_client.fetch_details(ecuabet_event_id)
                    ecu_tracker = ecuabet_client.fetch_tracker(ecuabet_event_id)
                    ecuabet_snapshot = ecuabet.build_snapshot(
                        event_id=ecuabet_event_id,
                        details=ecu_details,
                        tracker=ecu_tracker,
                        request_params=ecu_request_params,
                        include_raw=not args.no_raw,
                        odds_floor=args.odds_floor,
                        odds_ceiling=args.odds_ceiling,
                    )
                    if not home_name or not away_name:
                        ecu_home, ecu_away = team_names_from_ecuabet_details(
                            ecu_details
                        )
                        home_name = home_name or ecu_home
                        away_name = away_name or ecu_away
                elif args.require_ecuabet:
                    msg = "Ecuabet event id unresolved"
                    raise ValueError(msg)  # noqa: TRY301
            except Exception as exc:
                feed_errors["ecuabet"] = str(exc)
                if args.fail_fast:
                    raise

            try:
                if args.weather_location:
                    resolved_location = open_meteo.resolve_location(
                        client=client,
                        location=args.weather_location,
                        latitude=None,
                        longitude=None,
                        country_code=args.weather_country_code,
                    )
                else:
                    venue_coords = (event.get("venue") or {}).get(
                        "venueCoordinates"
                    ) or {}
                    lat = venue_coords.get("latitude")
                    lon = venue_coords.get("longitude")
                    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                        resolved_location = {
                            "name": ((event.get("venue") or {}).get("name")),
                            "latitude": lat,
                            "longitude": lon,
                            "country": (
                                ((event.get("venue") or {}).get("country") or {}).get(
                                    "name"
                                )
                            ),
                            "timezone": None,
                            "source": "sofascore-venue",
                        }
                    else:
                        city_name = ((event.get("venue") or {}).get("city") or {}).get(
                            "name"
                        )
                        if not city_name:
                            msg = (
                                "Could not resolve weather location from "
                                "SofaScore venue."
                            )
                            raise ValueError(msg)  # noqa: TRY301
                        resolved_location = open_meteo.resolve_location(
                            client=client,
                            location=city_name,
                            latitude=None,
                            longitude=None,
                            country_code=args.weather_country_code,
                        )

                weather_response = client.get(
                    open_meteo.FORECAST_URL,
                    params={
                        "latitude": resolved_location["latitude"],
                        "longitude": resolved_location["longitude"],
                        "current": ",".join(open_meteo.DEFAULT_CURRENT_FIELDS),
                        "hourly": ",".join(open_meteo.DEFAULT_HOURLY_FIELDS),
                        "daily": ",".join(open_meteo.DEFAULT_DAILY_FIELDS),
                        "timezone": "auto",
                        "forecast_days": 3,
                        "past_days": 0,
                    },
                )
                weather_response.raise_for_status()
                weather_payload = weather_response.json()

                at_time_local = None
                start_ts = (
                    event.get("startTimestamp") if isinstance(event, dict) else None
                )
                tz_name = weather_payload.get("timezone")
                if (
                    isinstance(start_ts, (int, float))
                    and isinstance(tz_name, str)
                    and tz_name
                ):
                    try:
                        dt_utc = datetime.fromtimestamp(start_ts, tz=timezone.utc)
                        at_time_local = dt_utc.astimezone(ZoneInfo(tz_name)).replace(
                            tzinfo=None
                        )
                    except (ValueError, ZoneInfo.NotFoundError):
                        at_time_local = None

                weather_snapshot = open_meteo.build_snapshot(
                    payload=weather_payload,
                    resolved=resolved_location,
                    at_time=at_time_local,
                    include_raw=not args.no_raw,
                    hourly_limit=12,
                )
            except Exception as exc:
                feed_errors["openMeteo"] = str(exc)
                if args.fail_fast:
                    raise

            try:
                if understat_league_in_use is None:
                    understat_snapshot = None
                elif home_name and away_name:
                    u_league = understat.canonical_league(understat_league_in_use)
                    league_ep = understat_client.league(u_league)
                    league_matches = league_ep.get_match_data(
                        season=args.understat_season
                    )
                    league_teams = league_ep.get_team_data(season=args.understat_season)

                    u_home = understat.find_team_title(league_teams, home_name)
                    u_away = understat.find_team_title(league_teams, away_name)

                    team_snaps = [
                        understat.build_team_snapshot(
                            client=understat_client,
                            team_title=u_home,
                            season=args.understat_season,
                            top_players=args.top_players,
                            include_raw=not args.no_raw,
                        ),
                        understat.build_team_snapshot(
                            client=understat_client,
                            team_title=u_away,
                            season=args.understat_season,
                            top_players=args.top_players,
                            include_raw=not args.no_raw,
                        ),
                    ]

                    understat_snapshot = understat.build_snapshot(
                        league=u_league,
                        season=args.understat_season,
                        home_team=u_home,
                        away_team=u_away,
                        league_match_data=league_matches,
                        league_team_data=league_teams,
                        teams=team_snaps,
                        include_raw=not args.no_raw,
                    )
                else:
                    msg = "team names unavailable for Understat resolution"
                    raise ValueError(msg)  # noqa: TRY301
            except Exception as exc:
                feed_errors["understat"] = str(exc)
                if args.fail_fast:
                    raise

            decision_summary = derive_decision_summary(
                sofa=sofa_snapshot,
                espn_snap=espn_snapshot,
                weather=weather_snapshot,
                understat_snap=understat_snapshot,
                ecuabet_snap=ecuabet_snapshot,
            )

            snapshot = {
                "fetchedAtUtc": utc_now_iso(),
                "source": "all-feeds",
                "inputs": {
                    "match": args.match,
                    "sofascore": args.sofascore,
                    "ecuabet": args.ecuabet,
                    "espn": args.espn,
                    "espnLeague": espn_league_in_use,
                    "weatherLocation": args.weather_location,
                    "understatLeague": understat_league_in_use,
                    "understatSeason": args.understat_season,
                    "oddsFloor": args.odds_floor,
                    "oddsCeiling": args.odds_ceiling,
                    "recommendTop": args.recommend_top,
                    "recommendMinOdds": args.recommend_min_odds,
                    "recommendMaxOdds": args.recommend_max_odds,
                    "recommendMinConfidence": args.recommend_min_confidence,
                    "recommendIncludeHighRisk": args.recommend_include_high_risk,
                    "staleThresholdSeconds": args.stale_threshold_seconds,
                },
                "ids": {
                    "sofascoreEventId": sofa_event_id,
                    "ecuabetEventId": ecuabet_event_id,
                    "espnEventId": espn_event_id,
                },
                "match": {
                    "home": home_name,
                    "away": away_name,
                },
                "feedErrors": feed_errors,
                "decisionSummary": decision_summary,
                "feeds": {
                    "ecuabet": ecuabet_snapshot,
                    "sofascore": sofa_snapshot,
                    "espn": espn_snapshot,
                    "openMeteo": weather_snapshot,
                    "understat": understat_snapshot,
                },
            }
            recommendation_pack, line_history, last_success_feed_epoch = (
                recommendations.build_recommendations(
                    snapshot,
                    config=recommendation_cfg,
                    line_history=line_history,
                    last_success_epoch=last_success_feed_epoch,
                )
            )
            snapshot["recommendations"] = recommendation_pack
            shortlist = recommendation_pack.get("shortlist")
            top_pick = (
                shortlist[0] if isinstance(shortlist, list) and shortlist else None
            )
            snapshot["oneShot"] = {
                "generatedAtUtc": recommendation_pack.get("generatedAtUtc"),
                "globalConfidence": recommendation_pack.get("globalConfidence"),
                "statusBoard": decision_summary.get("statusBoard"),
                "scoreConsensus": decision_summary.get("scoreConsensus"),
                "signalBundle": recommendation_pack.get("signalBundle"),
                "feedHealth": recommendation_pack.get("feedHealth"),
                "topRecommendation": top_pick,
                "shortlist": shortlist if isinstance(shortlist, list) else [],
            }

            path: Path | None = None
            if args.output:
                path = write_snapshot(
                    snapshot, args.output, iteration, watch_mode=watch_mode
                )
            if path is not None:
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
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
        if ecuabet_client is not None:
            ecuabet_client.close()


if __name__ == "__main__":
    raise SystemExit(main())
