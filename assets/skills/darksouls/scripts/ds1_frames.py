# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only DARK SOULS REMASTERED local frame scanner.

This module deliberately keeps all binary payloads in memory.  Public values
contain relative source identities and evidence labels, never install paths or
raw event bytes.
"""

from __future__ import annotations

import argparse
import math
import re
import struct
import zlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

FRAME_RATE = 30
_WEAPON_ROW_SIZE = 0x110
_GOODS_ROW_SIZE = 92


class FrameScannerError(ValueError):
    """Base class for scanner failures."""


class FrameInstallError(FrameScannerError):
    """The supplied install is missing or cannot be read."""


class FrameFormatError(FrameScannerError):
    """A local binary has invalid magic, offsets, counts, or values."""


class FrameQueryError(FrameScannerError):
    """A selection argument is invalid or has no matching records."""


@dataclass(frozen=True)
class _Member:
    name: str
    data: bytes


@dataclass(frozen=True)
class _Event:
    event_type: int
    start_seconds: float
    end_seconds: float
    start_frame: int
    end_frame: int
    behavior_judge_id: int | None = None


@dataclass(frozen=True)
class _Animation:
    animation_id: int
    events: tuple[_Event, ...]


@dataclass(frozen=True)
class ScanResult:
    """In-memory scan result returned by :func:`scan_install`."""

    schema_version: str
    frame_rate: int
    summary: Mapping[str, Any]
    weapons: tuple[Mapping[str, Any], ...]
    items: tuple[Mapping[str, Any], ...]
    sources: Mapping[str, str]

    @property
    def records(self) -> tuple[Mapping[str, Any], ...]:
        return self.weapons + self.items


def _u16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise FrameFormatError("PARAM field offset is outside payload")
    return struct.unpack_from("<H", data, offset)[0]


def _i16(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise FrameFormatError("PARAM field offset is outside payload")
    return struct.unpack_from("<h", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise FrameFormatError("binary field offset is outside payload")
    return struct.unpack_from("<I", data, offset)[0]


def _i32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise FrameFormatError("binary field offset is outside payload")
    return struct.unpack_from("<i", data, offset)[0]


def _f32(data: bytes, offset: int) -> float:
    if offset < 0 or offset + 4 > len(data):
        raise FrameFormatError("float field offset is outside payload")
    value = struct.unpack_from("<f", data, offset)[0]
    if not math.isfinite(value):
        raise FrameFormatError("TAE timing contains a non-finite float32")
    return value


def _name(data: bytes, offset: int, encoding: str = "shift_jis") -> str:
    if offset < 0 or offset >= len(data):
        return ""
    end = data.find(b"\0", offset)
    if end < 0:
        return ""
    try:
        return data[offset:end].decode(encoding, errors="replace").strip()
    except (LookupError, UnicodeError):
        return ""


def _read_dcx_bnd3(path: Path) -> tuple[_Member, ...]:
    try:
        compressed = path.read_bytes()
    except OSError as exc:
        raise FrameInstallError(
            f"cannot read required install file: {path.name}"
        ) from exc
    if len(compressed) < 0x50 or compressed[:4] != b"DCX\0":
        raise FrameFormatError(f"{path.name}: expected DCX")
    try:
        payload = zlib.decompress(compressed[0x4C:])
    except zlib.error as exc:
        raise FrameFormatError(f"{path.name}: invalid DCX zlib stream") from exc
    if len(payload) < 0x20 or payload[:4] != b"BND3":
        raise FrameFormatError(f"{path.name}: expected BND3 payload")
    count = _u32(payload, 0x10)
    if count > 1_000_000 or 0x20 + count * 0x18 > len(payload):
        raise FrameFormatError(f"{path.name}: BND3 member count is out of bounds")
    members: list[_Member] = []
    for index in range(count):
        record = 0x20 + index * 0x18
        size = _u32(payload, record + 4)
        data_offset = _u32(payload, record + 8)
        name_offset = _u32(payload, record + 16)
        if data_offset > len(payload) or size > len(payload) - data_offset:
            raise FrameFormatError(f"{path.name}: BND3 member data is out of bounds")
        if name_offset >= len(payload):
            raise FrameFormatError(f"{path.name}: BND3 member name is out of bounds")
        member_name = _name(payload, name_offset)
        if not member_name:
            raise FrameFormatError(f"{path.name}: BND3 member has no name")
        members.append(_Member(member_name, payload[data_offset : data_offset + size]))
    return tuple(members)


def _member(members: Sequence[_Member], suffix: str) -> _Member | None:
    wanted = suffix.casefold()
    for item in members:
        normalized = item.name.replace("\\", "/").casefold()
        if normalized.endswith(wanted):
            return item
    return None


def _read_tae(data: bytes) -> tuple[_Animation, ...]:
    if len(data) < 0x5C or data[:4] != b"TAE ":
        raise FrameFormatError("expected DS1/DSR TAE payload")
    if data[7] != 0 or _u32(data, 8) != 0x1000B:
        raise FrameFormatError("expected little-endian DS1/DSR TAE 0x1000B")
    count = _u32(data, 0x54)
    headers = _u32(data, 0x58)
    if count > 1_000_000 or headers > len(data) or count * 8 > len(data) - headers:
        raise FrameFormatError("TAE animation table is out of bounds")
    animations: list[_Animation] = []
    for index in range(count):
        header = headers + index * 8
        animation_id = _u32(data, header)
        animation_offset = _u32(data, header + 4)
        if animation_offset > len(data) or animation_offset + 8 > len(data):
            raise FrameFormatError("TAE animation header is out of bounds")
        event_count = _i32(data, animation_offset)
        events_offset = _u32(data, animation_offset + 4)
        if (
            event_count < 0
            or event_count > 1_000_000
            or events_offset > len(data)
            or event_count * 12 > len(data) - events_offset
        ):
            raise FrameFormatError("TAE event table is out of bounds")
        rows: list[tuple[int, int, int, float, float]] = []
        for event_index in range(event_count):
            event_header = events_offset + event_index * 12
            start_offset = _u32(data, event_header)
            end_offset = _u32(data, event_header + 4)
            data_offset = _u32(data, event_header + 8)
            start = _f32(data, start_offset)
            end = _f32(data, end_offset)
            if data_offset > len(data) or data_offset + 4 > len(data):
                raise FrameFormatError("TAE event payload is out of bounds")
            rows.append((data_offset, event_header, event_index, start, end))
        data_offsets = sorted({row[0] for row in rows})
        next_offset = {
            offset: (data_offsets[i + 1] if i + 1 < len(data_offsets) else len(data))
            for i, offset in enumerate(data_offsets)
        }
        events: list[_Event] = []
        for data_offset, _header, _event_index, start, end in rows:
            event_type = _i32(data, data_offset)
            judge: int | None = None
            if event_type == 1:
                parameter_start = data_offset + 8
                parameter_end = next_offset[data_offset]
                if parameter_end < parameter_start:
                    raise FrameFormatError("TAE event parameter range is invalid")
                if parameter_end - parameter_start == 12:
                    judge = _i32(data, parameter_start + 8)
            events.append(
                _Event(
                    event_type,
                    start,
                    end,
                    round(start * FRAME_RATE),
                    round(end * FRAME_RATE),
                    judge,
                )
            )
        animations.append(_Animation(animation_id, tuple(events)))
    return tuple(animations)


def _param_rows(data: bytes, minimum_size: int) -> list[tuple[int, int, int]]:
    if len(data) < 0x4C:
        raise FrameFormatError("PARAM member is too short")
    table_end = _u32(data, 0x34)
    if table_end <= 0x30 or table_end > len(data) or (table_end - 0x30) % 12:
        raise FrameFormatError("PARAM row index is malformed")
    entry_count = (table_end - 0x30) // 12
    if entry_count < 1:
        raise FrameFormatError("PARAM row index is empty")
    entries = [
        (
            _u32(data, 0x30 + i * 12),
            _u32(data, 0x34 + i * 12),
            _u32(data, 0x38 + i * 12),
        )
        for i in range(entry_count)
    ]
    # DSR PARAM indices are normally [row_id,row_offset,name_offset].
    # A few tools emit [row_offset,name_offset,row_id]; identify the layout
    # from the fixed row stride rather than trusting plausible-looking values.
    layout: int | None = None
    for candidate in (0, 1):
        if entry_count >= 2:
            stride = entries[1][candidate] - entries[0][candidate]
            if stride >= minimum_size and stride <= len(data):
                if all(
                    entries[i][candidate] + minimum_size <= len(data)
                    and (
                        i == 0
                        or entries[i][candidate] - entries[i - 1][candidate] == stride
                    )
                    for i in range(min(entry_count, 64))
                ):
                    layout = candidate
                    break
        else:
            if entries[0][candidate] + minimum_size <= len(data):
                layout = candidate
                break
    if layout is None:
        raise FrameFormatError("PARAM row index has no fixed row stride")
    rows: list[tuple[int, int, int]] = []
    for first, second, third in entries:
        if layout == 1:
            row_id, row_offset, name_offset = first, second, third
        else:
            row_offset, name_offset, row_id = first, second, third
        if row_offset + minimum_size > len(data) or name_offset >= len(data):
            continue
        rows.append((row_id, row_offset, name_offset))
    if not rows:
        raise FrameFormatError("PARAM row index is empty")
    return rows


def _fmg_names(data: bytes) -> dict[int, list[str]]:
    if len(data) < 0x20 or _u32(data, 0) != 0x10000:
        return {}
    group_count, pointer_table = _u32(data, 0x0C), _u32(data, 0x14)
    if pointer_table <= 0x20 or pointer_table >= len(data):
        return {}
    max_groups = min(group_count, (pointer_table - 0x20) // 12)
    names: dict[int, list[str]] = defaultdict(list)
    for i in range(max_groups):
        first, last, pointer = (
            _u32(data, 0x20 + i * 12),
            _u32(data, 0x24 + i * 12),
            _u32(data, 0x28 + i * 12),
        )
        if pointer == 0 or last < first or last - first > 1_000_000:
            continue
        for item_id in range(first, last + 1):
            po = pointer_table + (pointer + item_id - first) * 4
            if po + 4 > len(data):
                continue
            text_offset = _u32(data, po)
            if text_offset == 0 or text_offset + 2 > len(data) or text_offset & 1:
                continue
            end = text_offset
            while end + 1 < len(data) and data[end : end + 2] != b"\0\0":
                end += 2
            try:
                text = (
                    data[text_offset:end].decode("utf-16le", errors="replace").strip()
                )
            except UnicodeError:
                continue
            if text:
                names[item_id].append(text)
    return dict(names)


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _weapon_name(
    row_id: int, names: Mapping[int, Sequence[str]]
) -> tuple[str | None, int | None, str]:
    aliases = {100_000: 100, 350_000: 315_700, 1_105_000: 1_103_900}
    candidates = [aliases[row_id]] if row_id in aliases else []
    candidates.extend(
        (row_id, row_id - 100, row_id - 1100, row_id - 1000, row_id - 200)
    )
    upgrade = (
        "crystal ",
        "crys. ",
        "lightning ",
        "raw ",
        "magic ",
        "enchanted ",
        "divine ",
        "occult ",
        "fire ",
        "chaos ",
    )
    found: list[tuple[str, int]] = []
    seen: set[int] = set()
    for message_id in candidates:
        if message_id in seen:
            continue
        seen.add(message_id)
        for value in names.get(message_id, ()):
            if not value.casefold().startswith(upgrade) and not re.search(
                r"\+\d+$", value
            ):
                found.append((value, message_id))
    unique = list(dict.fromkeys(found))
    if len(unique) == 1:
        return (
            unique[0][0],
            unique[0][1],
            "local_message_id_alias"
            if row_id in aliases
            else "local_message_id_candidate",
        )
    if len(unique) > 1:
        return None, None, "unresolved_ambiguous_local_name_ids"
    return None, None, "unresolved_no_local_english_name_id"


def _goods_name(
    parameter: str,
    english: Mapping[int, Sequence[str]],
    japanese: Mapping[int, Sequence[str]],
) -> tuple[list[str], dict[str, Any]]:
    key = _norm(parameter)
    ids: list[int] = []
    if key:
        for message_id, values in japanese.items():
            if message_id < 3000 and any(_norm(value) == key for value in values):
                ids.append(message_id)
        if not ids:
            for message_id, values in japanese.items():
                if message_id < 3000 and any(
                    len(_norm(value)) >= 4
                    and (_norm(value) in key or key in _norm(value))
                    for value in values
                ):
                    ids.append(message_id)
    special = {
        "武器炎強化": (238, 260),
        "武器雷強化": (239, 261),
        "武器毒化": (263,),
        "武器対霊強化": (240, 262),
        "帰還石": (266, 310),
        "帰還": (266, 310),
        "火の防人のソウル": tuple(range(288, 295)),
        "大王グウィンのソウル": (387, 502),
        "ゴーレムのソウル": (388,),
        "金キメラのソウル": (394,),
        "深淵の主のソウル": (396, 511),
    }
    for token, values in special.items():
        if token in parameter:
            ids = list(values)
            break
    match = re.search(r"エストビン（HP）([1-8])_補充", parameter)
    if match:
        tier = int(match.group(1)) - 1
        ids = [100 + tier * 2, 101 + tier * 2]
    result: list[str] = []
    for message_id in ids:
        for value in english.get(message_id, ()):
            if value not in result:
                result.append(value)
    return result, {
        "basis": "local_fmg_japanese_identity"
        if result
        else "no_local_fmg_identity_relation",
        "confidence": "high" if result else "unresolved",
        "japanese_message_ids": ids,
        "english_message_ids": [i for i in ids if english.get(i)],
    }


def _decode_goods_rows(data: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row_id, offset, name_offset in _param_rows(data, _GOODS_ROW_SIZE):
        row = data[offset : offset + _GOODS_ROW_SIZE]
        values = [_i32(row, n) for n in range(0, 44, 4)]
        flags_bits = int.from_bytes(row[66:71], "little")
        flags = {
            "isEquip": bool(flags_bits & (1 << 23)),
            "isConsume": bool(flags_bits & (1 << 24)),
        }
        rows.append(
            {
                "parameter_row_id": row_id,
                "parameter_name": _name(data, name_offset),
                "ref_id": values[0],
                "sfx_variation_id": values[1],
                "behavior_id": values[5],
                "goods_use_anim": row[62],
                "goods_category": row[61],
                "flags": flags,
            }
        )
    return rows


def _decode_weapon_rows(data: bytes) -> list[tuple[int, int, int]]:
    return _param_rows(data, _WEAPON_ROW_SIZE)


def _relative_member(member_name: str, fallback: str) -> str:
    leaf = member_name.replace("\\", "/").split("/")[-1]
    return f"chr/c0000.anibnd.dcx#{leaf}" if member_name else fallback


def scan_install(install: str | Path) -> ScanResult:
    root = Path(install).expanduser()
    if not root.is_dir():
        raise FrameInstallError("DSR install directory does not exist")
    game_path = root / "param" / "GameParam" / "GameParam.parambnd.dcx"
    anim_path = root / "chr" / "c0000.anibnd.dcx"
    if not game_path.is_file() or not anim_path.is_file():
        raise FrameInstallError(
            "DSR install is missing required GameParam or c0000 animation bundle"
        )
    game = _read_dcx_bnd3(game_path)
    weapon_member = _member(game, "EquipParamWeapon.param")
    goods_member = _member(game, "EquipParamGoods.param")
    behavior_member = _member(game, "BehaviorParam_PC.param")
    if weapon_member is None or goods_member is None or behavior_member is None:
        raise FrameInstallError("GameParam bundle is missing required PARAM members")
    weapons_rows = _decode_weapon_rows(weapon_member.data)
    goods_rows = _decode_goods_rows(goods_member.data)
    behavior_rows = _param_rows(behavior_member.data, 20)
    behavior_by_variation: dict[int, list[dict[str, int]]] = defaultdict(list)
    for action_id, offset, _name_offset in behavior_rows:
        behavior_by_variation[_i32(behavior_member.data, offset)].append(
            {
                "action_id": action_id,
                "behavior_judge_id": _i32(behavior_member.data, offset + 4),
                "ref_type": behavior_member.data[offset + 9],
                "ref_id": _i32(behavior_member.data, offset + 12),
            }
        )
    banks: dict[int, tuple[str, tuple[_Animation, ...]]] = {}
    for member in _read_dcx_bnd3(anim_path):
        match = re.search(r"(?:^|/)a(\d+)\.tae$", member.name.replace("\\", "/"), re.I)
        if match:
            banks[int(match.group(1))] = (member.name, _read_tae(member.data))
    english_weapon: Mapping[int, Sequence[str]] = {}
    english_item: Mapping[int, Sequence[str]] = {}
    japanese: Mapping[int, Sequence[str]] = {}
    msg_root = root / "msg"
    for language, target in (("ENGLISH", "english"), ("JAPANESE", "japanese")):
        path = msg_root / language / "item.msgbnd.dcx"
        if path.is_file():
            for member in _read_dcx_bnd3(path):
                lowered = member.name.casefold()
                if "weapon_name_.fmg" in lowered and target == "english":
                    english_weapon = _fmg_names(member.data)
                elif "item_name_.fmg" in lowered:
                    parsed = _fmg_names(member.data)
                    if target == "english":
                        english_item = parsed
                    else:
                        japanese = parsed
    english = english_weapon
    weapon_records: list[Mapping[str, Any]] = []
    for row_id, offset, name_offset in weapons_rows:
        if row_id % 1000 != 0:
            continue
        parameter_name = _name(weapon_member.data, name_offset)
        if not parameter_name:
            continue
        category = weapon_member.data[offset + 226]
        if category in (12, 13, 14):
            continue
        variation = _i32(weapon_member.data, offset)
        motion = weapon_member.data[offset + 227]
        sp = weapon_member.data[offset + 234]
        one = weapon_member.data[offset + 235]
        both = weapon_member.data[offset + 236]
        bank = banks.get(motion)
        animations = bank[1] if bank else ()
        judges = {
            item["behavior_judge_id"]
            for item in behavior_by_variation.get(variation, ())
        }
        actions: list[dict[str, Any]] = []
        for animation in animations:
            for event in animation.events:
                if (
                    event.event_type == 1
                    and event.behavior_judge_id is not None
                    and event.behavior_judge_id in judges
                ):
                    actions.append(
                        {
                            "action": "weapon_action_timing",
                            "status": "resolved",
                            "animation_id": animation.animation_id,
                            "event_type": 1,
                            "start_seconds": event.start_seconds,
                            "end_seconds": event.end_seconds,
                            "frames_30fps": {
                                "start": event.start_frame,
                                "end": event.end_frame,
                            },
                            "evidence": "confirmed_event1_behavior_judge_join",
                        }
                    )
        if not actions:
            actions.append(
                {
                    "action": "weapon_action_timing",
                    "status": "unresolved",
                    "animation_id": None,
                    "event_type": 1,
                    "start_seconds": None,
                    "end_seconds": None,
                    "frames_30fps": None,
                    "evidence": "no_confirmed_event1_behavior_judge_join",
                }
            )
        name, message_id, name_status = _weapon_name(row_id, english)
        weapon_records.append(
            {
                "id": row_id,
                "raw_id": row_id,
                "parameter_name": parameter_name,
                "name": name,
                "english_name": {
                    "value": name,
                    "message_id": message_id,
                    "status": name_status,
                    "evidence": "local Weapon_name_.fmg sparse-ID relation"
                    if name
                    else "raw EquipParamWeapon ID retained",
                },
                "category": {
                    "weapon_category": category,
                    "weapon_motion_category": motion,
                    "sp_attack_category": sp,
                    "motion_one_hand_id": one,
                    "motion_both_hand_id": both,
                },
                "behavior_chain": {
                    "variation_id": variation,
                    "local_rows": behavior_by_variation.get(variation, ()),
                    "status": "joined_variation_only"
                    if behavior_by_variation.get(variation)
                    else "unresolved_no_behavior_row",
                },
                "actions": actions,
                "animation_bank": {
                    "bank": f"a{motion:02d}.tae",
                    "source": _relative_member(bank[0], "chr/c0000.anibnd.dcx")
                    if bank
                    else "chr/c0000.anibnd.dcx",
                    "status": "selected_local_bank"
                    if bank
                    else "unresolved_missing_local_bank",
                },
            }
        )
    timing_by_category: dict[int, dict[str, Any]] = {}
    a00 = banks.get(0)
    if a00:
        by_category: dict[int, list[_Animation]] = defaultdict(list)
        for animation in a00[1]:
            if 6000 <= animation.animation_id < 8000:
                by_category[animation.animation_id // 100 - 60].append(animation)
        for category, values in by_category.items():
            values.sort(key=lambda item: item.animation_id)
            base = 6000 + category * 100
            chosen = next(
                (item for item in values if item.animation_id == base), values[0]
            )
            timing_by_category[category] = {
                "status": "category_exact"
                if len(values) == 1
                else "category_variant_ambiguous",
                "candidate_count": len(values),
                "candidate_animation_ids": [item.animation_id for item in values],
                "representative_animation_id": chosen.animation_id,
                "representative_selection": "category_exact_but_variation_unresolved"
                if len(values) == 1
                else "category_representative_only",
                "event_windows": [
                    {
                        "event_type": e.event_type,
                        "start_seconds": e.start_seconds,
                        "end_seconds": e.end_seconds,
                        "frames_30fps": {"start": e.start_frame, "end": e.end_frame},
                    }
                    for e in chosen.events
                ],
                "evidence": "local c0000 a00.tae animation category family",
                "source": "chr/c0000.anibnd.dcx#a00.tae",
            }
    item_records: list[Mapping[str, Any]] = []
    for row in goods_rows:
        flags = cast(Mapping[str, bool], row["flags"])
        category = int(row["goods_use_anim"])
        if not (flags.get("isEquip") or flags.get("isConsume")) or category in (0, 254):
            continue
        names, name_evidence = _goods_name(
            str(row["parameter_name"]), english_item, japanese
        )
        mapping = timing_by_category.get(
            category,
            {
                "status": "unresolved_no_local_tae_category",
                "candidate_count": 0,
                "candidate_animation_ids": [],
                "representative_animation_id": None,
                "event_windows": [],
                "evidence": "no local c0000 a00.tae animation family",
            },
        )
        item_records.append(
            {
                **row,
                "raw_id": row["parameter_row_id"],
                "name": names[0] if names else None,
                "english_name": names[0] if names else None,
                "english_name_candidates": names,
                "name_mapping": name_evidence,
                "equippable": bool(flags.get("isEquip")),
                "consumable": bool(flags.get("isConsume")),
                "animation_mapping": {
                    **mapping,
                    "goods_use_anim": category,
                    "sfx_variation_id": row["sfx_variation_id"],
                    "variation_status": "unresolved",
                },
            }
        )
    sources = {
        "game_param": "param/GameParam/GameParam.parambnd.dcx",
        "animation_banks": "chr/c0000.anibnd.dcx",
    }
    resolved_actions = sum(
        1
        for item in weapon_records
        for action in cast(Sequence[Mapping[str, object]], item["actions"])
        if action.get("status") == "resolved"
    )
    unresolved_actions = sum(
        1
        for item in weapon_records
        for action in cast(Sequence[Mapping[str, object]], item["actions"])
        if action.get("status") == "unresolved"
    )
    return ScanResult(
        "dsr-frame-scan.v1",
        FRAME_RATE,
        {
            "weapon_roots": len(weapon_records),
            "usable_goods": len(item_records),
            "timing_categories": len(timing_by_category),
            "resolved_weapon_actions": resolved_actions,
            "unresolved_weapon_actions": unresolved_actions,
        },
        tuple(weapon_records),
        tuple(item_records),
        sources,
    )


def _match_values(record: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        str(record.get("id", "")),
        str(record.get("raw_id", "")),
        str(record.get("name", "") or ""),
        str(record.get("parameter_name", "")),
    )


def _match(record: Mapping[str, Any], query: str, *, exact: bool = False) -> bool:
    needle = _norm(query)
    if not needle:
        return False
    normalized_values = tuple(_norm(value) for value in _match_values(record))
    if exact:
        return any(needle == value for value in normalized_values)
    return any(needle in value for value in normalized_values)


def select_frame_records(
    scan: ScanResult,
    *,
    kind: str = "all",
    query: str | None = None,
    spoilers: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    if kind not in {"all", "weapon", "item"}:
        raise FrameQueryError("kind must be all, weapon, or item")
    if limit is not None and (
        not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
    ):
        raise FrameQueryError("limit must be a non-negative integer")
    if query is not None and not query.strip():
        raise FrameQueryError("query must be non-empty when provided")
    records: list[Mapping[str, Any]] = []
    if kind in {"all", "weapon"}:
        records.extend(scan.weapons)
    if kind in {"all", "item"}:
        records.extend(scan.items)
    if query is not None:
        exact_matches = [
            record for record in records if _match(record, query, exact=True)
        ]
        records = exact_matches or [
            record for record in records if _match(record, query)
        ]
        if not records:
            raise FrameQueryError(f"no {kind} frame records match query")
    if limit is not None:
        records = records[:limit]
    reveal = spoilers or query is not None
    view: dict[str, Any] = {
        "schema_version": scan.schema_version,
        "frame_rate": scan.frame_rate,
        "summary": dict(scan.summary),
        "counts": {"weapons": len(scan.weapons), "items": len(scan.items)},
        "sources": dict(scan.sources),
        "records": [dict(record) for record in records] if reveal else [],
        "spoilers": reveal,
        "kind": kind,
        "query": query,
    }
    return view


def to_jsonable(view: ScanResult | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(view, ScanResult):
        return {
            "schema_version": view.schema_version,
            "frame_rate": view.frame_rate,
            "summary": dict(view.summary),
            "counts": {"weapons": len(view.weapons), "items": len(view.items)},
            "records": [],
            "sources": dict(view.sources),
        }

    def clean(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): clean(item)
                for key, item in value.items()
                if key not in {"raw_parameter_bytes", "raw_payload", "payload_bytes"}
                and "absolute" not in str(key).casefold()
            }
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        return value

    return cast(dict[str, Any], clean(view))


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only DSR local frame scanner")
    parser.add_argument("query", nargs="?")
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--kind", choices=("all", "weapon", "item"), default="all")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--spoilers", action="store_true")
    args = parser.parse_args()
    scan = scan_install(args.install)
    output = to_jsonable(
        select_frame_records(
            scan,
            kind=args.kind,
            query=args.query,
            spoilers=args.spoilers,
            limit=args.limit,
        )
    )
    import json

    print(
        json.dumps(output, ensure_ascii=False, sort_keys=True)
        if args.json
        else output["summary"]
    )


__all__ = [
    "FrameScannerError",
    "FrameInstallError",
    "FrameFormatError",
    "FrameQueryError",
    "ScanResult",
    "scan_install",
    "select_frame_records",
    "to_jsonable",
]

if __name__ == "__main__":
    main()
