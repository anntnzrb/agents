#!/usr/bin/env -S uv run --script
"""
Generate a structured Apple Shortcuts blueprint.

Usage:
  uv run --script <skill-dir>/scripts/cli.py blueprint --goal "..." --devices "iPhone,Mac"
"""

from __future__ import annotations

import argparse
import json
from typing import Any


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _default_action_graph(trigger: str, automation_type: str) -> list[str]:
    steps: list[str] = []
    trig = trigger.lower()

    if "share" in trig:
        steps.append("Receive Input from Share Sheet")
    elif "siri" in trig:
        steps.append("Capture/resolve spoken parameters")
    elif automation_type in {"personal", "home"}:
        steps.append("Evaluate automation trigger payload")
    else:
        steps.append("Get initial input (or use defaults)")

    steps.extend(
        [
            "Normalize and validate input data",
            "Run core task actions",
            "Format output for target surfaces",
            "Emit final result (notification, file, clipboard, app handoff)",
        ]
    )
    return steps


def _validation_matrix(devices: list[str], automation_type: str) -> list[dict[str, str]]:
    matrix = [
        {"case": "Happy path", "expectation": "Correct output and completion status."},
        {"case": "Empty input", "expectation": "Graceful message and safe exit."},
        {"case": "Permission denied", "expectation": "Clear prompt or fallback path."},
        {"case": "Network/API failure", "expectation": "Retry or fallback output."},
    ]
    if len(devices) > 1:
        matrix.append(
            {
                "case": "Cross-device run parity",
                "expectation": "Equivalent behavior on each target device.",
            }
        )
    if automation_type in {"personal", "home"}:
        matrix.append(
            {
                "case": "Automation re-entry",
                "expectation": "No infinite loop; cooldown or state gate works.",
            }
        )
    return matrix


def build_blueprint(args: argparse.Namespace) -> dict[str, Any]:
    devices = _split_csv(args.devices)
    inputs = _split_csv(args.inputs)
    outputs = _split_csv(args.outputs)
    constraints = args.constraint or []
    failures = args.failure_mode or []

    return {
        "goal": args.goal,
        "target_devices": devices,
        "trigger": args.trigger,
        "automation_type": args.automation_type,
        "inputs": inputs,
        "outputs": outputs,
        "constraints": constraints,
        "expected_failures": failures,
        "action_graph": _default_action_graph(args.trigger, args.automation_type),
        "variables": [
            {"name": "input_payload", "type": "Any", "source": "trigger/input action"},
            {"name": "normalized_input", "type": "Dictionary|Text|List", "source": "normalize block"},
            {"name": "result", "type": "Any", "source": "core task block"},
        ],
        "failure_handling": [
            "Guard on required input before side-effect actions.",
            "Branch for permission and network failures.",
            "Provide explicit user-visible fallback output.",
        ],
        "validation_matrix": _validation_matrix(devices, args.automation_type),
    }


def render_markdown(bp: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("## Goal")
    lines.append(bp["goal"])
    lines.append("")
    lines.append("## Target Devices")
    for d in bp["target_devices"]:
        lines.append(f"- {d}")
    lines.append("")
    lines.append("## Trigger")
    lines.append(f"- {bp['trigger']}")
    lines.append(f"- Automation type: {bp['automation_type']}")
    lines.append("")
    lines.append("## Inputs")
    if bp["inputs"]:
        for x in bp["inputs"]:
            lines.append(f"- {x}")
    else:
        lines.append("- (none specified)")
    lines.append("")
    lines.append("## Outputs")
    if bp["outputs"]:
        for x in bp["outputs"]:
            lines.append(f"- {x}")
    else:
        lines.append("- (none specified)")
    lines.append("")
    lines.append("## Action Graph")
    for i, step in enumerate(bp["action_graph"], start=1):
        lines.append(f"{i}. {step}")
    lines.append("")
    lines.append("## Variables")
    for v in bp["variables"]:
        lines.append(f"- `{v['name']}` ({v['type']}): {v['source']}")
    lines.append("")
    lines.append("## Failure Handling")
    for step in bp["failure_handling"]:
        lines.append(f"- {step}")
    lines.append("")
    if bp["constraints"]:
        lines.append("## Constraints")
        for c in bp["constraints"]:
            lines.append(f"- {c}")
        lines.append("")
    if bp["expected_failures"]:
        lines.append("## Expected Failure Modes")
        for f in bp["expected_failures"]:
            lines.append(f"- {f}")
        lines.append("")
    lines.append("## Validation Matrix")
    for row in bp["validation_matrix"]:
        lines.append(f"- {row['case']}: {row['expectation']}")
    lines.append("")
    lines.append("## Notes")
    lines.append("- Replace generic action labels with exact Shortcuts action names before implementation.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Shortcuts blueprint.")
    parser.add_argument("--goal", required=True, help="Primary automation objective.")
    parser.add_argument("--devices", default="iPhone", help="Comma-separated devices.")
    parser.add_argument("--trigger", default="Manual run from Shortcuts app", help="Trigger source.")
    parser.add_argument("--inputs", default="", help="Comma-separated input contract.")
    parser.add_argument("--outputs", default="", help="Comma-separated output contract.")
    parser.add_argument(
        "--automation-type",
        choices=["manual", "personal", "home", "app-intents"],
        default="manual",
        help="Execution category.",
    )
    parser.add_argument(
        "--constraint",
        action="append",
        help="Add constraint lines (repeatable).",
    )
    parser.add_argument(
        "--failure-mode",
        action="append",
        help="Add expected failure mode lines (repeatable).",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format.",
    )
    args = parser.parse_args()

    blueprint = build_blueprint(args)
    if args.format == "json":
        print(json.dumps(blueprint, ensure_ascii=True, indent=2))
    else:
        print(render_markdown(blueprint))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
