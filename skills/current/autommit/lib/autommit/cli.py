"""Command-line boundary for the portable autommit protocol."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NoReturn, cast

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
    parser = Parser(prog="autommit", description="Autommit transaction boundary.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_cmd = subparsers.add_parser("prepare")
    prepare_cmd.add_argument("--repo", type=Path, default=Path.cwd())
    prepare_cmd.add_argument(
        "--scope", choices=["staged", "all"], default="all", type=str
    )
    prepare_cmd.add_argument("--context", action="append", default=[])
    prepare_cmd.add_argument("positional_context", nargs="*", default=[])

    validate_cmd = subparsers.add_parser("validate-plan")
    validate_cmd.add_argument("--repo", type=Path, default=Path.cwd())
    validate_cmd.add_argument("--snapshot", required=True)
    validate_cmd.add_argument("--plan-file", type=Path, required=True)
    validate_cmd.add_argument("--require-split", action="store_true")

    apply_cmd = subparsers.add_parser("apply")
    apply_cmd.add_argument("--repo", type=Path, default=Path.cwd())
    apply_cmd.add_argument("--snapshot", required=True)
    apply_cmd.add_argument("--plan-file", type=Path, required=True)
    apply_cmd.add_argument("--decision-file", type=Path)

    subparsers.add_parser("schema")
    return parser


def _prepare_arguments(values: Sequence[str]) -> argparse.Namespace:
    context: list[str] = []
    repo: Path = Path.cwd()
    scope = "all"
    idx = 0
    double_dash = False
    while idx < len(values):
        tok = values[idx]
        if double_dash:
            context.append(tok)
            idx += 1
        elif tok == "--":
            double_dash = True
            idx += 1
        elif tok == "--repo":
            if idx + 1 >= len(values):
                raise AutommitError("usage_error", "--repo requires an argument.")
            repo = Path(values[idx + 1])
            idx += 2
        elif tok.startswith("--repo="):
            repo = Path(tok.split("=", 1)[1])
            idx += 1
        elif tok == "--scope":
            if idx + 1 >= len(values) or values[idx + 1] not in ("staged", "all"):
                raise AutommitError("usage_error", "--scope must be 'staged' or 'all'.")
            scope = values[idx + 1]
            idx += 2
        elif tok.startswith("--scope="):
            val = tok.split("=", 1)[1]
            if val not in ("staged", "all"):
                raise AutommitError("usage_error", "--scope must be 'staged' or 'all'.")
            scope = val
            idx += 1
        elif tok == "--context":
            if idx + 1 >= len(values):
                raise AutommitError("usage_error", "--context requires an argument.")
            context.append(values[idx + 1])
            idx += 2
        elif tok.startswith("--context="):
            context.append(tok.split("=", 1)[1])
            idx += 1
        elif tok.startswith("-"):
            raise AutommitError("usage_error", f"Unrecognized option: {tok}")
        else:
            context.append(tok)
            idx += 1
    return argparse.Namespace(
        command="prepare",
        repo=repo,
        scope=scope,
        context=context,
        positional_context=[],
    )


def _schema() -> dict[str, object]:
    return {
        "protocol": SCHEMA,
        "version": SCHEMA,
        "commands": {
            "prepare": {
                "inputs": {
                    "scope": "staged | all",
                    "repo": "path (optional, default: cwd)",
                    "context": "array of strings (optional)",
                },
                "returns": "Evidence object with snapshot and diff",
            },
            "validate-plan": {
                "inputs": {
                    "snapshot": "string",
                    "plan_file": "path",
                    "require_split": "boolean (optional)",
                    "repo": "path (optional, default: cwd)",
                },
                "returns": "Validation status with review requirement flag",
            },
            "apply": {
                "inputs": {
                    "snapshot": "string",
                    "plan_file": "path",
                    "decision_file": "path (optional)",
                    "repo": "path (optional, default: cwd)",
                },
                "returns": "Publication evidence with created commit objects",
            },
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
    return cast("str", getattr(arguments, field))


def _config_bool(arguments: argparse.Namespace, field: str) -> bool:
    return cast("bool", getattr(arguments, field))


def _config_path(arguments: argparse.Namespace, field: str) -> Path:
    return cast("Path", getattr(arguments, field))


def _optional_path(arguments: argparse.Namespace, field: str) -> Path | None:
    return cast("Path | None", getattr(arguments, field))


def _config_str_list(arguments: argparse.Namespace, field: str) -> list[str]:
    return cast("list[str]", getattr(arguments, field))


def _dispatch(arguments: argparse.Namespace) -> object:
    command = _config_str(arguments, "command")
    if command == "schema":
        return _schema()
    if command == "prepare":
        repo = _config_path(arguments, "repo").resolve()
        scope_str = _config_str(arguments, "scope")
        scope: Literal["staged", "all"] = "staged" if scope_str == "staged" else "all"
        flag_context = _config_str_list(arguments, "context")
        pos_context = _config_str_list(arguments, "positional_context")
        return prepare(repo, tuple(flag_context + pos_context), scope=scope)
    if command == "validate-plan":
        repo = _config_path(arguments, "repo").resolve()
        snapshot = _config_str(arguments, "snapshot")
        plan_file = _config_path(arguments, "plan_file").resolve()
        require_split = _config_bool(arguments, "require_split")
        return validate_plan(repo, snapshot, plan_file, require_split=require_split)
    if command == "apply":
        repo = _config_path(arguments, "repo").resolve()
        snapshot = _config_str(arguments, "snapshot")
        plan_file = _config_path(arguments, "plan_file").resolve()
        decision_file = _optional_path(arguments, "decision_file")
        if decision_file is not None:
            decision_file = decision_file.resolve()
        return apply(repo, snapshot, plan_file, decision_file)
    raise AutommitError("usage_error", "Unknown command.")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and preserve protocol output on expected failures."""
    args_list = list(sys.argv[1:] if argv is None else argv)
    command = args_list[0] if args_list and not args_list[0].startswith("-") else ""
    try:
        if command == "prepare":
            arguments = _prepare_arguments(args_list[1:])
        else:
            parser = build_parser()
            arguments = parser.parse_args(args_list)
        result = _dispatch(arguments)
        _emit(_success(command, result))
    except AutommitError as err:
        _emit(_failure(command or "autommit", err), error=True)
        return err.exit_code
    except Exception as err:
        unknown = AutommitError("internal_error", f"Unexpected failure: {err}", 1)
        _emit(_failure(command or "autommit", unknown), error=True)
        return 1
    else:
        return 0
