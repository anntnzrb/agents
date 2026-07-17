from __future__ import annotations

import json
import plistlib
import sqlite3
import sys
from pathlib import Path
from typing import TypeGuard

import inspect_local_shortcuts
import pytest
import shortcuts_local_inspector as inspector


def _is_object_dict(value: object) -> TypeGuard[dict[str, object]]:
    return type(value) is dict


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _create_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE ZSHORTCUT (Z_PK INTEGER, ZNAME TEXT, ZWORKFLOWID TEXT, ZACTIONCOUNT INTEGER, ZASSOCIATEDAPPBUNDLEIDENTIFIER TEXT, ZHIDDENFROMLIBRARYANDSYNC INTEGER);
        CREATE TABLE ZSHORTCUTACTIONS (ZSHORTCUT INTEGER, ZDATA BLOB);
        CREATE TABLE ZSHORTCUTRUNEVENT (ZSHORTCUT INTEGER, ZOUTCOME TEXT, ZSOURCE TEXT, ZDATE REAL);
        CREATE TABLE ZSMARTPROMPTPERMISSION (Z_PK INTEGER, ZSHORTCUT INTEGER, ZACTIONUUID TEXT, ZDATA BLOB);
        """,
    )
    actions = [
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
            "WFWorkflowActionParameters": {
                "UUID": "A",
                "WFTextActionText": "Bearer secret-token",
            },
        },
    ]
    smart_prompt = {
        "Mode": "Ask",
        "Status": "Allowed",
        "DataType": "Text",
        "ContentDestination": {
            "appDescriptor": {"BundleIdentifier": "com.example.app", "Name": "Example"},
        },
        "SourceContentAttribution": {"origin": {"identifier": "com.example.source"}},
    }
    conn.execute(
        "INSERT INTO ZSHORTCUT VALUES (1, 'Visible', 'ABC', 1, 'com.example.app', 0)",
    )
    conn.execute(
        "INSERT INTO ZSHORTCUTACTIONS VALUES (1, ?)",
        (plistlib.dumps(actions),),
    )
    conn.execute("INSERT INTO ZSHORTCUTRUNEVENT VALUES (1, 'success', 'widget', 0)")
    conn.execute("INSERT INTO ZSHORTCUTRUNEVENT VALUES (1, 'failure', 'widget', 1)")
    conn.execute(
        "INSERT INTO ZSMARTPROMPTPERMISSION VALUES (10, 1, 'A', ?)",
        (plistlib.dumps(smart_prompt),),
    )
    conn.commit()
    conn.close()


def test_sqlite_plist_stats_and_redaction(tmp_path: Path) -> None:
    database = tmp_path / "Shortcuts.sqlite"
    _create_database(database)
    rows = inspector.load_rows(database)
    assert rows[0].name == "Visible"
    actions = inspector.decode_actions(rows[0].action_blob)
    assert inspector.summarize_action(actions[0]).endswith("Bearer secret-token")
    redacted = inspector.redact_object(actions)
    assert _is_object_list(redacted)
    assert _is_object_dict(redacted[0])
    params = redacted[0]["WFWorkflowActionParameters"]
    assert _is_object_dict(params)
    secret = params["WFTextActionText"]
    assert isinstance(secret, str)
    assert secret.endswith("<REDACTED>")
    stats = inspector.load_run_stats(database)[1]
    assert stats["total_runs"] == 2
    assert stats["outcomes"] == {"failure": 1, "success": 1}
    permission = inspector.load_smart_prompts(database)[1][0]
    assert permission.destination_bundle == "com.example.app"
    assert permission.source_origin == "com.example.source"
    assert inspector.matches(rows[0], {"Visible"}, None, True)


def test_redaction_is_recursive_and_tolerates_empty_plist_blob() -> None:
    value = {"nested": ["sk-proj-abcdefghijkl", {"token": "Bearer top-secret"}]}
    redacted = inspector.redact_object(value)
    assert _is_object_dict(redacted)
    nested = redacted["nested"]
    assert _is_object_list(nested)
    assert nested[0] == "<REDACTED>"
    assert _is_object_dict(nested[1])
    assert nested[1]["token"] == "Bearer <REDACTED>"
    assert inspector.decode_actions(b"") == []


def test_inspection_cli_outputs_redacted_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "Shortcuts.sqlite"
    _create_database(database)
    monkeypatch.setattr(
        sys,
        "argv",
        ["inspect", "--db", str(database), "--json", "--raw", "--include-run-stats"],
    )
    assert inspect_local_shortcuts.main() == 0
    payload: object = json.loads(capsys.readouterr().out)
    assert _is_object_list(payload)
    assert _is_object_dict(payload[0])
    actions = payload[0]["actions"]
    assert _is_object_list(actions)
    assert _is_object_dict(actions[0])
    raw = actions[0]["raw"]
    assert _is_object_dict(raw)
    params = raw["WFWorkflowActionParameters"]
    assert _is_object_dict(params)
    assert params["WFTextActionText"] == "Bearer <REDACTED>"
