# Copyright (c) 2026
from __future__ import annotations

from livebench.contracts import RawArtifact
from livebench.normalization import numeric_value


def test_explicit_percent_preserves_raw_and_normalizes() -> None:
    artifact = RawArtifact(
        "a",
        "livebench",
        "r",
        "score_table",
        "fixture://table",
        "fixture://source",
        b"",
        200,
        "text/csv",
        {},
        "2026-08-09T00:00:00Z",
        "2026-08-09T00:00:00Z",
        "0" * 64,
        0,
        None,
        "snapshot",
        False,
        True,
        False,
        None,
    )
    value, diagnostics = numeric_value(
        "72.4%", path="csv[row=0,column=task]", artifact=artifact, semantics="known"
    )
    assert value.raw_value == "72.4%"
    assert value.normalized_value == 72.4
    assert value.unit == "percent"
    assert value.normalization == "removed_percent_sign"
    assert not diagnostics


def test_bare_numeric_is_visible_but_blocked() -> None:
    value, diagnostics = numeric_value("0.724", path="csv[row=0,column=task]")
    assert value.normalized_value == 0.724
    assert value.metric_semantics_status == "ambiguous"
    assert value.comparison_eligibility == "blocked"
    assert any(item.code == "NUMERIC_AMBIGUITY" for item in diagnostics)
