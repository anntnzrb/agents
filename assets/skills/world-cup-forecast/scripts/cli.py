#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""AI-facing JSON-only live World Cup forecast CLI."""

#
# ruff: noqa: D101,D103
from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NotRequired, TypedDict

VERSION = "1"
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_SCORE = 5
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates={date}&limit=100"
ESPN_STANDINGS = "https://site.web.api.espn.com/apis/v2/sports/soccer/fifa.world/standings?region=us&lang=en&contentorigin=espn"
ESPN_PLAYER_STATS = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/statistics"
)
HTML_SCRIPT_RE = re.compile(
    r"<(script|style)[^>]*>.*?</\\1>",
    re.IGNORECASE | re.DOTALL,
)
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
TEAM_KEY_RE = re.compile(r"[^a-z0-9]+")
XG_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<label>xg|xga)\b|\b(?P<label2>xg|xga)\s*(?P<num2>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
SCORE_DASH = r"[-\u2013]"
SCORE_RE = re.compile(rf"\b([0-5])\s*{SCORE_DASH}\s*([0-5])\b")
SNIPPET_RE = re.compile(
    rf"\b(xg|xga|injur\w*|doubt\w*|missing|prediction|predicts?|\d\s*{SCORE_DASH}\s*\d)\b",
    re.IGNORECASE,
)
TEAM_COUNT = 2
SNIPPET_LIMIT = 5
SCORE_PART_COUNT = 2

JsonObject = dict[str, object]


class Freshness(TypedDict):
    source: str
    url: str
    fetched_at_utc: str
    ok: bool
    status: int | None
    content_type: str | None
    elapsed_ms: int
    error: NotRequired[str]


@dataclass(frozen=True, slots=True)
class FetchResult:
    source: str
    url: str
    text: str | None
    json_payload: object | None
    freshness: Freshness


@dataclass(frozen=True, slots=True)
class TeamForm:
    team: str
    abbreviation: str
    points: int
    played: int
    goals_for: int
    goals_against: int
    goal_difference: int
    form_score: float


@dataclass(frozen=True, slots=True)
class PlayerSignal:
    team: str
    abbreviation: str
    listed_goal_assists: float
    best_goal_assists_per_appearance: float
    contributor_count: int
    top_contributors: list[dict[str, object]]
    attack_score: float


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    date_utc: str
    status: str
    team_a: str
    team_b: str
    score_a: int | None
    score_b: int | None
    abbreviation_a: str
    abbreviation_b: str


@dataclass(frozen=True, slots=True)
class TextSignal:
    available: bool
    source_count: int
    snippets: list[str]
    metrics: dict[str, list[float]]
    predicted_scores: list[str]
    reason: str | None = None


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def emit(payload: JsonObject) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    sys.stdout.write("\n")


def compact_error(code: str, message: str) -> JsonObject:
    return {"code": code, "message": message}


def normalize_team(value: str) -> str:
    return TEAM_KEY_RE.sub("", value.casefold())


def as_mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def text_value(value: object) -> str:
    return value if isinstance(value, str) else ""


def int_value(value: object, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.replace("+", "").strip()
        if stripped.lstrip("-").isdigit():
            return int(stripped)
    return default


def float_value(value: object, default: float = 0.0) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def fetch(source: str, url: str, *, expect_json: bool) -> FetchResult:
    started = time.monotonic()
    fetched_at = utc_now()
    status: int | None = None
    content_type: str | None = None
    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.scheme not in {"http", "https"}:
        freshness: Freshness = {
            "source": source,
            "url": url,
            "fetched_at_utc": fetched_at,
            "ok": False,
            "status": None,
            "content_type": None,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "error": f"unsupported_url_scheme:{parsed_url.scheme or '<empty>'}",
        }
        return FetchResult(source, url, None, None, freshness)
    try:
        request = urllib.request.Request(  # noqa: S310
            url,
            headers={
                "User-Agent": "Mozilla/5.0 world-cup-forecast/1",
                "Accept": "application/json,text/html,text/plain,*/*",
            },
        )
        with urllib.request.urlopen(  # noqa: S310
            request,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        ) as response:
            status = response.status
            content_type = response.headers.get("content-type")
            raw = response.read().decode("utf-8", errors="replace")
        payload: object | None = json.loads(raw) if expect_json else None
        freshness: Freshness = {
            "source": source,
            "url": url,
            "fetched_at_utc": fetched_at,
            "ok": True,
            "status": status,
            "content_type": content_type,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
        return FetchResult(source, url, raw, payload, freshness)
    except urllib.error.HTTPError as exc:
        status = exc.code
        content_type = (
            exc.headers.get("content-type") if exc.headers is not None else None
        )
        error = f"http_error:{exc.code}"
    except urllib.error.URLError as exc:
        error = f"url_error:{exc.reason}"
    except TimeoutError:
        error = "timeout"
    except json.JSONDecodeError as exc:
        error = f"json_decode_error:{exc.msg}"
    except OSError as exc:
        error = f"os_error:{exc}"
    freshness = {
        "source": source,
        "url": url,
        "fetched_at_utc": fetched_at,
        "ok": False,
        "status": status,
        "content_type": content_type,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "error": error,
    }
    return FetchResult(source, url, None, None, freshness)


def stat_map(entry: dict[str, object]) -> dict[str, object]:
    stats: dict[str, object] = {}
    for stat in as_list(entry.get("stats")):
        item = as_mapping(stat)
        name = text_value(item.get("name"))
        if name:
            stats[name] = item.get("displayValue", item.get("value"))
    return stats


def parse_team_forms(payload: object) -> dict[str, TeamForm]:
    root = as_mapping(payload)
    forms: dict[str, TeamForm] = {}
    for child in as_list(root.get("children")):
        standings = as_mapping(as_mapping(child).get("standings"))
        for entry_raw in as_list(standings.get("entries")):
            entry = as_mapping(entry_raw)
            team = as_mapping(entry.get("team"))
            stats = stat_map(entry)
            abbreviation = text_value(team.get("abbreviation"))
            name = text_value(team.get("displayName"))
            if not abbreviation or not name:
                continue
            points = int_value(stats.get("points"))
            played = int_value(stats.get("gamesPlayed"), 3)
            goals_for = int_value(stats.get("pointsFor"))
            goals_against = int_value(stats.get("pointsAgainst"))
            goal_difference = int_value(stats.get("pointDifferential"))
            forms[abbreviation] = TeamForm(
                team=name,
                abbreviation=abbreviation,
                points=points,
                played=played,
                goals_for=goals_for,
                goals_against=goals_against,
                goal_difference=goal_difference,
                form_score=(10 * points)
                + (2 * goal_difference)
                + goals_for
                - (0.5 * goals_against),
            )
    return forms


def athlete_numbers(athlete: dict[str, object]) -> tuple[float, float, float]:
    goals = 0.0
    assists = 0.0
    appearances = 0.0
    for stat_raw in as_list(athlete.get("statistics")):
        stat = as_mapping(stat_raw)
        name = text_value(stat.get("name"))
        value = float_value(stat.get("value"))
        if name == "totalGoals":
            goals = max(goals, value)
        elif name == "goalAssists":
            assists = max(assists, value)
        elif name == "appearances":
            appearances = max(appearances, value)
    return goals, assists, appearances


def parse_player_signals(
    payload: object,
    forms: dict[str, TeamForm],
) -> dict[str, PlayerSignal]:
    root = as_mapping(payload)
    players: dict[str, dict[str, object]] = {}
    for category_raw in as_list(root.get("stats")):
        category = as_mapping(category_raw)
        for leader_raw in as_list(category.get("leaders")):
            leader = as_mapping(leader_raw)
            athlete = as_mapping(leader.get("athlete"))
            player_id = text_value(athlete.get("id")) or text_value(athlete.get("uid"))
            team = as_mapping(athlete.get("team"))
            abbreviation = text_value(team.get("abbreviation"))
            if not player_id or not abbreviation:
                continue
            goals, assists, appearances = athlete_numbers(athlete)
            current = players.setdefault(
                player_id,
                {
                    "name": text_value(athlete.get("displayName")),
                    "team": text_value(team.get("displayName")),
                    "abbreviation": abbreviation,
                    "goals": 0.0,
                    "assists": 0.0,
                    "appearances": 0.0,
                },
            )
            current["goals"] = max(float_value(current["goals"]), goals)
            current["assists"] = max(float_value(current["assists"]), assists)
            current["appearances"] = max(
                float_value(current["appearances"]),
                appearances,
            )
    by_team: dict[str, list[dict[str, object]]] = {}
    for player in players.values():
        by_team.setdefault(text_value(player.get("abbreviation")), []).append(player)
    signals: dict[str, PlayerSignal] = {}
    for abbreviation, form in forms.items():
        team_players = by_team.get(abbreviation, [])
        total = sum(
            float_value(p.get("goals")) + float_value(p.get("assists"))
            for p in team_players
        )
        best_rate = 0.0
        for player in team_players:
            contribution = float_value(player.get("goals")) + float_value(
                player.get("assists"),
            )
            appearances = max(1.0, float_value(player.get("appearances"), 1.0))
            best_rate = max(best_rate, contribution / appearances)
        top = sorted(
            team_players,
            key=lambda p: float_value(p.get("goals")) + float_value(p.get("assists")),
            reverse=True,
        )[:3]
        top_contributors = [
            {
                "name": text_value(p.get("name")),
                "goals": float_value(p.get("goals")),
                "assists": float_value(p.get("assists")),
                "appearances": float_value(p.get("appearances")),
            }
            for p in top
        ]
        attack_score = (
            (8 * (total / max(1, form.goals_for)))
            + (4 * best_rate)
            + (0.5 * len(team_players))
        )
        signals[abbreviation] = PlayerSignal(
            team=form.team,
            abbreviation=abbreviation,
            listed_goal_assists=total,
            best_goal_assists_per_appearance=best_rate,
            contributor_count=len(team_players),
            top_contributors=top_contributors,
            attack_score=attack_score,
        )
    return signals


def parse_matches(payload: object) -> list[MatchCandidate]:
    root = as_mapping(payload)
    matches: list[MatchCandidate] = []
    for event_raw in as_list(root.get("events")):
        event = as_mapping(event_raw)
        competitions = as_list(event.get("competitions"))
        competition = as_mapping(competitions[0]) if competitions else {}
        status = as_mapping(as_mapping(competition.get("status")).get("type"))
        competitors = [
            as_mapping(item) for item in as_list(competition.get("competitors"))
        ]
        teams = []
        for competitor in competitors:
            team = as_mapping(competitor.get("team"))
            teams.append(
                {
                    "name": text_value(team.get("displayName")),
                    "abbreviation": text_value(team.get("abbreviation")),
                    "score": int_value(competitor.get("score"), -1),
                },
            )
        if len(teams) != TEAM_COUNT or any(
            team["abbreviation"] == "RD32" for team in teams
        ):
            continue
        matches.append(
            MatchCandidate(
                date_utc=text_value(event.get("date")),
                status=text_value(status.get("description"))
                or text_value(status.get("name")),
                team_a=text_value(teams[0]["name"]),
                team_b=text_value(teams[1]["name"]),
                score_a=None
                if int_value(teams[0]["score"], -1) < 0
                else int_value(teams[0]["score"]),
                score_b=None
                if int_value(teams[1]["score"], -1) < 0
                else int_value(teams[1]["score"]),
                abbreviation_a=text_value(teams[0]["abbreviation"]),
                abbreviation_b=text_value(teams[1]["abbreviation"]),
            ),
        )
    return matches


def strip_html(text: str) -> str:
    cleaned = HTML_SCRIPT_RE.sub(" ", text)
    cleaned = HTML_TAG_RE.sub(" ", cleaned)
    return WHITESPACE_RE.sub(" ", html.unescape(cleaned)).strip()


def text_signal(results: list[FetchResult], source_name: str) -> TextSignal:  # noqa: C901
    snippets: list[str] = []
    metrics: dict[str, list[float]] = {"xg": [], "xga": []}
    scores: list[str] = []
    for result in results:
        if not result.text:
            continue
        clean = strip_html(result.text)
        for match in SNIPPET_RE.finditer(clean):
            start = max(0, match.start() - 140)
            end = min(len(clean), match.end() + 180)
            snippet = clean[start:end].strip()
            if snippet not in snippets:
                snippets.append(snippet)
            if len(snippets) >= SNIPPET_LIMIT:
                break
        for found in XG_RE.finditer(clean):
            label = (found.group("label") or found.group("label2") or "").lower()
            number = found.group("num") or found.group("num2")
            if label in metrics and number is not None:
                metrics[label].append(float(number))
        for score in SCORE_RE.finditer(clean):
            value = f"{score.group(1)}-{score.group(2)}"
            if value not in scores:
                scores.append(value)
        if len(snippets) >= SNIPPET_LIMIT:
            break
    available = bool(snippets or metrics["xg"] or metrics["xga"] or scores)
    return TextSignal(
        available=available,
        source_count=sum(1 for result in results if result.freshness["ok"]),
        snippets=snippets,
        metrics=metrics,
        predicted_scores=scores[:5],
        reason=None if available else f"no_parseable_{source_name}_context",
    )


def zscores(values: list[float]) -> list[float]:
    if not values:
        return []
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    stdev = math.sqrt(variance)
    if stdev == 0:
        return [0.0 for _ in values]
    return [(value - mean) / stdev for value in values]


def poisson_probability(lam: float, goals: int) -> float:
    return math.exp(-lam) * (lam**goals) / math.factorial(goals)


def score_grid(lambda_a: float, lambda_b: float) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for score_a in range(MAX_SCORE + 1):
        for score_b in range(MAX_SCORE + 1):
            probability = poisson_probability(lambda_a, score_a) * poisson_probability(
                lambda_b,
                score_b,
            )
            rows.append({"score": f"{score_a}-{score_b}", "probability": probability})
    total = sum(float_value(row["probability"]) for row in rows) or 1.0
    for row in rows:
        row["probability"] = round(float_value(row["probability"]) / total, 6)
    return sorted(rows, key=lambda row: float_value(row["probability"]), reverse=True)[
        :5
    ]


def form_payload(form: TeamForm) -> JsonObject:
    return {
        "team": form.team,
        "abbreviation": form.abbreviation,
        "points": form.points,
        "played": form.played,
        "goals_for": form.goals_for,
        "goals_against": form.goals_against,
        "goal_difference": form.goal_difference,
        "form_score": round(form.form_score, 3),
    }


def player_payload(signal: PlayerSignal | None) -> JsonObject:
    if signal is None:
        return {"available": False, "reason": "player_stats_unavailable"}
    return {
        "available": True,
        "team": signal.team,
        "abbreviation": signal.abbreviation,
        "listed_goal_assists": signal.listed_goal_assists,
        "best_goal_assists_per_appearance": round(
            signal.best_goal_assists_per_appearance,
            3,
        ),
        "contributor_count": signal.contributor_count,
        "top_contributors": signal.top_contributors,
        "attack_score": round(signal.attack_score, 3),
        "coverage": "espn_leaderboard_only",
    }


def text_signal_payload(signal: TextSignal) -> JsonObject:
    return {
        "available": signal.available,
        "source_count": signal.source_count,
        "snippets": signal.snippets,
        "metrics": signal.metrics,
        "predicted_scores": signal.predicted_scores,
        "reason": signal.reason,
    }


def build_forecast(  # noqa: PLR0913
    match: MatchCandidate,
    forms: dict[str, TeamForm],
    players: dict[str, PlayerSignal],
    xg_context: TextSignal,
    odds_context: TextSignal,
    all_abbreviations: list[str],
) -> JsonObject:
    form_a = forms.get(match.abbreviation_a)
    form_b = forms.get(match.abbreviation_b)
    player_a = players.get(match.abbreviation_a)
    player_b = players.get(match.abbreviation_b)
    fixture = {
        "date_utc": match.date_utc,
        "status": match.status,
        "team_a": match.team_a,
        "team_b": match.team_b,
        "abbreviation_a": match.abbreviation_a,
        "abbreviation_b": match.abbreviation_b,
        "score_a": match.score_a,
        "score_b": match.score_b,
    }
    if form_a is None or form_b is None:
        return {
            "fixture": fixture,
            "signals": {
                "team_form": {"available": False, "reason": "missing_standings_team"},
                "player_attack": {"available": bool(players)},
                "xg_context": text_signal_payload(xg_context),
                "odds": text_signal_payload(odds_context),
                "composite": {"available": False, "reason": "missing_team_form"},
            },
            "forecast": {
                "available": False,
                "kind": "unavailable",
                "reason": "missing_team_form",
            },
            "source_notes": [],
        }
    form_values = [
        forms[abbr].form_score for abbr in all_abbreviations if abbr in forms
    ]
    player_values = [
        players.get(abbr, PlayerSignal("", abbr, 0, 0, 0, [], 0)).attack_score
        for abbr in all_abbreviations
    ]
    form_z_map = dict(
        zip(
            [abbr for abbr in all_abbreviations if abbr in forms],
            zscores(form_values),
            strict=False,
        ),
    )
    player_z_map = dict(zip(all_abbreviations, zscores(player_values), strict=False))
    xg_z_a = 0.0
    xg_z_b = 0.0
    use_xg = bool(xg_context.available and xg_context.metrics.get("xg"))
    form_weight = 0.60 if use_xg else 0.75
    player_weight = 0.25
    xg_weight = 0.15 if use_xg else 0.0
    composite_a = (
        (form_weight * form_z_map.get(match.abbreviation_a, 0.0))
        + (player_weight * player_z_map.get(match.abbreviation_a, 0.0))
        + (xg_weight * xg_z_a)
    )
    composite_b = (
        (form_weight * form_z_map.get(match.abbreviation_b, 0.0))
        + (player_weight * player_z_map.get(match.abbreviation_b, 0.0))
        + (xg_weight * xg_z_b)
    )
    if (
        "final" in match.status.casefold()
        and match.score_a is not None
        and match.score_b is not None
    ):
        exact_score = f"{match.score_a}-{match.score_b}"
        kind = "result"
        scorelines: list[JsonObject] = [{"score": exact_score, "probability": 1.0}]
        winner = (
            match.team_a
            if match.score_a > match.score_b
            else match.team_b
            if match.score_b > match.score_a
            else "draw"
        )
        forecast: JsonObject = {
            "available": True,
            "kind": kind,
            "winner_90": winner,
            "exact_score": exact_score,
            "scorelines": scorelines,
        }
    else:
        player_boost_a = (
            0.0
            if player_a is None
            else min(
                0.35,
                (0.03 * player_a.listed_goal_assists)
                + (0.06 * player_a.best_goal_assists_per_appearance),
            )
        )
        player_boost_b = (
            0.0
            if player_b is None
            else min(
                0.35,
                (0.03 * player_b.listed_goal_assists)
                + (0.06 * player_b.best_goal_assists_per_appearance),
            )
        )
        delta = clamp(composite_a - composite_b, -2.0, 2.0)
        lambda_a = (
            (form_a.goals_for / max(1, form_a.played))
            + (form_b.goals_against / max(1, form_b.played))
        ) / 2
        lambda_b = (
            (form_b.goals_for / max(1, form_b.played))
            + (form_a.goals_against / max(1, form_a.played))
        ) / 2
        lambda_a += (
            (0.08 * max(0.0, delta)) - (0.04 * max(0.0, -delta)) + player_boost_a
        )
        lambda_b += (
            (0.08 * max(0.0, -delta)) - (0.04 * max(0.0, delta)) + player_boost_b
        )
        lambda_a = clamp(lambda_a * 0.92, 0.25, 3.5)
        lambda_b = clamp(lambda_b * 0.92, 0.25, 3.5)
        scorelines = score_grid(lambda_a, lambda_b)
        exact_score = text_value(scorelines[0]["score"])
        first_score = exact_score.split("-", 1)
        winner = "draw"
        if len(first_score) == SCORE_PART_COUNT:
            left = int_value(first_score[0])
            right = int_value(first_score[1])
            winner = (
                match.team_a
                if left > right
                else match.team_b
                if right > left
                else "draw"
            )
        forecast = {
            "available": True,
            "kind": "prediction",
            "winner_90": winner,
            "exact_score": exact_score,
            "expected_goals": {
                match.team_a: round(lambda_a, 3),
                match.team_b: round(lambda_b, 3),
            },
            "scorelines": scorelines,
            "model_note": (
                "transparent_recent_form_poisson_heuristic_not_high_accuracy_claim"
            ),
        }
    warnings: list[str] = []
    if (
        xg_context.predicted_scores
        and forecast.get("exact_score") not in xg_context.predicted_scores
    ):
        warnings.append("source_prediction_disagreement")
    return {
        "fixture": fixture,
        "signals": {
            "team_form": {
                match.team_a: form_payload(form_a),
                match.team_b: form_payload(form_b),
            },
            "player_attack": {
                match.team_a: player_payload(player_a),
                match.team_b: player_payload(player_b),
            },
            "xg_context": text_signal_payload(xg_context),
            "odds": text_signal_payload(odds_context),
            "composite": {
                "available": True,
                match.team_a: round(composite_a, 3),
                match.team_b: round(composite_b, 3),
                "weights": {
                    "team_form": form_weight,
                    "player_attack": player_weight,
                    "xg_context": xg_weight,
                },
            },
        },
        "forecast": forecast,
        "source_notes": warnings,
    }


def command_help() -> JsonObject:
    return {
        "type": "world-cup-forecast.help",
        "version": VERSION,
        "ok": True,
        "commands": {
            "schema": "print JSON contract",
            "self-test": "run embedded offline fixture",
            "today": "forecast all matches on a date",
            "match": "forecast one match by team names",
        },
        "examples": [
            "uv run --script <skill-dir>/scripts/cli.py today --date 20260629",
            (
                "uv run --script <skill-dir>/scripts/cli.py match "
                "--team-a Brazil --team-b Japan --date 20260629"
            ),
        ],
    }


def command_schema() -> JsonObject:
    return {
        "type": "world-cup-forecast.schema",
        "version": VERSION,
        "ok": True,
        "commands": ["--help", "schema", "self-test", "today", "match"],
        "top_level_required": [
            "type",
            "version",
            "ok",
            "generated_at_utc",
            "query",
            "freshness",
            "warnings",
            "errors",
        ],
        "match_fields": ["fixture", "signals", "forecast", "source_notes"],
        "json_only": True,
        "primary_signals": [
            "recent_team_form",
            "player_attack",
            "optional_xg_context",
            "optional_odds_context",
        ],
        "prohibited_primary_signals": ["historical_rating_only"],
    }


def default_date() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(add_help=False)
    cli.add_argument("command", nargs="?")
    cli.add_argument("--help", action="store_true", dest="help_json")
    cli.add_argument("--team-a")
    cli.add_argument("--team-b")
    cli.add_argument("--date", default=default_date())
    cli.add_argument("--source-url", action="append", default=[])
    cli.add_argument("--odds-url")
    cli.add_argument("--scoreboard-url")
    cli.add_argument("--standings-url")
    cli.add_argument("--stats-url")
    return cli


def fetch_inputs(
    args: argparse.Namespace,
) -> tuple[
    list[FetchResult],
    list[MatchCandidate],
    dict[str, TeamForm],
    dict[str, PlayerSignal],
    TextSignal,
    TextSignal,
    list[str],
    list[JsonObject],
]:
    date = str(args.date)
    scoreboard_url = str(
        args.scoreboard_url or ESPN_SCOREBOARD.format(date=urllib.parse.quote(date)),
    )
    standings_url = str(args.standings_url or ESPN_STANDINGS)
    stats_url = str(args.stats_url or ESPN_PLAYER_STATS)
    scoreboard = fetch("espn_scoreboard", scoreboard_url, expect_json=True)
    standings = fetch("espn_standings", standings_url, expect_json=True)
    player_stats = fetch("espn_player_stats", stats_url, expect_json=True)
    extra_results = [
        fetch("source_url", str(url), expect_json=False)
        for url in list(args.source_url or [])
    ]
    odds_results = (
        [fetch("odds_url", str(args.odds_url), expect_json=False)]
        if args.odds_url
        else []
    )
    freshness = [scoreboard, standings, player_stats, *extra_results, *odds_results]
    errors: list[JsonObject] = []
    warnings: list[str] = []
    if not scoreboard.freshness["ok"]:
        errors.append(
            compact_error("scoreboard_unavailable", "ESPN scoreboard fetch failed"),
        )
    matches = (
        parse_matches(scoreboard.json_payload)
        if scoreboard.json_payload is not None
        else []
    )
    if not standings.freshness["ok"]:
        errors.append(
            compact_error("standings_unavailable", "ESPN standings fetch failed"),
        )
    forms = (
        parse_team_forms(standings.json_payload)
        if standings.json_payload is not None
        else {}
    )
    if not player_stats.freshness["ok"]:
        warnings.append("player_stats_unavailable")
    players = (
        parse_player_signals(player_stats.json_payload, forms)
        if player_stats.json_payload is not None
        else {}
    )
    xg_context = text_signal(extra_results, "xg")
    odds_context = text_signal(odds_results, "odds")
    return (
        freshness,
        matches,
        forms,
        players,
        xg_context,
        odds_context,
        warnings,
        errors,
    )


def all_match_abbreviations(matches: list[MatchCandidate]) -> list[str]:
    out: list[str] = []
    for match in matches:
        if match.abbreviation_a not in out:
            out.append(match.abbreviation_a)
        if match.abbreviation_b not in out:
            out.append(match.abbreviation_b)
    return out


def build_today(args: argparse.Namespace) -> tuple[int, JsonObject]:
    (
        freshness_results,
        matches,
        forms,
        players,
        xg_context,
        odds_context,
        warnings,
        errors,
    ) = fetch_inputs(args)
    status = 0
    if any(error.get("code") == "scoreboard_unavailable" for error in errors):
        status = 2
    forecasts = [
        build_forecast(
            match,
            forms,
            players,
            xg_context,
            odds_context,
            all_match_abbreviations(matches),
        )
        for match in matches
    ]
    ok = bool(matches) and status == 0
    payload: JsonObject = {
        "type": "world-cup-forecast.today",
        "version": VERSION,
        "ok": ok,
        "generated_at_utc": utc_now(),
        "query": {"command": "today", "date": args.date},
        "freshness": [result.freshness for result in freshness_results],
        "warnings": warnings,
        "errors": errors,
        "matches": forecasts,
    }
    return status, payload


def build_match(args: argparse.Namespace) -> tuple[int, JsonObject]:
    (
        freshness_results,
        matches,
        forms,
        players,
        xg_context,
        odds_context,
        warnings,
        errors,
    ) = fetch_inputs(args)
    base_payload: JsonObject = {
        "type": "world-cup-forecast.match",
        "version": VERSION,
        "ok": False,
        "generated_at_utc": utc_now(),
        "query": {
            "command": "match",
            "date": args.date,
            "team_a": args.team_a,
            "team_b": args.team_b,
        },
        "freshness": [result.freshness for result in freshness_results],
        "warnings": warnings,
        "errors": errors,
    }
    if any(error.get("code") == "scoreboard_unavailable" for error in errors):
        return 2, base_payload
    if not args.team_a or not args.team_b:
        base_payload["errors"] = [
            *errors,
            compact_error("usage_error", "match requires --team-a and --team-b"),
        ]
        return 2, base_payload
    wanted = {normalize_team(str(args.team_a)), normalize_team(str(args.team_b))}
    candidates = [
        match
        for match in matches
        if {normalize_team(match.team_a), normalize_team(match.team_b)} == wanted
    ]
    if not candidates:
        base_payload["errors"] = [
            *errors,
            compact_error("match_not_found", "Requested match was not found"),
        ]
        base_payload["available_matches"] = [
            {
                "team_a": match.team_a,
                "team_b": match.team_b,
                "date_utc": match.date_utc,
                "status": match.status,
            }
            for match in matches
        ]
        return 3, base_payload
    if len(candidates) > 1:
        base_payload["errors"] = [
            *errors,
            compact_error(
                "ambiguous_match",
                "Requested teams matched multiple fixtures",
            ),
        ]
        base_payload["candidates"] = [
            {
                "team_a": match.team_a,
                "team_b": match.team_b,
                "date_utc": match.date_utc,
                "status": match.status,
            }
            for match in candidates
        ]
        return 3, base_payload
    if any(error.get("code") == "standings_unavailable" for error in errors):
        forecast = build_forecast(
            candidates[0],
            forms,
            players,
            xg_context,
            odds_context,
            all_match_abbreviations(matches),
        )
        base_payload["match"] = forecast
        return 2, base_payload
    base_payload["ok"] = True
    base_payload["match"] = build_forecast(
        candidates[0],
        forms,
        players,
        xg_context,
        odds_context,
        all_match_abbreviations(matches),
    )
    return 0, base_payload


def self_test_payload() -> JsonObject:
    forms = {
        "BRA": TeamForm("Brazil", "BRA", 7, 3, 7, 1, 6, 88.5),
        "JPN": TeamForm("Japan", "JPN", 5, 3, 7, 3, 4, 67.5),
    }
    players = {
        "BRA": PlayerSignal(
            "Brazil",
            "BRA",
            8,
            1.7,
            3,
            [
                {
                    "name": "Vinicius Junior",
                    "goals": 4.0,
                    "assists": 1.0,
                    "appearances": 3.0,
                },
            ],
            18.7,
        ),
        "JPN": PlayerSignal(
            "Japan",
            "JPN",
            5,
            1.0,
            2,
            [{"name": "Ayase Ueda", "goals": 3.0, "assists": 0.0, "appearances": 3.0}],
            12.2,
        ),
    }
    match = MatchCandidate(
        "2026-06-29T17:00Z",
        "Scheduled",
        "Brazil",
        "Japan",
        None,
        None,
        "BRA",
        "JPN",
    )
    freshness: Freshness = {
        "source": "embedded_fixture",
        "url": "embedded://self-test",
        "fetched_at_utc": utc_now(),
        "ok": True,
        "status": None,
        "content_type": "application/json",
        "elapsed_ms": 0,
    }
    empty_context = TextSignal(
        available=False,
        source_count=0,
        snippets=[],
        metrics={"xg": [], "xga": []},
        predicted_scores=[],
        reason="not_provided",
    )
    forecast = build_forecast(
        match,
        forms,
        players,
        empty_context,
        empty_context,
        ["BRA", "JPN"],
    )
    ok = bool(as_mapping(forecast.get("forecast")).get("exact_score"))
    return {
        "type": "world-cup-forecast.self_test",
        "version": VERSION,
        "ok": ok,
        "generated_at_utc": utc_now(),
        "query": {"command": "self-test"},
        "freshness": [freshness],
        "warnings": [],
        "errors": []
        if ok
        else [
            compact_error(
                "self_test_failed",
                "embedded forecast did not produce exact_score",
            ),
        ],
        "forecast": forecast.get("forecast", {}),
        "match": forecast,
    }


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0911
    try:
        args = parser().parse_args(argv)
        if args.help_json or args.command is None:
            emit(command_help())
            return 0
        if args.command == "schema":
            emit(command_schema())
            return 0
        if args.command == "self-test":
            payload = self_test_payload()
            emit(payload)
            return 0 if payload.get("ok") is True else 1
        if args.command == "today":
            status, payload = build_today(args)
            emit(payload)
            return status
        if args.command == "match":
            status, payload = build_match(args)
            emit(payload)
            return status
        emit(
            {
                "type": "world-cup-forecast.error",
                "version": VERSION,
                "ok": False,
                "generated_at_utc": utc_now(),
                "query": {"command": args.command},
                "freshness": [],
                "warnings": [],
                "errors": [
                    compact_error("usage_error", f"unknown command: {args.command}"),
                ],
            },
        )
        return 2  # noqa: TRY300
    except (OSError, ValueError, TypeError, KeyError) as exc:
        emit(
            {
                "type": "world-cup-forecast.error",
                "version": VERSION,
                "ok": False,
                "generated_at_utc": utc_now(),
                "query": {"command": "internal_error"},
                "freshness": [],
                "warnings": [],
                "errors": [compact_error("internal_error", str(exc))],
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
