"""DeepSWE overlap-kernel contract tests."""

from __future__ import annotations

from deepswe.overlap import dependency_summary, detect_overlap


def test_absent_claims_do_not_invent_dependencies() -> None:
    assert dependency_summary() == {
        "dependencies": [],
        "independence_class": "unknown",
    }
    assert detect_overlap() == []


def test_exact_canonical_component_release_collision_warns_only() -> None:
    caller = [
        {
            "caller": "index-a",
            "source": "deep-swe",
            "canonical_component_id": "deepswe:leaderboard",
            "release": "v1.1",
            "score": 0.5,
        }
    ]
    source = [
        {
            "source": "deep-swe",
            "canonical_component_id": "deepswe:leaderboard",
            "release": "v1.1",
            "score": 0.8,
        }
    ]

    warnings = detect_overlap(caller, source)
    assert len(warnings) == 1
    assert warnings[0]["code"] == "OVERLAP_DOUBLE_COUNTING_RISK"
    assert warnings[0]["severity"] == "warning"
    assert warnings[0]["component"] == "deepswe:leaderboard"
    assert warnings[0]["release"] == "v1.1"
    assert "score" not in warnings[0]


def test_fuzzy_or_different_release_claims_do_not_warn() -> None:
    fuzzy = detect_overlap(
        [{"canonical_component_id": "deepswe:leaderboard", "release": "v1.1"}],
        [{"canonical_component_id": "DeepSWE leaderboard", "release": "v1.1"}],
    )
    different_release = detect_overlap(
        [{"canonical_component_id": "deepswe:leaderboard", "release": "v1.1"}],
        [{"canonical_component_id": "deepswe:leaderboard", "release": "v1.2"}],
    )

    assert fuzzy == []
    assert different_release == []


def test_claimed_dependencies_are_retained_without_inference() -> None:
    claims = [
        {
            "source": "published-index",
            "canonical_component_id": "deepswe:leaderboard",
            "release": "v1.1",
        }
    ]
    summary = dependency_summary(claims)

    assert summary["dependencies"] == claims
    assert summary["independence_class"] == "unknown"
