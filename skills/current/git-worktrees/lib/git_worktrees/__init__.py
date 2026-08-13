"""Durable, raw-Git worktree lifecycle core for the local CLI."""

from .controller import Controller, DEFAULT_ROOT
from .errors import DomainError, GitError, GitMissingError, InputError, RefusalError
from .models import AcquireRequest, Handoff, Lease, SetupCommand
from .service import acquire, complete_handoff, handoff, inspect_repository, release, status

__all__ = [
    "AcquireRequest",
    "Controller",
    "DEFAULT_ROOT",
    "DomainError",
    "GitError",
    "GitMissingError",
    "Handoff",
    "InputError",
    "Lease",
    "RefusalError",
    "SetupCommand",
    "acquire",
    "complete_handoff",
    "handoff",
    "inspect_repository",
    "release",
    "status",
]
