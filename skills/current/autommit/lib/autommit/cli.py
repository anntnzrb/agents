"""Command-line boundary for the portable autommit protocol."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NoReturn, cast

from expression import Error, Ok, Result

from autommit.errors import AutommitError
from autommit.service import apply, prepare, validate_plan

if TYPE_CHECKING:
    from collections.abc import Sequence

SCHEMA = "autommit/v1"


class Parser(argparse.ArgumentParser):
    """Map parse failures into the structured protocol."""

    def error(self, message: str) -> NoReturn:
        raise AutommitError("usage_error", message, 2)


def build_parser() -> Parser:
    """Build the public command parser."""
    parser = Parser(
        prog="autommit",
        description="Prepare and atomically publish model-planned Git commits.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    _ = commands.add_parser("schema", help="Describe the JSON protocol.")
    prepare_parser = commands.add_parser(
        "prepare", help="Recover, stage changes, and return exact planning evidence."
    )
    _ = prepare_parser.add_argument(
        "--scope",
        choices=["all", "staged"],
        default="all",
        help="Scope of changes to capture: all (default) or staged",
    )
    _ = prepare_parser.add_argument("--repo", default=".", metavar="PATH")
    validate = commands.add_parser(
        "validate-plan", help="Validate a plan against a snapshot."
    )
    _ = validate.add_argument("--snapshot", required=True)
    _ = validate.add_argument("--plan-file", type=Path, required=True)
    _ = validate.add_argument("--require-split", action="store_true")
    _ = validate.add_argument("--repo", default=".", metavar="PATH")
    apply_parser = commands.add_parser(
        "apply", help="Create and atomically publish commits."
    )
    _ = apply_parser.add_argument("--snapshot", required=True)
    _ = apply_parser.add_argument("--plan-file", type=Path, required=True)
    _ = apply_parser.add_argument("--decision-file", type=Path)
    _ = apply_parser.add_argument("--repo", default=".", metavar="PATH")
    return parser


def _prepare_arguments(
    values: Sequence[str],
) -> Result[argparse.Namespace, AutommitError]:
    context: list[str] = []
    repository = "."
    scope_val: Literal["all", "staged"] = "all"
    passthrough = False
    index = 0
    while index < len(values):
        value = values[index]
        if passthrough:
            context.append(value)
        elif value == "--":
            passthrough = True
        elif value in {"--context", "--repo", "--scope"}:
            index += 1
            if index >= len(values) or not values[index]:
                return Error(AutommitError("usage_error", f"{value} requires a value"))
            if value == "--context":
                context.append(values[index])
            elif value == "--repo":
                repository = values[index]
            elif value == "--scope":
                arg_scope = values[index]
                if arg_scope not in {"all", "staged"}:
                    return Error(
                        AutommitError(
                            "usage_error", "--scope must be 'all' or 'staged'"
                        )
                    )
                scope_val = cast('Literal["all", "staged"]', arg_scope)
        elif value.startswith("--context="):
            item = value.removeprefix("--context=")
            if not item:
                return Error(AutommitError("usage_error", "--context requires a value"))
            context.append(item)
        elif value.startswith("--repo="):
            repository = value.removeprefix("--repo=")
            if not repository:
                return Error(AutommitError("usage_error", "--repo requires a value"))
        elif value.startswith("--scope="):
            raw_scope = value.removeprefix("--scope=")
            if raw_scope not in {"all", "staged"}:
                return Error(
                    AutommitError("usage_error", "--scope must be 'all' or 'staged'")
                )
            scope_val = cast('Literal["all", "staged"]', raw_scope)
        elif value.startswith("-"):
            return Error(AutommitError("usage_error", f"Unsupported option: {value}"))
        else:
            context.append(value)
        index += 1
    return Ok(
        argparse.Namespace(
            command="prepare", context=context, repo=repository, scope=scope_val
        )
    )


def _schema() -> dict[str, object]:
    return {
        "protocol": SCHEMA,
        "commands": {
            "schema": "Describe this protocol without repository mutation.",
            "prepare": (
                "Recover, stage only when the index is empty, "
                "and return exact planning evidence."
            ),
            "validate-plan": (
                "Validate complete staged-diff coverage; optionally require a split."
            ),
            "apply": (
                "Prepare commits in a temporary worktree "
                "and publish the branch by compare-and-swap."
            ),
        },
        "plan": {
            "commits": [
                {
                    "summary": "non-empty string",
                    "details": ["optional detail"],
                    "changes": [
                        {
                            "path": "staged path",
                            "hunks": "all | {type:indices,indices:[1]} | "
                            "{type:lines,start:1,end:2}",
                        }
                    ],
                }
            ]
        },
        "decision": {
            "decision": "accept | split",
            "concerns": ["optional concern"],
            "rationale": "non-empty string",
        },
    }


def _success(command: str, data: object) -> dict[str, object]:
    return {"schema": SCHEMA, "ok": True, "command": command, "result": data}


def _failure(command: str, error: AutommitError) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "ok": False,
        "command": command,
        "error": {"code": error.code, "message": error.message},
    }


def _emit(payload: dict[str, object], *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
    stream.flush()


def _config_str(arguments: argparse.Namespace, field: str) -> str:
    """Extract a required str option from parsed args."""
    return cast("str", getattr(arguments, field))


def _config_bool(arguments: argparse.Namespace, field: str) -> bool:
    """Extract a required bool flag from parsed args."""
    return cast("bool", getattr(arguments, field))


def _config_path(arguments: argparse.Namespace, field: str) -> Path:
    """Extract a required path option from parsed args."""
    return cast("Path", getattr(arguments, field))


def _optional_path(arguments: argparse.Namespace, field: str) -> Path | None:
    """Extract an optional path option from parsed args."""
    return cast("Path | None", getattr(arguments, field))


def _config_str_list(arguments: argparse.Namespace, field: str) -> list[str]:
    """Extract a required string-list option from parsed args."""
    return cast("list[str]", getattr(arguments, field))


def _dispatch(
    arguments: argparse.Namespace,
) -> Result[object, AutommitError]:
    command = _config_str(arguments, "command")
    if command == "schema":
        return Ok(_schema())
    repo = _config_str(arguments, "repo")
    cwd = Path(repo).resolve()
    if command == "prepare":
        context = _config_str_list(arguments, "context")
        raw_scope = getattr(arguments, "scope", "all")
        scope: Literal["all", "staged"] = "staged" if raw_scope == "staged" else "all"
        return prepare(cwd, tuple(context), scope=scope)
    if command == "validate-plan":
        return validate_plan(
            cwd,
            _config_str(arguments, "snapshot"),
            _config_path(arguments, "plan_file"),
            require_split=_config_bool(arguments, "require_split"),
        )
    if command == "apply":
        return apply(
            cwd,
            _config_str(arguments, "snapshot"),
            _config_path(arguments, "plan_file"),
            _optional_path(arguments, "decision_file"),
        )
    return Error(AutommitError("usage_error", "Unknown command."))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and preserve protocol output on expected failures."""
    values = list(sys.argv[1:] if argv is None else argv)
    command = values[0] if values else "unknown"
    parser = build_parser()
    try:
        if command == "prepare" and not any(
            value in {"-h", "--help"} for value in values[1:]
        ):
            match _prepare_arguments(values[1:]):
                case Result(tag="ok", ok=parsed_args):
                    arguments = parsed_args
                case Result(tag="error", error=err):
                    _emit(_failure(command, err), error=True)
                    return err.exit_code
                case _:
                    return 2
        else:
            arguments = parser.parse_args(values)
        command = _config_str(arguments, "command")
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

    match result:
        case Result(tag="ok", ok=data):
            _emit(_success(command, data))
            return 0
        case Result(tag="error", error=err):
            _emit(_failure(command, err), error=True)
            return err.exit_code
        case _:
            return 2
