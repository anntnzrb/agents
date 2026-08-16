# ruff: noqa: CPY001, EM101, PLR2004, TC003
"""Durable receipts and exclusive operation locking."""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from autommit.errors import AutommitError, RefusalError

AUTOMMIT_DIRECTORY = "autommit"
RECEIPT_FILENAME = "receipt.json"
LOCK_FILENAME = "operation.lock"
MAX_JSON_BYTES = 16 * 1024
MAX_LOCK_BYTES = 4 * 1024
MAX_STRING_LENGTH = 4 * 1024


@dataclass(frozen=True, slots=True)
class Receipt:
    """Publication evidence persisted before compare-and-swap."""

    version: Literal[1]
    state: Literal["prepared", "committed"]
    ref: str
    before: str
    after: str
    index_tree: str


def _paths(common_dir: Path) -> tuple[Path, Path, Path]:
    directory = common_dir / AUTOMMIT_DIRECTORY
    return directory, directory / RECEIPT_FILENAME, directory / LOCK_FILENAME


def _ensure_common_dir(common_dir: Path) -> None:
    if common_dir.is_symlink() or not common_dir.is_dir():
        raise AutommitError(
            "invalid_git_directory",
            f"Git common directory is not a real directory: {common_dir}",
            4,
        )


def _ensure_directory(common_dir: Path) -> Path:
    _ensure_common_dir(common_dir)
    directory, _, _ = _paths(common_dir)
    with suppress(FileExistsError):
        directory.mkdir(mode=0o700)
    if directory.is_symlink() or not directory.is_dir():
        raise AutommitError(
            "unsafe_transaction_path",
            f"Refusing non-directory or symlink Autommit path: {directory}",
            4,
        )
    return directory


def _regular_file(path: Path, kind: str) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink() or not path.is_file():
        raise AutommitError(
            "unsafe_transaction_path",
            f"Refusing non-regular or symlink Autommit {kind}: {path}",
            4,
        )
    return True


