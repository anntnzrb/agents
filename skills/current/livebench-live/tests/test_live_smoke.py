# Copyright (c) 2026
import os
from io import StringIO
from typing import TYPE_CHECKING

import pytest
from tests._path import LIB_DIR

from livebench.cli import main
from livebench.contracts import as_dict, load_json

if TYPE_CHECKING:
    from pathlib import Path

_ = LIB_DIR


@pytest.mark.live_smoke
@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_SMOKE") != "1", reason="opt-in official-source smoke"
)
def test_live_smoke_records_dynamic_evidence(tmp_path: Path) -> None:
    stdout = StringIO()
    status = main(
        ["releases", "--cache-dir", str(tmp_path)], stdout=stdout, stderr=StringIO()
    )
    payload = as_dict(load_json(stdout.getvalue()))
    assert status == 0
    assert payload["ok"] is True
    data = as_dict(payload["data"])
    provenance = as_dict(data["provenance"])
    assert (
        provenance["source_url"]
        if "source_url" in provenance
        else provenance["authority_url"]
    )
