# ruff: noqa: BLE001, C901, CPY001, D102, E501, EM101, PLR0912
"""Command-line boundary for the portable autommit protocol."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Never

if TYPE_CHECKING:
    from collections.abc import Sequence

from autommit.errors import AutommitError
from autommit.service import apply, prepare, validate_plan

SCHEMA = "autommit/v1"


class Parser(argparse.ArgumentParser):
    """Map parse failures into the structured protocol."""

    def error(self, message: str) -> Never:
        raise AutommitError("usage_error", message)


def build_parser() -> Parser:
    """Build the public command parser."""
    parser = Parser(
        prog="autommit",
        description="Prepare and atomically publish model-planned Git commits.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema", help="Describe the JSON protocol.")
    prepare_parser = commands.add_parser(
        "prepare",
        help="Recover, stage if needed, and return planning evidence.",
    )
    prepare_parser.add_argument("context", nargs="*", help="Free-form planner context.")
    prepare_parser.add_argument("--context", action="append", default=[])
    prepare_parser.add_argument("--repo", default=".", metavar="PATH")
    validate = commands.add_parser(
        "validate-plan", help="Validate a plan against a snapshot."
    )
    validate.add_argument("--snapshot", required=True)
    validate.add_argument("--plan-file", type=Path, required=True)
    validate.add_argument("--require-split", action="store_true")
    validate.add_argument("--repo", default=".", metavar="PATH")
    apply_parser = commands.add_parser(
        "apply", help="Create and atomically publish commits."
    )
    apply_parser.add_argument("--snapshot", required=True)
    apply_parser.add_argument("--plan-file", type=Path, required=True)
    apply_parser.add_argument("--decision-file", type=Path)
    apply_parser.add_argument("--repo", default=".", metavar="PATH")
    return parser


def _prepare_arguments(values: Sequence[str]) -> argparse.Namespace:
    context: list[str] = []
    repository = "."
    passthrough = False
    index = 0
    while index < len(values):
        value = values[index]
        if passthrough:
            context.append(value)
        elif value == "--":
            passthrough = True
        elif value in {"--context", "--repo"}:
            index += 1
            if index >= len(values) or not values[index]:
                raise AutommitError("usage_error", f"{value} requires a value")
            if value == "--context":
                context.append(values[index])
            else:
                repository = values[index]
        elif value.startswith("--context="):
            item = value.removeprefix("--context=")
            if not item:
                raise AutommitError("usage_error", "--context requires a value")
            context.append(item)
        elif value.startswith("--repo="):
            repository = value.removeprefix("--repo=")
            if not repository:
                raise AutommitError("usage_error", "--repo requires a value")
        elif value.startswith("-"):
            raise AutommitError("usage_error", f"Unsupported option: {value}")
        else:
            context.append(value)
        index += 1
    return argparse.Namespace(command="prepare", context=context, repo=repository)


def _schema() -> dict[str, object]:
    return {
        "protocol": SCHEMA,
        "commands": {
            "schema": "Describe this protocol without repository mutation.",
            "prepare": "Recover, stage only when the index is empty, and return exact planning evidence.",
            "validate-plan": "Validate complete staged-diff coverage; optionally require a split.",
            "apply": "Prepare commits in a temporary worktree and publish the branch by compare-and-swap.",
        },
        "plan": {
            "commits": [
                {
                    "summary": "non-empty string",
                    "details": ["optional detail"],
                    "changes": [
                        {
                            "path": "staged path",
                            "hunks": "all | {type:indices,indices:[1]} | {type:lines,start:1,end:2}",
                        }
                    ],
                }
            ]
        },
        "atomicity_decision": {
            "decision": "accept | split",
            "concerns": [],
            "rationale": "non-empty string",
        },
        "exit_codes": {
            "0": "success",
            "2": "usage, input, plan, or decision error",
            "3": "safe refusal because concurrent or recovered state differs",
            "4": "Git, filesystem, or runtime error",
            "127": "Git executable unavailable",
        },
    }


def _success(command: str, result: object) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "type": "response",
        "ok": True,
        "command": command,
        "result": result,
    }


def _failure(command: str, error: AutommitError) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "type": "error",
        "ok": False,
        "command": command,
        "error": {"code": error.code, "message": error.message},
    }


def _emit(payload: dict[str, object], *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    stream.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")


def _dispatch(arguments: argparse.Namespace) -> object:
    if arguments.command == "schema":
        return _schema()
    cwd = Path(arguments.repo).resolve()
    if arguments.command == "prepare":
        return prepare(cwd, tuple(arguments.context))
    if arguments.command == "validate-plan":
        return validate_plan(
            cwd,
            arguments.snapshot,
            arguments.plan_file,
            require_split=arguments.require_split,
        )
    if arguments.command == "apply":
        return apply(
            cwd,
            arguments.snapshot,
            arguments.plan_file,
            arguments.decision_file,
        )
    raise AutommitError("usage_error", "Unknown command.")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and preserve protocol output on expected failures."""
    values = list(sys.argv[1:] if argv is None else argv)
    command = values[0] if values else "unknown"
    parser = build_parser()
    try:
        if command == "prepare" and not any(
            value in {"-h", "--help"} for value in values[1:]
        ):
            arguments = _prepare_arguments(values[1:])
        else:
            arguments = parser.parse_args(values)
        command = arguments.command
        result = _dispatch(arguments)
    except AutommitError as error:
        _emit(_failure(command, error), error=True)
        return error.exit_code
    except KeyboardInterrupt:
        error = AutommitError("interrupted", "Autommit was interrupted.", 4)
        _emit(_failure(command, error), error=True)
        return error.exit_code
    except Exception:
        error = AutommitError(
            "runtime_error",
            "Autommit failed unexpectedly; repository state was preserved.",
            4,
        )
        _emit(_failure(command, error), error=True)
        return error.exit_code
    _emit(_success(command, result))
    return 0
