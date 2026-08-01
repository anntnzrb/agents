"""Filter-script default regression tests."""

# ruff: noqa: CPY001, D101, D102, D103, INP001, S101
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import _path  # noqa: F401
import pytest

if TYPE_CHECKING:
    from types import ModuleType


def load_filter_agent_models() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "filter_agent_models.py"
    )
    spec = importlib.util.spec_from_file_location(
        "filter_agent_models_defaults",
        script_path,
    )
    if spec is None or spec.loader is None:
        msg = f"cannot load script module: {script_path}"
        raise AssertionError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestFilterAgentModelsDefaults(unittest.TestCase):
    def test_default_snapshot_uses_tmp_artifacts(self) -> None:
        module = load_filter_agent_models()

        assert (
            Path(tempfile.gettempdir())
            / "artifacts"
            / "artificial-analysis"
            / "full-data.json"
            == module.DEFAULT_SNAPSHOT
        )

    def test_default_snapshot_guard_rejects_stale_tmp_snapshot(self) -> None:
        module = load_filter_agent_models()
        stale_snapshot = {
            "meta": {"fetched_at": (datetime.now(UTC) - timedelta(days=2)).isoformat()},
        }

        with pytest.raises(ValueError, match="default snapshot is stale"):
            module.ensure_default_snapshot_fresh(
                module.DEFAULT_SNAPSHOT,
                stale_snapshot,
            )

    def test_default_snapshot_guard_allows_explicit_stale_snapshot(self) -> None:
        module = load_filter_agent_models()
        stale_snapshot = {"meta": {"fetched_at": "2000-01-01T00:00:00+00:00"}}

        module.ensure_default_snapshot_fresh(
            Path("fixtures/old-snapshot.json"),
            stale_snapshot,
        )


if __name__ == "__main__":
    unittest.main()
