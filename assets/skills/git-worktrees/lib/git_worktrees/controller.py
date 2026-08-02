"""Private durable state and repository-scoped interprocess locking."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
import errno
import os
from pathlib import Path
import sqlite3
import stat
import sys
import time
from typing import Iterator
from urllib.parse import quote

from .errors import InputError, RefusalError
from .models import Handoff, Lease, LeaseState, Mode
from .paths import default_root


DEFAULT_ROOT = default_root().resolve()


class Controller:
    """Owns controller-private SQLite state beneath the fixed worktree root."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = DEFAULT_ROOT if root is None else root.expanduser()

    @property
    def control_dir(self) -> Path:
        return self.root / ".control" / "v1"

    @property
    def database_path(self) -> Path:
        return self.control_dir / "state.sqlite3"

    @property
    def lock_dir(self) -> Path:
        return self.control_dir / "locks"

    def state_exists(self) -> bool:
        return self._regular_leaf_exists(self.database_path, label="Controller state database")

    def initialize(self) -> None:
        self._ensure_safe_root()
        for directory in (self.root / ".control", self.control_dir, self.lock_dir):
            try:
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            except OSError as error:
                raise RefusalError("controller_path_unsafe", "Controller path cannot be created", {"path": str(directory)}) from error
            self._validate_private_directory(directory)
        with self.connect(write=True) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS repository_names (
                    visible_slug TEXT PRIMARY KEY NOT NULL,
                    common_git_dir TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS leases (
                    lease_id TEXT PRIMARY KEY NOT NULL,
                    common_git_dir TEXT NOT NULL,
                    primary_path TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    mode TEXT NOT NULL,
                    branch TEXT,
                    base TEXT,
                    owner TEXT NOT NULL,
                    session_actor TEXT NOT NULL,
                    task TEXT NOT NULL,
                    state TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    owner_token_hash TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    released_at TEXT,
                    failure TEXT
                );
                CREATE INDEX IF NOT EXISTS leases_common_git_dir_idx ON leases(common_git_dir);
                CREATE TABLE IF NOT EXISTS handoffs (
                    handoff_id TEXT PRIMARY KEY NOT NULL,
                    lease_id TEXT NOT NULL REFERENCES leases(lease_id),
                    actor TEXT NOT NULL,
                    session_actor TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS handoffs_lease_state_idx ON handoffs(lease_id, state);
                """
            )

    def _ensure_safe_root(self) -> None:
        root = self.root.absolute()
        try:
            physical = root.resolve(strict=False)
        except OSError as error:
            raise RefusalError("allocation_root_unsafe", "The fixed worktree root cannot be resolved", {"path": str(root)}) from error
        if physical != root:
            raise RefusalError("allocation_root_symlink", "The fixed worktree root traverses a symlink", {"path": str(root)})
        if root.exists() and root.is_symlink():
            raise RefusalError("allocation_root_symlink", "The fixed worktree root is a symlink", {"path": str(root)})
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as error:
            raise RefusalError("allocation_root_unsafe", "The fixed worktree root cannot be created", {"path": str(root)}) from error
        try:
            root_stat = root.lstat()
        except OSError as error:
            raise RefusalError("allocation_root_unsafe", "The fixed worktree root cannot be inspected", {"path": str(root)}) from error
        if (
            root.is_symlink()
            or not stat.S_ISDIR(root_stat.st_mode)
            or (sys.platform != "win32" and (root_stat.st_mode & 0o022 or root_stat.st_uid != os.getuid()))
        ):
            raise RefusalError("allocation_root_unsafe", "The fixed worktree root is not a private real directory", {"path": str(root)})

    @staticmethod
    def _regular_leaf_exists(path: Path, *, label: str) -> bool:
        try:
            leaf_stat = path.lstat()
        except FileNotFoundError:
            return False
        except OSError as error:
            raise RefusalError("controller_path_unsafe", f"{label} cannot be inspected", {"path": str(path)}) from error
        if stat.S_ISLNK(leaf_stat.st_mode) or not stat.S_ISREG(leaf_stat.st_mode):
            raise RefusalError("controller_path_unsafe", f"{label} is not a regular file", {"path": str(path)})
        return True

    @staticmethod
    def _validate_private_directory(path: Path) -> None:
        try:
            directory_stat = path.lstat()
        except OSError as error:
            raise RefusalError("controller_path_unsafe", "Controller path cannot be inspected", {"path": str(path)}) from error
        if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
            raise RefusalError("controller_path_unsafe", "Controller path is not a real directory", {"path": str(path)})
        if sys.platform != "win32" and (directory_stat.st_mode & 0o022 or directory_stat.st_uid != os.getuid()):
            raise RefusalError("controller_path_unsafe", "Controller path is writable by another user", {"path": str(path)})

    def connect(self, *, write: bool) -> sqlite3.Connection:
        database_exists = self._regular_leaf_exists(self.database_path, label="Controller state database")
        if write or database_exists:
            # sqlite3 connects by pathname; the private directory chain protects this checked leaf.
            for directory in (self.root, self.root / ".control", self.control_dir):
                self._validate_private_directory(directory)
        if write:
            connection = sqlite3.connect(str(self.database_path), isolation_level=None, timeout=30.0)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
        else:
            if not database_exists:
                raise InputError("lease_unknown", "No controller state exists for this lease", {})
            connection = sqlite3.connect(f"file:{quote(str(self.database_path))}?mode=ro", uri=True, isolation_level=None, timeout=30.0)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def repository_lock(self, common_git_dir: Path) -> Iterator[None]:
        """Take a bounded cross-platform lock indexed by physical Git identity."""
        self.initialize()
        digest = sha256(str(common_git_dir).encode("utf-8")).hexdigest()
        path = self.lock_dir / f"{digest}.lock"
        self._regular_leaf_exists(path, label="Repository controller lock")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as error:
            if error.errno in {errno.ELOOP, errno.EMLINK}:
                raise RefusalError("controller_path_unsafe", "Repository controller lock is a symlink", {"path": str(path)}) from error
            raise RefusalError("controller_path_unsafe", "Repository controller lock cannot be opened", {"path": str(path)}) from error
        acquired = False
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise RefusalError("controller_path_unsafe", "Repository controller lock is not a regular file", {"path": str(path)})
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            self._lock_descriptor(descriptor, path)
            acquired = True
            yield
        finally:
            try:
                if acquired:
                    self._unlock_descriptor(descriptor)
            finally:
                os.close(descriptor)

    @staticmethod
    def _lock_descriptor(descriptor: int, path: Path) -> None:
        deadline = time.monotonic() + 30.0
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError as error:
                if time.monotonic() >= deadline:
                    raise RefusalError("repository_lock_timeout", "Timed out waiting for the repository controller lock", {"path": str(path)}) from error
                time.sleep(0.05)

    @staticmethod
    def _unlock_descriptor(descriptor: int) -> None:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def row_to_lease(row: sqlite3.Row | tuple[object, ...]) -> Lease:
    (
        lease_id,
        common_git_dir,
        primary_path,
        path,
        mode,
        branch,
        base,
        owner,
        session_actor,
        task,
        state,
        provenance,
        owner_token_hash,
        created_at,
        updated_at,
        released_at,
        failure,
    ) = row
    return Lease(
        str(lease_id), Path(str(common_git_dir)), Path(str(primary_path)), Path(str(path)),
        str(mode), None if branch is None else str(branch), None if base is None else str(base),
        str(owner), str(session_actor), str(task), str(state), str(provenance),
        None if owner_token_hash is None else str(owner_token_hash), str(created_at), str(updated_at),
        None if released_at is None else str(released_at), None if failure is None else str(failure),
    )


def row_to_handoff(row: sqlite3.Row | tuple[object, ...]) -> Handoff:
    handoff_id, lease_id, actor, session_actor, state, created_at, completed_at = row
    return Handoff(
        str(handoff_id), str(lease_id), str(actor), str(session_actor), str(state), str(created_at),
        None if completed_at is None else str(completed_at),
    )
