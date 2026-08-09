# Copyright (c) 2026
from __future__ import annotations

import json
import os
from io import StringIO
from pathlib import Path

import pytest
from _path import LIB_DIR as _LIB_DIR  # noqa: F401
from livebench.cli import main


@pytest.mark.live_smoke
@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_SMOKE") != "1", reason="opt-in official-source smoke"
)
def test_live_smoke_records_dynamic_evidence(tmp_path: Path) -> None:
    stdout = StringIO()
    status = main(
        ["releases", "--cache-dir", str(tmp_path)], stdout=stdout, stderr=StringIO()
    )
    payload = json.loads(stdout.getvalue())
    assert status == 0
    assert payload["ok"] is True
    assert (
        payload["data"]["provenance"]["source_url"]
        if "source_url" in payload["data"]["provenance"]
        else payload["data"]["provenance"]["authority_url"]
    )
