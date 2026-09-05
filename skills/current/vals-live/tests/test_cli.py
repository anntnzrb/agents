# Copyright 2026 Vals-live contributors.
"""Exercise the one-object vals-live CLI contract."""

import io
import json
import unittest
from typing import cast
from unittest.mock import patch

from _path import FIXTURES
from vals_live.cli import main


def _data(payload: dict[str, object]) -> dict[str, object]:
    """Return the data object of a CLI envelope."""
    return cast("dict[str, object]", payload["data"])


def _error(payload: dict[str, object]) -> dict[str, object]:
    """Return the error object of a CLI envelope."""
    return cast("dict[str, object]", payload["error"])


def _rows(data: dict[str, object]) -> list[dict[str, object]]:
    """Return the rows list of a command data object."""
    return cast("list[dict[str, object]]", data["rows"])


class CLITests(unittest.TestCase):
    """Verify compact success and failure envelopes."""

    def invoke(self, *args: str) -> tuple[int, dict[str, object], str]:
        out, err = io.StringIO(), io.StringIO()
        code = main(list(args), stdout=out, stderr=err)
        lines = out.getvalue().splitlines()
        assert len(lines) == 1, out.getvalue()
        payload = cast("dict[str, object]", json.loads(lines[0]))
        assert out.getvalue().strip() == json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        )
        assert isinstance(payload, dict)
        return code, payload, err.getvalue()

    def snapshot(self, relative: str) -> str:
        return str(FIXTURES / relative)

    def test_schema(self) -> None:
        code, payload, stderr = self.invoke("schema")
        assert code == 0
        assert payload["schema_version"] == "1"
        assert stderr == ""

    def test_catalog_models_benchmark_model_commands(self) -> None:
        code, payload, _ = self.invoke(
            "catalog", "--snapshot", self.snapshot("catalog/current.json")
        )
        assert code == 0
        assert payload["command"] == "catalog"
        assert _rows(_data(payload))
        code, payload, _ = self.invoke(
            "models", "--snapshot", self.snapshot("models/new-variant.json")
        )
        assert code == 0
        assert len(_rows(_data(payload))) >= 2
        code, payload, _ = self.invoke(
            "benchmark",
            "--benchmark",
            "code-migration",
            "--snapshot",
            self.snapshot("records/coding-compare.json"),
        )
        assert code == 0
        benchmark = cast("dict[str, object]", _data(payload)["benchmark"])
        assert benchmark["benchmark_id"] == "vals:benchmark:code_migration"
        code, payload, _ = self.invoke(
            "model",
            "--model",
            "Model A",
            "--snapshot",
            self.snapshot("records/coding-compare.json"),
        )
        assert code == 0
        assert _rows(_data(payload))[0]["model"] == "Model A"

    def test_compare_and_dynamic_unknown(self) -> None:
        code, payload, _ = self.invoke(
            "compare",
            "--models",
            "Model A,Model B,Model C",
            "--benchmarks",
            "code-migration",
            "--snapshot",
            self.snapshot("records/coding-compare.json"),
        )
        assert code == 0
        assert payload["schema_version"] == "1"
        assert len(_rows(_data(payload))) == 3
        assert "rankings" in _data(payload)
        code, payload, _ = self.invoke(
            "diagnose", "--snapshot", self.snapshot("pages/unknown-score.json")
        )
        assert code == 0
        warnings = cast("list[dict[str, object]]", _data(payload)["warnings"])
        assert any(item["code"] == "UNKNOWN_SCORE_SEMANTICS" for item in warnings)

    def test_diff_and_snapshot_metadata(self) -> None:
        code, payload, _ = self.invoke(
            "catalog-diff",
            "--left",
            self.snapshot("catalog/baseline.json"),
            "--right",
            self.snapshot("catalog/changed.json"),
        )
        assert code == 0
        diff = cast("dict[str, object]", _data(payload)["catalog_diff"])
        assert diff["added"]
        assert diff["renamed"]

    def test_help_is_one_success_object(self) -> None:
        code, payload, stderr = self.invoke("--help")
        assert code == 0
        assert payload["ok"]
        assert payload["command"] == "help"
        assert "usage" in _data(payload)
        assert stderr == ""

    def test_invalid_snapshot_is_configuration_error(self) -> None:
        code, payload, stderr = self.invoke(
            "catalog", "--snapshot", str(FIXTURES / "missing-snapshot.json")
        )
        assert code == 2
        assert not payload["ok"]
        assert _error(payload)["code"] == "SNAPSHOT_INVALID"
        assert stderr == ""

    def test_unexpected_exception_still_emits_one_object(self) -> None:

        with patch(
            "vals_live.cli.dispatch",
            side_effect=NameError("programmer bug?token=secret"),
        ):
            code, payload, stderr = self.invoke("schema")
        assert code == 1
        assert not payload["ok"]
        assert _error(payload)["code"] == "INTERNAL_ERROR"
        details = cast("dict[str, object]", _error(payload)["details"])
        assert details["reason"] == ("programmer bug?token=<redacted>")
        assert "secret" not in json.dumps(details)
        assert stderr == ""

    def test_errors_are_one_object(self) -> None:
        code, payload, stderr = self.invoke(
            "benchmark",
            "--benchmark",
            "missing",
            "--snapshot",
            self.snapshot("catalog/current.json"),
        )
        assert code != 0
        assert not payload["ok"]
        assert payload["schema_version"] == "1"
        assert stderr == ""


if __name__ == "__main__":
    _ = unittest.main()
