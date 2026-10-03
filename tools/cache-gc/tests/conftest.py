# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
# ruff: noqa: INP001 - pytest rootdir conftest, not a package
"""Make the standalone cache_gc script importable as a module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
