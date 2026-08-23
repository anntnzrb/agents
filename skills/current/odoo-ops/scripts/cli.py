# /// script
# requires-python = ">=3.10"
# ///
"""Public entrypoint and dispatcher for Odoo Ops."""

from __future__ import annotations

import sys
import odooctl


def main(argv: list[str] | None = None) -> int:
    """Delegate directly to odooctl."""
    return odooctl.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
