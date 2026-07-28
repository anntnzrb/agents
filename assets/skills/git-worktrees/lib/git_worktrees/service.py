"""Safe raw-Git worktree lifecycle operations."""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
from threading import Lock, Thread
from typing import BinaryIO, Iterator
from uuid import uuid4

from .controller import Controller, row_to_handoff, row_to_lease, utc_now
from .errors import DomainError, GitError, InputError, RefusalError
from .git import (
    inspect_repository as git_inspect_repository,
    local_branch_exists,
    validate_branch,
    worktree_add,
    worktree_dirty,
    worktree_head_and_ref,
    worktree_remove,
)
from .models import AcquireRequest, GitWorktree, Handoff, Lease, Mode, Repository, SetupCommand


_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_LEASE_COLUMNS = "lease_id, common_git_dir, primary_path, path, mode, branch, base, owner, session_actor, task, state, provenance, owner_token_hash, created_at, updated_at, released_at, failure"


def _require_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise InputError("invalid_argument", f"{field} must be a nonempty string without NUL", {"field": field})


def _validate_acquire(request: AcquireRequest) -> None:
    for field, value in (("owner", request.owner), ("session_actor", request.session_actor), ("task", request.task)):
        _require_text(value, field)
    if not _NAME.fullmatch(request.name):
        raise InputError("invalid_name", "name must be a lower-case ASCII slug", {"name": request.name})
    if request.setup_timeout_seconds <= 0:
        raise InputError("invalid_setup_timeout", "setup timeout must be positive", {})
    if request.mode == "new-branch":
        if not request.base or request.branch is not None:
            raise InputError("invalid_mode_arguments", "new-branch requires base and forbids branch", {})
    elif request.mode == "existing-branch":
        if not request.branch or request.base is not None:
            raise InputError("invalid_mode_arguments", "existing-branch requires branch and forbids base", {})
    elif request.mode == "detached-ephemeral":
        if not request.base or request.branch is not None:
            raise InputError("invalid_mode_arguments", "detached-ephemeral requires base and forbids branch", {})
    else:
        raise InputError("invalid_mode", "mode is invalid", {"mode": request.mode})
    for setup in request.setup:
        if not setup.argv or any(not isinstance(argument, str) or not argument or "\x00" in argument for argument in setup.argv):
            raise InputError("invalid_setup_argv", "each setup argv must be a nonempty array of nonempty strings", {})


def _namespace_slug(repository: Repository) -> str:
    base = repository.primary_path.name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return slug or "repo"


