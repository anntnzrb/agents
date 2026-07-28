"""Argparse boundary for the raw-Git worktree lifecycle controller."""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Never

SCHEMA = "git-worktrees/v1"
ROOT = Path.home() / ".agents" / "worktrees"
DEFAULT_SETUP_TIMEOUT_SECONDS = 600
NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


class CliError(Exception):
    """An expected protocol error raised before the controller is invoked."""

    def __init__(
        self,
        code: str,
        message: str,
        details: Mapping[str, object] | None = None,
        exit_code: int = 2,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})
        self.exit_code = exit_code


class ProtocolArgumentParser(argparse.ArgumentParser):
    """Argparse parser which keeps ordinary parse errors inside the protocol."""

    def error(self, message: str) -> Never:
        raise CliError("usage_error", message)

    def exit(self, status: int = 0, message: str | None = None) -> Never:
        if status == 0:
            raise SystemExit(0)
        raise CliError("usage_error", (message or "invalid command line").strip())


def _json_argv(value: str) -> tuple[str, ...]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError("must be a JSON array of strings") from error
    if not isinstance(decoded, list) or not decoded or any(
        not isinstance(item, str) or not item for item in decoded
    ):
        raise argparse.ArgumentTypeError(
            "must be a nonempty JSON array of nonempty strings"
        )
    return tuple(decoded)


