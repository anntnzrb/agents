#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "understatapi>=0.6.1,<1.0",
# ]
# ///
"""CLI client for Understat league and team modeling signals."""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import time
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from understatapi import UnderstatClient

__all__: list[str] = []
MID_YEAR_MONTH = 7
ASCII_UPPER_BOUND = 128
FUZZY_TEAM_MATCH_MIN_RATIO = 0.6

LEAGUE_ALIASES = {
    "epl": "EPL",
    "england": "EPL",
    "la_liga": "La_Liga",
    "laliga": "La_Liga",
    "la liga": "La_Liga",
    "bundesliga": "Bundesliga",
    "serie_a": "Serie_A",
    "serie a": "Serie_A",
    "ligue_1": "Ligue_1",
    "ligue 1": "Ligue_1",
    "rfpl": "RFPL",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_season() -> str:
    now = datetime.now(timezone.utc)
    return str(now.year - 1 if now.month < MID_YEAR_MONTH else now.year)


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(ch for ch in text if ord(ch) < ASCII_UPPER_BOUND)
    return re.sub(r"\s+", " ", ascii_text).strip().lower()


def to_understat_team_slug(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    ascii_text = "".join(ch for ch in text if ord(ch) < ASCII_UPPER_BOUND)
    return re.sub(r"[^A-Za-z0-9]+", "_", ascii_text).strip("_")


def canonical_league(name: str) -> str:
    raw = name.strip()
    if raw in ("EPL", "La_Liga", "Bundesliga", "Serie_A", "Ligue_1", "RFPL"):
        return raw
    key = normalize_text(raw)
    if key in LEAGUE_ALIASES:
        return LEAGUE_ALIASES[key]
    msg = (
        "Invalid league. Use one of: EPL, La_Liga, Bundesliga, Serie_A, Ligue_1, RFPL."
    )
    raise ValueError(msg)


def find_team_title(league_team_data: dict[str, Any], requested: str) -> str:
    requested_n = normalize_text(requested)
    titles = [v.get("title") for v in league_team_data.values() if isinstance(v, dict)]
    titles = [t for t in titles if isinstance(t, str)]

    exact = [t for t in titles if normalize_text(t) == requested_n]
    if exact:
        return exact[0]

    contains = [t for t in titles if requested_n in normalize_text(t)]
    if contains:
        return contains[0]

    slug_match = [
        t
        for t in titles
        if normalize_text(to_understat_team_slug(t).replace("_", " ")) == requested_n
    ]
    if slug_match:
        return slug_match[0]

    best_title = ""
    best_ratio = 0.0
    for title in titles:
        ratio = SequenceMatcher(None, requested_n, normalize_text(title)).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_title = title
    if best_ratio >= FUZZY_TEAM_MATCH_MIN_RATIO:
        return best_title

    msg = f"Could not match team '{requested}' in selected league/season."
    raise ValueError(msg)


def extract_match_view(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": match.get("id"),
        "datetime": match.get("datetime"),
        "home": (match.get("h") or {}).get("title"),
        "away": (match.get("a") or {}).get("title"),
        "goals": match.get("goals"),
        "xG": match.get("xG"),
        "forecast": match.get("forecast"),
        "isResult": match.get("isResult"),
    }


def as_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def filter_head_to_head(
    matches: list[dict[str, Any]], home: str, away: str
) -> list[dict[str, Any]]:
    h = normalize_text(home)
    a = normalize_text(away)
    out = []
    for row in matches:
        home_title = normalize_text((row.get("h") or {}).get("title") or "")
        away_title = normalize_text((row.get("a") or {}).get("title") or "")
        if (home_title == h and away_title == a) or (
            home_title == a and away_title == h
        ):
            out.append(row)
    out.sort(key=lambda x: x.get("datetime") or "", reverse=True)
    return out


def team_form_summary(
    team_matches: list[dict[str, Any]], team_title: str
) -> dict[str, Any]:
    finished = [m for m in team_matches if m.get("isResult")]
    recent = sorted(finished, key=lambda x: x.get("datetime") or "", reverse=True)[:5]
    n_team = normalize_text(team_title)

    gf = 0
    ga = 0
    xgf = 0.0
    xga = 0.0
    wins = 0
    draws = 0
    losses = 0

    for match in recent:
        home = match.get("h") or {}
        match.get("a") or {}
        goals = match.get("goals") or {}
        xg = match.get("xG") or {}

        is_home = normalize_text(home.get("title") or "") == n_team
        team_goals = as_int(goals.get("h" if is_home else "a"), 0)
        opp_goals = as_int(goals.get("a" if is_home else "h"), 0)
        team_xg = as_float(xg.get("h" if is_home else "a"), 0.0)
        opp_xg = as_float(xg.get("a" if is_home else "h"), 0.0)

        gf += team_goals
        ga += opp_goals
        xgf += team_xg
        xga += opp_xg

        if team_goals > opp_goals:
            wins += 1
        elif team_goals == opp_goals:
            draws += 1
        else:
            losses += 1

    return {
        "sampleSize": len(recent),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goalsFor": gf,
        "goalsAgainst": ga,
        "xGFor": round(xgf, 3),
        "xGAgainst": round(xga, 3),
    }


def team_season_totals(
    team_matches: list[dict[str, Any]], team_title: str
) -> dict[str, Any]:
    finished = [m for m in team_matches if m.get("isResult")]
    n_team = normalize_text(team_title)

    played = 0
    wins = 0
    draws = 0
    losses = 0
    gf = 0
    ga = 0
    xgf = 0.0
    xga = 0.0
    xpts = 0.0

    for match in finished:
        home = match.get("h") or {}
        match.get("a") or {}
        goals = match.get("goals") or {}
        xg = match.get("xG") or {}
        forecast = match.get("forecast") or {}

        is_home = normalize_text(home.get("title") or "") == n_team
        team_goals = as_int(goals.get("h" if is_home else "a"), 0)
        opp_goals = as_int(goals.get("a" if is_home else "h"), 0)
        team_xg = as_float(xg.get("h" if is_home else "a"), 0.0)
        opp_xg = as_float(xg.get("a" if is_home else "h"), 0.0)

        # Understat forecast: w/d/l probability from home perspective.
        if is_home:
            team_xpts = (
                as_float(forecast.get("w"), 0.0) * 3
                + as_float(forecast.get("d"), 0.0) * 1
                + as_float(forecast.get("l"), 0.0) * 0
            )
        else:
            team_xpts = (
                as_float(forecast.get("l"), 0.0) * 3
                + as_float(forecast.get("d"), 0.0) * 1
                + as_float(forecast.get("w"), 0.0) * 0
            )

        played += 1
        gf += team_goals
        ga += opp_goals
        xgf += team_xg
        xga += opp_xg
        xpts += team_xpts

        if team_goals > opp_goals:
            wins += 1
        elif team_goals == opp_goals:
            draws += 1
        else:
            losses += 1

    points = wins * 3 + draws
    return {
        "played": played,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "points": points,
        "goalsFor": gf,
        "goalsAgainst": ga,
        "goalDifference": gf - ga,
        "xGFor": round(xgf, 3),
        "xGAgainst": round(xga, 3),
        "xGDiff": round(xgf - xga, 3),
        "xPointsApprox": round(xpts, 3),
        "ppg": round(points / played, 3) if played else None,
    }


def league_table_signals(league_team_data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in league_team_data.values():
        if not isinstance(row, dict):
            continue
        title = row.get("title")
        history = row.get("history") or []
        if not isinstance(title, str):
            continue

        played = 0
        points = 0
        wins = 0
        draws = 0
        losses = 0
        gf = 0
        ga = 0
        xpts = 0.0
        xg = 0.0
        xga = 0.0

        for item in history:
            if not isinstance(item, dict):
                continue
            played += 1
            points += as_int(item.get("pts"), 0)
            wins += as_int(item.get("wins"), 0)
            draws += as_int(item.get("draws"), 0)
            losses += as_int(item.get("loses"), 0)
            gf += as_int(item.get("scored"), 0)
            ga += as_int(item.get("missed"), 0)
            xpts += as_float(item.get("xpts"), 0.0)
            xg += as_float(item.get("xG"), 0.0)
            xga += as_float(item.get("xGA"), 0.0)

        rows.append(
            {
                "team": title,
                "played": played,
                "points": points,
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "goalsFor": gf,
                "goalsAgainst": ga,
                "goalDifference": gf - ga,
                "xPointsApprox": round(xpts, 3),
                "xGFor": round(xg, 3),
                "xGAgainst": round(xga, 3),
                "xGDiff": round(xg - xga, 3),
            }
        )

    rows.sort(
        key=lambda x: (x["points"], x["goalDifference"], x["goalsFor"]), reverse=True
    )
    for idx, row in enumerate(rows, start=1):
        row["positionByPoints"] = idx
    return rows


def build_team_snapshot(
    client: UnderstatClient,
    team_title: str,
    season: str,
    top_players: int,
    *,
    include_raw: bool,
) -> dict[str, Any]:
    slug = to_understat_team_slug(team_title)
    endpoint = client.team(slug)

    match_data = endpoint.get_match_data(season=season)
    player_data = endpoint.get_player_data(season=season)
    context_data = endpoint.get_context_data(season=season)

    players_sorted = sorted(
        player_data, key=lambda x: float(x.get("xG", 0.0)), reverse=True
    )

    top = [
        {
            "player": row.get("player_name"),
            "position": row.get("position"),
            "games": row.get("games"),
            "minutes": row.get("time"),
            "goals": row.get("goals"),
            "assists": row.get("assists"),
            "xG": row.get("xG"),
            "xA": row.get("xA"),
            "shots": row.get("shots"),
            "keyPasses": row.get("key_passes"),
        }
        for row in players_sorted[: max(0, top_players)]
    ]

    team_snapshot: dict[str, Any] = {
        "title": team_title,
        "slug": slug,
        "season": season,
        "matchCount": len(match_data),
        "seasonTotals": team_season_totals(match_data, team_title),
        "form": team_form_summary(match_data, team_title),
        "recentMatches": [
            extract_match_view(x)
            for x in sorted(
                match_data, key=lambda m: m.get("datetime") or "", reverse=True
            )[:10]
        ],
        "topPlayersByXG": top,
        "context": context_data,
    }

    if include_raw:
        team_snapshot["raw"] = {
            "matchData": match_data,
            "playerData": player_data,
            "contextData": context_data,
        }

    return team_snapshot


def build_snapshot(  # noqa: PLR0913
    league: str,
    season: str,
    home_team: str | None,
    away_team: str | None,
    league_match_data: list[dict[str, Any]],
    league_team_data: dict[str, Any],
    teams: list[dict[str, Any]],
    *,
    include_raw: bool,
) -> dict[str, Any]:
    h2h = []
    if home_team and away_team:
        h2h = [
            extract_match_view(x)
            for x in filter_head_to_head(league_match_data, home_team, away_team)[:20]
        ]

    snapshot: dict[str, Any] = {
        "fetchedAtUtc": utc_now_iso(),
        "source": {
            "provider": "understatapi",
        },
        "request": {
            "league": league,
            "season": season,
            "homeTeam": home_team,
            "awayTeam": away_team,
        },
        "coverage": {
            "leagueMatchCount": len(league_match_data),
            "leagueTeamCount": len(league_team_data),
            "teamSnapshots": len(teams),
            "headToHeadCount": len(h2h),
        },
        "headToHead": h2h,
        "leagueTableSignals": league_table_signals(league_team_data),
        "teams": teams,
    }

    if include_raw:
        snapshot["raw"] = {
            "leagueMatchData": league_match_data,
            "leagueTeamData": league_team_data,
        }

    return snapshot


def write_snapshot(
    snapshot: dict[str, Any], output: Path, iteration: int, *, watch_mode: bool
) -> Path:
    output = output.expanduser()
    if watch_mode:
        output.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = output / f"understat_{ts}_{iteration:04d}.json"
    else:
        target = output
        target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Understat league/team data for match modeling."
    )
    parser.add_argument("--league", default="La_Liga")
    parser.add_argument("--season", default=default_season())
    parser.add_argument("--home-team")
    parser.add_argument("--away-team")
    parser.add_argument(
        "--team",
        action="append",
        default=[],
        help="Add team to fetch (repeatable).",
    )
    parser.add_argument("--top-players", type=int, default=10)
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Network timeout (seconds) for Understat requests.",
    )
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

    try:
        league = canonical_league(args.league)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    socket.setdefaulttimeout(args.timeout)
    client = UnderstatClient()

    try:
        league_endpoint = client.league(league)
        league_match_data = league_endpoint.get_match_data(season=args.season)
        league_team_data = league_endpoint.get_team_data(season=args.season)

        requested_teams = list(args.team)
        if args.home_team:
            requested_teams.append(args.home_team)
        if args.away_team:
            requested_teams.append(args.away_team)

        if not requested_teams:
            print(
                "error: pass at least one of --team, --home-team, --away-team",
                file=sys.stderr,
            )
            return 2

        resolved_titles: list[str] = []
        for team_name in requested_teams:
            title = find_team_title(league_team_data, team_name)
            if title not in resolved_titles:
                resolved_titles.append(title)

        watch_mode = args.watch > 0
        iteration = 0

        while True:
            iteration += 1
            team_snapshots = [
                build_team_snapshot(
                    client=client,
                    team_title=title,
                    season=args.season,
                    top_players=args.top_players,
                    include_raw=not args.no_raw,
                )
                for title in resolved_titles
            ]

            home_title = (
                find_team_title(league_team_data, args.home_team)
                if args.home_team
                else None
            )
            away_title = (
                find_team_title(league_team_data, args.away_team)
                if args.away_team
                else None
            )

            snapshot = build_snapshot(
                league=league,
                season=args.season,
                home_team=home_title,
                away_team=away_title,
                league_match_data=league_match_data,
                league_team_data=league_team_data,
                teams=team_snapshots,
                include_raw=not args.no_raw,
            )

            if args.output:
                path = write_snapshot(
                    snapshot, args.output, iteration, watch_mode=watch_mode
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
    except Exception as exc:  # noqa: BLE001
        print(f"error: understat request failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
