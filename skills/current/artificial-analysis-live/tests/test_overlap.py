"""Exact-declaration overlap contracts."""

from __future__ import annotations

from artificial_analysis.overlap import (
    OVERLAP_DOUBLE_COUNTING_RISK,
    declarative_dependencies,
    detect_overlap,
    overlap_metadata,
    overlap_warnings,
)


def _component(component_id: str, release: str) -> dict[str, str]:
    return {"canonical_id": component_id, "release": release}


def test_exact_declared_join_emits_requirements_claim_warning() -> None:
    left = _component("terminal-bench", "2.1")
    right = _component("sci-code", "1")
    claims = [
        {
            "left": left,
            "right": right,
            "relation": "join",
        },
    ]

    warnings = overlap_warnings(left, right, declared_joins=claims)
    assert warnings == [
        {
            "code": OVERLAP_DOUBLE_COUNTING_RISK,
            "certainty": "requirements_claim",
            "left": left,
            "right": right,
        },
    ]
    assert detect_overlap(left, right, declarations=claims) == warnings


def test_fuzzy_or_partial_overlap_never_warns() -> None:
    left = _component("terminal-bench", "2.1")
    right = _component("sci-code", "1")
    fuzzy_claim = [
        {
            "left": _component("terminal-bench-v2", "2.1"),
            "right": right,
            "relation": "join",
        },
    ]
    assert overlap_warnings(left, right, declared_joins=fuzzy_claim) == []
    assert (
        overlap_warnings(
            left,
            {"canonical_id": "sci-code"},
            declared_joins=fuzzy_claim,
        )
        == []
    )
    assert (
        overlap_metadata(left=left, right=right, declarations=[])["status"] == "unknown"
    )


def test_dependencies_and_independence_are_declarative_and_unchanged() -> None:
    metadata = declarative_dependencies(
        component_id="harness",
        release="1",
        depends_on=[_component("agentic", "2026-01")],
        independent_of=[_component("price", "2026-01")],
    )
    assert metadata["component_id"] == "harness"
    assert metadata["release"] == "1"
    assert metadata["dependencies"] == [_component("agentic", "2026-01")]
    assert metadata["independence"] == [_component("price", "2026-01")]
