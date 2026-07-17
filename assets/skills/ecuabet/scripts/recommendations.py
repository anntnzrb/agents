"""Recommendation and scoring engine for live football betting snapshots."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

__all__: list[str] = []

ASCII_UPPER_BOUND = 128
PROB_MIN = 0.0001
PROB_MAX = 0.97
EPSILON = 1e-9
MINUTE_CAP = 90.0
DEFAULT_EXPECTED_GOALS = 2.6
GOAL_SCALE = 2.0
MODEL_BLEND = 0.72
EARLY_MINUTE = 30
EARLY_UNDER_BONUS = 0.03
LEAD_IMPACT = 0.03
HISTORY_DEFAULT_LIMIT = 120
MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 1.0
TWO_ITEMS = 2

DOMINANCE_XG_WEIGHT = 0.46
DOMINANCE_SHOTS_ON_TARGET_WEIGHT = 0.2
DOMINANCE_SHOTS_WEIGHT = 0.14
DOMINANCE_CORNERS_WEIGHT = 0.1
DOMINANCE_POSSESSION_WEIGHT = 0.1

HOME_DOMINANCE_WEIGHT = 0.11
HOME_STRENGTH_WEIGHT = 0.08
DRAW_BALANCE_WEIGHT = 0.06
TOTAL_TEMPO_WEIGHT = 0.08
WEATHER_WEIGHT = 0.02
BTTS_THREAT_WEIGHT = 0.06

EDGE_TO_SIGNAL_SCORE = 220.0
CONFIDENCE_TO_SIGNAL_SCORE = 40.0
BASE_SIGNAL_SCORE = 50.0
BASE_CONFIDENCE_SCORE = 0.6

EV_SORT_WEIGHT = 0.62
EDGE_SORT_WEIGHT = 0.2
PROB_SORT_WEIGHT = 0.1
CONF_SORT_WEIGHT = 0.08
HIGH_RISK_SORT_PENALTY = 0.25
LONGSHOT_ODDS_PENALTY_START = 8.0
LONGSHOT_ODDS_PENALTY_WEIGHT = 0.02
LOW_RISK_MIN_PROBABILITY = 0.68
LOW_RISK_MAX_ODDS = 1.9
LOW_RISK_MIN_CONFIDENCE = 0.7
MEDIUM_RISK_MIN_PROBABILITY = 0.55
MEDIUM_RISK_MAX_ODDS = 3.2
MEDIUM_RISK_MIN_CONFIDENCE = 0.55

FEED_WEIGHTS = {
    "sofascore": 0.3,
    "espn": 0.2,
    "ecuabet": 0.2,
    "openMeteo": 0.15,
    "understat": 0.15,
}

SIMPLE_MARKET_FAMILIES = (
    "1x2",
    "doubleChance",
    "btts",
    "handicap",
    "firstGoal",
    "lastGoal",
    "correctScore",
)
TOTAL_MARKET_FAMILIES = ("totals", "totals_1st_half", "totals_2nd_half")
SAFE_MARKET_FAMILIES = {
    "1x2",
    "doubleChance",
    "btts",
    "handicap",
    "totals",
    "totals_1st_half",
    "totals_2nd_half",
}


@dataclass(frozen=True)
class RecommendationConfig:
    top_n: int = 8
    min_odds: float = 1.01
    max_odds: float | None = None
    min_confidence: float = MIN_CONFIDENCE
    stale_threshold_seconds: float = 180.0
    history_limit: int = HISTORY_DEFAULT_LIMIT
    include_high_risk: bool = False


def normalize_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(ch for ch in text if ord(ch) < ASCII_UPPER_BOUND)
    return " ".join(ascii_text.lower().split())


def get_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def get_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def to_percent(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value * 100.0, digits)


def parse_iso_utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_clock_minute(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"(\d{1,3})", value)
    if not match:
        return None
    try:
        minute = int(match.group(1))
    except ValueError:
        return None
    return clamp(minute, 0, int(MINUTE_CAP))


def implied_probability(odds: float) -> float:
    if odds <= 0:
        return PROB_MIN
    return clamp(1.0 / odds, PROB_MIN, PROB_MAX)


def parse_handicap_line(selection_name: object) -> float | None:
    text = normalize_text(selection_name)
    match = re.search(r"\(([+-]?\d+(?:\.\d+)?)\)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def parse_total_line(selection_name: object) -> float | None:
    text = normalize_text(selection_name)
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def extract_market_candidates(
    decision_summary: dict[str, object],
) -> list[dict[str, object]]:
    ecuabet_markets = get_dict(decision_summary.get("ecuabetMarkets"))
    key_lines = get_dict(ecuabet_markets.get("keyLines"))

    candidates: list[dict[str, object]] = []

    for family in SIMPLE_MARKET_FAMILIES:
        rows = get_list(key_lines.get(family))
        for row in rows:
            item = get_dict(row)
            odds = as_float(item.get("price"))
            if odds is None or odds <= 0:
                continue
            market_name = family
            selection_name = str(item.get("name") or "")
            line = parse_handicap_line(selection_name) if family == "handicap" else None
            group_key = family
            if family == "handicap" and line is not None:
                group_key = f"{family}:{abs(line):.2f}"
            candidates.append(
                {
                    "id": f"{market_name}|{selection_name}",
                    "marketFamily": family,
                    "marketName": market_name,
                    "selectionName": selection_name,
                    "odds": odds,
                    "line": line,
                    "groupKey": group_key,
                },
            )

    for family in TOTAL_MARKET_FAMILIES:
        rows = get_list(key_lines.get(family))
        for row in rows:
            ladder = get_dict(row)
            line = as_float(ladder.get("line"))
            for side in ("over", "under"):
                side_row = get_dict(ladder.get(side))
                odds = as_float(side_row.get("price"))
                if odds is None or odds <= 0:
                    continue
                selection_name = str(side_row.get("name") or "")
                inferred_line = (
                    line if line is not None else parse_total_line(selection_name)
                )
                line_text = (
                    f"{inferred_line:.2f}" if inferred_line is not None else "na"
                )
                candidates.append(
                    {
                        "id": f"{family}|{selection_name}",
                        "marketFamily": family,
                        "marketName": family,
                        "selectionName": selection_name,
                        "odds": odds,
                        "line": inferred_line,
                        "groupKey": f"{family}:{line_text}",
                    },
                )

    for row in candidates:
        odds = float(row["odds"])
        row["impliedProbability"] = implied_probability(odds)

    return candidates


def assign_fair_probabilities(candidates: list[dict[str, object]]) -> None:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in candidates:
        key = str(row.get("groupKey") or "")
        grouped.setdefault(key, []).append(row)

    for group_rows in grouped.values():
        overround = sum(
            as_float(x.get("impliedProbability")) or 0.0 for x in group_rows
        )
        if overround <= EPSILON:
            for row in group_rows:
                row["fairProbability"] = row.get("impliedProbability")
            continue
        for row in group_rows:
            implied = as_float(row.get("impliedProbability")) or PROB_MIN
            row["fairProbability"] = clamp(implied / overround, PROB_MIN, PROB_MAX)


def get_pair_values(row: object) -> tuple[float | None, float | None]:
    pair = get_dict(row)
    left = as_float(pair.get("homeValue"))
    right = as_float(pair.get("awayValue"))
    if left is None or right is None:
        left = as_float(pair.get("home"))
        right = as_float(pair.get("away"))
    return left, right


def select_understat_rows(
    understat: dict[str, object],
    home_name: str,
    away_name: str,
) -> tuple[dict[str, object], dict[str, object]]:
    home_norm = normalize_text(home_name)
    away_norm = normalize_text(away_name)
    rows = get_list(understat.get("teams"))

    home_row: dict[str, object] = {}
    away_row: dict[str, object] = {}

    for item in rows:
        team = get_dict(item)
        title_norm = normalize_text(team.get("team"))
        if home_norm and (home_norm in title_norm or title_norm in home_norm):
            home_row = team
        if away_norm and (away_norm in title_norm or title_norm in away_norm):
            away_row = team

    return home_row, away_row


def build_feed_health(
    snapshot: dict[str, object],
    *,
    now_utc: datetime,
    last_success_epoch: dict[str, float],
    stale_threshold_seconds: float,
) -> tuple[dict[str, object], dict[str, float], float]:
    feeds = get_dict(snapshot.get("feeds"))
    feed_errors = get_dict(snapshot.get("feedErrors"))

    health: dict[str, object] = {}
    confidence_by_feed: dict[str, float] = {}

    threshold = max(stale_threshold_seconds, 1.0)

    for feed_name in FEED_WEIGHTS:
        payload = get_dict(feeds.get(feed_name))
        fetched_at = parse_iso_utc(payload.get("fetchedAtUtc"))
        has_error = feed_name in feed_errors and bool(feed_errors.get(feed_name))

        if fetched_at is not None and not has_error:
            last_success_epoch[feed_name] = fetched_at.timestamp()

        last_success = last_success_epoch.get(feed_name)
        age_seconds: float | None = None
        if last_success is not None:
            age_seconds = max(0.0, now_utc.timestamp() - last_success)

        confidence = 1.0
        if has_error:
            confidence = 0.25
        elif fetched_at is None:
            confidence = 0.55

        if age_seconds is not None and age_seconds > threshold:
            decay = (age_seconds - threshold) / max(threshold * 2.0, 1.0)
            confidence *= max(0.3, 1.0 - decay)

        confidence = clamp(confidence, MIN_CONFIDENCE, MAX_CONFIDENCE)
        confidence_by_feed[feed_name] = confidence

        health[feed_name] = {
            "ok": not has_error,
            "error": feed_errors.get(feed_name),
            "hasPayload": bool(payload),
            "fetchedAtUtc": payload.get("fetchedAtUtc"),
            "ageSeconds": age_seconds,
            "stale": age_seconds is not None and age_seconds > threshold,
            "confidence": round(confidence, 4),
            "confidencePct": to_percent(confidence, 2),
        }

    weight_total = sum(FEED_WEIGHTS.values())
    weighted = 0.0
    for name, weight in FEED_WEIGHTS.items():
        weighted += confidence_by_feed.get(name, 0.0) * weight

    global_confidence = clamp(weighted / max(weight_total, EPSILON), 0.0, 1.0)
    return health, confidence_by_feed, global_confidence


def extract_signal_bundle(snapshot: dict[str, object]) -> dict[str, object]:  # noqa: PLR0915
    decision_summary = get_dict(snapshot.get("decisionSummary"))
    live_metrics = get_dict(decision_summary.get("liveMetrics"))
    sofa_live = get_dict(live_metrics.get("sofascore"))

    xg_home, xg_away = get_pair_values(sofa_live.get("expectedGoals"))
    shots_home, shots_away = get_pair_values(sofa_live.get("totalShots"))
    sot_home, sot_away = get_pair_values(sofa_live.get("shotsOnTarget"))
    corners_home, corners_away = get_pair_values(sofa_live.get("corners"))
    pos_home, pos_away = get_pair_values(sofa_live.get("possession"))

    xg_diff = (xg_home or 0.0) - (xg_away or 0.0)
    shots_diff = (shots_home or 0.0) - (shots_away or 0.0)
    sot_diff = (sot_home or 0.0) - (sot_away or 0.0)
    corners_diff = (corners_home or 0.0) - (corners_away or 0.0)
    pos_diff = (pos_home or 0.0) - (pos_away or 0.0)

    dominance = (
        DOMINANCE_XG_WEIGHT * clamp(xg_diff / 1.5, -1.0, 1.0)
        + DOMINANCE_SHOTS_ON_TARGET_WEIGHT * clamp(sot_diff / 3.0, -1.0, 1.0)
        + DOMINANCE_SHOTS_WEIGHT * clamp(shots_diff / 7.0, -1.0, 1.0)
        + DOMINANCE_CORNERS_WEIGHT * clamp(corners_diff / 6.0, -1.0, 1.0)
        + DOMINANCE_POSSESSION_WEIGHT * clamp(pos_diff / 45.0, -1.0, 1.0)
    )
    dominance = clamp(dominance, -1.0, 1.0)

    status_board = get_dict(decision_summary.get("statusBoard"))
    espn_status = get_dict(status_board.get("espn"))
    ecuabet_status = get_dict(status_board.get("ecuabet"))
    minute = parse_clock_minute(espn_status.get("clock"))
    if minute is None:
        minute = parse_clock_minute(ecuabet_status.get("liveTime"))

    score_consensus = get_dict(decision_summary.get("scoreConsensus"))
    consensus = get_list(score_consensus.get("consensusScore"))
    home_score = (
        int(consensus[0])
        if len(consensus) >= TWO_ITEMS and isinstance(consensus[0], int)
        else 0
    )
    away_score = (
        int(consensus[1])
        if len(consensus) >= TWO_ITEMS and isinstance(consensus[1], int)
        else 0
    )

    projected_goals: float | None = None
    xg_total = (xg_home or 0.0) + (xg_away or 0.0)
    if minute is not None and minute > 0:
        projected_goals = clamp(xg_total * (MINUTE_CAP / minute), 0.0, 8.0)

    tempo = 0.0
    if projected_goals is not None:
        tempo = clamp(
            (projected_goals - DEFAULT_EXPECTED_GOALS) / GOAL_SCALE,
            -1.0,
            1.0,
        )

    weather = get_dict(decision_summary.get("weather"))
    comfort = get_dict(weather.get("comfort"))
    comfort_score = as_float(comfort.get("score"))
    weather_signal = 0.0
    if comfort_score is not None:
        weather_signal = clamp((comfort_score - 50.0) / 50.0, -1.0, 1.0)

    understat = get_dict(decision_summary.get("understatForm"))
    match = get_dict(snapshot.get("match"))
    home_name = str(match.get("home") or "")
    away_name = str(match.get("away") or "")
    home_row, away_row = select_understat_rows(understat, home_name, away_name)

    strength = 0.0
    home_totals = get_dict(home_row.get("seasonTotals"))
    away_totals = get_dict(away_row.get("seasonTotals"))
    home_ppg = as_float(home_totals.get("ppg"))
    away_ppg = as_float(away_totals.get("ppg"))
    home_xg_diff = as_float(home_totals.get("xGDiff"))
    away_xg_diff = as_float(away_totals.get("xGDiff"))
    if (
        home_ppg is not None
        and away_ppg is not None
        and home_xg_diff is not None
        and away_xg_diff is not None
    ):
        ppg_signal = clamp((home_ppg - away_ppg) / 1.5, -1.0, 1.0)
        xg_signal = clamp((home_xg_diff - away_xg_diff) / 12.0, -1.0, 1.0)
        strength = clamp((ppg_signal * 0.6) + (xg_signal * 0.4), -1.0, 1.0)

    return {
        "dominance": dominance,
        "strength": strength,
        "tempo": tempo,
        "weather": weather_signal,
        "minute": minute,
        "homeScore": home_score,
        "awayScore": away_score,
        "homeXg": xg_home,
        "awayXg": xg_away,
        "projectedGoals": projected_goals,
    }


def infer_selection_profile(
    candidate: dict[str, object],
    home_name: str,
    away_name: str,
) -> dict[str, object]:
    market_name = normalize_text(candidate.get("marketName"))
    selection_name = normalize_text(candidate.get("selectionName"))

    home_norm = normalize_text(home_name)
    away_norm = normalize_text(away_name)

    side = "neutral"
    if home_norm and home_norm in selection_name:
        side = "home"
    elif away_norm and away_norm in selection_name:
        side = "away"
    elif "empate" in selection_name or selection_name == "draw":
        side = "draw"

    total = "none"
    if selection_name.startswith(("mas de", "over")):
        total = "over"
    elif selection_name.startswith(("menos de", "under")):
        total = "under"

    btts = "none"
    if "ambos equipos marcan" in market_name:
        if selection_name in ("si", "yes"):
            btts = "yes"
        elif selection_name == "no":
            btts = "no"

    return {
        "side": side,
        "total": total,
        "btts": btts,
    }


def estimate_model_probability(  # noqa: C901,PLR0912
    candidate: dict[str, object],
    profile: dict[str, object],
    signal_bundle: dict[str, object],
    global_confidence: float,
) -> tuple[float, float, float]:
    implied = as_float(candidate.get("impliedProbability")) or PROB_MIN
    fair = as_float(candidate.get("fairProbability")) or implied
    line = as_float(candidate.get("line"))

    dominance = as_float(signal_bundle.get("dominance")) or 0.0
    strength = as_float(signal_bundle.get("strength")) or 0.0
    tempo = as_float(signal_bundle.get("tempo")) or 0.0
    weather = as_float(signal_bundle.get("weather")) or 0.0
    minute = signal_bundle.get("minute")
    home_score = int(signal_bundle.get("homeScore") or 0)
    away_score = int(signal_bundle.get("awayScore") or 0)

    adjustment = 0.0

    side = str(profile.get("side") or "neutral")
    total = str(profile.get("total") or "none")
    btts = str(profile.get("btts") or "none")

    if side == "home":
        adjustment += (HOME_DOMINANCE_WEIGHT * dominance) + (
            HOME_STRENGTH_WEIGHT * strength
        )
    elif side == "away":
        adjustment -= (HOME_DOMINANCE_WEIGHT * dominance) + (
            HOME_STRENGTH_WEIGHT * strength
        )
    elif side == "draw":
        adjustment -= DRAW_BALANCE_WEIGHT * (abs(dominance) + abs(strength))

    projected_goals = as_float(signal_bundle.get("projectedGoals"))
    if total in ("over", "under"):
        line_target = line if line is not None else DEFAULT_EXPECTED_GOALS
        line_signal = tempo
        if projected_goals is not None:
            line_signal = clamp((projected_goals - line_target) / GOAL_SCALE, -1.0, 1.0)
        if total == "over":
            adjustment += (TOTAL_TEMPO_WEIGHT * line_signal) + (
                WEATHER_WEIGHT * weather
            )
        else:
            adjustment -= (TOTAL_TEMPO_WEIGHT * line_signal) + (
                WEATHER_WEIGHT * weather
            )

    if btts in ("yes", "no"):
        away_threat = clamp(
            ((as_float(signal_bundle.get("awayXg")) or 0.0) - 0.3) / 0.9,
            -1.0,
            1.0,
        )
        if btts == "yes":
            adjustment += BTTS_THREAT_WEIGHT * away_threat
        else:
            adjustment -= BTTS_THREAT_WEIGHT * away_threat

    if (
        isinstance(minute, int)
        and minute <= EARLY_MINUTE
        and (home_score + away_score) == 0
    ):
        if total == "under":
            adjustment += EARLY_UNDER_BONUS
        elif total == "over":
            adjustment -= EARLY_UNDER_BONUS

    if side == "home" and home_score > away_score:
        adjustment += LEAD_IMPACT
    if side == "away" and away_score > home_score:
        adjustment += LEAD_IMPACT

    raw_model = clamp(fair + adjustment, PROB_MIN, PROB_MAX)
    blended = implied + ((raw_model - implied) * MODEL_BLEND)
    model_probability = clamp(
        implied + ((blended - implied) * global_confidence),
        PROB_MIN,
        PROB_MAX,
    )

    edge = model_probability - fair
    expected_value = (float(candidate["odds"]) * model_probability) - 1.0
    return model_probability, edge, expected_value


def risk_tier(probability: float, odds: float, confidence: float) -> str:
    if (
        probability >= LOW_RISK_MIN_PROBABILITY
        and odds <= LOW_RISK_MAX_ODDS
        and confidence >= LOW_RISK_MIN_CONFIDENCE
    ):
        return "low"
    if (
        probability >= MEDIUM_RISK_MIN_PROBABILITY
        and odds <= MEDIUM_RISK_MAX_ODDS
        and confidence >= MEDIUM_RISK_MIN_CONFIDENCE
    ):
        return "medium"
    return "high"


def update_line_history(
    candidates: list[dict[str, object]],
    *,
    line_history: dict[str, list[dict[str, object]]],
    now_iso: str,
    history_limit: int,
) -> None:
    limit = max(history_limit, 2)
    for row in candidates:
        key = str(row.get("id") or "")
        if not key:
            continue
        price = as_float(row.get("odds"))
        if price is None:
            continue
        history = line_history.setdefault(key, [])
        history.append(
            {
                "ts": now_iso,
                "odds": price,
                "implied": as_float(row.get("impliedProbability")),
            },
        )
        if len(history) > limit:
            del history[:-limit]


def movement_stats(history: list[dict[str, object]]) -> dict[str, object]:
    if len(history) < TWO_ITEMS:
        return {
            "direction": "flat",
            "delta": 0.0,
            "pct": 0.0,
            "samples": len(history),
        }

    first = as_float(history[0].get("odds")) or 0.0
    prev = as_float(history[-2].get("odds")) or 0.0
    last = as_float(history[-1].get("odds")) or 0.0

    delta = last - prev
    pct = 0.0 if abs(prev) <= EPSILON else (delta / prev)

    direction = "flat"
    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"

    total_delta = last - first
    prices = [as_float(x.get("odds")) or 0.0 for x in history]
    span = max(prices) - min(prices)

    return {
        "direction": direction,
        "delta": round(delta, 6),
        "pct": round(pct, 6),
        "totalDelta": round(total_delta, 6),
        "range": round(span, 6),
        "samples": len(history),
    }


def shortlist_candidates(  # noqa: C901,PLR0913
    rows: list[dict[str, object]],
    *,
    top_n: int,
    min_odds: float,
    max_odds: float | None,
    min_confidence: float,
    include_high_risk: bool,
) -> list[dict[str, object]]:
    filtered: list[dict[str, object]] = []
    for row in rows:
        odds = as_float(row.get("odds"))
        confidence = as_float(row.get("confidence"))
        if odds is None or confidence is None:
            continue
        if odds < min_odds:
            continue
        if max_odds is not None and odds > max_odds:
            continue
        if confidence < min_confidence:
            continue
        family = str(row.get("marketFamily") or "")
        if not include_high_risk and family not in SAFE_MARKET_FAMILIES:
            continue
        if not include_high_risk and row.get("riskTier") == "high":
            continue
        filtered.append(row)

    filtered.sort(key=lambda x: as_float(x.get("sortScore")) or -math.inf, reverse=True)
    if filtered:
        return filtered[: max(top_n, 1)]

    # Fallback: if strict risk filter empties the shortlist, return best-ranked
    # candidates so the caller always gets actionable output.
    fallback = [x for x in rows if (as_float(x.get("odds")) or 0.0) >= min_odds]
    if max_odds is not None:
        fallback = [x for x in fallback if (as_float(x.get("odds")) or 0.0) <= max_odds]
    if not include_high_risk:
        fallback = [
            x
            for x in fallback
            if str(x.get("marketFamily") or "") in SAFE_MARKET_FAMILIES
        ]
    fallback = [
        x for x in fallback if (as_float(x.get("confidence")) or 0.0) >= min_confidence
    ]
    fallback.sort(key=lambda x: as_float(x.get("sortScore")) or -math.inf, reverse=True)
    return fallback[: max(top_n, 1)]


def build_recommendations(
    snapshot: dict[str, object],
    *,
    config: RecommendationConfig,
    line_history: dict[str, list[dict[str, object]]],
    last_success_epoch: dict[str, float],
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]], dict[str, float]]:
    now_utc = datetime.now(timezone.utc)
    now_iso = now_utc.replace(microsecond=0).isoformat()

    feed_health, _confidence_by_feed, global_confidence = build_feed_health(
        snapshot,
        now_utc=now_utc,
        last_success_epoch=last_success_epoch,
        stale_threshold_seconds=config.stale_threshold_seconds,
    )

    signal_bundle = extract_signal_bundle(snapshot)
    decision_summary = get_dict(snapshot.get("decisionSummary"))
    match = get_dict(snapshot.get("match"))
    home_name = str(match.get("home") or "")
    away_name = str(match.get("away") or "")

    candidates = extract_market_candidates(decision_summary)
    assign_fair_probabilities(candidates)
    update_line_history(
        candidates,
        line_history=line_history,
        now_iso=now_iso,
        history_limit=config.history_limit,
    )

    scored: list[dict[str, object]] = []
    for row in candidates:
        profile = infer_selection_profile(row, home_name=home_name, away_name=away_name)
        model_probability, edge, expected_value = estimate_model_probability(
            row,
            profile,
            signal_bundle,
            global_confidence,
        )

        odds = as_float(row.get("odds")) or 0.0
        implied_probability = as_float(row.get("impliedProbability"))
        fair_probability = as_float(row.get("fairProbability")) or 0.0
        model_probability_rounded = round(model_probability, 6)
        confidence_rounded = round(global_confidence, 4)
        signal_score = clamp(
            BASE_SIGNAL_SCORE
            + (edge * EDGE_TO_SIGNAL_SCORE)
            + (
                (global_confidence - BASE_CONFIDENCE_SCORE) * CONFIDENCE_TO_SIGNAL_SCORE
            ),
            0.0,
            100.0,
        )

        tier = risk_tier(model_probability, odds, global_confidence)
        movement = movement_stats(line_history.get(str(row.get("id") or ""), []))

        sort_score = (
            (expected_value * EV_SORT_WEIGHT)
            + (edge * EDGE_SORT_WEIGHT)
            + (model_probability * PROB_SORT_WEIGHT)
            + (global_confidence * CONF_SORT_WEIGHT)
        )
        if tier == "high":
            sort_score -= HIGH_RISK_SORT_PENALTY
        if odds > LONGSHOT_ODDS_PENALTY_START:
            sort_score -= (
                odds - LONGSHOT_ODDS_PENALTY_START
            ) * LONGSHOT_ODDS_PENALTY_WEIGHT

        scored.append(
            {
                "selectionId": row.get("id"),
                "marketFamily": row.get("marketFamily"),
                "marketName": row.get("marketName"),
                "selectionName": row.get("selectionName"),
                "odds": odds,
                "line": row.get("line"),
                "impliedProbability": implied_probability,
                "impliedProbabilityPct": to_percent(implied_probability, 2),
                "fairProbability": fair_probability,
                "fairProbabilityPct": to_percent(fair_probability, 2),
                "modelProbability": model_probability_rounded,
                "modelProbabilityPct": to_percent(model_probability_rounded, 2),
                "edge": round(edge, 6),
                "edgePctPoints": to_percent(edge, 2),
                "expectedValue": round(expected_value, 6),
                "signalScore": round(signal_score, 2),
                "confidence": confidence_rounded,
                "confidencePct": to_percent(confidence_rounded, 2),
                "riskTier": tier,
                "movement": movement,
                "sortScore": round(sort_score, 6),
            },
        )

    shortlist = shortlist_candidates(
        scored,
        top_n=config.top_n,
        min_odds=max(config.min_odds, 1.0),
        max_odds=config.max_odds,
        min_confidence=clamp(config.min_confidence, 0.0, 1.0),
        include_high_risk=config.include_high_risk,
    )

    for idx, row in enumerate(shortlist, start=1):
        row["rank"] = idx

    recommendation = {
        "generatedAtUtc": now_iso,
        "engineVersion": "1.0.0",
        "filters": {
            "topN": config.top_n,
            "minOdds": config.min_odds,
            "maxOdds": config.max_odds,
            "minConfidence": config.min_confidence,
            "staleThresholdSeconds": config.stale_threshold_seconds,
            "includeHighRisk": config.include_high_risk,
        },
        "feedHealth": feed_health,
        "globalConfidence": round(global_confidence, 4),
        "globalConfidencePct": to_percent(global_confidence, 2),
        "signalBundle": signal_bundle,
        "candidateCount": len(scored),
        "shortlist": shortlist,
    }

    return recommendation, line_history, last_success_epoch
