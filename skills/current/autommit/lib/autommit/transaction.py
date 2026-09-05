"""Durable receipts and exclusive operation locking."""

from __future__ import annotations

import json
import os
import secrets
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

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

    version: Literal[1]
    state: Literal["prepared", "committed"]
    ref: str
    before: str
    after: str
    index_tree: str


def _paths(common_dir: Path) -> tuple[Path, Path, Path]:
    directory = common_dir / AUTOMMIT_DIRECTORY
    return directory, directory / RECEIPT_FILENAME, directory / LOCK_FILENAME


def _ensure_common_dir(common_dir: Path) -> Result[None, AutommitError]:
    if common_dir.is_symlink() or not common_dir.is_dir():
        return Error(
            AutommitError(
                "invalid_git_directory",
                f"Git common directory is not a real directory: {common_dir}",
                4,
            )
        )
    return Ok(None)


def _ensure_directory(common_dir: Path) -> Result[Path, AutommitError]:
    match _ensure_common_dir(common_dir):
        case Result(tag="ok"):
            directory, _, _ = _paths(common_dir)
            with suppress(FileExistsError):
                directory.mkdir(mode=0o700)
            if directory.is_symlink() or not directory.is_dir():
                return Error(
                    AutommitError(
                        "unsafe_transaction_path",
                        f"Refusing non-directory or symlink Autommit path: {directory}",
                        4,
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
                "unsafe_transaction_path",
                f"Refusing non-regular or symlink Autommit {kind}: {path}",
                4,
            )
        )
    return Ok(value=True)


def _bounded_string(value: object, field: str) -> Result[str, AutommitError]:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_STRING_LENGTH
        or any(
            ord(character) < _MIN_PRINTABLE_ORD or ord(character) == _DELETE_ORD
            for character in value
        )
    ):
        return Error(
            AutommitError(
                "invalid_receipt",
                f"Invalid Autommit receipt: {field} must be non-empty bounded text.",
                4,
            )
        )
    return Ok(value)


