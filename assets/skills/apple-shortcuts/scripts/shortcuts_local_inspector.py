from __future__ import annotations

import plistlib
import re
import sqlite3
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeGuard

DEFAULT_DB = Path("~/Library/Shortcuts/Shortcuts.sqlite").expanduser()
APPLE_REFERENCE_DATE = datetime(2001, 1, 1, tzinfo=UTC)
_OBJECT_REPLACEMENT = "\ufffc"
_IDENTIFIER_LINE_RE = re.compile(r"^(?P<name>.+)\s+\((?P<id>[0-9A-F-]{36})\)$")


@dataclass
class ShortcutRow:
    pk: int
    name: str
    workflow_id: str
    action_count: int
    associated_bundle: str | None
    hidden_from_library: bool
    action_blob: bytes | None


@dataclass
class SmartPromptPermission:
    pk: int
    shortcut_pk: int
    action_uuid: str
    mode: str
    status: str
    data_type: str
    destination_bundle: str
    destination_name: str
    source_origin: str


type JsonObject = dict[str, object]


def _is_object_dict(value: object) -> TypeGuard[JsonObject]:
    return type(value) is dict


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _row_value(row: sqlite3.Row, key: str) -> object:
    return row[key]


def _integer(value: object) -> int:
    return value if isinstance(value, int) else 0


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _bytes_or_none(value: object) -> bytes | None:
    return value if isinstance(value, bytes) else None


def clean_text(text: str) -> str:
    return " ".join(text.replace(_OBJECT_REPLACEMENT, "").split())


def redact_text(text: str) -> str:
    redacted = re.sub(r"(Bearer\s+)([^\s\"']+)", r"\1<REDACTED>", text, flags=re.IGNORECASE)
    redacted = re.sub(r"\b(cpk_[A-Za-z0-9._-]{12,})\b", "<REDACTED>", redacted)
    redacted = re.sub(r"\b(sk-[A-Za-z0-9._-]{12,})\b", "<REDACTED>", redacted)
    redacted = re.sub(r"\b(sk-proj-[A-Za-z0-9._-]{12,})\b", "<REDACTED>", redacted)
    redacted = re.sub(r"\b(xox[baprs]-[A-Za-z0-9-]{10,})\b", "<REDACTED>", redacted)
    return redacted


def redact_object(obj: object) -> object:
    if isinstance(obj, str):
        return redact_text(obj)
    if _is_object_list(obj):
        return [redact_object(item) for item in obj]
    if _is_object_dict(obj):
        return {key: redact_object(value) for key, value in obj.items()}
    return obj


def _extract_text(value: object) -> str:
    if isinstance(value, str):
        return clean_text(value)
    if _is_object_dict(value):
        if "string" in value and isinstance(value["string"], str):
            return clean_text(value["string"])
        if "Value" in value:
            return _extract_text(value["Value"])
    return ""


def _pluck(params: JsonObject, key: str) -> str:
    value = params.get(key)
    if value is None:
        return ""
    return _extract_text(value)


def _travel_label(field: object) -> str:
    if not _is_object_dict(field):
        return ""
    placemark = field.get("placemark")
    if not _is_object_dict(placemark):
        return ""
    address = placemark.get("addressDictionary", {})
    if _is_object_dict(address):
        for key in ("Name", "Street", "City"):
            name = address.get(key)
            if isinstance(name, str) and name.strip():
                return clean_text(name)
    return ""


def _quantity_label(field: object) -> str:
    if not _is_object_dict(field):
        return ""
    value = field.get("Value")
    if not _is_object_dict(value):
        return ""
    magnitude = value.get("Magnitude")
    unit = value.get("Unit")
    if _is_object_dict(magnitude):
        output_name = magnitude.get("OutputName")
        if isinstance(output_name, str) and output_name.strip():
            mag_str = f"var({output_name})"
        else:
            mag_str = "var"
    elif magnitude is None:
        mag_str = ""
    else:
        mag_str = str(magnitude)
    return clean_text(f"{mag_str} {unit}".strip())


def action_uuid(action: JsonObject) -> str:
    params = action.get("WFWorkflowActionParameters")
    if not _is_object_dict(params):
        return ""
    value = params.get("UUID")
    return value if isinstance(value, str) else ""