def _bounded_string(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_STRING_LENGTH
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise AutommitError(
            "invalid_receipt",
            f"Invalid Autommit receipt: {field} must be non-empty bounded text.",
            4,
        )
    return value


def _validate_receipt(value: object) -> Receipt:
    keys = {"version", "state", "ref", "before", "after", "indexTree"}
    if not isinstance(value, dict):
        raise AutommitError(
            "invalid_receipt",
            "Invalid Autommit receipt: unexpected shape.",
            4,
        )
    raw = cast("dict[object, object]", value)
    if any(not isinstance(key, str) for key in raw):
        raise AutommitError(
            "invalid_receipt",
            "Invalid Autommit receipt: unexpected shape.",
            4,
        )
    record = {key: item for key, item in raw.items() if isinstance(key, str)}
    if set(record) != keys:
        raise AutommitError(
            "invalid_receipt",
            "Invalid Autommit receipt: unexpected shape.",
            4,
        )
    if record["version"] != 1 or record["state"] not in {"prepared", "committed"}:
        raise AutommitError(
            "invalid_receipt",
            "Invalid Autommit receipt version or state.",
            4,
        )
    state = cast("Literal['prepared', 'committed']", record["state"])
    return Receipt(
        1,
        state,
        _bounded_string(record["ref"], "ref"),
        _bounded_string(record["before"], "before"),
        _bounded_string(record["after"], "after"),
        _bounded_string(record["indexTree"], "indexTree"),
    )


def read_receipt(common_dir: Path) -> Receipt | None:
    """Read and validate a pending receipt without following symlinks."""
    directory, receipt_path, _ = _paths(common_dir)
    if not directory.exists() and not directory.is_symlink():
        return None
    _ensure_directory(common_dir)
    if not _regular_file(receipt_path, "receipt"):
        return None
    try:
        data = receipt_path.read_bytes()
    except OSError as error:
        raise AutommitError(
            "receipt_io", f"Unable to read Autommit receipt: {error}", 4
        ) from error
    if len(data) > MAX_JSON_BYTES:
        raise AutommitError("invalid_receipt", "Autommit receipt exceeds 16 KiB.", 4)
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AutommitError(
            "invalid_receipt", f"Invalid Autommit receipt JSON: {error}", 4
        ) from error
    if receipt_path.is_symlink():
        raise AutommitError(
            "unsafe_transaction_path", "Autommit receipt became a symlink.", 4
        )
    return _validate_receipt(value)


def _sync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError as error:
        if os.name == "nt":
            return
        raise AutommitError(
            "receipt_io", f"Unable to open Autommit directory: {error}", 4
        ) from error
    try:
        os.fsync(descriptor)
    except OSError as error:
        if os.name != "nt":
            raise AutommitError(
                "receipt_io", f"Unable to sync Autommit directory: {error}", 4
            ) from error
    finally:
        os.close(descriptor)


def write_receipt(common_dir: Path, receipt: Receipt) -> None:
    """Atomically persist and fsync publication evidence."""
    directory = _ensure_directory(common_dir)
    _, receipt_path, _ = _paths(common_dir)
    _regular_file(receipt_path, "receipt")
    serialized_value = {
        "version": receipt.version,
        "state": receipt.state,
        "ref": receipt.ref,
        "before": receipt.before,
        "after": receipt.after,
        "indexTree": receipt.index_tree,
    }
    validated = _validate_receipt(serialized_value)
    serialized = (
        json.dumps(
            {
                "version": validated.version,
                "state": validated.state,
                "ref": validated.ref,
                "before": validated.before,
                "after": validated.after,
                "indexTree": validated.index_tree,
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    if len(serialized) > MAX_JSON_BYTES:
        raise AutommitError("invalid_receipt", "Autommit receipt exceeds 16 KiB.", 4)
    temporary = directory / f".{RECEIPT_FILENAME}.tmp-{secrets.token_hex(12)}"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        _regular_file(receipt_path, "receipt")
        temporary.replace(receipt_path)
        _sync_directory(directory)
    except OSError as error:
        raise AutommitError(
            "receipt_io", f"Unable to write Autommit receipt: {error}", 4
        ) from error
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def remove_receipt(common_dir: Path) -> None:
    """Remove a receipt idempotently and durably."""
    directory, receipt_path, _ = _paths(common_dir)
    if not directory.exists() and not directory.is_symlink():
        return
    _ensure_directory(common_dir)
    if not _regular_file(receipt_path, "receipt"):
        return
    try:
        receipt_path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise AutommitError(
            "receipt_io", f"Unable to remove Autommit receipt: {error}", 4
        ) from error
    _sync_directory(directory)


@contextmanager
def operation_lock(common_dir: Path) -> Generator[None]:
    """Serialize autommit operations; never guess whether an existing lock is stale."""
    directory = _ensure_directory(common_dir)
    _, _, lock_path = _paths(common_dir)
    owner = {"pid": os.getpid(), "token": secrets.token_urlsafe(24)}
    serialized = (json.dumps(owner, separators=(",", ":")) + "\n").encode()
    if len(serialized) > MAX_LOCK_BYTES:
        raise AutommitError("lock_error", "Autommit lock metadata exceeds 4 KiB.", 4)
    try:
        descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise RefusalError(
            "operation_locked",
            f"Autommit operation already in progress (lock: {lock_path}). "
            "Inspect its PID; stale locks are never removed automatically.",
        ) from error
    except OSError as error:
        raise AutommitError(
            "lock_error", f"Unable to acquire Autommit lock: {error}", 4
        ) from error
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        try:
            if _regular_file(lock_path, "operation lock"):
                current = json.loads(lock_path.read_text(encoding="utf-8"))
                if current == owner:
                    lock_path.unlink()
                    _sync_directory(directory)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AutommitError):
            pass
