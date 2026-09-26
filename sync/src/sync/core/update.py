# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Background SSOT updates: fast-forward the checkout, remember what was synced.

Every machine converges on ``origin/main``. The updater only fast-forwards a
clean ``main`` checkout; anything else means someone is working there, so the
checkout is left untouched. :mod:`sync.core.services` schedules it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from sync.runtime.errors import warn
from sync.runtime.process import RunProcessOptions, run_process

__all__ = [
    "fast_forward_ssot",
    "read_synced_commit",
    "record_synced_commit",
]

UPDATE_BRANCH = "main"
UPDATE_REMOTE = "origin"
SYNCED_STATE_FILE = "update.json"
GIT_TIMEOUT_MS = 60_000


async def _git(ssot_home: str, *args: str) -> tuple[bool, str]:
    result = await run_process(
        ["git", "-C", ssot_home, *args], RunProcessOptions(timeout_ms=GIT_TIMEOUT_MS)
    )
    ok = result.exit_code == 0 and not result.timed_out and not result.output_limited
    return ok, (result.stdout if ok else result.stderr).strip()


async def fast_forward_ssot(ssot_home: str) -> str | None:
    """Fast-forward a clean ``main`` checkout; return HEAD, or None to skip.

    Never merges, stashes, or resets. A failed fetch (offline) keeps the
    current HEAD so an unsynced local commit is still reconciled.
    """
    ok, branch = await _git(ssot_home, "symbolic-ref", "--short", "-q", "HEAD")
    if not ok or branch != UPDATE_BRANCH:
        return None
    ok, changes = await _git(ssot_home, "status", "--porcelain", "--untracked-files=no")
    if not ok or changes:
        return None

    upstream = f"{UPDATE_REMOTE}/{UPDATE_BRANCH}"
    fetched, detail = await _git(
        ssot_home, "fetch", "--quiet", UPDATE_REMOTE, UPDATE_BRANCH
    )
    if not fetched:
        warn(f"update: fetch failed; keeping local checkout ({detail})")
    else:
        behind, _ = await _git(
            ssot_home, "merge-base", "--is-ancestor", "HEAD", upstream
        )
        if behind:
            merged, detail = await _git(
                ssot_home, "merge", "--ff-only", "--quiet", upstream
            )
            if not merged:
                warn(f"update: fast-forward failed; keeping local checkout ({detail})")

    ok, head = await _git(ssot_home, "rev-parse", "HEAD")
    return head if ok else None


def _synced_state_path(managed_state_home: str) -> Path:
    return Path(managed_state_home) / SYNCED_STATE_FILE


def read_synced_commit(managed_state_home: str) -> str | None:
    """Return the last commit ``sync update`` reconciled successfully."""
    try:
        data = cast(
            "object", json.loads(_synced_state_path(managed_state_home).read_text())
        )
    except (OSError, ValueError):
        return None
    commit = (
        cast("dict[str, object]", data).get("commit")
        if isinstance(data, dict)
        else None
    )
    return commit if isinstance(commit, str) else None


def record_synced_commit(managed_state_home: str, commit: str) -> None:
    """Persist the commit that was just reconciled."""
    path = _synced_state_path(managed_state_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    _ = tmp.write_text(json.dumps({"commit": commit}) + "\n")
    _ = tmp.replace(path)
