"""Filter-script default regression tests."""

# ruff: noqa: CPY001, D101, D102, D103, INP001, S101, PLR2004
from __future__ import annotations

import importlib.util
import json
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

    def test_v2_rows_join_canonical_models_and_reject_non_finite_values(self) -> None:
        module = load_filter_agent_models()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "snapshot.json"
            path.write_text(
                json.dumps(
                    {
                        "meta": {"fetched_at": datetime.now(UTC).isoformat()},
                        "models": [
                            {
                                "slug": "canonical",
                                "name": "Canonical",
                                "omniscience": float("nan"),
                                "raw_fields": {"newField": True},
                                "evidence": {"source": "api"},
                            },
                        ],
                        "hosts_models": [
                            {"slug": "provider_canonical", "model_slug": "canonical"},
                            {"slug": "provider_missing", "model_slug": "missing"},
                        ],
                    },
                ),
            )
            diagnostics: list[dict[str, object]] = []
            rows = module.load_rows(path, diagnostics=diagnostics)
        assert rows[0]["slug"] == "canonical"
        assert rows[0]["omni"] == -999.0
        assert rows[0]["raw_fields"]["newField"] is True
        assert diagnostics[0]["code"] == "MISSING_MODEL_JOIN"


if __name__ == "__main__":
    unittest.main()
