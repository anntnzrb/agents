# -*- coding: utf-8 -*-
"""Conservative, read-only Dark Souls Remastered PC save reader.

This module deliberately does not share DS3 offsets, container code, or keys.
The DSR PC container is a fixed-size file containing eleven AES-CBC user-data
slots.  A slot is accepted only when its MD5 digest, decryptable block shape,
and basic field invariants agree.  No function in this module writes, repairs,
or re-encrypts save bytes.

Evidence for the container/field layout: Piroshkiv/DSRSave (MIT),
``DSRSave/DSRSaveEditor.cs``, ``Editors/NameEditor.cs`` and
``Editors/StatsEditor.cs``.  The source is recorded in ``resources/save_support.json``.
Anything not covered by that evidence is returned as an explicit unsupported
result rather than guessed from byte patterns.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypedDict, cast

# DSR-specific values from the source cited above.  These are not DS3 values.
SAVE_FILE_SIZE = 0x4204D0
SLOT_SIZE = 0x060030
BASE_SLOT_OFFSET = 0x02C0
USER_DATA_SIZE = 0x060020
SLOT_COUNT = 11
SLOT_HEADER_SIZE = 16
DSR_AES_KEY = bytes.fromhex("0123456789ABCDEFFEDCBA9876543210")

# DSR plaintext offsets, relative to one decrypted user-data slot.
NAME_OFFSETS = (0x108, 0x18C)
NAME_BYTES = 64
STAT_OFFSETS = {
    "vitality": 0x00A0,
    "attunement": 0x00A8,
    "endurance": 0x00B0,
    "strength": 0x00B8,
    "dexterity": 0x00C0,
    "resistance": 0x00E8,
    "intelligence": 0x00C8,
    "faith": 0x00D0,
}
LEVEL_OFFSET = 0x00F0
CLASS_OFFSET = 0x012E
HUMANITY_OFFSET = 0x00E4

# The only auto-detection location.  Explicit paths are permitted separately.
DEFAULT_SAVE_FILENAME = "DRAKS0005.sl2"
DEFAULT_SAVE_RELATIVE = Path("Documents") / "NBGI" / "DARK SOULS REMASTERED"


class UnsupportedResult(TypedDict):
    supported: bool
    reason: str
    evidence: str


class CharacterStats(TypedDict, total=False):
    name: str
    level: int
    class_id: int
    class_name: str
    vitality: int
    attunement: int
    endurance: int
    strength: int
    dexterity: int
    resistance: int
    intelligence: int
    faith: int
    humanity: int
    slot: int
    validated: bool


@dataclass(frozen=True)
class Slot:
    """One validated DSR user-data slot.

    ``data`` is kept private to prevent callers accidentally treating it as a
    writable save representation.  It is only used by this module's readers.
    """

    index: int
    data: bytes
    digest_valid: bool


@dataclass(frozen=True)
class SaveFile:
    path: Path
    slots: tuple[Slot, ...]
    file_size: int


class SaveReadError(ValueError):
    """Safe, user-facing parse failure; no guessed fields are exposed."""


class SaveUnsupportedError(SaveReadError):
    """The file is identifiable but the requested category is unvalidated."""


class _AESCipher(Protocol):
    def decrypt(self, ciphertext: bytes) -> bytes: ...


class _AESModule(Protocol):
    MODE_CBC: int

    def new(self, key: bytes, mode: int, *, iv: bytes) -> _AESCipher: ...


# DSR class IDs from the source StatsEditor.cs.
CLASS_NAMES = {
    0: "Warrior",
    1: "Knight",
    2: "Wanderer",
    3: "Thief",
    4: "Bandit",
    5: "Hunter",
    6: "Sorcerer",
    7: "Pyromancer",
    8: "Cleric",
    9: "Deprived",
}


def _unsupported(
    reason: str, evidence: str = "No validated DSR layout for this category."
) -> UnsupportedResult:
    return {"supported": False, "reason": reason, "evidence": evidence}


def _default_candidates() -> list[Path]:
    """Return documented DSR paths ordered newest first.

    Candidate discovery is intentionally narrow: no recursive drive scan and no
    DS1/DS3 fallback locations are performed.  File metadata can change while
    scanning, so candidates that disappear or cannot be stat'ed are ignored.
    """

    home = Path.home()
    root = home / DEFAULT_SAVE_RELATIVE
    try:
        if not root.is_dir():
            return []
        result: list[tuple[float, Path]] = []
        for child in root.iterdir():
            try:
                if not child.is_dir() or not child.name.isdigit():
                    continue
                candidate = child / DEFAULT_SAVE_FILENAME
                if candidate.is_file() and candidate.suffix.lower() == ".sl2":
                    result.append((candidate.stat().st_mtime, candidate))
            except OSError:
                continue
    except OSError:
        return []
    return [
        candidate
        for _, candidate in sorted(result, key=lambda item: item[0], reverse=True)
    ]


def _candidate_is_defensible(candidate: Path) -> bool:
    """Return whether a candidate contains at least one validated character."""

    try:
        save = read_save(candidate)
    except SaveUnsupportedError:
        # Missing decryption support is actionable and should not be hidden as
        # an absent save.
        raise
    except (OSError, SaveReadError):
        return False

    for slot in save.slots:
        if not slot.data:
            continue
        try:
            _validated_name(slot.data)
        except SaveReadError:
            continue
        if _validate_stats(slot.data) is not None:
            return True
    return False


def _find_valid_default_path(candidates: list[Path]) -> Path | None:
    """Select the newest candidate that survives structural validation."""

    for candidate in candidates:
        if _candidate_is_defensible(candidate):
            return candidate
    return None


def find_save_path() -> str | None:
    """Return the newest defensible default DSR save path, or ``None``.

    Auto-detection intentionally considers only the documented Windows DSR
    path.  Use an explicit path for backups or non-default installations.
    """

    selected = _find_valid_default_path(_default_candidates())
    return str(selected) if selected is not None else None


def resolve_save_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve an explicit ``.sl2`` path or the one verified default path."""

    if path is None:
        candidates = _default_candidates()
        found = _find_valid_default_path(candidates)
        if found is None:
            if candidates:
                raise SaveReadError(
                    "No valid DSR save found at Documents/NBGI/DARK SOULS REMASTERED/"
                    "<SteamID>/DRAKS0005.sl2; discovered candidates were malformed, "
                    "empty, or lacked validated character data. Provide an explicit .sl2 path."
                )
            raise SaveReadError(
                "No DSR save found at Documents/NBGI/DARK SOULS REMASTERED/<SteamID>/DRAKS0005.sl2; "
                "provide an explicit .sl2 path."
            )
        selected = found
    else:
        selected = Path(path).expanduser()
        if selected.suffix.lower() != ".sl2":
            raise SaveReadError(
                "DSR saves must have a .sl2 extension; refusing the supplied path."
            )
    try:
        selected = selected.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SaveReadError(f"Save path is not readable: {selected}") from exc
    if not selected.is_file():
        raise SaveReadError(f"Save path is not a regular file: {selected}")
    return selected