def _validate_receipt(value: object) -> Result[Receipt, AutommitError]:
    keys = {"version", "state", "ref", "before", "after", "indexTree"}
    if not isinstance(value, dict):
        return Error(
            AutommitError(
                "invalid_receipt",
                "Invalid Autommit receipt: unexpected shape.",
                4,
            )
        )
    raw = cast("dict[object, object]", value)
    if any(not isinstance(key, str) for key in raw):
        return Error(
            AutommitError(
                "invalid_receipt",
                "Invalid Autommit receipt: unexpected shape.",
                4,
            )
        )
    record = {key: item for key, item in raw.items() if isinstance(key, str)}
    if set(record) != keys:
        return Error(
            AutommitError(
                "invalid_receipt",
                "Invalid Autommit receipt: unexpected shape.",
                4,
            )
        )
    if record["version"] != 1 or record["state"] not in {
        "prepared",
        "committed",
    }:
        return Error(
            AutommitError(
                "invalid_receipt",
                "Invalid Autommit receipt version or state.",
                4,
            )
        )
    state = cast("Literal['prepared', 'committed']", record["state"])
    match _bounded_string(record["ref"], "ref"):
        case Result(tag="ok", ok=ref):
            match _bounded_string(record["before"], "before"):
                case Result(tag="ok", ok=before):
                    match _bounded_string(record["after"], "after"):
                        case Result(tag="ok", ok=after):
                            match _bounded_string(record["indexTree"], "indexTree"):
                                case Result(tag="ok", ok=index_tree):
                                    return Ok(
                                        Receipt(
                                            1,
                                            state,
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
    common_dir: Path,
) -> Result[Option[Receipt], AutommitError]:
    """Read and validate a pending receipt without following symlinks."""
    directory, receipt_path, _ = _paths(common_dir)
    if not directory.exists() and not directory.is_symlink():
        return Ok(Nothing)
    match _ensure_directory(common_dir):
        case Result(tag="ok"):
            match _regular_file(receipt_path, "receipt"):
                case Result(tag="ok", ok=True):
                    try:
                        data = receipt_path.read_bytes()
                    except OSError as error:
                        return Error(
                            AutommitError(
                                "receipt_io",
                                f"Unable to read Autommit receipt: {error}",
                                4,
                            )
                        )
                    if len(data) > MAX_JSON_BYTES:
                        return Error(
                            AutommitError(
                                "invalid_receipt",
                                "Autommit receipt exceeds 16 KiB.",
                                4,
                            )
                        )
                    try:
                        value = cast("object", json.loads(data.decode("utf-8")))
                    except (UnicodeDecodeError, json.JSONDecodeError) as error:
                        return Error(
                            AutommitError(
                                "invalid_receipt",
                                f"Invalid Autommit receipt JSON: {error}",
                                4,
                            )
                        )
                    if receipt_path.is_symlink():
                        return Error(
                            AutommitError(
                                "unsafe_transaction_path",
                                "Autommit receipt became a symlink.",
                                4,
                            )
                        )
                    match _validate_receipt(value):
                        case Result(tag="ok", ok=receipt):
                            return Ok(Some(receipt))
                        case Result(error=err):
                            return Error(err)
                case Result(tag="ok", ok=False):
                    return Ok(Nothing)
                case Result(error=err):
                    return Error(err)
        case Result(error=err):
            return Error(err)


def _sync_directory(directory: Path) -> Result[None, AutommitError]:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError as error:
        if os.name == "nt":
            return Ok(None)
        return Error(
            AutommitError(
                "receipt_io",
                f"Unable to open Autommit directory: {error}",
                4,
            )
        )
    try:
        os.fsync(descriptor)
    except OSError as error:
        if os.name != "nt":
            return Error(
                AutommitError(
                    "receipt_io",
                    f"Unable to sync Autommit directory: {error}",
                    4,
                )
            )
    finally:
        os.close(descriptor)
    return Ok(None)


def write_receipt(common_dir: Path, receipt: Receipt) -> Result[None, AutommitError]:
    """Atomically persist and fsync publication evidence."""
    match _ensure_directory(common_dir):
        case Result(tag="ok", ok=directory):
            _, receipt_path, _ = _paths(common_dir)
            match _regular_file(receipt_path, "receipt"):
                case Result(tag="ok"):
                    serialized_value = {
                        "version": receipt.version,
                        "state": receipt.state,
                        "ref": receipt.ref,
                        "before": receipt.before,
                        "after": receipt.after,
                        "indexTree": receipt.index_tree,
                    }
                    match _validate_receipt(serialized_value):
                        case Result(tag="ok", ok=validated):
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
                                return Error(
                                    AutommitError(
                                        "invalid_receipt",
                                        "Autommit receipt exceeds 16 KiB.",
                                        4,
                                    )
                                )
                            temporary = (
                                directory
                                / f".{RECEIPT_FILENAME}.tmp-{secrets.token_hex(12)}"
                            )
                            try:
                                descriptor = os.open(
                                    temporary,
                                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                    0o600,
                                )
                                with os.fdopen(descriptor, "wb") as handle:
                                    _ = handle.write(serialized)
                                    handle.flush()
                                    os.fsync(handle.fileno())
                                match _regular_file(receipt_path, "receipt"):
                                    case Result(tag="ok"):
                                        _ = temporary.replace(receipt_path)
                                        return _sync_directory(directory)
                                    case Result(error=err):
                                        return Error(err)
                            except OSError as error:
                                return Error(
                                    AutommitError(
                                        "receipt_io",
                                        f"Unable to write Autommit receipt: {error}",
                                        4,
                                    )
                                )
                            finally:
                                with suppress(FileNotFoundError):
                                    temporary.unlink()
                        case Result(error=err):
                            return Error(err)
                case Result(error=err):
                    return Error(err)
        case Result(error=err):
            return Error(err)


def remove_receipt(common_dir: Path) -> Result[None, AutommitError]:
    """Remove a receipt idempotently and durably."""
    directory, receipt_path, _ = _paths(common_dir)
    if not directory.exists() and not directory.is_symlink():
        return Ok(None)
    match _ensure_directory(common_dir):
        case Result(tag="ok"):
            match _regular_file(receipt_path, "receipt"):
                case Result(tag="ok", ok=True):
                    try:
                        receipt_path.unlink()
                    except FileNotFoundError:
                        return Ok(None)
                    except OSError as error:
                        return Error(
                            AutommitError(
                                "receipt_io",
                                f"Unable to remove Autommit receipt: {error}",
                                4,
                            )
                        )
                    return _sync_directory(directory)
                case Result(tag="ok", ok=False):
                    return Ok(None)
                case Result(error=err):
                    return Error(err)
        case Result(error=err):
            return Error(err)


@contextmanager
def operation_lock(common_dir: Path) -> Generator[None, None, None]:
    """Serialize autommit operations; never guess whether an existing lock is stale."""
    match _ensure_directory(common_dir):
        case Result(tag="ok", ok=directory):
            _, _, lock_path = _paths(common_dir)
            owner = {"pid": os.getpid(), "token": secrets.token_urlsafe(24)}
            serialized = (json.dumps(owner, separators=(",", ":")) + "\n").encode()
            if len(serialized) > MAX_LOCK_BYTES:
                raise AutommitError(
                    "lock_error", "Autommit lock metadata exceeds 4 KiB.", 4
                )
            try:
                descriptor = os.open(
                    lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
            except FileExistsError as error:
                raise RefusalError(
                    "operation_locked",
                    f"Autommit operation already in progress (lock: {lock_path}). "
                    + "Inspect its PID; stale locks are never removed automatically.",
                ) from error
            except OSError as error:
                raise AutommitError(
                    "lock_error", f"Unable to acquire Autommit lock: {error}", 4
                ) from error
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    _ = handle.write(serialized)
                    handle.flush()
                    os.fsync(handle.fileno())
                yield
            finally:
                try:
                    match _regular_file(lock_path, "operation lock"):
                        case Result(tag="ok", ok=True):
                            current = cast(
                                "object",
                                json.loads(lock_path.read_text(encoding="utf-8")),
                            )
                            if current == owner:
                                lock_path.unlink()
                                _ = _sync_directory(directory)
                        case _:
                            pass
                except (
                    OSError,
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                    AutommitError,
                ):
                    pass
        case Result(error=err):
            raise err
