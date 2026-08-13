# Copyright 2026 Vals-live contributors.
# ruff: noqa: D102,S101,INP001
"""Exercise opt-in live source smoke checks."""

import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from vals_live.cli import main


@pytest.mark.live_smoke
@unittest.skipUnless(
    os.environ.get("RUN_LIVE_SMOKE") == "1", "opt-in official-source smoke"
)
class LiveSmokeTests(unittest.TestCase):
    """Exercise opt-in network-backed smoke evidence."""

    def test_official_catalog_evidence(self) -> None:
        out, err = io.StringIO(), io.StringIO()

        code = main(["catalog"], stdout=out, stderr=err)
        assert code == 0, err.getvalue()
        payload = json.loads(out.getvalue())
        assert payload["ok"]
        with TemporaryDirectory(prefix="vals-live-smoke-") as temp_dir:
            evidence = Path(temp_dir) / "vals"
            evidence.mkdir()
            (evidence / "latest.json").write_text(
                json.dumps({"source": "vals", "payload": payload}, ensure_ascii=False),
                encoding="utf-8",
            )
