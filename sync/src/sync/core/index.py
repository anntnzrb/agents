# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Top-level orchestration: full sync and launch-wrapped sync.

Scaffold stub: :func:`main` and :func:`launch_main` are fully ported in P4.
Signatures and exit-code contracts are already final.
"""

from __future__ import annotations


def main() -> int:
    """Run full reconciliation; return the process exit code."""
    message = "P4 ports run_sync/main"
    raise NotImplementedError(message)


def launch_main(source_name: str, args: list[str]) -> int:
    """Launch ``source_name`` with ``args``; return the child exit code."""
    message = f"P4 ports launch_main for {source_name} with {len(args)} args"
    raise NotImplementedError(message)