def summarize_action(action: JsonObject) -> str:
    identifier = str(action.get("WFWorkflowActionIdentifier", "<unknown>"))
    params = action.get("WFWorkflowActionParameters")
    if not _is_object_dict(params):
        return identifier

    if identifier == "is.workflow.actions.url":
        url = _pluck(params, "WFURLActionURL")
        return f"{identifier} | url={url}" if url else identifier
    if identifier == "is.workflow.actions.downloadurl":
        method = _pluck(params, "WFHTTPMethod")
        url = _pluck(params, "WFURL")
        bits = [identifier]
        if method:
            bits.append(f"method={method}")
        if url:
            bits.append(f"url={url}")
        return " | ".join(bits)
    if identifier == "is.workflow.actions.ask":
        prompt = _pluck(params, "WFAskActionPrompt")
        return f"{identifier} | prompt={prompt}" if prompt else identifier
    if identifier == "is.workflow.actions.gettext":
        text = _pluck(params, "WFTextActionText")
        return f"{identifier} | text={text}" if text else identifier
    if identifier == "is.workflow.actions.choosefrommenu":
        mode = params.get("WFControlFlowMode")
        if mode == 0:
            prompt = _pluck(params, "WFMenuPrompt")
            items = params.get("WFMenuItems")
            if _is_object_list(items):
                return f"{identifier} | menu={items} prompt={prompt!r}"
        if mode == 1:
            title = _pluck(params, "WFMenuItemTitle")
            return f"{identifier} | branch={title}" if title else identifier
        if mode == 2:
            return f"{identifier} | end-menu"
    if identifier == "is.workflow.actions.runworkflow":
        name = _pluck(params, "WFWorkflowName")
        if not name:
            wf = params.get("WFWorkflow")
            if _is_object_dict(wf):
                wf_name = wf.get("workflowName")
                if isinstance(wf_name, str):
                    name = clean_text(wf_name)
        return f"{identifier} | run={name}" if name else identifier
    if identifier == "is.workflow.actions.getvalueforkey":
        key = _pluck(params, "WFDictionaryKey")
        return f"{identifier} | key={key}" if key else identifier
    if identifier == "is.workflow.actions.gettraveltime":
        origin = _travel_label(params.get("WFGetDirectionsCustomLocation"))
        destination = _travel_label(params.get("WFDestination"))
        if origin or destination:
            return f"{identifier} | from={origin} to={destination}"
    if identifier == "is.workflow.actions.lowpowermode.set":
        return f"{identifier} | state=off" if params.get("OnValue") == 0 else f"{identifier} | state=on"
    if identifier == "is.workflow.actions.setbrightness":
        level = params.get("WFBrightness")
        if isinstance(level, (int, float)):
            return f"{identifier} | brightness={int(round(float(level) * 100))}%"
    if identifier == "is.workflow.actions.timer.start":
        label = _quantity_label(params.get("WFDuration"))
        return f"{identifier} | duration={label}" if label else identifier
    if identifier == "is.workflow.actions.health.quantity.log":
        sample_type = _pluck(params, "WFQuantitySampleType")
        quantity = _quantity_label(params.get("WFQuantitySampleQuantity"))
        if sample_type or quantity:
            return f"{identifier} | type={sample_type} quantity={quantity}"
    if identifier == "is.workflow.actions.dnd.set":
        mode = params.get("FocusModes")
        if _is_object_dict(mode):
            display = mode.get("DisplayString")
            if isinstance(display, str) and display.strip():
                return f"{identifier} | focus={clean_text(display)}"
    return identifier


