"""Filter-script default regression tests."""

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from artificial_analysis.contracts import as_dict
from filter_agent_models import (
    DEFAULT_SNAPSHOT,
    ensure_default_snapshot_fresh,
    load_rows,
)


class TestFilterAgentModelsDefaults(unittest.TestCase):
    def test_default_snapshot_uses_tmp_artifacts(self) -> None:
        assert (
            Path(tempfile.gettempdir())
            / "artifacts"
            / "artificial-analysis"
            / "full-data.json"
            == DEFAULT_SNAPSHOT
        )

    def test_default_snapshot_guard_rejects_stale_tmp_snapshot(self) -> None:
        stale_snapshot: dict[str, object] = {
            "meta": {"fetched_at": (datetime.now(UTC) - timedelta(days=2)).isoformat()},
        }

        with pytest.raises(ValueError, match="default snapshot is stale"):
            ensure_default_snapshot_fresh(
                DEFAULT_SNAPSHOT,
                stale_snapshot,
            )

    def test_default_snapshot_guard_allows_explicit_stale_snapshot(self) -> None:
        stale_snapshot: dict[str, object] = {
            "meta": {"fetched_at": "2000-01-01T00:00:00+00:00"},
        }

        ensure_default_snapshot_fresh(
            Path("fixtures/old-snapshot.json"),
            stale_snapshot,
        )

    def test_v2_rows_join_canonical_models_and_reject_non_finite_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "snapshot.json"
            _ = path.write_text(
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
            rows = load_rows(path, diagnostics=diagnostics)
        assert rows[0]["slug"] == "canonical"
        assert rows[0]["omni"] == -999.0
        raw_fields = as_dict(rows[0].get("raw_fields"))
        assert raw_fields["newField"] is True
        assert diagnostics[0]["code"] == "MISSING_MODEL_JOIN"


if __name__ == "__main__":
    _ = unittest.main()
