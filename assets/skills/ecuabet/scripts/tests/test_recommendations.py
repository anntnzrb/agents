# ruff: noqa: PLR2004, S101
"""Regression tests for recommendation engine behavior."""

from __future__ import annotations

import json
from pathlib import Path

import recommendations

FIXTURE = Path(__file__).parent / "fixtures" / "main_snapshot_sample.json"
__all__: list[str] = []


def load_fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text())


def test_shortlist_shape() -> None:
    snapshot = load_fixture()
    cfg = recommendations.RecommendationConfig(top_n=5, include_high_risk=True)

    result, _, _ = recommendations.build_recommendations(
        snapshot,
        config=cfg,
        line_history={},
        last_success_epoch={},
    )

    shortlist = result["shortlist"]
    assert isinstance(shortlist, list)
    assert shortlist
    assert len(shortlist) <= 5
    first = shortlist[0]
    assert "marketName" in first
    assert "selectionName" in first
    assert "expectedValue" in first
    assert "riskTier" in first
    assert "modelProbabilityPct" in first
    assert "confidencePct" in first
    assert "impliedProbabilityPct" in first


def test_fair_probability_normalization_for_1x2() -> None:
    snapshot = load_fixture()
    decision_summary = recommendations.get_dict(snapshot.get("decisionSummary"))
    rows = recommendations.extract_market_candidates(decision_summary)
    recommendations.assign_fair_probabilities(rows)

    one_x_two = [r for r in rows if r.get("groupKey") == "1x2"]
    fair_sum = sum(float(r["fairProbability"]) for r in one_x_two)
    assert len(one_x_two) == 3
    assert abs(fair_sum - 1.0) < 1e-6


def test_staleness_penalizes_confidence() -> None:
    snapshot = load_fixture()
    feeds = recommendations.get_dict(snapshot.get("feeds"))
    for name in ("sofascore", "espn", "ecuabet", "openMeteo", "understat"):
        payload = recommendations.get_dict(feeds.get(name))
        payload["fetchedAtUtc"] = "2024-01-01T00:00:00+00:00"
        feeds[name] = payload
    snapshot["feedErrors"] = {"espn": "timeout"}

    cfg = recommendations.RecommendationConfig(stale_threshold_seconds=1.0)
    result, _, _ = recommendations.build_recommendations(
        snapshot,
        config=cfg,
        line_history={},
        last_success_epoch={},
    )

    assert float(result["globalConfidence"]) < 0.7
    assert isinstance(result.get("globalConfidencePct"), float)
    espn_health = recommendations.get_dict(
        recommendations.get_dict(result["feedHealth"]).get("espn")
    )
    assert espn_health.get("ok") is False
    assert isinstance(espn_health.get("confidencePct"), float)


def test_schema_tolerance_without_live_metrics() -> None:
    snapshot = load_fixture()
    decision_summary = recommendations.get_dict(snapshot.get("decisionSummary"))
    decision_summary.pop("liveMetrics", None)

    cfg = recommendations.RecommendationConfig(top_n=3)
    result, _, _ = recommendations.build_recommendations(
        snapshot,
        config=cfg,
        line_history={},
        last_success_epoch={},
    )

    assert "shortlist" in result
    assert isinstance(result["shortlist"], list)