def _db_connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def load_rows(db_path: Path) -> list[ShortcutRow]:
    query = """
    SELECT
      s.Z_PK,
      s.ZNAME,
      s.ZWORKFLOWID,
      COALESCE(s.ZACTIONCOUNT, 0) AS ACTION_COUNT,
      s.ZASSOCIATEDAPPBUNDLEIDENTIFIER,
      COALESCE(s.ZHIDDENFROMLIBRARYANDSYNC, 0) AS HIDDEN_FROM_LIBRARY,
      a.ZDATA
    FROM ZSHORTCUT s
    LEFT JOIN ZSHORTCUTACTIONS a ON a.ZSHORTCUT = s.Z_PK
    ORDER BY s.ZNAME COLLATE NOCASE;
    """
    conn = _db_connect(db_path)
    try:
        rows = conn.execute(query).fetchall()
    finally:
        conn.close()
    out: list[ShortcutRow] = []
    for row in rows:
        out.append(
            ShortcutRow(
                pk=_integer(_row_value(row, "Z_PK")),
                name=_text(_row_value(row, "ZNAME")),
                workflow_id=_text(_row_value(row, "ZWORKFLOWID")),
                action_count=_integer(_row_value(row, "ACTION_COUNT")),
                associated_bundle=_text(_row_value(row, "ZASSOCIATEDAPPBUNDLEIDENTIFIER")) or None,
                hidden_from_library=bool(_integer(_row_value(row, "HIDDEN_FROM_LIBRARY"))),
                action_blob=_bytes_or_none(_row_value(row, "ZDATA")),
            )
        )
    return out


def decode_actions(blob: bytes | None) -> list[JsonObject]:
    if not blob:
        return []
    parsed = plistlib.loads(blob)
    if not _is_object_list(parsed):
        return []
    return [item for item in parsed if _is_object_dict(item)]


def _decode_smart_prompt(blob: bytes) -> dict[str, str]:
    decoded = plistlib.loads(blob)
    if not _is_object_dict(decoded):
        return {}
    content_destination = decoded.get("ContentDestination", {})
    app_descriptor = content_destination.get("appDescriptor") if _is_object_dict(content_destination) else None
    source_attr = decoded.get("SourceContentAttribution", {})
    origin = source_attr.get("origin") if _is_object_dict(source_attr) else None
    destination_bundle = ""
    destination_name = ""
    source_origin = ""
    if _is_object_dict(app_descriptor):
        bundle = app_descriptor.get("BundleIdentifier")
        name = app_descriptor.get("Name")
        if isinstance(bundle, str):
            destination_bundle = clean_text(bundle)
        if isinstance(name, str):
            destination_name = clean_text(name)
    if _is_object_dict(origin):
        origin_id = origin.get("identifier")
        if isinstance(origin_id, str):
            source_origin = clean_text(origin_id)
    return {
        "mode": clean_text(str(decoded.get("Mode", ""))),
        "status": clean_text(str(decoded.get("Status", ""))),
        "data_type": clean_text(str(decoded.get("DataType", ""))),
        "destination_bundle": destination_bundle,
        "destination_name": destination_name,
        "source_origin": source_origin,
    }


def load_smart_prompts(db_path: Path) -> dict[int, list[SmartPromptPermission]]:
    query = "SELECT Z_PK, ZSHORTCUT, ZACTIONUUID, ZDATA FROM ZSMARTPROMPTPERMISSION ORDER BY ZSHORTCUT, Z_PK;"
    conn = _db_connect(db_path)
    try:
        rows = conn.execute(query).fetchall()
    finally:
        conn.close()
    grouped: dict[int, list[SmartPromptPermission]] = defaultdict(list)
    for row in rows:
        data = row["ZDATA"]
        if not isinstance(data, (bytes, bytearray)):
            continue
        decoded = _decode_smart_prompt(bytes(data))
        grouped[int(row["ZSHORTCUT"])].append(
            SmartPromptPermission(
                pk=int(row["Z_PK"]),
                shortcut_pk=int(row["ZSHORTCUT"]),
                action_uuid=str(row["ZACTIONUUID"] or ""),
                mode=decoded.get("mode", ""),
                status=decoded.get("status", ""),
                data_type=decoded.get("data_type", ""),
                destination_bundle=decoded.get("destination_bundle", ""),
                destination_name=decoded.get("destination_name", ""),
                source_origin=decoded.get("source_origin", ""),
            )
        )
    return grouped


