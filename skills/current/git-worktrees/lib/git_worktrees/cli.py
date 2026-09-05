"""Argparse boundary for the raw-Git worktree lifecycle controller."""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Never, TypeGuard, cast

if TYPE_CHECKING:
    from git_worktrees.controller import Controller
    from git_worktrees.errors import DomainError
    from git_worktrees.models import AcquireRequest, Mode, SetupCommand

from git_worktrees.paths import default_root

SCHEMA = "git-worktrees/v1"
ROOT = default_root().resolve()
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
        """Store the machine-readable code, message, and exit code."""
        super().__init__(message)
        self.code: str = code
        self.message: str = message
        self.details: Mapping[str, object] = dict(details or {})
        self.exit_code: int = exit_code


class ProtocolArgumentParser(argparse.ArgumentParser):
    """Argparse parser which keeps ordinary parse errors inside the protocol."""

    # typing.override needs 3.12+; this ignore marks the intentional override.
    def error(self, message: str) -> Never:  # pyright: ignore[reportImplicitOverride]
        """Map parse failures into the protocol envelope."""
        raise CliError("usage_error", message)

    # typing.override needs 3.12+; this ignore marks the intentional override.
    def exit(  # pyright: ignore[reportImplicitOverride]
        self, status: int = 0, message: str | None = None
    ) -> Never:
        """Map parser exits into the protocol envelope."""
        if status == 0:
            raise SystemExit(0)
        raise CliError("usage_error", (message or "invalid command line").strip())


def _is_nonempty_list(value: object) -> TypeGuard[list[object]]:
    """Check for a nonempty list (elements validated by callers)."""
    return bool(value) and isinstance(value, list)


def _is_str_dict(value: object) -> TypeGuard[dict[str, object]]:
    """Check for a plain string-keyed dict."""
    return isinstance(value, dict)


def _json_argv(value: str) -> tuple[str, ...]:
    try:
        decoded = cast("object", json.loads(value))
    except json.JSONDecodeError as error:
        msg = "must be a JSON array of strings"
        raise argparse.ArgumentTypeError(msg) from error
    msg = "must be a nonempty JSON array of nonempty strings"
    if not _is_nonempty_list(decoded):
        raise argparse.ArgumentTypeError(msg)
    items: list[str] = []
    for item in decoded:
        if not isinstance(item, str) or not item:
            raise argparse.ArgumentTypeError(msg)
        items.append(item)
    return tuple(items)


def _positive_integer(value: str) -> int:
    """Parse a positive integer CLI value."""
    msg = "must be a positive integer"
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(msg) from error
    if number <= 0:
        raise argparse.ArgumentTypeError(msg)
    return number


