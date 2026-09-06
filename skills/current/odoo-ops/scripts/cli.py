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


def main(argv: list[str] | None = None) -> int:
    """Delegate to odoo_rpc if command is 'rpc', otherwise odooctl."""
    args = sys.argv[1:] if argv is None else list(argv)
    if args and args[0] == "rpc":
        return odoo_rpc.main(args[1:])
    return odooctl.main(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
