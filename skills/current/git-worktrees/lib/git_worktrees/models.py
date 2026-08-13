"""Typed values used by the raw-Git worktree lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict


Mode = Literal["new-branch", "existing-branch", "detached-ephemeral"]
LeaseState = Literal["reserved", "ready", "create_failed", "setup_failed", "released"]


class WorktreeSnapshot(TypedDict):
    path: str
    head: str
    ref: str | None
    detached: bool
    locked: str | None
    prunable: str | None


@dataclass(frozen=True, slots=True)
class GitWorktree:
    path: Path
    head: str
    ref: str | None
    detached: bool
    locked: str | None
    prunable: str | None

    def snapshot(self) -> WorktreeSnapshot:
        return {
            "path": str(self.path),
            "head": self.head,
            "ref": self.ref,
            "detached": self.detached,
            "locked": self.locked,
            "prunable": self.prunable,
        }


@dataclass(frozen=True, slots=True)
class Repository:
    common_git_dir: Path
    primary_path: Path
    worktrees: tuple[GitWorktree, ...]


@dataclass(frozen=True, slots=True)
class SetupCommand:
    argv: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AcquireRequest:
    repo: Path
    owner: str
    session_actor: str
    task: str
    name: str
    mode: Mode
    base: str | None
    branch: str | None
    setup: tuple[SetupCommand, ...] = ()
    setup_timeout_seconds: int = 600


@dataclass(frozen=True, slots=True)
class Lease:
    lease_id: str
    common_git_dir: Path
    primary_path: Path
    path: Path
    mode: Mode
    branch: str | None
    base: str | None
    owner: str
    session_actor: str
    task: str
    state: LeaseState
    provenance: str
    owner_token_hash: str | None
    created_at: str
    updated_at: str
    released_at: str | None
    failure: str | None

    def public(self) -> dict[str, object]:
        return {
            "lease_id": self.lease_id,
            "canonical_root": str(self.primary_path),
            "common_git_dir": str(self.common_git_dir),
            "primary_path": str(self.primary_path),
            "path": str(self.path),
            "mode": self.mode,
            "branch": self.branch,
            "ref": self.branch,
            "base": self.base,
            "owner": self.owner,
            "session_actor": self.session_actor,
            "task": self.task,
            "state": self.state,
            "ready": self.state == "ready",
            "provenance": self.provenance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "released_at": self.released_at,
            "failure": self.failure,
        }


@dataclass(frozen=True, slots=True)
class Handoff:
    handoff_id: str
    lease_id: str
    actor: str
    session_actor: str
    state: Literal["active", "completed"]
    created_at: str
    completed_at: str | None

    def public(self) -> dict[str, object]:
        return {
            "handoff_id": self.handoff_id,
            "lease_id": self.lease_id,
            "actor": self.actor,
            "session_actor": self.session_actor,
            "state": self.state,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }
