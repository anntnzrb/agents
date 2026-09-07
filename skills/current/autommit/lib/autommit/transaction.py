"""Durable receipts and exclusive operation locking scoped to the Git worktree."""

from __future__ import annotations

import contextlib
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Generator
from autommit.errors import AutommitError, RefusalError

AUTOMMIT_DIRECTORY = "autommit"
RECEIPT_FILENAME = "receipt.json"
LOCK_FILENAME = "operation.lock"
MAX_JSON_BYTES = 16 * 1024
MAX_LOCK_BYTES = 4 * 1024
MAX_STRING_LENGTH = 4 * 1024
_MIN_PRINTABLE_ORD = 32
_DELETE_ORD = 127


@dataclass(frozen=True, slots=True)
class Receipt:
    """Publication evidence persisted before compare-and-swap."""

    version: int
    state: Literal["prepared", "published"]
    ref: str
    before: str
    after: str
    index_tree: str


def _paths(git_dir: Path) -> tuple[Path, Path, Path]:
    directory = git_dir / AUTOMMIT_DIRECTORY
    return directory, directory / RECEIPT_FILENAME, directory / LOCK_FILENAME


def _ensure_git_dir(git_dir: Path) -> None:
    if git_dir.is_symlink() or not git_dir.is_dir():
        raise RefusalError(
            "unsafe_git_directory",
            f"Target Git directory is not a safe regular directory: {git_dir}",
        )


def _ensure_directory(git_dir: Path) -> Path:
    _ensure_git_dir(git_dir)
    directory = git_dir / AUTOMMIT_DIRECTORY
    if directory.is_symlink():
        raise RefusalError(
            "unsafe_autommit_directory",
            f"Autommit state directory must not be a symlink: {directory}",
        )
    if not directory.is_dir():
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise RefusalError(
            "unsafe_autommit_directory",
            f"Autommit state directory is invalid: {directory}",
        )
    return directory


def _regular_file(path: Path, kind: str) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink() or not path.is_file():
        raise AutommitError(
            "invalid_receipt_file" if kind == "receipt" else "unsafe_state_file",
            f"Autommit {kind} file must be a regular non-symlink file: {path}",
            exit_code=2,
        )
    return True


def _bounded_string(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_STRING_LENGTH
        or any(ord(c) < _MIN_PRINTABLE_ORD or ord(c) == _DELETE_ORD for c in value)
    ):
        raise AutommitError(
            "invalid_receipt",
            f"Receipt field '{field}' must be a bounded printable string.",
        )
    return value


def _validate_receipt(value: object) -> Receipt:
    keys = {"version", "state", "ref", "before", "after", "indexTree"}
    if not isinstance(value, dict) or set(value.keys()) != keys:
        raise AutommitError(
            "invalid_receipt", "Receipt payload does not match expected schema."
        )
    version = value.get("version")
    state = value.get("state")
    if version != 1:
        raise AutommitError(
            "invalid_receipt", f"Unsupported receipt version: {version}"
        )
    if state not in ("prepared", "published"):
        raise AutommitError("invalid_receipt", f"Unsupported receipt state: {state}")
    return Receipt(
        version=1,
        state=state,
        ref=_bounded_string(value.get("ref"), "ref"),
        before=_bounded_string(value.get("before"), "before"),
        after=_bounded_string(value.get("after"), "after"),
        index_tree=_bounded_string(value.get("indexTree"), "indexTree"),
    )


