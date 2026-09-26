#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pytest>=8",
#     "lxml>=5.0",
# ]
# ///
"""Public entrypoint and dispatcher for Odoo Ops."""

from __future__ import annotations

import sys

import odoo_rpc
import odooctl

_ODOOCTL_COMMANDS: frozenset[str] = frozenset(
    {
        "dev",
        "test",
        "lint",
        "fmt",
        "lint-views",
        "stop",
        "logs",
        "env",
        "addons",
        "module",
        "routes",
        "db-summary",
        "db-tables",
        "db-query",
        "db-clone",
        "db-restore",
    }
)

_RPC_FLAGS: frozenset[str] = frozenset(
    {
        "--allow-rpc",
        "--write",
        "--url",
        "--db",
        "--user",
        "--token",
        "--token-path",
        "--insecure",
        "--env-file",
    }
)


def _starts_with_rpc_flag(first_arg: str) -> bool:
    """Return True if first_arg is one of the RPC global flags (including --flag=value)."""
    if first_arg in _RPC_FLAGS:
        return True
    return any(first_arg.startswith(f"{flag}=") for flag in _RPC_FLAGS)


def main(argv: list[str] | None = None) -> int:
    """Delegate to odoo_rpc if command is 'rpc', otherwise odooctl."""
    args = sys.argv[1:] if argv is None else list(argv)
    if not args or args in (["-h"], ["--help"]):
        odooctl._build_parser().print_help()
        print("rpc: Odoo JSON-RPC client (see 'cli.py rpc --help')")
        return 0
    if args[0] == "rpc":
        return odoo_rpc.main(args[1:])
    if _starts_with_rpc_flag(args[0]) or (
        args[0] not in _ODOOCTL_COMMANDS and "rpc" in args[1:]
    ):
        _ = sys.stderr.write(
            "Hint: RPC flags go with the rpc command, e.g. 'cli.py rpc --allow-rpc <op> ...'\n"
        )
        return 2
    return odooctl.main(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
