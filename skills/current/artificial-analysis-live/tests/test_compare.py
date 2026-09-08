"""Tests for model family and effort comparison interfaces."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import cast

import pytest

from artificial_analysis import cli
from artificial_analysis.comparison import compare_models

SYNTHETIC_PATH = Path("synthetic.json")


def _synthetic_snapshot() -> dict[str, object]:
    return {
        "meta": {
            "schema_version": 2,
            "fetched_at": "2026-09-08T00:00:00Z",
        },
        "models": [
            {
                "slug": "model-a-max",
                "name": "Model Alpha (max)",
                "reasoning_model": True,
                "intelligence_index": 85.0,
                "coding_index": None,
                "raw_fields": {
                    "release": {"slug": "model-alpha", "name": "Model Alpha"},
                    "effort": {"slug": "max", "label": "max", "level": 60},
                    "isReasoning": True,
                    "unknown_metric_x": 123.4,
                },
            },
            {
                "slug": "model-a-low",
                "name": "Model Alpha (low)",
                "reasoning_model": True,
                "intelligence_index": 70.0,
                "coding_index": None,
                "raw_fields": {
                    "release": {"slug": "model-alpha", "name": "Model Alpha"},
                    "effort": {"slug": "low", "label": "low", "level": 20},
                    "isReasoning": True,
                },
            },
            {
                "slug": "model-a-non-reasoning",
                "name": "Model Alpha (Non-reasoning)",
                "reasoning_model": False,
                "intelligence_index": 65.0,
                "coding_index": None,
                "raw_fields": {
                    "release": {"slug": "model-alpha", "name": "Model Alpha"},
                    "effort": None,
                    "isReasoning": False,
                },
            },
            {
                "slug": "model-b-thinking-only",
                "name": "Model Beta Thinking",
                "reasoning_model": True,
                "raw_fields": {
                    "release": {"slug": "model-beta", "name": "Model Beta"},
                    "effort": None,
                    "isReasoning": True,
                },
            },
            {
                "slug": "model-c-1",
                "name": "Common Prefix 1",
                "raw_fields": {
                    "release": {"slug": "common-one", "name": "Common One"},
                    "effort": {"slug": "high", "label": "high", "level": 40},
                    "isReasoning": True,
                },
            },
            {
                "slug": "model-c-2",
                "name": "Common Prefix 2",
                "raw_fields": {
                    "release": {"slug": "common-two", "name": "Common Two"},
                    "effort": {"slug": "high", "label": "high", "level": 40},
                    "isReasoning": True,
                },
            },
            {
                "slug": "model-no-release-meta",
                "name": "Model No Release Meta",
                "raw_fields": {
                    "effort": {"slug": "high", "label": "high", "level": 40},
                },
            },
        ],
    }


def test_ambiguous_family_raises_usage_error() -> None:
    snapshot = _synthetic_snapshot()
    with pytest.raises(cli.CliUsageError):
        _ = compare_models(
            snapshot,
            SYNTHETIC_PATH,
            ["Common"],
            usage_error_factory=cli.CliUsageError,
        )


def test_missing_requested_effort_fails_completely() -> None:
    snapshot = _synthetic_snapshot()
    with pytest.raises(cli.CliUsageError):
        _ = compare_models(
            snapshot,
            SYNTHETIC_PATH,
            ["Model Alpha:max,superhigh"],
            usage_error_factory=cli.CliUsageError,
        )


@pytest.mark.parametrize(
    "malformed",
    ["Model Alpha:", "Model Alpha:low,", "Model Alpha:,low", "Model Alpha:   ", ":low"],
)
def test_malformed_selector_rejected(malformed: str) -> None:
    snapshot = _synthetic_snapshot()
    with pytest.raises(cli.CliUsageError):
        _ = compare_models(
            snapshot,
            SYNTHETIC_PATH,
            [malformed],
            usage_error_factory=cli.CliUsageError,
        )


def test_missing_release_metadata_not_guessed_from_slug() -> None:
    snapshot = _synthetic_snapshot()
    with pytest.raises(cli.CliUsageError):
        _ = compare_models(
            snapshot,
            SYNTHETIC_PATH,
            ["Model No Release Meta"],
            usage_error_factory=cli.CliUsageError,
        )


def test_conflicting_reasoning_flags_raise_usage_error() -> None:
    snapshot: dict[str, object] = {
        "meta": {"schema_version": 2, "fetched_at": "2026-09-08T00:00:00Z"},
        "models": [
            {
                "slug": "conflict-model",
                "name": "Conflict Model",
                "reasoning_model": True,
                "raw_fields": {
                    "release": {"slug": "conflict-family", "name": "Conflict Family"},
                    "effort": {"slug": "high", "label": "high", "level": 40},
                    "isReasoning": False,
                },
            }
        ],
    }
    with pytest.raises(cli.CliUsageError):
        _ = compare_models(
            snapshot,
            SYNTHETIC_PATH,
            ["Conflict Family"],
            usage_error_factory=cli.CliUsageError,
        )


def test_future_effort_and_unknown_fields_retained_losslessly() -> None:
    custom_snapshot: dict[str, object] = {
        "meta": {"schema_version": 2, "fetched_at": "2026-09-08T00:00:00Z"},
        "models": [
            {
                "slug": "future-model-ultra",
                "name": "Future Model Ultra",
                "reasoning_model": True,
                "raw_fields": {
                    "release": {"slug": "future-family", "name": "Future Family"},
                    "effort": {
                        "slug": "ultra-tier",
                        "label": "Ultra Tier",
                        "level": 99,
                    },
                    "isReasoning": True,
                    "arbitrary_future_benchmark": 98.7,
                },
                "unknown_top_level_metric": {"complex": [1, 2, 3]},
            }
        ],
    }

    result = compare_models(
        custom_snapshot,
        SYNTHETIC_PATH,
        ["Future Family:ultra-tier"],
        usage_error_factory=cli.CliUsageError,
    )
    rows = cast("list[dict[str, object]]", result["rows"])
    assert len(rows) == 1
    row = rows[0]
    assert row["slug"] == "future-model-ultra"
    assert row["effort_slug"] == "ultra-tier"
    assert row["effort_level"] == 99
    raw = cast("dict[str, object]", row["raw_fields"])
    assert raw["arbitrary_future_benchmark"] == 98.7
    assert row["unknown_top_level_metric"] == {"complex": [1, 2, 3]}


def test_null_effort_with_true_reasoning_is_unknown_not_non_reasoning() -> None:
    snapshot = _synthetic_snapshot()
    with pytest.raises(cli.CliUsageError):
        _ = compare_models(
            snapshot,
            SYNTHETIC_PATH,
            ["Model Beta:non-reasoning"],
            usage_error_factory=cli.CliUsageError,
        )

    result = compare_models(
        snapshot,
        SYNTHETIC_PATH,
        ["Model Beta"],
        usage_error_factory=cli.CliUsageError,
    )
    rows = cast("list[dict[str, object]]", result["rows"])
    assert len(rows) == 1
    assert rows[0]["effort_slug"] is None
    assert rows[0]["is_reasoning"] is True


def test_unavailable_metrics_remain_none_not_zero() -> None:
    snapshot = _synthetic_snapshot()
    result = compare_models(
        snapshot,
        SYNTHETIC_PATH,
        ["Model Alpha:max"],
        usage_error_factory=cli.CliUsageError,
    )
    rows = cast("list[dict[str, object]]", result["rows"])
    assert rows[0]["coding_index"] is None


def test_canonical_row_deduplication_across_selectors() -> None:
    snapshot = _synthetic_snapshot()
    result = compare_models(
        snapshot,
        SYNTHETIC_PATH,
        ["Model Alpha:max", "Model Alpha:max"],
        usage_error_factory=cli.CliUsageError,
    )
    rows = cast("list[dict[str, object]]", result["rows"])
    assert len(rows) == 1
    assert rows[0]["slug"] == "model-a-max"


def test_qa_rejects_multi_model_comparisons_with_compare_guidance(
    tmp_path: Path,
) -> None:
    snapshot_file = tmp_path / "snapshot.json"
    _ = snapshot_file.write_text(json.dumps(_synthetic_snapshot()), encoding="utf-8")

    with pytest.raises(cli.CliUsageError):
        _ = cli._qa_payload(  # pyright: ignore[reportPrivateUsage]
            argparse.Namespace(
                question="compare Model Alpha against Model Beta",
                snapshot=snapshot_file,
                model=None,
                provider=None,
                sort_by=None,
                order=None,
                limit=None,
            )
        )


def test_cli_and_rpc_parity_via_tmp_snapshot(tmp_path: Path) -> None:
    snapshot_file = tmp_path / "snapshot.json"
    _ = snapshot_file.write_text(json.dumps(_synthetic_snapshot()), encoding="utf-8")

    cli_args = argparse.Namespace(
        snapshot=snapshot_file,
        select=["Model Alpha:max,non-reasoning", "Model Beta"],
    )
    payload_cli = cli._compare_payload(cli_args)  # pyright: ignore[reportPrivateUsage]
    assert payload_cli["matched_models"] == 3

    rpc_input = (
        json.dumps(
            {
                "id": "test-123",
                "type": "compare",
                "args": {
                    "snapshot": str(snapshot_file),
                    "select": ["Model Alpha:max,non-reasoning", "Model Beta"],
                },
            }
        )
        + "\n"
    )
    rpc_stdout = io.StringIO()
    exit_code = cli.run_rpc(
        stdin=io.StringIO(rpc_input),
        stdout=rpc_stdout,
    )
    assert exit_code == 0
    rpc_lines = rpc_stdout.getvalue().strip().splitlines()
    assert len(rpc_lines) == 1
    response = cast("dict[str, object]", json.loads(rpc_lines[0]))
    assert response["id"] == "test-123"
    assert response["success"] is True
    data = cast("dict[str, object]", response["data"])
    assert data["matched_models"] == 3
    rows = cast("list[dict[str, object]]", data["rows"])
    assert [r["slug"] for r in rows] == [
        "model-a-max",
        "model-a-non-reasoning",
        "model-b-thinking-only",
    ]