def _decrypt_aes_cbc(ciphertext: bytes, iv: bytes) -> bytes:
    """Decrypt one DSR slot using optional PyCryptodome.

    Decryption is read-only.  If the optional dependency is unavailable, the
    caller receives an explicit unsupported error instead of plaintext guesses.
    """

    try:
        aes = cast(_AESModule, importlib.import_module("Crypto.Cipher.AES"))
    except ImportError as exc:
        raise SaveUnsupportedError(
            "DSR slot decryption requires the optional PyCryptodome package; no fields were read."
        ) from exc
    if len(ciphertext) % 16 or len(iv) != 16:
        raise SaveReadError(
            "DSR slot is not AES-CBC block aligned; refusing to parse it."
        )
    try:
        return aes.new(DSR_AES_KEY, aes.MODE_CBC, iv=iv).decrypt(ciphertext)
    except Exception as exc:  # library-specific errors must not leak or fabricate data
        raise SaveReadError(
            "DSR slot decryption failed; the save may be corrupt or unsupported."
        ) from exc


def _decode_name(data: bytes, offset: int) -> str | None:
    if offset < 0 or offset + NAME_BYTES > len(data):
        return None
    raw = data[offset : offset + NAME_BYTES]
    terminator = next(
        (i for i in range(0, len(raw) - 1, 2) if raw[i : i + 2] == b"\x00\x00"),
        len(raw),
    )
    if terminator == 0:
        return None
    try:
        name = raw[:terminator].decode("utf-16-le", errors="strict")
    except UnicodeDecodeError:
        return None
    if not name or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        return None
    return name


def _json_object(value: object) -> dict[str, object] | None:
    """Narrow a decoded JSON value to an object with string keys."""

    if not isinstance(value, dict):
        return None
    if not all(isinstance(key, str) for key in value):
        return None
    return cast(dict[str, object], value)