def _apple_timestamp_to_local_str(value: object) -> str:
    if value is None:
        return ""
    try:
        seconds = float(value) if isinstance(value, (int, float, str)) else 0.0
        dt = APPLE_REFERENCE_DATE + timedelta(seconds=seconds)
    except (TypeError, ValueError, OverflowError):
        return ""
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def load_run_stats(db_path: Path) -> dict[int, dict[str, object]]:
    conn = _db_connect(db_path)
    try:
        outcome_rows = conn.execute(
            "SELECT ZSHORTCUT, ZOUTCOME, COUNT(*) AS C FROM ZSHORTCUTRUNEVENT GROUP BY ZSHORTCUT, ZOUTCOME"
        ).fetchall()
        source_rows = conn.execute(
            "SELECT ZSHORTCUT, COALESCE(ZSOURCE, '') AS SRC, COUNT(*) AS C FROM ZSHORTCUTRUNEVENT GROUP BY ZSHORTCUT, SRC"
        ).fetchall()
        last_rows = conn.execute(
            "SELECT ZSHORTCUT, MAX(ZDATE) AS LAST_DATE FROM ZSHORTCUTRUNEVENT GROUP BY ZSHORTCUT"
        ).fetchall()
    finally:
        conn.close()
    stats: dict[int, dict[str, object]] = {}
    for row in outcome_rows:
        shortcut_pk = _integer(_row_value(row, "ZSHORTCUT"))
        entry = stats.setdefault(
            shortcut_pk,
            {"total_runs": 0, "outcomes": {}, "sources": {}, "last_run_local": ""},
        )
        outcome_key = _text(_row_value(row, "ZOUTCOME"))
        count = _integer(_row_value(row, "C"))
        outcomes = entry["outcomes"]
        total_runs = entry["total_runs"]
        if _is_object_dict(outcomes) and isinstance(total_runs, int):
            outcomes[outcome_key] = count
            entry["total_runs"] = total_runs + count
    for row in source_rows:
        shortcut_pk = _integer(_row_value(row, "ZSHORTCUT"))
        entry = stats.setdefault(
            shortcut_pk,
            {"total_runs": 0, "outcomes": {}, "sources": {}, "last_run_local": ""},
        )
        sources = entry["sources"]
        if _is_object_dict(sources):
            sources[_text(_row_value(row, "SRC"))] = _integer(_row_value(row, "C"))
    for row in last_rows:
        shortcut_pk = _integer(_row_value(row, "ZSHORTCUT"))
        entry = stats.setdefault(
            shortcut_pk,
            {"total_runs": 0, "outcomes": {}, "sources": {}, "last_run_local": ""},
        )
        entry["last_run_local"] = _apple_timestamp_to_local_str(_row_value(row, "LAST_DATE"))
    return stats


def _run_shortcuts_cli(args: list[str]) -> str:
    proc = subprocess.run(["shortcuts", *args], check=True, capture_output=True, text=True)
    return proc.stdout


def _parse_identifier_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text:
        return None
    m = _IDENTIFIER_LINE_RE.match(text)
    if not m:
        return None
    return (m.group("name"), m.group("id"))


def load_folder_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    try:
        folder_output = _run_shortcuts_cli(["list", "--folders"])
    except (subprocess.CalledProcessError, FileNotFoundError):
        return mapping
    folders = [line.strip() for line in folder_output.splitlines() if line.strip()]
    for folder in folders:
        try:
            out = _run_shortcuts_cli(["list", "--folder-name", folder, "--show-identifiers"])
        except subprocess.CalledProcessError:
            continue
        for line in out.splitlines():
            parsed = _parse_identifier_line(line)
            if parsed:
                mapping[parsed[1]] = folder
    try:
        out_none = _run_shortcuts_cli(["list", "--folder-name", "none", "--show-identifiers"])
    except subprocess.CalledProcessError:
        out_none = ""
    for line in out_none.splitlines():
        parsed = _parse_identifier_line(line)
        if parsed:
            mapping[parsed[1]] = "<none>"
    return mapping


def matches(row: ShortcutRow, exact: set[str], contains: str | None, visible_only: bool) -> bool:
    if visible_only and row.hidden_from_library:
        return False
    if exact and row.name not in exact:
        return False
    if contains and contains.lower() not in row.name.lower():
        return False
    return True