def _positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def build_parser() -> tuple[ProtocolArgumentParser, frozenset[str]]:
    parser = ProtocolArgumentParser(
        prog="git-worktrees",
        description="Local raw-Git worktree lifecycle controller.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("schema", help="Describe the JSON protocol.")

    inspect = commands.add_parser("inspect", help="Inspect a repository without mutation.")
    inspect.add_argument("--repo", required=True, metavar="PATH")

    acquire = commands.add_parser("acquire", help="Acquire a managed worktree lease.")
    acquire.add_argument("--repo", required=True, metavar="PATH")
    acquire.add_argument("--owner", required=True, metavar="ID")
    acquire.add_argument("--session-actor", required=True, metavar="ID")
    acquire.add_argument("--task", required=True, metavar="TEXT")
    acquire.add_argument("--name", required=True, metavar="SLUG")
    acquire.add_argument(
        "--mode",
        required=True,
        choices=("new-branch", "existing-branch", "detached-ephemeral"),
    )
    acquire.add_argument("--base", metavar="REV")
    acquire.add_argument("--branch", metavar="BRANCH")
    acquire.add_argument(
        "--setup-argv",
        action="append",
        default=[],
        type=_json_argv,
        metavar="JSON_ARRAY",
        help="Repeatable nonempty JSON argv array; no shell is used.",
    )
    acquire.add_argument(
        "--setup-timeout-seconds",
        type=_positive_integer,
        default=DEFAULT_SETUP_TIMEOUT_SECONDS,
        metavar="N",
    )

    status = commands.add_parser("status", help="Report a managed lease.")
    status.add_argument("--lease-id", required=True, metavar="ID")

    handoff = commands.add_parser("handoff", help="Create a worker handoff.")
    handoff.add_argument("--lease-id", required=True, metavar="ID")
    handoff.add_argument("--owner-token", required=True, metavar="TOKEN")
    handoff.add_argument("--actor", required=True, metavar="ID")
    handoff.add_argument("--session-actor", required=True, metavar="ID")

    complete = commands.add_parser("complete-handoff", help="Close a worker handoff.")
    complete.add_argument("--lease-id", required=True, metavar="ID")
    complete.add_argument("--handoff-token", required=True, metavar="TOKEN")
    complete.add_argument("--quiescent", action="store_true", required=True)

    release = commands.add_parser("release", help="Release a managed worktree lease.")
    release.add_argument("--lease-id", required=True, metavar="ID")
    release.add_argument("--owner-token", required=True, metavar="TOKEN")
    release.add_argument("--quiescent", action="store_true", required=True)
    return parser, frozenset(commands.choices)


def _require_nonblank(value: str, argument: str) -> None:
    if not value.strip():
        raise CliError(
            "usage_error",
            f"{argument} must not be blank",
            {"argument": argument},
        )


def _validate_arguments(args: argparse.Namespace) -> None:
    command = args.command
    if command == "schema":
        return
    if command == "inspect":
        _require_nonblank(args.repo, "--repo")
        return
    if command == "acquire":
        for argument in ("--repo", "--owner", "--session-actor", "--task", "--name"):
            _require_nonblank(getattr(args, argument[2:].replace("-", "_")), argument)
        if not NAME_PATTERN.fullmatch(args.name):
            raise CliError(
                "usage_error",
                "--name must be a lower-case ASCII slug",
                {"argument": "--name", "pattern": NAME_PATTERN.pattern},
            )
        if args.mode == "new-branch":
            if not args.base:
                raise CliError("usage_error", "new-branch mode requires --base")
            if args.branch is not None:
                raise CliError("usage_error", "new-branch mode forbids --branch")
        elif args.mode == "existing-branch":
            if not args.branch:
                raise CliError("usage_error", "existing-branch mode requires --branch")
            if args.base is not None:
                raise CliError("usage_error", "existing-branch mode forbids --base")
        else:
            if not args.base:
                raise CliError("usage_error", "detached-ephemeral mode requires --base")
            if args.branch is not None:
                raise CliError("usage_error", "detached-ephemeral mode forbids --branch")
        if args.base is not None:
            _require_nonblank(args.base, "--base")
        if args.branch is not None:
            _require_nonblank(args.branch, "--branch")
        return
    if command == "status":
        _require_nonblank(args.lease_id, "--lease-id")
        return
    if command == "handoff":
        for argument in ("--lease-id", "--owner-token", "--actor", "--session-actor"):
            _require_nonblank(getattr(args, argument[2:].replace("-", "_")), argument)
        return
    if command == "complete-handoff":
        _require_nonblank(args.lease_id, "--lease-id")
        _require_nonblank(args.handoff_token, "--handoff-token")
        return
    if command == "release":
        _require_nonblank(args.lease_id, "--lease-id")
        _require_nonblank(args.owner_token, "--owner-token")


def _schema_result() -> dict[str, object]:
    return {
        "version": SCHEMA,
        "root": str(ROOT),
        "verbs": {
            "schema": {"arguments": {}, "result": {"protocol": "discovery"}},
            "inspect": {
                "arguments": {"repo": "PATH"},
                "result": {
                    "identity": "repository identity or inspection finding",
                    "worktrees": "porcelain snapshot",
                    "leases": "durable managed leases",
                    "findings": "inspection findings",
                },
            },
            "acquire": {
                "arguments": {
                    "repo": "PATH",
                    "owner": "ID",
                    "session_actor": "ID",
                    "task": "TEXT",
                    "name": "SLUG",
                    "mode": "new-branch|existing-branch|detached-ephemeral",
                    "base": "REV when new-branch or detached-ephemeral",
                    "branch": "BRANCH when existing-branch",
                    "setup_argv": "repeatable JSON argv arrays",
                    "setup_timeout_seconds": "positive integer, default 600",
                },
                "result": {
                    "lease": {
                        "lease_id": "ID",
                        "path": "absolute path",
                        "ready": True,
                        "state": "ready",
                        "ref": "branch or null",
                        "mode": "requested mode",
                    },
                    "capabilities": {"owner_token": "opaque token returned once"},
                },
            },
            "status": {
                "arguments": {"lease_id": "ID"},
                "result": {"lease": "durable lease", "observation": "fresh safety state", "blockers": "release blockers", "safe_to_release": "boolean"},
            },
            "handoff": {
                "arguments": {
                    "lease_id": "ID",
                    "owner_token": "TOKEN",
                    "actor": "ID",
                    "session_actor": "ID",
                },
                "result": {"capabilities": {"handoff_token": "opaque token returned once"}},
            },
            "complete-handoff": {
                "arguments": {"lease_id": "ID", "handoff_token": "TOKEN", "quiescent": True},
                "result": {"handoff": "completed"},
            },
            "release": {
                "arguments": {"lease_id": "ID", "owner_token": "TOKEN", "quiescent": True},
                "result": {"lease": "released tombstone"},
            },
        },
        "exit_codes": {
            "0": "success",
            "2": "usage/input/controller error",
            "3": "safe refusal/conflict/precondition",
            "4": "Git/setup/runtime error",
            "127": "Git executable unavailable",
        },
    }


def _core_api() -> tuple[object, object, object, object, object, object, object, object, object]:
    """Import the core lazily so even import failures retain the JSON protocol."""

    from git_worktrees import (
        AcquireRequest,
        Controller,
        DomainError,
        SetupCommand,
        acquire,
        complete_handoff,
        handoff,
        inspect_repository,
        release,
        status,
    )

    return (
        AcquireRequest,
        Controller,
        DomainError,
        SetupCommand,
        acquire,
        complete_handoff,
        handoff,
        inspect_repository,
        release,
        status,
    )


def _dispatch(args: argparse.Namespace) -> object:
    if args.command == "schema":
        return _schema_result()

    (
        acquire_request_type,
        controller_type,
        _domain_error_type,
        setup_command_type,
        acquire_operation,
        complete_handoff_operation,
        handoff_operation,
        inspect_operation,
        release_operation,
        status_operation,
    ) = _core_api()

    if args.command == "inspect":
        return inspect_operation(Path(args.repo), controller_type())

    controller = controller_type()
    if args.command == "acquire":
        setup_commands = tuple(
            setup_command_type(argv=argv) for argv in args.setup_argv
        )
        request = acquire_request_type(
            repo=Path(args.repo),
            owner=args.owner,
            session_actor=args.session_actor,
            task=args.task,
            name=args.name,
            mode=args.mode,
            base=args.base,
            branch=args.branch,
            setup=setup_commands,
            setup_timeout_seconds=args.setup_timeout_seconds,
        )
        return acquire_operation(controller, request)
    if args.command == "status":
        return status_operation(controller, args.lease_id)
    if args.command == "handoff":
        return handoff_operation(
            controller,
            args.lease_id,
            args.owner_token,
            args.actor,
            args.session_actor,
        )
    if args.command == "complete-handoff":
        return complete_handoff_operation(
            controller,
            args.lease_id,
            args.handoff_token,
            args.quiescent,
        )
    if args.command == "release":
        return release_operation(
            controller,
            args.lease_id,
            args.owner_token,
            args.quiescent,
        )
    raise CliError("usage_error", "unknown command")


def _json_value(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _json_value(dataclasses.asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _emit(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(_json_value(payload), separators=(",", ":")) + "\n")


def _success(command: str, result: object) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "type": "response",
        "ok": True,
        "command": command,
        "result": result,
        "warnings": [],
    }


def _error(command: str, error: CliError) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "type": "error",
        "ok": False,
        "command": command,
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details,
        },
        "warnings": [],
    }


