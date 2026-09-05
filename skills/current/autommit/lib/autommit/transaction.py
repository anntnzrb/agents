"""Durable receipts and exclusive operation locking scoped to the Git worktree."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from collections.abc import Generator

from expression import Error, Nothing, Ok, Option, Result, Some

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
    state: Literal["prepared", "committed"]
    ref: str
    before: str
    after: str
    index_tree: str


def _paths(git_dir: Path) -> tuple[Path, Path, Path]:
    directory = git_dir / AUTOMMIT_DIRECTORY
    return directory, directory / RECEIPT_FILENAME, directory / LOCK_FILENAME


def _ensure_git_dir(git_dir: Path) -> Result[None, AutommitError]:
    if git_dir.is_symlink() or not git_dir.is_dir():
        return Error(
            AutommitError(
                "invalid_git_dir",
                "Git directory must be a non-symlink directory.",
            )
        )
    return Ok(None)


def _ensure_directory(git_dir: Path) -> Result[Path, AutommitError]:
    match _ensure_git_dir(git_dir):
        case Result(tag="ok"):
            directory, _, _ = _paths(git_dir)
            if directory.is_symlink():
                return Error(
                    AutommitError(
                        "invalid_directory",
                        "Autommit state directory must not be a symlink.",
                    )
                )
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                return Error(
                    AutommitError(
                        "directory_creation_failed",
                        f"Unable to create autommit state directory: {error}.",
                    )
                )
            if directory.is_symlink() or not directory.is_dir():
                return Error(
                    AutommitError(
                        "invalid_directory",
                        "Autommit state directory must be a non-symlink directory.",
                    )
                )
            return Ok(directory)
        case Result(error=err):
            return Error(err)


def _regular_file(path: Path, kind: str) -> Result[bool, AutommitError]:
    if not path.exists() and not path.is_symlink():
        return Ok(value=False)
    if path.is_symlink() or not path.is_file():
        return Error(
            AutommitError(
                f"invalid_{kind}_file",
                (
                    f"Autommit {kind} file must be a regular file, "
                    "not a symlink or directory."
                ),
            )
        )
    return Ok(value=True)


def _bounded_string(value: object, field: str) -> Result[str, AutommitError]:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_STRING_LENGTH
        or any(
            ord(char) < _MIN_PRINTABLE_ORD or ord(char) == _DELETE_ORD for char in value
        )
    ):
        return Error(
            AutommitError(
                "invalid_receipt",
                (
                    f"Autommit receipt field {field} must be a "
                    "non-empty bounded printable string."
                ),
            )
        )
    return Ok(value)


def _validate_receipt(value: object) -> Result[Receipt, AutommitError]:
    keys = {"version", "state", "ref", "before", "after", "indexTree"}
    if not isinstance(value, dict) or set(value.keys()) != keys:
        return Error(
            AutommitError(
                "invalid_receipt",
                "Autommit receipt must contain the exact expected schema keys.",
            )
        )
    raw = cast("dict[str, object]", value)
    if raw.get("version") != 1:
        return Error(
            AutommitError(
                "invalid_receipt",
                "Unsupported Autommit receipt version.",
            )
        )
    state = raw.get("state")
    if state not in ("prepared", "committed"):
        return Error(
            AutommitError(
                "invalid_receipt",
                "Autommit receipt state must be prepared or committed.",
            )
        )
    match _bounded_string(raw.get("ref"), "ref"):
        case Result(tag="ok", ok=ref):
            match _bounded_string(raw.get("before"), "before"):
                case Result(tag="ok", ok=before):
                    match _bounded_string(raw.get("after"), "after"):
                        case Result(tag="ok", ok=after):
                            match _bounded_string(raw.get("indexTree"), "indexTree"):
                                case Result(tag="ok", ok=index_tree):
                                    return Ok(
                                        Receipt(
                                            1,
                                            cast(
                                                'Literal["prepared", "committed"]',
                                                state,
                                            ),
                                            ref,
                                            before,
                                            after,
                                            index_tree,
                                        )
                                    )
                                case Result(error=err):
                                    return Error(err)
                        case Result(error=err):
                            return Error(err)
                case Result(error=err):
                    return Error(err)
        case Result(error=err):
            return Error(err)


def read_receipt(
    git_dir: Path,
) -> Result[Option[Receipt], AutommitError]:
    """Read and validate a pending receipt without following symlinks."""
    match _ensure_git_dir(git_dir):
        case Result(tag="ok"):
            _, receipt_path, _ = _paths(git_dir)
            match _regular_file(receipt_path, "receipt"):
                case Result(tag="ok", ok=is_regular):
                    if not is_regular:
                        return Ok(Nothing)
                    try:
                        with receipt_path.open("rb") as handle:
                            content = handle.read(MAX_JSON_BYTES + 1)
                    except OSError as error:
                        return Error(
                            AutommitError(
                                "receipt_io",
                                f"Unable to read Autommit receipt: {error}.",
                            )
                        )
                    if len(content) > MAX_JSON_BYTES:
                        return Error(
                            AutommitError(
                                "receipt_payload_too_large",
                                "Autommit receipt payload exceeds size limit.",
                            )
                        )
                    try:
                        data: object = json.loads(content.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as error:
                        return Error(
                            AutommitError(
                                "invalid_receipt",
                                f"Autommit receipt is not valid JSON: {error}.",
                            )
                        )
                    match _validate_receipt(data):
                        case Result(tag="ok", ok=receipt):
                            return Ok(Some(receipt))
                        case Result(error=err):
                            return Error(err)
                case Result(error=err):
                    return Error(err)
        case Result(error=err):
            return Error(err)


def _sync_directory(directory: Path) -> Result[None, AutommitError]:
    if os.name == "nt":
        return Ok(None)
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError as error:
        return Error(
            AutommitError(
                "directory_sync_failed",
                f"Unable to open Autommit directory for sync: {error}.",
            )
        )
    try:
        os.fsync(descriptor)
    except OSError as error:
        return Error(
            AutommitError(
                "directory_sync_failed",
                f"Unable to sync Autommit directory: {error}.",
            )
        )
    finally:
        with suppress(OSError):
            os.close(descriptor)
    return Ok(None)


def write_receipt(git_dir: Path, receipt: Receipt) -> Result[None, AutommitError]:
    """Atomically persist and fsync publication evidence."""
    match _ensure_directory(git_dir):
        case Result(tag="ok", ok=directory):
            _, receipt_path, _ = _paths(git_dir)
            temp_path = directory / f"{RECEIPT_FILENAME}.tmp"
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
            try:
                with open(
                    temp_path,
                    "wb",
                    opener=lambda path, flags: os.open(
                        path, flags | os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600
                    ),
                ) as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                temp_path.replace(receipt_path)
            except OSError as error:
                return Error(
                    AutommitError(
                        "receipt_write_failed",
                        f"Unable to persist Autommit receipt: {error}.",
                    )
                )
            return _sync_directory(directory)
        case Result(error=err):
            return Error(err)


def remove_receipt(git_dir: Path) -> Result[None, AutommitError]:
    """Remove a receipt idempotently and durably."""
    match _ensure_directory(git_dir):
        case Result(tag="ok", ok=directory):
            _, receipt_path, _ = _paths(git_dir)
            try:
                receipt_path.unlink(missing_ok=True)
            except OSError as error:
                return Error(
                    AutommitError(
                        "receipt_remove_failed",
                        f"Unable to remove Autommit receipt: {error}.",
                    )
                )
            return _sync_directory(directory)
        case Result(error=err):
            return Error(err)


@contextmanager
def operation_lock(git_dir: Path) -> Generator[None, None, None]:
    """Serialize autommit operations for the target worktree; no stale lock guessing."""
    match _ensure_directory(git_dir):
        case Result(tag="ok", ok=directory):
            _, _, lock_path = _paths(git_dir)
            descriptor: int | None = None
            try:
                try:
                    descriptor = os.open(
                        lock_path,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                        0o600,
                    )
                except FileExistsError:
                    raise RefusalError(
                        "operation_locked",
                        (
                            "Another Autommit process holds the operation "
                            "lock for this worktree."
                        ),
                    ) from None
                except OSError as error:
                    raise AutommitError(
                        "lock_failed",
                        f"Unable to create Autommit operation lock: {error}.",
                    ) from error
                try:
                    metadata = json.dumps(
                        {"pid": os.getpid(), "command": "autommit"}
                    ).encode("utf-8")
                    os.write(descriptor, metadata)
                    os.fsync(descriptor)
                except OSError as error:
                    raise AutommitError(
                        "lock_write_failed",
                        f"Unable to write Autommit lock payload: {error}.",
                    ) from error
                match _sync_directory(directory):
                    case Result(tag="ok"):
                        pass
                    case Result(error=err):
                        raise err
                yield
            finally:
                if descriptor is not None:
                    with suppress(OSError):
                        os.close(descriptor)
                    with suppress(OSError):
                        lock_path.unlink(missing_ok=True)
                    _ = _sync_directory(directory)
        case Result(error=err):
            raise err