def _validate_stats(data: bytes) -> CharacterStats | None:
    if (
        len(data)
        < max(max(STAT_OFFSETS.values()), LEVEL_OFFSET + 2, CLASS_OFFSET + 1) + 1
    ):
        return None
    for offset in STAT_OFFSETS.values():
        value = data[offset]
        if not 1 <= value <= 99:
            return None
    level = struct.unpack_from("<H", data, LEVEL_OFFSET)[0]
    if not 1 <= level <= 713:
        return None
    class_id = data[CLASS_OFFSET]
    if class_id not in CLASS_NAMES:
        return None
    humanity = data[HUMANITY_OFFSET]
    if humanity > 99:
        return None
    stats: CharacterStats = {
        "vitality": data[STAT_OFFSETS["vitality"]],
        "attunement": data[STAT_OFFSETS["attunement"]],
        "endurance": data[STAT_OFFSETS["endurance"]],
        "strength": data[STAT_OFFSETS["strength"]],
        "dexterity": data[STAT_OFFSETS["dexterity"]],
        "resistance": data[STAT_OFFSETS["resistance"]],
        "intelligence": data[STAT_OFFSETS["intelligence"]],
        "faith": data[STAT_OFFSETS["faith"]],
        "level": level,
        "class_id": class_id,
        "class_name": CLASS_NAMES[class_id],
        "humanity": humanity,
        "validated": True,
    }
    return stats


def _parse_slot(raw: bytes, index: int) -> Slot:
    if len(raw) != SLOT_SIZE:
        raise SaveReadError(f"DSR slot {index} has an invalid container size.")
    digest = raw[:SLOT_HEADER_SIZE]
    encrypted = raw[SLOT_HEADER_SIZE : SLOT_HEADER_SIZE + USER_DATA_SIZE]
    if len(encrypted) != USER_DATA_SIZE:
        raise SaveReadError(f"DSR slot {index} is truncated.")
    # DSR stores an MD5 digest in the slot header.  Requiring it avoids treating
    # arbitrary bytes as a character; all-zero empty slots are retained as empty.
    if digest == b"\x00" * SLOT_HEADER_SIZE and encrypted == b"\x00" * USER_DATA_SIZE:
        return Slot(index=index, data=b"", digest_valid=True)
    if hashlib.md5(encrypted).digest() != digest:
        raise SaveReadError(
            f"DSR slot {index} checksum mismatch; refusing to report character data from a malformed save."
        )
    plain = _decrypt_aes_cbc(encrypted, digest)
    if len(plain) != USER_DATA_SIZE:
        raise SaveReadError(f"DSR slot {index} decrypted to an unexpected size.")
    return Slot(index=index, data=plain, digest_valid=True)


def read_save(path: str | os.PathLike[str] | None = None) -> SaveFile:
    """Read and validate a DSR save without modifying it."""

    selected = resolve_save_path(path)
    try:
        raw = selected.read_bytes()
    except OSError as exc:
        raise SaveReadError(f"Unable to read DSR save: {selected}") from exc
    if len(raw) != SAVE_FILE_SIZE:
        raise SaveReadError(
            f"Unsupported DSR save size {len(raw):#x}; expected the validated {SAVE_FILE_SIZE:#x}-byte container."
        )
    slots: list[Slot] = []
    for index in range(SLOT_COUNT):
        start = BASE_SLOT_OFFSET + index * SLOT_SIZE
        end = start + SLOT_SIZE
        slots.append(_parse_slot(raw[start:end], index))
    return SaveFile(path=selected, slots=tuple(slots), file_size=len(raw))


def _select_slot(save: SaveFile, slot: int = 0) -> Slot:
    if (
        not isinstance(slot, int)
        or isinstance(slot, bool)
        or not 0 <= slot < SLOT_COUNT
    ):
        raise SaveReadError(f"Slot must be an integer from 0 through {SLOT_COUNT - 1}.")
    selected = save.slots[slot]
    if not selected.data:
        raise SaveReadError(f"DSR slot {slot} is empty; no character is available.")
    return selected


def read_stats(
    path: str | os.PathLike[str] | None = None, slot: int = 0
) -> dict[str, object]:
    """Return validated character identity and stats for one slot."""

    selected = _select_slot(read_save(path), slot)
    name_a, name_b = (_decode_name(selected.data, offset) for offset in NAME_OFFSETS)
    if name_a is None or name_b is None or name_a != name_b:
        raise SaveReadError(
            "DSR character name copies are absent or disagree; refusing to report identity."
        )
    stats = _validate_stats(selected.data)
    if stats is None:
        raise SaveReadError(
            "DSR stat fields failed range/class validation; refusing to report guessed values."
        )
    return {"name": name_a, "slot": slot, **stats}


def _validated_name(data: bytes) -> str:
    name_a, name_b = (_decode_name(data, offset) for offset in NAME_OFFSETS)
    if name_a is None or name_b is None or name_a != name_b:
        raise SaveReadError(
            "DSR character name copies are absent or disagree; refusing to report identity."
        )
    return name_a


