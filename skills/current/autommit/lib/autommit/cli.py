"""Command-line boundary for the portable autommit protocol."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final, Literal, NoReturn, TypeIs, override

from autommit.client import ModelRequest, list_models
from autommit.config import ConfigOverrides, load_config
from autommit.errors import AutommitError
from autommit.orchestrate import RunOptions, run_orchestrated
from autommit.rewrite import run_rewrite
from autommit.service import apply, prepare, validate_plan


def _is_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


SCHEMA = "autommit/v1"
DEBUG_COMMANDS = ("prepare", "validate-plan", "apply", "schema")


class Parser(argparse.ArgumentParser):
    """Map parse failures into the structured protocol."""

    @override
    def error(self, message: str) -> NoReturn:
        raise AutommitError("usage_error", message, 2)


def build_parser() -> Parser:
    """Build the public command parser."""
    parser = Parser(prog="autommit", description="Autommit transaction boundary.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_cmd = subparsers.add_parser("prepare")
    _ = prepare_cmd.add_argument("--repo", type=Path, default=Path.cwd())
    _ = prepare_cmd.add_argument(
        "--scope", choices=["auto", "staged", "all"], default="auto", type=str
    )
    _ = prepare_cmd.add_argument("--context", action="append", default=[])
    _ = prepare_cmd.add_argument("positional_context", nargs="*", default=[])

    validate_cmd = subparsers.add_parser("validate-plan")
    _ = validate_cmd.add_argument("--repo", type=Path, default=Path.cwd())
    _ = validate_cmd.add_argument("--snapshot", required=True)
    _ = validate_cmd.add_argument("--plan-file", type=Path, required=True)
    _ = validate_cmd.add_argument("--require-split", action="store_true")

    apply_cmd = subparsers.add_parser("apply")
    _ = apply_cmd.add_argument("--repo", type=Path, default=Path.cwd())
    _ = apply_cmd.add_argument("--snapshot", required=True)
    _ = apply_cmd.add_argument("--plan-file", type=Path, required=True)
    _ = apply_cmd.add_argument("--decision-file", type=Path)

    _ = subparsers.add_parser("schema")
    return parser


MODELS_DISCOVERY_MODEL: Final[str] = "models-discovery-placeholder"


def _run_parser() -> Parser:
    """Build the default single-command parser."""
    parser = Parser(
        prog="autommit",
        description="Plan and create atomic commits from the staged snapshot.",
    )
    _ = parser.add_argument("--repo", type=Path, default=Path.cwd())
    _ = parser.add_argument(
        "--scope", choices=["auto", "staged", "all"], default="auto", type=str
    )
    _ = parser.add_argument("--context", action="append", default=[])
    _ = parser.add_argument("--model", type=str, default=None)
    _ = parser.add_argument("--base-url", type=str, default=None)
    _ = parser.add_argument("--api-key", type=str, default=None)
    _ = parser.add_argument("--timeout", type=float, default=None)
    _ = parser.add_argument("--reasoning-effort", type=str, default=None)
    _ = parser.add_argument("--smoke", type=str, default=None)
    _ = parser.add_argument("--base", type=str, default=None)
    _ = parser.add_argument("--filter", type=str, default=None)
    _ = parser.add_argument("--dry-run", action="store_true")
    _ = parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the staged pre-commit gate or rewrite frozen-tree whitespace gate",
    )
    _ = parser.add_argument("--json", action="store_true", dest="json_output")
    _ = parser.add_argument("positional_context", nargs="*", default=[])
    return parser


def _arg_path(
    args: argparse.Namespace, field: str, default: Path | None = None
) -> Path:
    val: object = getattr(args, field, None)
    if isinstance(val, Path):
        return val.resolve()
    if isinstance(val, str) and val:
        return Path(val).resolve()
    if default is not None:
        return default.resolve()
    raise AutommitError("usage_error", f"Missing or invalid --{field}")


def _arg_optional_path(args: argparse.Namespace, field: str) -> Path | None:
    val: object = getattr(args, field, None)
    if isinstance(val, Path):
        return val.resolve()
    if isinstance(val, str) and val:
        return Path(val).resolve()
    return None


def _arg_str(args: argparse.Namespace, field: str, default: str = "") -> str:
    val: object = getattr(args, field, None)
    return val if isinstance(val, str) else default


def _arg_optional_str(args: argparse.Namespace, field: str) -> str | None:
    val: object = getattr(args, field, None)
    return val if isinstance(val, str) else None


def _arg_float(args: argparse.Namespace, field: str) -> float | None:
    val: object = getattr(args, field, None)
    return float(val) if isinstance(val, (int, float)) else None


def _arg_bool(args: argparse.Namespace, field: str) -> bool:
    val: object = getattr(args, field, False)
    return bool(val)


def _arg_context(args: argparse.Namespace) -> tuple[str, ...]:
    context: list[str] = []
    c_val: object = getattr(args, "context", None)
    if _is_list(c_val):
        for item in c_val:
            if isinstance(item, str):
                context.append(item)
    p_val: object = getattr(args, "positional_context", None)
    if _is_list(p_val):
        for item in p_val:
            if isinstance(item, str):
                context.append(item)
    return tuple(context)


def _arg_scope(args: argparse.Namespace) -> Literal["auto", "staged", "all"]:
    val: object = getattr(args, "scope", "auto")
    match val:
        case "auto":
            return "auto"
        case "staged":
            return "staged"
        case "all":
            return "all"
        case _:
            raise AutommitError("usage_error", f"Invalid scope: {val!r}")


def _run_options(arguments: argparse.Namespace) -> RunOptions:
    return RunOptions(
        repo=_arg_path(arguments, "repo", default=Path.cwd()),
        scope=_arg_scope(arguments),
        context=_arg_context(arguments),
        model=_arg_optional_str(arguments, "model"),
        base_url=_arg_optional_str(arguments, "base_url"),
        api_key=_arg_optional_str(arguments, "api_key"),
        timeout=_arg_float(arguments, "timeout"),
        reasoning_effort=_arg_optional_str(arguments, "reasoning_effort"),
        smoke=_arg_optional_str(arguments, "smoke"),
        base=_arg_optional_str(arguments, "base"),
        dry_run=_arg_bool(arguments, "dry_run"),
        json_output=_arg_bool(arguments, "json_output"),
        no_verify=_arg_bool(arguments, "no_verify"),
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
                    "no_verify": "boolean (optional): skip the pre-commit gate",
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
    _ = stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
    _ = stream.flush()


def _dispatch(arguments: argparse.Namespace) -> object:
    command = _arg_str(arguments, "command")
    if command == "schema":
        return _schema()
    if command == "prepare":
        repo = _arg_path(arguments, "repo", default=Path.cwd())
        scope = _arg_scope(arguments)
        context = _arg_context(arguments)
        return prepare(repo, context, scope=scope)
    if command == "validate-plan":
        repo = _arg_path(arguments, "repo", default=Path.cwd())
        snapshot = _arg_str(arguments, "snapshot")
        plan_file = _arg_path(arguments, "plan_file")
        require_split = _arg_bool(arguments, "require_split")
        return validate_plan(
            repo,
            snapshot,
            plan_file,
            require_split=require_split,
        )
    if command == "apply":
        repo = _arg_path(arguments, "repo", default=Path.cwd())
        snapshot = _arg_str(arguments, "snapshot")
        plan_file = _arg_path(arguments, "plan_file")
        decision_file = _arg_optional_path(arguments, "decision_file")
        return apply(repo, snapshot, plan_file, decision_file)
    raise AutommitError("usage_error", "Unknown command.")


def _print_models(arguments: argparse.Namespace) -> int:
    """List the model ids the configured endpoint exposes.

    The models endpoint ignores the model id, so discovery must not require one.
    """
    config = load_config(
        overrides=ConfigOverrides(
            model=_arg_optional_str(arguments, "model") or MODELS_DISCOVERY_MODEL,
            base_url=_arg_optional_str(arguments, "base_url"),
            api_key=_arg_optional_str(arguments, "api_key"),
            timeout=_arg_float(arguments, "timeout"),
            reasoning_effort=_arg_optional_str(arguments, "reasoning_effort"),
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
    pattern = _arg_str(arguments, "filter").lower()
    ids = [item for item in list_models(request) if pattern in item.lower()]
    if _arg_bool(arguments, "json_output"):
        _emit(_success("models", {"base_url": config.base_url, "models": ids}))
    else:
        for item in ids:
            _ = sys.stdout.write(item + "\n")
        _ = sys.stdout.flush()
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
    except Exception as err:  # noqa: BLE001 - boundary catch to map error
        unknown = AutommitError("internal_error", f"Unexpected failure: {err}", 1)
        _emit(_failure(command or "run", unknown), error=True)
        return 1
