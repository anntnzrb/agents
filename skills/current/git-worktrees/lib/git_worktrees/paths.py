"""XDG data-path selection for durable git-worktree controller state."""

from __future__ import annotations

import os
from pathlib import Path


def default_root() -> Path:
    """Return the fixed allocation root under the user's XDG data home."""
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        base = Path(data_home).expanduser()
    else:
        base = Path.home() / ".local" / "share"
    return base / "agents" / "worktrees"