def read_name(path: str | os.PathLike[str] | None = None, slot: int = 0) -> str | None:
    """Read the duplicated UTF-16 name after identity validation."""

    return _validated_name(_select_slot(read_save(path), slot).data)


def read_level(path: str | os.PathLike[str] | None = None, slot: int = 0) -> int:
    """Read the level field after its independent range validation."""

    data = _select_slot(read_save(path), slot).data
    level = struct.unpack_from("<H", data, LEVEL_OFFSET)[0]
    if not 1 <= level <= 713:
        raise SaveReadError(
            "DSR level field failed range validation; refusing to report a guessed value."
        )
    return level


def read_currency(
    path: str | os.PathLike[str] | None = None, slot: int = 0
) -> UnsupportedResult:
    del path, slot
    return _unsupported(
        "Current souls/currency offset is not validated for DSR Remastered."
    )


def read_inventory(
    path: str | os.PathLike[str] | None = None, slot: int = 0
) -> UnsupportedResult:
    del path, slot
    return _unsupported(
        "Inventory record boundaries and item-handle semantics are not validated for DSR Remastered."
    )


def owned_item_names(
    path: str | os.PathLike[str] | None = None, slot: int = 0
) -> UnsupportedResult:
    del path, slot
    return _unsupported(
        "Inventory ownership cannot be established without a validated DSR inventory layout."
    )


def read_bosses(
    path: str | os.PathLike[str] | None = None, slot: int = 0
) -> UnsupportedResult:
    del path, slot
    return _unsupported("Boss/event-flag offsets are not validated for DSR Remastered.")


def read_bonfires(
    path: str | os.PathLike[str] | None = None, slot: int = 0
) -> UnsupportedResult:
    del path, slot
    return _unsupported(
        "Bonfire/event-flag offsets are not validated for DSR Remastered."
    )


def read_completion_status(
    path: str | os.PathLike[str] | None = None, slot: int = 0
) -> UnsupportedResult:
    del path, slot
    return _unsupported(
        "Completion status requires validated inventory and event-flag layouts."
    )


def read_achievements(
    path: str | os.PathLike[str] | None = None, slot: int = 0
) -> dict[str, object]:
    """Return the static checklist and an explicit unknown save-backed state."""

    del path, slot
    resource = (
        Path(__file__).resolve().parent.parent
        / "resources"
        / "achievement_checklist.json"
    )
    try:
        decoded = cast(object, json.loads(resource.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SaveReadError(
            "Achievement checklist resource is unavailable or malformed."
        ) from exc
    raw = _json_object(decoded)
    if raw is None:
        raise SaveReadError(
            "Achievement checklist resource has an invalid top-level shape."
        )
    entries = raw.get("achievements")
    if not isinstance(entries, list):
        raise SaveReadError(
            "Achievement checklist resource has no valid achievements list."
        )
    entries = cast(list[object], entries)
    checklist: list[dict[str, object]] = []
    for entry in entries:
        parsed_entry = _json_object(entry)
        if parsed_entry is None:
            raise SaveReadError(
                "Achievement checklist contains an invalid entry; refusing to report it."
            )
        if not isinstance(parsed_entry.get("id"), str) or not isinstance(
            parsed_entry.get("title"), str
        ):
            raise SaveReadError(
                "Achievement checklist contains an invalid entry; refusing to report it."
            )
        checklist.append(parsed_entry)
    return {
        "supported": True,
        "static": True,
        "save_backed": False,
        "achievements": checklist,
        "save_state": _unsupported(
            "Achievement unlock state is platform-account data, not validated in DSR saves."
        ),
    }


def read_summary(
    path: str | os.PathLike[str] | None = None, slot: int = 0
) -> dict[str, object]:
    """Stable summary API: validated stats plus explicit unsupported categories."""

    stats = read_stats(path, slot)
    return {
        "supported": True,
        "stats": stats,
        "currency": read_currency(path, slot),
        "inventory": read_inventory(path, slot),
        "progress": {
            "bosses": read_bosses(path, slot),
            "bonfires": read_bonfires(path, slot),
        },
        "completion": read_completion_status(path, slot),
        "achievements": read_achievements(path, slot),
        "read_only": True,
    }


# Compatibility spelling used by the CLI's generic save action.
read_progress = read_completion_status

__all__ = [
    "SaveFile",
    "SaveReadError",
    "SaveUnsupportedError",
    "find_save_path",
    "resolve_save_path",
    "read_save",
    "read_summary",
    "read_stats",
    "read_name",
    "read_level",
    "read_currency",
    "read_inventory",
    "owned_item_names",
    "read_bosses",
    "read_bonfires",
    "read_progress",
    "read_completion_status",
    "read_achievements",
]
