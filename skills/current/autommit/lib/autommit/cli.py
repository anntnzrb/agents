"""Command-line boundary for the portable autommit protocol."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NoReturn, cast

from autommit.client import ModelRequest, list_models
from autommit.config import ConfigOverrides, load_config
from autommit.errors import AutommitError
from autommit.orchestrate import RunOptions, run_orchestrated
from autommit.rewrite import run_rewrite
from autommit.service import apply, prepare, validate_plan

if TYPE_CHECKING:
    from collections.abc import Sequence

SCHEMA = "autommit/v1"
DEBUG_COMMANDS = ("prepare", "validate-plan", "apply", "schema")


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
        "--scope", choices=["auto", "staged", "all"], default="auto", type=str
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


def _run_parser() -> Parser:
    """Build the default single-command parser."""
    parser = Parser(
        prog="autommit",
        description="Plan and create atomic commits from the staged snapshot.",
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--scope", choices=["auto", "staged", "all"], default="auto", type=str
    )
    parser.add_argument("--context", action="append", default=[])
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--reasoning-effort", type=str, default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--smoke", type=str, default=None)
    parser.add_argument("--base", type=str, default=None)
    parser.add_argument("--filter", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("positional_context", nargs="*", default=[])
    return parser


def _run_options(arguments: argparse.Namespace) -> RunOptions:
    return RunOptions(
        repo=arguments.repo.resolve(),
        scope=cast('Literal["auto", "staged", "all"]', arguments.scope),
        context=tuple(arguments.context + arguments.positional_context),
        model=arguments.model,
        base_url=arguments.base_url,
        api_key=arguments.api_key,
        timeout=arguments.timeout,
        reasoning_effort=arguments.reasoning_effort,
        config_file=arguments.config,
        smoke=arguments.smoke,
        base=arguments.base,
        dry_run=bool(arguments.dry_run),
        json_output=bool(arguments.json_output),
    )


def _prepare_arguments(values: Sequence[str]) -> argparse.Namespace:
    context: list[str] = []
    repo: Path = Path.cwd()
    scope = "auto"
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
            if idx + 1 >= len(values) or values[idx + 1] not in (
                "auto",
                "staged",
                "all",
            ):
                raise AutommitError(
                    "usage_error", "--scope must be 'auto', 'staged' or 'all'."
                )
            scope = values[idx + 1]
            idx += 2
        elif tok.startswith("--scope="):
            val = tok.split("=", 1)[1]
            if val not in ("auto", "staged", "all"):
                raise AutommitError(
                    "usage_error", "--scope must be 'auto', 'staged' or 'all'."
                )
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
            "run": {
                "inputs": {
                    "scope": "auto | staged | all (optional, default: auto)",
                    "repo": "path (optional, default: cwd)",
                    "model": "string (optional)",
                    "base_url": "string (optional)",
                    "api_key": "string (optional)",
                    "timeout": "number (optional)",
                    "smoke": "shell command run per commit (optional)",
                    "dry_run": "boolean (optional)",
                    "context": "array of strings (optional)",
                },
                "returns": "Publication evidence with created commit objects",
            },
            "rewrite": {
                "inputs": {
                    "base": "revision to rebuild from (optional, default: origin/HEAD, origin/main, main)",
                    "repo": "path (optional, default: cwd)",
                    "model": "string (optional)",
                    "dry_run": "boolean (optional)",
                    "smoke": "shell command run per commit (optional)",
                    "context": "array of strings (optional)",
                },
                "returns": "Rewrite evidence with the rebuilt commit objects",
            },
            "prepare": {
                "inputs": {
                    "scope": "auto | staged | all (optional, default: auto)",
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


def _dispatch(arguments: argparse.Namespace) -> object:
    command: str = arguments.command
    if command == "schema":
        return _schema()
    if command == "prepare":
        repo: Path = arguments.repo.resolve()
        scope = cast('Literal["auto", "staged", "all"]', arguments.scope)
        context = tuple(arguments.context + arguments.positional_context)
        return prepare(repo, context, scope=scope)
    if command == "validate-plan":
        repo = arguments.repo.resolve()
        return validate_plan(
            repo,
            arguments.snapshot,
            arguments.plan_file.resolve(),
            require_split=arguments.require_split,
        )
    if command == "apply":
        repo = arguments.repo.resolve()
        snapshot: str = arguments.snapshot
        plan_file: Path = arguments.plan_file.resolve()
        decision_file: Path | None = (
            arguments.decision_file.resolve()
            if arguments.decision_file is not None
            else None
        )
        return apply(repo, snapshot, plan_file, decision_file)
    raise AutommitError("usage_error", "Unknown command.")


def _print_models(arguments: argparse.Namespace) -> int:
    """List the model ids the configured endpoint exposes."""
    config = load_config(
        arguments.repo.resolve(),
        overrides=ConfigOverrides(
            model=arguments.model,
            base_url=arguments.base_url,
            api_key=arguments.api_key,
            timeout=arguments.timeout,
            reasoning_effort=arguments.reasoning_effort,
            config_file=arguments.config,
        ),
        environ=os.environ,
    )
    request = ModelRequest(
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        timeout=config.timeout,
        reasoning_effort=config.reasoning_effort,
        system="",
        user="",
    )
    pattern = (arguments.filter or "").lower()
    ids = [item for item in list_models(request) if pattern in item.lower()]
    if arguments.json_output:
        _emit(_success("models", {"base_url": config.base_url, "models": ids}))
    else:
        for item in ids:
            sys.stdout.write(item + "\n")
        sys.stdout.flush()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the single command by default, or a hidden debug subcommand."""
    args_list = list(sys.argv[1:] if argv is None else argv)
    command = args_list[0] if args_list and not args_list[0].startswith("-") else ""
    try:
        if command in DEBUG_COMMANDS:
            if command == "prepare":
                arguments = _prepare_arguments(args_list[1:])
            else:
                arguments = build_parser().parse_args(args_list)
            result = _dispatch(arguments)
            _emit(_success(command, result))
            return 0
        run_args = args_list[1:] if command == "run" else args_list
        if command == "models":
            return _print_models(_run_parser().parse_args(args_list[1:]))
        if command == "rewrite":
            run_args = args_list[1:]
            return run_rewrite(_run_options(_run_parser().parse_args(run_args)))
        return run_orchestrated(_run_options(_run_parser().parse_args(run_args)))
    except AutommitError as err:
        _emit(_failure(command or "run", err), error=True)
        return err.exit_code
    except Exception as err:
        unknown = AutommitError("internal_error", f"Unexpected failure: {err}", 1)
        _emit(_failure(command or "run", unknown), error=True)
        return 1
