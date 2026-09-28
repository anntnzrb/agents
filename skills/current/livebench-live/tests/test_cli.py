# Copyright (c) 2026
import json
from io import StringIO

from tests._path import SKILL_DIR

from livebench.cli import main
from livebench.contracts import as_dict, as_list, load_json

FIXTURES = SKILL_DIR / "tests" / "fixtures"


def invoke(*argv: str) -> tuple[int, dict[str, object], str]:
    stdout = StringIO()
    stderr = StringIO()
    status = main(list(argv), stdout=stdout, stderr=stderr)
    lines = stdout.getvalue().splitlines()
    assert len(lines) == 1
    payload = as_dict(load_json(lines[0]))
    assert stdout.getvalue().strip() == json.dumps(
        payload, separators=(",", ":"), ensure_ascii=False
    )
    return status, payload, stderr.getvalue()


def test_catalog_success_has_required_data_fields() -> None:
    status, payload, stderr = invoke(
        "catalog", "--snapshot", str(FIXTURES / "catalog/current.json")
    )
    assert status == 0
    assert payload["ok"] is True
    assert payload["schema_version"] == "1"
    data = as_dict(payload["data"])
    scope = as_dict(data["scope"])
    assert scope["source"] == "livebench"
    assert "provenance" in data
    assert stderr == ""


def test_schema_is_offline_and_fixed_interface_is_additive() -> None:
    status, payload, stderr = invoke("schema")
    assert status == 0
    data = as_dict(payload["data"])
    commands = as_list(data["commands"])
    assert commands[:3] == ["releases", "catalog", "leaderboard"]
    assert "categories" in as_dict(data["dynamic_rules"])
    assert stderr == ""
