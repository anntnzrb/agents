"""
Inspect local Apple Shortcuts definitions from Shortcuts.sqlite.

Usage:
  uv run --script <skill-dir>/scripts/cli.py inspect
  uv run --script <skill-dir>/scripts/cli.py inspect --name "Action Button"
  uv run --script <skill-dir>/scripts/cli.py inspect --include-run-stats --include-smart-prompts
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from shortcuts_local_inspector import (
    DEFAULT_DB,
    action_uuid,
    decode_actions,
    load_folder_map,
    load_rows,
    load_run_stats,
    load_smart_prompts,
    matches,
    redact_object,
    summarize_action,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect local Apple Shortcuts action graphs."
    )
    parser.add_argument(
        "--db", default=str(DEFAULT_DB), help="Path to Shortcuts.sqlite"
    )
    parser.add_argument(
        "--name", action="append", help="Exact shortcut name (repeatable)"
    )
    parser.add_argument("--contains", help="Substring filter for shortcut names")
    parser.add_argument(
        "--json", action="store_true", help="Print JSON instead of text output"
    )
    parser.add_argument(
        "--raw", action="store_true", help="Include full decoded action objects"
    )
    parser.add_argument(
        "--no-redact", action="store_true", help="Disable redaction in strings"
    )
    parser.add_argument(
        "--visible-only",
        action="store_true",
        help="Skip hidden shortcuts (for example hidden templates/placeholders).",
    )
    parser.add_argument(
        "--include-run-stats",
        action="store_true",
        help="Include run-event stats from ZSHORTCUTRUNEVENT.",
    )
    parser.add_argument(
        "--include-smart-prompts",
        action="store_true",
        help="Include decoded ZSMARTPROMPTPERMISSION entries.",
    )
    parser.add_argument(
        "--include-folders",
        action="store_true",
        help="Map workflow IDs to folders via `shortcuts list` CLI.",
    )
    return parser.parse_args()


def _render_text(results: list[dict[str, Any]]) -> str:
    if not results:
        return "No shortcuts matched filters."
    lines: list[str] = []
    for shortcut in results:
        lines.append(f"Shortcut: {shortcut['name']}")
        lines.append(
            "  id={pk} workflow_id={workflow_id} action_count={action_count}".format(
                **shortcut
            )
        )
        if shortcut.get("hidden_from_library"):
            lines.append("  hidden_from_library=true")
        if shortcut.get("folder"):
            lines.append(f"  folder={shortcut['folder']}")
        if shortcut.get("associated_bundle"):
            lines.append(f"  associated_app={shortcut['associated_bundle']}")
        run_stats = shortcut.get("run_stats")
        if isinstance(run_stats, dict):
            lines.append(
                "  runs={total_runs} outcomes={outcomes} sources={sources} last_run={last_run}".format(
                    total_runs=run_stats.get("total_runs", 0),
                    outcomes=run_stats.get("outcomes", {}),
                    sources=run_stats.get("sources", {}),
                    last_run=run_stats.get("last_run_local", ""),
                )
            )
        actions = shortcut.get("actions", [])
        if not actions:
            lines.append("  actions: (none)")
        else:
            for action in actions:
                line = f"  {action['index']}. {action['summary']}"
                if action.get("action_uuid"):
                    line += f" [UUID={action['action_uuid']}]"
                lines.append(line)
        smart_prompts = shortcut.get("smart_prompts", [])
        if smart_prompts:
            lines.append("  smart_prompt_permissions:")
            for item in smart_prompts:
                lines.append(
                    "    - action_uuid={action_uuid} action_index={action_index} mode={mode} status={status} dest_bundle={dest} source_origin={origin}".format(
                        action_uuid=item.get("action_uuid", ""),
                        action_index=item.get("action_index", ""),
                        mode=item.get("mode", ""),
                        status=item.get("status", ""),
                        dest=item.get("destination_bundle", ""),
                        origin=item.get("source_origin", ""),
                    )
                )
        lines.append("")
    return "\n".join(lines).rstrip()


def main() -> int:
    args = _parse_args()
    db_path = Path(args.db).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"Shortcuts DB not found: {db_path}")

    rows = load_rows(db_path)
    exact = set(args.name or [])

    run_stats_by_shortcut = load_run_stats(db_path) if args.include_run_stats else {}
    smart_prompts_by_shortcut = (
        load_smart_prompts(db_path) if args.include_smart_prompts else {}
    )
    folder_map = load_folder_map() if args.include_folders else {}

    results: list[dict[str, Any]] = []
    for row in rows:
        if not matches(row, exact, args.contains, args.visible_only):
            continue
        decoded = decode_actions(row.action_blob)
        if not args.no_redact:
            decoded = redact_object(decoded)

        actions = []
        action_index_by_uuid: dict[str, int] = {}
        for idx, action in enumerate(decoded, start=1):
            act_uuid = action_uuid(action)
            if act_uuid:
                action_index_by_uuid[act_uuid] = idx
            entry = {
                "index": idx,
                "identifier": action.get("WFWorkflowActionIdentifier", ""),
                "summary": summarize_action(action),
                "action_uuid": act_uuid,
            }
            if args.raw:
                entry["raw"] = action
            actions.append(entry)

        item: dict[str, Any] = {
            "pk": row.pk,
            "name": row.name,
            "workflow_id": row.workflow_id,
            "action_count": row.action_count,
            "associated_bundle": row.associated_bundle or "",
            "hidden_from_library": row.hidden_from_library,
            "folder": folder_map.get(row.workflow_id, ""),
            "actions": actions,
        }
        if args.include_run_stats:
            item["run_stats"] = run_stats_by_shortcut.get(
                row.pk,
                {"total_runs": 0, "outcomes": {}, "sources": {}, "last_run_local": ""},
            )
        if args.include_smart_prompts:
            perms = smart_prompts_by_shortcut.get(row.pk, [])
            item["smart_prompts"] = [
                {
                    "pk": perm.pk,
                    "action_uuid": perm.action_uuid,
                    "action_index": action_index_by_uuid.get(perm.action_uuid, 0),
                    "mode": perm.mode,
                    "status": perm.status,
                    "data_type": perm.data_type,
                    "destination_bundle": perm.destination_bundle,
                    "destination_name": perm.destination_name,
                    "source_origin": perm.source_origin,
                }
                for perm in perms
            ]
        results.append(item)

    if args.json:
        print(json.dumps(results, ensure_ascii=True, indent=2, default=str))
        return 0

    print(_render_text(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