def _emit_error_and_exit(command: str, error: CliError) -> int:
    _emit(_error(command, error))
    return error.exit_code


def _requested_command(argv: Sequence[str], commands: frozenset[str]) -> str:
    for value in argv:
        if value in commands:
            return value
    return "unknown"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser, commands = build_parser()
    command = _requested_command(arguments, commands)
    try:
        args = parser.parse_args(arguments)
        command = args.command
        _validate_arguments(args)
        result = _dispatch(args)
    except SystemExit as error:
        if error.code == 0:
            return 0
        protocol_error = CliError("usage_error", "invalid command line")
        return _emit_error_and_exit(command, protocol_error)
    except argparse.ArgumentError as error:
        protocol_error = CliError("usage_error", str(error))
        return _emit_error_and_exit(command, protocol_error)
    except CliError as error:
        return _emit_error_and_exit(command, error)
    except FileNotFoundError:
        error = CliError("git_missing", "Git executable was not found", exit_code=127)
        return _emit_error_and_exit(command, error)
    except Exception as error:
        domain_error_type: type[BaseException] | None = None
        try:
            domain_error_type = _core_api()[2]
        except Exception:
            pass
        if domain_error_type is not None and isinstance(error, domain_error_type):
            details = getattr(error, "details", {})
            exit_code = getattr(error, "exit_code", 2)
            protocol_error = CliError(
                getattr(error, "code", "controller_error"),
                getattr(error, "message", str(error)),
                details if isinstance(details, Mapping) else {},
                exit_code if isinstance(exit_code, int) else 2,
            )
        else:
            protocol_error = CliError(
                "runtime_error", "The worktree controller failed unexpectedly", exit_code=4
            )
        return _emit_error_and_exit(command, protocol_error)
    _emit(_success(command, result))
    return 0
