# /// script
# requires-python = ">=3.10"
# ///
"""Cross-platform public dispatcher for Odoo Local Ops."""

from __future__ import annotations

import sys

import odooctl


def main(argv: list[str] | None = None) -> int:
    """Delegate to odooctl while preserving its exit behavior."""
    return odooctl.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