def read_receipt(git_dir: Path) -> Receipt | None:
    """Read and validate a pending receipt without following symlinks."""
    _ensure_git_dir(git_dir)
    _, receipt_path, _ = _paths(git_dir)
    if not _regular_file(receipt_path, "receipt"):
        return None
    try:
        raw = receipt_path.read_bytes()
    except OSError as err:
        raise AutommitError(
            "read_failed", f"Failed to read receipt at {receipt_path}: {err}"
        ) from err
    if len(raw) > MAX_JSON_BYTES:
        raise AutommitError(
            "invalid_receipt", f"Receipt payload exceeds maximum size: {receipt_path}"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as err:
        raise AutommitError(
            "invalid_receipt", f"Receipt payload is not valid JSON: {receipt_path}"
        ) from err
    return _validate_receipt(payload)


def _sync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        dir_fd = os.open(str(directory), flags)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def write_receipt(git_dir: Path, receipt: Receipt) -> None:
    """Atomically persist and fsync publication evidence."""
    directory = _ensure_directory(git_dir)
    receipt_path = directory / RECEIPT_FILENAME
    if receipt_path.is_symlink():
        raise RefusalError(
            "unsafe_receipt_file",
            f"Autommit receipt file must not be a symlink: {receipt_path}",
        )
    payload = json.dumps(
        {
            "version": receipt.version,
            "state": receipt.state,
            "ref": receipt.ref,
            "before": receipt.before,
            "after": receipt.after,
            "indexTree": receipt.index_tree,
        },
        indent=2,
    ).encode("utf-8")
    temp_path = directory / f"receipt.{os.getpid()}.tmp"
    try:
        temp_path.write_bytes(payload)
        temp_path.replace(receipt_path)
        _sync_directory(directory)
    except OSError as err:
        with contextlib.suppress(OSError):
            temp_path.unlink(missing_ok=True)
        raise AutommitError(
            "write_failed", f"Failed to write receipt to {receipt_path}: {err}"
        ) from err


def remove_receipt(git_dir: Path) -> None:
    """Remove a receipt idempotently and durably."""
    _ensure_git_dir(git_dir)
    directory, receipt_path, _ = _paths(git_dir)
    if not _regular_file(receipt_path, "receipt"):
        return
    try:
        receipt_path.unlink(missing_ok=True)
        _sync_directory(directory)
    except OSError as err:
        raise AutommitError(
            "remove_failed", f"Failed to remove receipt at {receipt_path}: {err}"
        ) from err


def describe_operation_lock(git_dir: Path) -> str | None:
    """Inspect existing operation lock file and return diagnosis if present."""
    _, _, lock_path = _paths(git_dir)
    if not lock_path.exists() or lock_path.is_symlink():
        return None
    try:
        raw = lock_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        pid = data.get("pid")
    except Exception:
        return f"operation lock is unreadable at {lock_path}; remove it if no autommit run is active."
    if not isinstance(pid, int) or pid <= 0:
        return f"operation lock at {lock_path} has no usable PID; remove it if no autommit run is active."
    alive = True
    try:
        os.kill(pid, 0)
    except OSError:
        alive = False
    return (
        f"operation lock is held by live process {pid}; wait for it or stop that run first."
        if alive
        else f"operation lock is stale (process {pid} is not running); remove {lock_path} to recover."
    )


@contextmanager
def operation_lock(git_dir: Path) -> Generator[None, None, None]:
    """Serialize autommit operations for the target worktree; no stale lock guessing."""
    directory = _ensure_directory(git_dir)
    lock_path = directory / LOCK_FILENAME
    if lock_path.is_symlink():
        raise RefusalError(
            "unsafe_lock_file",
            f"Autommit operation lock must not be a symlink: {lock_path}",
        )
    payload = json.dumps({"pid": os.getpid(), "host": os.uname().nodename}).encode(
        "utf-8"
    )
    temp_path = directory / f"lock.{os.getpid()}.tmp"
    try:
        temp_path.write_bytes(payload)
    except OSError as err:
        raise AutommitError(
            "write_failed", f"Failed to prepare lock file at {temp_path}: {err}"
        ) from err

    try:
        try:
            lock_fd = os.open(
                str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
        except FileExistsError as err:
            hint = describe_operation_lock(git_dir)
            msg = f"An autommit operation is already in progress: {lock_path}."
            if hint:
                msg = f"{msg} {hint}"
            raise RefusalError("operation_locked", msg) from err
        except OSError as err:
            raise AutommitError(
                "lock_failed", f"Failed to acquire lock at {lock_path}: {err}"
            ) from err

        try:
            os.write(lock_fd, payload)
        finally:
            os.close(lock_fd)
        _sync_directory(directory)
    finally:
        with contextlib.suppress(OSError):
            temp_path.unlink(missing_ok=True)

    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock_path.unlink(missing_ok=True)
            _sync_directory(directory)