def build_parser() -> tuple[ProtocolArgumentParser, frozenset[str]]:
    """Construct the git-worktrees argument parser."""
    parser = ProtocolArgumentParser(
        prog="git-worktrees",
        description="Local raw-Git worktree lifecycle controller.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    _ = commands.add_parser("schema", help="Describe the JSON protocol.")

    inspect = commands.add_parser(
        "inspect", help="Inspect a repository without mutation."
    )
    _ = inspect.add_argument("--repo", required=True, metavar="PATH")

    acquire = commands.add_parser("acquire", help="Acquire a managed worktree lease.")
    _ = acquire.add_argument("--repo", required=True, metavar="PATH")
    _ = acquire.add_argument("--owner", required=True, metavar="ID")
    _ = acquire.add_argument("--session-actor", required=True, metavar="ID")
    _ = acquire.add_argument("--task", required=True, metavar="TEXT")
    _ = acquire.add_argument("--name", required=True, metavar="SLUG")
    _ = acquire.add_argument(
        "--mode",
        required=True,
        choices=("new-branch", "existing-branch", "detached-ephemeral"),
    )
    _ = acquire.add_argument("--base", metavar="REV")
    _ = acquire.add_argument("--branch", metavar="BRANCH")
    _ = acquire.add_argument(
        "--setup-argv",
        action="append",
        default=[],
        type=_json_argv,
        metavar="JSON_ARRAY",
        help="Repeatable nonempty JSON argv array; no shell is used.",
    )
    _ = acquire.add_argument(
        "--setup-timeout-seconds",
        type=_positive_integer,
        default=DEFAULT_SETUP_TIMEOUT_SECONDS,
        metavar="N",
    )

    status = commands.add_parser("status", help="Report a managed lease.")
    _ = status.add_argument("--lease-id", required=True, metavar="ID")

    handoff = commands.add_parser("handoff", help="Create a worker handoff.")
    _ = handoff.add_argument("--lease-id", required=True, metavar="ID")
    _ = handoff.add_argument("--owner-token", required=True, metavar="TOKEN")
    _ = handoff.add_argument("--actor", required=True, metavar="ID")
    _ = handoff.add_argument("--session-actor", required=True, metavar="ID")

    complete = commands.add_parser("complete-handoff", help="Close a worker handoff.")
    _ = complete.add_argument("--lease-id", required=True, metavar="ID")
    _ = complete.add_argument("--handoff-token", required=True, metavar="TOKEN")
    _ = complete.add_argument("--quiescent", action="store_true", required=True)

    release = commands.add_parser("release", help="Release a managed worktree lease.")
    _ = release.add_argument("--lease-id", required=True, metavar="ID")
    _ = release.add_argument("--owner-token", required=True, metavar="TOKEN")
    _ = release.add_argument("--quiescent", action="store_true", required=True)
    return parser, frozenset(commands.choices)


def _require_nonblank(value: str, argument: str) -> None:
    if not value.strip():
        raise CliError(
            "usage_error",
            f"{argument} must not be blank",
            {"argument": argument},
        )


def _arg_str(args: argparse.Namespace, field: str) -> str:
    """Extract a required str option from parsed args."""
    return cast("str", getattr(args, field))


def _arg_optional_str(args: argparse.Namespace, field: str) -> str | None:
    """Extract an optional str option from parsed args."""
    return cast("str | None", getattr(args, field))


def _arg_bool(args: argparse.Namespace, field: str) -> bool:
    """Extract a required bool flag from parsed args."""
    return cast("bool", getattr(args, field))


def _arg_int(args: argparse.Namespace, field: str) -> int:
    """Extract a required int option from parsed args."""
    return cast("int", getattr(args, field))


def _arg_setup_argv(args: argparse.Namespace, field: str) -> list[tuple[str, ...]]:
    """Extract the setup argv list from parsed args."""
    return cast("list[tuple[str, ...]]", getattr(args, field))


def _arg_mode(args: argparse.Namespace, field: str) -> Mode:
    """Extract a worktree mode literal from parsed args."""
    return cast("Mode", getattr(args, field))


def _validate_arguments(args: argparse.Namespace) -> None:
    command = _arg_str(args, "command")
    if command == "schema":
        return
    if command == "inspect":
        _require_nonblank(_arg_str(args, "repo"), "--repo")
        return
    if command == "acquire":
        for argument in ("--repo", "--owner", "--session-actor", "--task", "--name"):
            _require_nonblank(_arg_str(args, argument[2:].replace("-", "_")), argument)
        if not NAME_PATTERN.fullmatch(_arg_str(args, "name")):
            raise CliError(
                "usage_error",
                "--name must be a lower-case ASCII slug",
                {"argument": "--name", "pattern": NAME_PATTERN.pattern},
            )
        mode = _arg_str(args, "mode")
        base = _arg_optional_str(args, "base")
        branch = _arg_optional_str(args, "branch")
        if mode == "new-branch":
            if not base:
                raise CliError("usage_error", "new-branch mode requires --base")
            if branch is not None:
                raise CliError("usage_error", "new-branch mode forbids --branch")
        elif mode == "existing-branch":
            if not branch:
                raise CliError("usage_error", "existing-branch mode requires --branch")
            if base is not None:
                raise CliError("usage_error", "existing-branch mode forbids --base")
        else:
            if not base:
                raise CliError("usage_error", "detached-ephemeral mode requires --base")
            if branch is not None:
                raise CliError(
                    "usage_error", "detached-ephemeral mode forbids --branch"
                )
        if base is not None:
            _require_nonblank(base, "--base")
        if branch is not None:
            _require_nonblank(branch, "--branch")
        return
    if command == "status":
        _require_nonblank(_arg_str(args, "lease_id"), "--lease-id")
        return
    if command == "handoff":
        for argument in ("--lease-id", "--owner-token", "--actor", "--session-actor"):
            _require_nonblank(_arg_str(args, argument[2:].replace("-", "_")), argument)
        return
    if command == "complete-handoff":
        _require_nonblank(_arg_str(args, "lease_id"), "--lease-id")
        _require_nonblank(_arg_str(args, "handoff_token"), "--handoff-token")
        return
    if command == "release":
        _require_nonblank(_arg_str(args, "lease_id"), "--lease-id")
        _require_nonblank(_arg_str(args, "owner_token"), "--owner-token")


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
                "result": {
                    "lease": "durable lease",
                    "observation": "fresh safety state",
                    "blockers": "release blockers",
                    "safe_to_release": "boolean",
                },
            },
            "handoff": {
                "arguments": {
                    "lease_id": "ID",
                    "owner_token": "TOKEN",
                    "actor": "ID",
                    "session_actor": "ID",
                },
                "result": {
                    "capabilities": {"handoff_token": "opaque token returned once"}
                },
            },
            "complete-handoff": {
                "arguments": {
                    "lease_id": "ID",
                    "handoff_token": "TOKEN",
                    "quiescent": True,
                },
                "result": {"handoff": "completed"},
            },
            "release": {
                "arguments": {
                    "lease_id": "ID",
                    "owner_token": "TOKEN",
                    "quiescent": True,
                },
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


_CoreApi = tuple[
    "type[AcquireRequest]",
    "type[Controller]",
    "type[DomainError]",
    "type[SetupCommand]",
    Callable[..., object],
    Callable[..., object],
    Callable[..., object],
    Callable[..., object],
    Callable[..., object],
    Callable[..., object],
]


def _core_api() -> _CoreApi:
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
    command = _arg_str(args, "command")
    if command == "schema":
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

    if command == "inspect":
        return inspect_operation(Path(_arg_str(args, "repo")), controller_type())

    controller = controller_type()
    if command == "acquire":
        setup_argv = _arg_setup_argv(args, "setup_argv")
        setup_commands = tuple(setup_command_type(argv=argv) for argv in setup_argv)
        request = acquire_request_type(
            repo=Path(_arg_str(args, "repo")),
            owner=_arg_str(args, "owner"),
            session_actor=_arg_str(args, "session_actor"),
            task=_arg_str(args, "task"),
            name=_arg_str(args, "name"),
            mode=_arg_mode(args, "mode"),
            base=_arg_optional_str(args, "base"),
            branch=_arg_optional_str(args, "branch"),
            setup=setup_commands,
            setup_timeout_seconds=_arg_int(args, "setup_timeout_seconds"),
        )
        return acquire_operation(controller, request)
    if command == "status":
        return status_operation(controller, _arg_str(args, "lease_id"))
    if command == "handoff":
        return handoff_operation(
            controller,
            _arg_str(args, "lease_id"),
            _arg_str(args, "owner_token"),
            _arg_str(args, "actor"),
            _arg_str(args, "session_actor"),
        )
    if command == "complete-handoff":
        return complete_handoff_operation(
            controller,
            _arg_str(args, "lease_id"),
            _arg_str(args, "handoff_token"),
            _arg_bool(args, "quiescent"),
        )
    if command == "release":
        return release_operation(
            controller,
            _arg_str(args, "lease_id"),
            _arg_str(args, "owner_token"),
            _arg_bool(args, "quiescent"),
        )
    raise CliError("usage_error", "unknown command")


def _json_value(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _json_value(dataclasses.asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return _json_value(cast("object", value.value))
    if isinstance(value, Mapping):
        fields = cast("Mapping[object, object]", value)
        return {str(key): _json_value(item) for key, item in fields.items()}
    if isinstance(value, (list, tuple)):
        items = cast("Sequence[object]", value)
        return [_json_value(item) for item in items]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _emit(payload: Mapping[str, object]) -> None:
    _ = sys.stdout.write(json.dumps(_json_value(payload), separators=(",", ":")) + "\n")


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
    """Run the git-worktrees CLI and return a process exit code."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser, commands = build_parser()
    command = _requested_command(arguments, commands)
    try:
        args = parser.parse_args(arguments)
        command = _arg_str(args, "command")
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
    except Exception as error:  # noqa: BLE001 - protocol safety net
        domain_error_type: type[BaseException] | None = None
        with suppress(Exception):
            domain_error_type = _core_api()[2]
        if domain_error_type is not None and isinstance(error, domain_error_type):
            details = cast("object", getattr(error, "details", {}))
            exit_code = cast("object", getattr(error, "exit_code", 2))
            protocol_error = CliError(
                getattr(error, "code", "controller_error"),
                getattr(error, "message", str(error)),
                details if _is_str_dict(details) else {},
                exit_code if isinstance(exit_code, int) else 2,
            )
        else:
            protocol_error = CliError(
                "runtime_error",
                "The worktree controller failed unexpectedly",
                exit_code=4,
            )
        return _emit_error_and_exit(command, protocol_error)
    _emit(_success(command, result))
    return 0