def _safe_path_chain(root: Path, path: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise RefusalError("allocation_root_unsafe", "The fixed worktree root is not a real directory", {"path": str(root)})
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise RefusalError("allocation_outside_root", "Allocation is outside the fixed worktree root", {"path": str(path)}) from error
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RefusalError("allocation_symlink", "Allocation path contains a symlink", {"path": str(current)})


def _visible_slug(connection: sqlite3.Connection, repository: Repository, controller: Controller) -> str:
    common = str(repository.common_git_dir)
    existing = connection.execute("SELECT visible_slug FROM repository_names WHERE common_git_dir = ?", (common,)).fetchone()
    if existing is not None:
        return str(existing[0])
    base = _namespace_slug(repository)
    bound = connection.execute("SELECT common_git_dir FROM repository_names WHERE visible_slug = ?", (base,)).fetchone()
    slug = base
    if bound is not None and str(bound[0]) != common:
        slug = f"{base}-{sha256(common.encode('utf-8')).hexdigest()[:6]}"
        alternate = connection.execute("SELECT common_git_dir FROM repository_names WHERE visible_slug = ?", (slug,)).fetchone()
        if alternate is not None and str(alternate[0]) != common:
            raise RefusalError("namespace_collision", "Visible repository namespace belongs to another repository", {"slug": slug})
    parent = controller.root / slug
    _safe_path_chain(controller.root, parent)
    mapping = connection.execute("SELECT common_git_dir FROM repository_names WHERE visible_slug = ?", (slug,)).fetchone()
    if parent.exists() and mapping is None:
        if not parent.is_dir():
            raise RefusalError("namespace_unbound", "Visible repository namespace is not a directory", {"path": str(parent)})
        try:
            has_contents = next(parent.iterdir(), None) is not None
        except OSError as error:
            raise RefusalError("namespace_unbound", "Visible repository namespace cannot be inspected", {"path": str(parent)}) from error
        if has_contents:
            raise RefusalError("namespace_unbound", "Visible repository namespace is not bound by this controller", {"path": str(parent)})
    connection.execute(
        "INSERT INTO repository_names(visible_slug, common_git_dir, created_at) VALUES (?, ?, ?)",
        (slug, common, utc_now()),
    )
    return slug

def _visible_slug_for_inspection(connection: sqlite3.Connection, repository: Repository) -> str:
    common = str(repository.common_git_dir)
    existing = connection.execute("SELECT visible_slug FROM repository_names WHERE common_git_dir = ?", (common,)).fetchone()
    if existing is not None:
        return str(existing[0])
    base = _namespace_slug(repository)
    bound = connection.execute("SELECT common_git_dir FROM repository_names WHERE visible_slug = ?", (base,)).fetchone()
    if bound is None or str(bound[0]) == common:
        return base
    return f"{base}-{sha256(common.encode('utf-8')).hexdigest()[:6]}"


def _allocate_destination(
    connection: sqlite3.Connection, controller: Controller, repository: Repository, name: str, mode: Mode
) -> tuple[Path, str]:
    slug = _visible_slug(connection, repository, controller)
    parent = controller.root / slug
    _safe_path_chain(controller.root, parent)
    parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink():
        raise RefusalError("allocation_symlink", "Visible repository namespace is a symlink", {"path": str(parent)})
    occupied_refs = {worktree.ref for worktree in repository.worktrees if worktree.ref is not None}
    candidate = name
    index = 2
    while True:
        destination = parent / candidate
        _safe_path_chain(controller.root, destination)
        branch = f"work/{candidate}"
        lease_path_exists = connection.execute("SELECT 1 FROM leases WHERE path = ? LIMIT 1", (str(destination),)).fetchone() is not None
        branch_taken = mode == "new-branch" and (
            f"refs/heads/{branch}" in occupied_refs or local_branch_exists(repository.primary_path, branch)
        )
        if not destination.exists() and not destination.is_symlink() and not lease_path_exists and not branch_taken:
            return destination, candidate
        candidate = f"{name}-{index}"
        index += 1


def _lease(connection: sqlite3.Connection, lease_id: str) -> Lease:
    row = connection.execute(f"SELECT {_LEASE_COLUMNS} FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
    if row is None:
        raise InputError("lease_unknown", "Lease is not managed by this controller", {"lease_id": lease_id})
    return row_to_lease(row)


def _active_handoffs(connection: sqlite3.Connection, lease_id: str) -> list[Handoff]:
    rows = connection.execute(
        "SELECT handoff_id, lease_id, actor, session_actor, state, created_at, completed_at FROM handoffs WHERE lease_id = ? AND state = 'active'",
        (lease_id,),
    ).fetchall()
    return [row_to_handoff(row) for row in rows]


@contextmanager
def _write_transaction(controller: Controller) -> Iterator[sqlite3.Connection]:
    connection = controller.connect(write=True)
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _mark_failure(controller: Controller, lease_id: str, state: str, error: DomainError) -> None:
    with _write_transaction(controller) as connection:
        connection.execute(
            "UPDATE leases SET state = ?, updated_at = ?, failure = ? WHERE lease_id = ?",
            (state, utc_now(), json.dumps(error.as_dict(), sort_keys=True), lease_id),
        )


def _assert_fresh_identity(initial: Repository, refreshed: Repository) -> None:
    if initial.common_git_dir != refreshed.common_git_dir or initial.primary_path != refreshed.primary_path:
        raise RefusalError(
            "repository_identity_changed",
            "Repository identity changed while waiting for the controller lock",
            {
                "expected_common_git_dir": str(initial.common_git_dir),
                "actual_common_git_dir": str(refreshed.common_git_dir),
            },
        )


def _expected_ref(lease: Lease) -> str | None:
    return None if lease.branch is None else f"refs/heads/{lease.branch}"


def _assert_managed_target(repository: Repository, lease: Lease) -> GitWorktree:
    matched = [worktree for worktree in repository.worktrees if worktree.path == lease.path]
    if len(matched) != 1:
        raise RefusalError("worktree_unregistered", "Managed worktree is not uniquely registered", {"path": str(lease.path)})
    target = matched[0]
    if target.path == repository.primary_path:
        raise RefusalError("worktree_primary", "The primary worktree can never be released", {"path": str(target.path)})
    if target.locked is not None or target.prunable is not None:
        raise RefusalError("worktree_uncertain", "Managed worktree has Git lock or prunable annotations", {"path": str(target.path)})
    expected = _expected_ref(lease)
    if expected is None:
        if not target.detached or target.ref is not None:
            raise RefusalError("worktree_ref_mismatch", "Detached worktree no longer matches its lease", {"path": str(target.path)})
    elif target.ref != expected or target.detached:
        raise RefusalError("worktree_ref_mismatch", "Worktree ref no longer matches its lease", {"path": str(target.path), "expected_ref": expected, "actual_ref": target.ref})
    return target


def _setup_command(command: SetupCommand, cwd: Path, timeout: int) -> dict[str, object]:
    """Run setup with bounded stream retention, preserving a failed worktree."""
    try:
        process = subprocess.Popen(
            command.argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
    except OSError as error:
        raise GitError("setup_start_failed", "Could not start setup command", {"argv": list(command.argv), "error": str(error)}) from error
    limit = 64 * 1024
    outputs = [bytearray(), bytearray()]
    truncated = [False, False]
    output_lock = Lock()

    if process.stdout is None or process.stderr is None:
        process.kill()
        process.wait()
        raise GitError("setup_start_failed", "Could not capture setup command output", {"argv": list(command.argv)})

    def collect(index: int, stream: BinaryIO) -> None:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            with output_lock:
                remaining = limit - len(outputs[index])
                if remaining > 0:
                    outputs[index].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    truncated[index] = True

    threads = [Thread(target=collect, args=(0, process.stdout), daemon=True), Thread(target=collect, args=(1, process.stderr), daemon=True)]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        returncode = process.wait()
    for thread in threads:
        thread.join(timeout=0.2)
    result: dict[str, object] = {
        "argv": list(command.argv),
        "returncode": returncode,
        "timed_out": timed_out,
        "stdout": bytes(outputs[0]).decode("utf-8", "replace"),
        "stderr": bytes(outputs[1]).decode("utf-8", "replace"),
        "stdout_truncated": truncated[0],
        "stderr_truncated": truncated[1],
    }
    if timed_out:
        raise GitError("setup_timeout", "Setup command timed out", result)
    if returncode != 0:
        raise GitError("setup_failed", "Setup command failed", result)
    return result


def inspect_repository(repo: Path, controller: Controller | None = None) -> dict[str, object]:
    """Read-only repository inspection; it never creates controller state."""
    repository = git_inspect_repository(repo)
    active_controller = Controller() if controller is None else controller
    leases: list[dict[str, object]] = []
    findings: list[dict[str, object]] = []
    visible_slug: str | None = None
    if active_controller.state_exists():
        try:
            with active_controller.connect(write=False) as connection:
                rows = connection.execute(f"SELECT {_LEASE_COLUMNS} FROM leases WHERE common_git_dir = ? ORDER BY created_at", (str(repository.common_git_dir),)).fetchall()
                leases = [row_to_lease(row).public() for row in rows]
                visible_slug = _visible_slug_for_inspection(connection, repository)
        except sqlite3.Error as error:
            findings.append({"code": "controller_state_unreadable", "message": "Controller state could not be read", "details": {"error": str(error)}})
    parent = active_controller.root / (visible_slug if visible_slug is not None else _namespace_slug(repository))
    try:
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            findings.append({"code": "allocation_parent_unsafe", "message": "Visible allocation parent is unsafe", "details": {"path": str(parent)}})
    except OSError as error:
        findings.append({"code": "allocation_parent_unreadable", "message": "Visible allocation parent cannot be inspected", "details": {"path": str(parent), "error": str(error)}})
    return {
        "canonical_root": str(repository.primary_path),
        "common_git_dir": str(repository.common_git_dir),
        "primary_path": str(repository.primary_path),
        "worktrees": [worktree.snapshot() for worktree in repository.worktrees],
        "leases": leases,
        "findings": findings,
    }


def acquire(controller: Controller, request: AcquireRequest) -> dict[str, object]:
    _validate_acquire(request)
    initial = git_inspect_repository(request.repo)
    with controller.repository_lock(initial.common_git_dir):
        repository = git_inspect_repository(request.repo)
        _assert_fresh_identity(initial, repository)
        with _write_transaction(controller) as connection:
            destination, candidate = _allocate_destination(connection, controller, repository, request.name, request.mode)
            branch = f"work/{candidate}" if request.mode == "new-branch" else request.branch
            if branch is not None:
                validate_branch(repository.primary_path, branch)
            if request.mode == "existing-branch":
                assert branch is not None
                if not local_branch_exists(repository.primary_path, branch):
                    raise RefusalError("branch_missing", "Existing branch does not exist", {"branch": branch})
                if any(worktree.ref == f"refs/heads/{branch}" for worktree in repository.worktrees):
                    raise RefusalError("branch_attached", "Existing branch is already attached to a worktree", {"branch": branch})
            lease_id = str(uuid4())
            created_at = utc_now()
            connection.execute(
                "INSERT INTO leases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', 'created-by-lease', NULL, ?, ?, NULL, NULL)",
                (lease_id, str(repository.common_git_dir), str(repository.primary_path), str(destination), request.mode, branch, request.base, request.owner, request.session_actor, request.task, created_at, created_at),
            )
        lease = Lease(lease_id, repository.common_git_dir, repository.primary_path, destination, request.mode, branch, request.base, request.owner, request.session_actor, request.task, "reserved", "created-by-lease", None, created_at, created_at, None, None)
        try:
            worktree_add(repository.primary_path, destination, request.mode, base=request.base, branch=branch)
            after_add = git_inspect_repository(repository.primary_path)
            _assert_fresh_identity(repository, after_add)
            _assert_managed_target(after_add, lease)
        except DomainError as error:
            _mark_failure(controller, lease_id, "create_failed", error)
            details = dict(error.details) | {"lease_id": lease_id, "state": "create_failed"}
            if error.exit_code == 127:
                raise
            if isinstance(error, RefusalError):
                raise RefusalError(error.code, error.message, details) from error
            raise GitError(error.code, error.message, details) from error
        try:
            for command in request.setup:
                _setup_command(command, destination, request.setup_timeout_seconds)
            after_setup = git_inspect_repository(repository.primary_path)
            _assert_fresh_identity(repository, after_setup)
            _assert_managed_target(after_setup, lease)
        except DomainError as error:
            _mark_failure(controller, lease_id, "setup_failed", error)
            details = dict(error.details) | {"lease_id": lease_id, "state": "setup_failed"}
            if error.exit_code == 127:
                raise
            if isinstance(error, RefusalError):
                raise RefusalError(error.code, error.message, details) from error
            raise GitError(error.code, error.message, details) from error
        token = secrets.token_urlsafe(32)
        now = utc_now()
        with _write_transaction(controller) as connection:
            connection.execute(
                "UPDATE leases SET state = 'ready', owner_token_hash = ?, updated_at = ? WHERE lease_id = ? AND state = 'reserved'",
                (sha256(token.encode("utf-8")).hexdigest(), now, lease_id),
            )
            ready = _lease(connection, lease_id)
        return {"lease": ready.public(), "capabilities": {"owner_token": token}}


def status(controller: Controller, lease_id: str) -> dict[str, object]:
    _require_text(lease_id, "lease_id")
    with controller.connect(write=False) as connection:
        lease = _lease(connection, lease_id)
        active = _active_handoffs(connection, lease_id)
    blockers: list[dict[str, object]] = []
    observation: dict[str, object] = {"path_exists": lease.path.exists(), "registered": False, "primary": False, "head": None, "ref": None, "dirty": None, "identity_matches": False, "provenance_matches": lease.provenance == "created-by-lease", "matches_lease": False}
    try:
        repository = git_inspect_repository(lease.primary_path)
        observation["identity_matches"] = repository.common_git_dir == lease.common_git_dir and repository.primary_path == lease.primary_path
        matching = [worktree for worktree in repository.worktrees if worktree.path == lease.path]
        observation["registered"] = len(matching) == 1
        observation["primary"] = lease.path == repository.primary_path
        if len(matching) == 1:
            observation["head"] = matching[0].head
            observation["ref"] = matching[0].ref
            target = matching[0]
            expected_ref = _expected_ref(lease)
            observation["matches_lease"] = (
                target.locked is None
                and target.prunable is None
                and ((expected_ref is None and target.detached and target.ref is None) or (expected_ref is not None and not target.detached and target.ref == expected_ref))
            )
        if lease.path.exists():
            head, ref = worktree_head_and_ref(lease.path)
            observation["head"] = head
            observation["ref"] = ref
            observation["dirty"] = worktree_dirty(lease.path)
    except DomainError as error:
        blockers.append(error.as_dict())
    if lease.state != "ready":
        blockers.append({"code": "lease_not_ready", "message": "Lease is not in ready state", "details": {"state": lease.state}})
    if active:
        blockers.append({"code": "active_handoffs", "message": "Lease has active handoffs", "details": {"handoff_ids": [handoff.handoff_id for handoff in active]}})
    if not bool(observation["identity_matches"]):
        blockers.append({"code": "repository_identity_changed", "message": "Repository identity does not match the lease", "details": {}})
    if not bool(observation["registered"]) or bool(observation["primary"]):
        blockers.append({"code": "worktree_registration_unsafe", "message": "Worktree is not a registered linked worktree", "details": {}})
    if not bool(observation["path_exists"]):
        blockers.append({"code": "worktree_missing", "message": "Managed worktree path is missing", "details": {"path": str(lease.path)}})
    if observation["dirty"] is None:
        blockers.append({"code": "worktree_state_uncertain", "message": "Worktree dirtiness could not be observed", "details": {}})
    if not bool(observation["matches_lease"]):
        blockers.append({"code": "worktree_ref_mismatch", "message": "Worktree does not match lease mode or ref", "details": {}})
    if observation["dirty"] is True:
        blockers.append({"code": "worktree_dirty", "message": "Worktree has uncommitted changes", "details": {}})
    if not bool(observation["provenance_matches"]):
        blockers.append({"code": "provenance_mismatch", "message": "Lease provenance is not controller managed", "details": {}})
    return {"lease": lease.public(), "observation": observation, "active_handoffs": [handoff.public() for handoff in active], "blockers": blockers, "safe_to_release": not blockers}


def _validate_owner(lease: Lease, token: str) -> None:
    _require_text(token, "owner_token")
    if lease.owner_token_hash is None or not hmac.compare_digest(lease.owner_token_hash, sha256(token.encode("utf-8")).hexdigest()):
        raise RefusalError("owner_capability_mismatch", "Owner capability does not match this lease", {"lease_id": lease.lease_id})


def handoff(controller: Controller, lease_id: str, owner_token: str, actor: str, session_actor: str) -> dict[str, object]:
    _require_text(lease_id, "lease_id")
    _require_text(actor, "actor")
    _require_text(session_actor, "session_actor")
    with controller.connect(write=False) as connection:
        initial_lease = _lease(connection, lease_id)
    initial_repository = git_inspect_repository(initial_lease.primary_path)
    if initial_repository.common_git_dir != initial_lease.common_git_dir or initial_repository.primary_path != initial_lease.primary_path:
        raise RefusalError("repository_identity_changed", "Repository identity no longer matches the lease", {})
    with controller.repository_lock(initial_repository.common_git_dir):
        repository = git_inspect_repository(initial_lease.primary_path)
        _assert_fresh_identity(initial_repository, repository)
        with _write_transaction(controller) as connection:
            lease = _lease(connection, lease_id)
            _validate_owner(lease, owner_token)
            if lease.state != "ready":
                raise RefusalError("lease_not_ready", "Only a ready lease can be handed off", {"state": lease.state})
            if lease.common_git_dir != repository.common_git_dir or lease.primary_path != repository.primary_path:
                raise RefusalError("repository_identity_changed", "Repository identity no longer matches the lease", {})
            if lease.path.is_symlink() or not lease.path.is_dir():
                raise RefusalError("worktree_unavailable", "Managed worktree path is not a real directory", {"path": str(lease.path)})
            _assert_managed_target(repository, lease)
            active = _active_handoffs(connection, lease_id)
            if active:
                raise RefusalError("handoff_active", "A handoff is already active for this lease", {"handoff_id": active[0].handoff_id})
            handoff_id = str(uuid4())
            token = secrets.token_urlsafe(32)
            now = utc_now()
            connection.execute(
                "INSERT INTO handoffs(handoff_id, lease_id, actor, session_actor, token_hash, state, created_at, completed_at) VALUES (?, ?, ?, ?, ?, 'active', ?, NULL)",
                (handoff_id, lease_id, actor, session_actor, sha256(token.encode("utf-8")).hexdigest(), now),
            )
            created = Handoff(handoff_id, lease_id, actor, session_actor, "active", now, None)
    return {"lease": lease.public(), "handoff": created.public(), "capabilities": {"handoff_token": token}}


def complete_handoff(controller: Controller, lease_id: str, handoff_token: str, quiescent: bool) -> dict[str, object]:
    _require_text(lease_id, "lease_id")
    _require_text(handoff_token, "handoff_token")
    if quiescent is not True:
        raise RefusalError("quiescence_required", "Completion requires a quiescence attestation", {})
    token_hash = sha256(handoff_token.encode("utf-8")).hexdigest()
    with _write_transaction(controller) as connection:
        row = connection.execute(
            "SELECT handoff_id, lease_id, actor, session_actor, state, created_at, completed_at FROM handoffs WHERE lease_id = ? AND token_hash = ? AND state = 'active'",
            (lease_id, token_hash),
        ).fetchone()
        if row is None:
            raise RefusalError("handoff_capability_mismatch", "No active handoff matches this capability", {"lease_id": lease_id})
        now = utc_now()
        connection.execute("UPDATE handoffs SET state = 'completed', completed_at = ? WHERE handoff_id = ?", (now, str(row[0])))
        completed = row_to_handoff((row[0], row[1], row[2], row[3], "completed", row[5], now))
        lease = _lease(connection, lease_id)
    return {"lease": lease.public(), "handoff": completed.public()}


def release(controller: Controller, lease_id: str, owner_token: str, quiescent: bool) -> dict[str, object]:
    _require_text(lease_id, "lease_id")
    if quiescent is not True:
        raise RefusalError("quiescence_required", "Release requires a quiescence attestation", {})
    with controller.connect(write=False) as connection:
        initial_lease = _lease(connection, lease_id)
    initial_repository = git_inspect_repository(initial_lease.primary_path)
    if initial_repository.common_git_dir != initial_lease.common_git_dir or initial_repository.primary_path != initial_lease.primary_path:
        raise RefusalError("repository_identity_changed", "Repository identity no longer matches the lease", {})
    with controller.repository_lock(initial_repository.common_git_dir):
        repository = git_inspect_repository(initial_lease.primary_path)
        _assert_fresh_identity(initial_repository, repository)
        with _write_transaction(controller) as connection:
            lease = _lease(connection, lease_id)
            _validate_owner(lease, owner_token)
            if lease.state != "ready":
                raise RefusalError("lease_not_ready", "Only a ready lease can be released", {"state": lease.state})
            if lease.common_git_dir != repository.common_git_dir or lease.primary_path != repository.primary_path:
                raise RefusalError("repository_identity_changed", "Repository identity no longer matches the lease", {})
            if lease.provenance != "created-by-lease":
                raise RefusalError("provenance_mismatch", "Lease provenance is not controller managed", {})
            active = _active_handoffs(connection, lease_id)
            if active:
                raise RefusalError("handoff_active", "Active handoffs must be completed before release", {"handoff_ids": [handoff.handoff_id for handoff in active]})
            _assert_managed_target(repository, lease)
            if not lease.path.exists():
                raise RefusalError("worktree_missing", "Managed worktree path is missing", {"path": str(lease.path)})
            if worktree_dirty(lease.path):
                raise RefusalError("worktree_dirty", "Managed worktree has uncommitted changes", {"path": str(lease.path)})
            worktree_remove(repository.primary_path, lease.path)
            after = git_inspect_repository(repository.primary_path)
            _assert_fresh_identity(repository, after)
            if any(worktree.path == lease.path for worktree in after.worktrees) or lease.path.exists():
                raise RefusalError("worktree_remove_unconfirmed", "Git removal did not remove the managed worktree", {"path": str(lease.path)})
            now = utc_now()
            connection.execute("UPDATE leases SET state = 'released', updated_at = ?, released_at = ? WHERE lease_id = ? AND state = 'ready'", (now, now, lease_id))
            released = _lease(connection, lease_id)
    return {"lease": released.public()}
