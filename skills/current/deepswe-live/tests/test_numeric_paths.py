"""Regression coverage for malformed published numeric values."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from deepswe.analysis import _metric_value  # pyright: ignore[reportPrivateUsage]
from deepswe.cli import (
    _comparison_numeric,  # pyright: ignore[reportPrivateUsage]
    _numeric,  # pyright: ignore[reportPrivateUsage]
    _stats_for_rows,  # pyright: ignore[reportPrivateUsage]
)
from deepswe.contracts import finite_number


def test_overflow_is_unavailable_on_every_analysis_path() -> None:
    """An oversized JSON integer must not crash stats or either comparison mode."""
    value = 10**400
    row: dict[str, object] = {
        "pass_at_1": value,
        "metrics": {
            "pass_at_1": {
                "normalized_value": value,
                "comparison_eligibility": "eligible",
            }
        },
    }
    assert finite_number(value) is None
    assert _numeric(value) is None
    for strict in (False, True):
        assert _metric_value(row, "pass_at_1", strict_semantics=strict) is None
        number, _ = _comparison_numeric(row, "pass_at_1", strict_semantics=strict)
        assert number is None
        result = _stats_for_rows([row], strict_semantics=strict)
        assert result["row_count"] == 1
        assert result["numeric_ranges"] == {}


@pytest.mark.parametrize(
    "command", [["stats"], ["compare"], ["compare", "--strict-compare"]]
)
def test_public_cli_accepts_oversized_snapshot_numbers(
    tmp_path: Path, command: list[str]
) -> None:
    """Stats and both comparison kernels must finish with real snapshot files."""
    snapshot = tmp_path / "snapshot.json"
    _ = snapshot.write_text(
        json.dumps(
            {
                "benchmark_version": "v1.1",
                "rows": [{"model": "fixture", "pass_at_1": 10**400}],
            }
        ),
        encoding="utf-8",
    )
    cli = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"
    args = (
        ["--snapshot", str(snapshot)]
        if command[0] == "stats"
        else [str(snapshot), str(snapshot)]
    )
    result = subprocess.run(
        [sys.executable, str(cli), *command, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert '"ok":true' in result.stdout
