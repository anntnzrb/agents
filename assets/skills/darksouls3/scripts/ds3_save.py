# -*- coding: utf-8 -*-
"""Dark Souls 3 save file parser -- read-only .sl2 decryptor + stat reader.

BND4 structure: tremwil/DS3SaveUnpacker (MIT).
Stats layout: JKAnderson/SoulsTemplates USER_DATA000_DS3.bt.
AES key: Atvaark/DarkSoulsIII.FileFormats.
Save event layout/values: alfizari/Dark-Souls-3-Save-Editor-PS4-PC (MIT).
Tracked bonfire bits: The Grand Archives DS3 CT SprjEventFlagMan records (reference-only; no license observed).
"""

from __future__ import annotations

import json as _json
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TypedDict, TypeVar, cast

from Crypto.Cipher import AES

AES_KEY: bytes = bytes.fromhex("FD464D695E69A39A10E319A7ACE8B7FA")

_resources_dir = Path(__file__).resolve().parent.parent / "resources"
_JSONFallback = TypeVar("_JSONFallback")


class BonfireFlag(TypedDict):
    area: str
    name: str
    offset: int
    bit: int


def _load_resource_json(
    name: str,
    fallback: _JSONFallback,
    *,
    catch_decode_error: bool = True,
) -> object | _JSONFallback:
    try:
        return _json.loads((_resources_dir / name).read_text(encoding="utf-8"))
    except _json.JSONDecodeError:
        if catch_decode_error:
            return fallback
        raise
    except (FileNotFoundError, OSError):
        return fallback


def _bonfire_flag(item: object) -> BonfireFlag | None:
    if not isinstance(item, dict):
        return None
    area = item.get("area")
    name = item.get("name")
    offset = item.get("offset")
    bit = item.get("bit")
    if (
        isinstance(area, str)
        and isinstance(name, str)
        and isinstance(offset, int)
        and isinstance(bit, int)
    ):
        return BonfireFlag(area=area, name=name, offset=offset, bit=bit)
    return None


def _bonfire_flags(items: list[object]) -> list[BonfireFlag]:
    flags: list[BonfireFlag] = []
    for item in items:
        if flag := _bonfire_flag(item):
            flags.append(flag)
    return flags


_event_flags = cast(
    dict[str, dict[str, int]],
    _load_resource_json("event_flags.json", {"bosses": {}}, catch_decode_error=False),
)
_bonfire_bit_flags_raw = cast(
    list[object],
    _load_resource_json("bonfire_flags.json", [], catch_decode_error=False),
)
BOSS_FLAGS: dict[str, int] = _event_flags["bosses"]
BONFIRE_SAVE_OFFSET_DELTA: int = 0x6F
BONFIRE_BIT_FLAGS: list[BonfireFlag] = _bonfire_flags(_bonfire_bit_flags_raw)

# Item name caches (lazy-loaded)
_ITEM_NAMES: dict[int, str] = {}
_WEAPON_NAMES: dict[int, str] = {}
_ARMOR_NAMES: dict[int, str] = {}
_RING_NAMES: dict[int, str] = {}
_GOODS_NAMES: dict[int, str] = {}

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class StatBlock(TypedDict):
    name: str
    soulLevel: int
    souls: int
    vigor: int
    attunement: int
    endurance: int
    vitality: int
    strength: int
    dexterity: int
    intelligence: int
    faith: int
    luck: int
    humanity: int
    health: int
    maxHealth: int
    mana: int
    maxMana: int
    stamina: int
    maxStamina: int
    class_: int
    gender: int
    embered: int
    estusAllocation: int
    ashenEstusAllocation: int
    maxWeaponReinforcement: int
    hollow: int
    yoelLevelUpsRemaining: int
    charID: int
    darkmoonPoints: int
    sunlightPoints: int
    moundmakerPoints: int
    fingersPoints: int
    watchdogsPoints: int
    aldrichPoints: int
    wayOfBluePoints: int


CLASS_NAMES: dict[int, str] = {
    0: "Deprived",
    1: "Knight",
    2: "Mercenary",
    3: "Warrior",
    4: "Herald",
    5: "Thief",
    6: "Assassin",
    7: "Sorcerer",
    8: "Pyromancer",
    9: "Cleric",
}

SAVE_PATH_DEFAULT: Path = Path.home() / "AppData" / "Roaming" / "DarkSoulsIII"

ITEM_THING_COUNT: int = 6144
STATS_SIZE: int = 0x1F0
ITEMS_INVENTORY_COUNT_OFFSET: int = 0x128
ITEMS_INVENTORY_OFFSET: int = 0x12C
INVENTORY_CAPACITY: int = 0x780
# Event flag offsets/values are community-derived from alfizari/Dark-Souls-3-Save-Editor-PS4-PC
# and cross-checked against The Grand Archives / SoulsModding flag IDs.
BOSS_EVENT_VALUES: dict[str, int] = {
    "Iudex Gundyr": 0xE0,
    "Vordt of the Boreal Valley": 0xC0,
    "Curse-Rotted Greatwood": 0xC0,
    "Crystal Sage": 0x28,
    "Abyss Watchers": 0xC0,
    "High Lord Wolnir": 0xC0,
    "Oceiros, the Consumed King": 0x42,
    "Champion Gundyr": 0x03,
    "Dancer of the Boreal Valley": 0x20,
    "Deacons of the Deep": 0xC0,
    "Old Demon King": 0x02,
    "Pontiff Sulyvahn": 0x20,
    "Aldrich, Devourer of Gods": 0x80,
    "Dragonslayer Armour": 0x80,
    "Yhorm the Giant": 0xC0,
    "Nameless King": 0x21,
    "Twin Princes": 0x03,
    "Soul of Cinder": 0xC0,
    "Champion's Gravetender": 0x0C,
    "Sister Friede": 0xC0,
    "Halflight, Spear of the Church": 0xC0,
    "Darkeater Midir": 0x30,
    "Slave Knight Gael": 0xC0,
    "Demon Prince": 0x80,
}


class BossStatus(TypedDict):
    name: str
    defeated: bool
    offset: int


class BonfireStatus(TypedDict):
    area: str
    name: str
    unlocked: bool
    offset: int
    bit: int


class ProgressSummary(TypedDict):
    stats: StatBlock
    bosses_defeated: list[str]
    bosses_total: int
    bonfires_unlocked: list[str]
    ng_plus: int


class ItemEntry(TypedDict):
    slot: int
    gaitem_handle: int
    item_id: int
    item_type: str
    name: str
    quantity: int
    reinforcement: int
    base_item_id: int


class InventoryResult(TypedDict):
    weapons: list[ItemEntry]
    armor: list[ItemEntry]
    rings: list[ItemEntry]
    goods: list[ItemEntry]
    total_items: int


class MissedKeyItem(TypedDict):
    name: str
    owned: bool
    check: bool
    supported: bool


class MissedSummary(TypedDict):
    current_area: str
    missing_bosses: list[str]
    key_items: list[MissedKeyItem]
    estus_shards_found: int | None
    estus_shards_total: int
    bone_shards_found: int | None
    bone_shards_total: int
    stats: StatBlock
    progress: ProgressSummary


# ---------------------------------------------------------------------------
# BND4 parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlotEntry:
    index: int
    name: str
    offset: int
    size: int


def _parse_bnd4(data: bytes) -> list[SlotEntry]:
    if data[:4] != b"BND4":
        raise ValueError("Not a valid DS3 save (missing BND4 magic)")
    file_cnt = struct.unpack_from("<I", data, 0x0C)[0]
    entries: list[SlotEntry] = []
    for i in range(file_cnt):
        base = 0x40 + i * 0x20
        e_size = struct.unpack_from("<Q", data, base + 0x08)[0]
        e_off = struct.unpack_from("<I", data, base + 0x10)[0]
        e_name_off = struct.unpack_from("<I", data, base + 0x14)[0]
        name_end = data.index(0, e_name_off)
        name_bytes = data[e_name_off:name_end]
        e_name = name_bytes.decode("utf-16-le", errors="replace").rstrip("\x00")
        entries.append(SlotEntry(i, e_name, e_off, e_size))
    return entries


def _decrypt_entry(data: bytes, entry: SlotEntry) -> bytes:
    blob = data[entry.offset : entry.offset + entry.size]
    iv = blob[16:32]
    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv=iv)
    decrypted = cipher.decrypt(blob[32:])
    pad = decrypted[-1]
    if 1 <= pad <= 16:
        decrypted = decrypted[:-pad]
    return decrypted


def read_save(path: str | Path) -> tuple[bytes, list[bytes]]:
    """Return (raw_bytes, decrypted slots), cached by path + mtime for live-save safety."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Not found: {p}")
    return _read_save_cached(str(p), p.stat().st_mtime_ns)


@lru_cache(maxsize=8)
def _read_save_cached(path: str, mtime_ns: int) -> tuple[bytes, list[bytes]]:
    del mtime_ns  # cache key only; file read uses path
    data = Path(path).read_bytes()
    entries = _parse_bnd4(data)
    if len(entries) < 11:
        raise ValueError(f"Expected >=11 slots, got {len(entries)}")
    return data, [_decrypt_entry(data, e) for e in entries]


def _valid_stats_offset(slot: bytes, offset: int) -> bool:
    if offset < 0 or offset + STATS_SIZE > len(slot):
        return False
    raw_name = slot[offset + 0x78 : offset + 0x78 + 32]
    if any(raw_name[i] for i in range(1, len(raw_name), 2)):
        return False
    name_bytes = bytes(raw_name[i] for i in range(0, len(raw_name), 2)).rstrip(b"\x00")
    if len(name_bytes) < 2 or not all(32 <= c < 127 for c in name_bytes):
        return False
    try:
        stats = struct.unpack_from("<8I", slot, offset + 0x34)
        soul_level = struct.unpack_from("<I", slot, offset + 0x60)[0]
    except struct.error:
        return False
    return (
        all(1 <= value <= 99 for value in stats)
        and 1 <= soul_level <= 999
        and slot[offset + 0x9E] <= 9
    )


def _find_stats_offset(slot: bytes) -> int:
    """Locate the Stats struct by walking the source-backed USER_DATA template."""
    if len(slot) < 0x14:
        return -1
    header_unk10 = struct.unpack_from("<I", slot, 0x10)[0]
    if header_unk10 not in (0x5C, 0x6C):
        return -1
    offset = header_unk10 + 4
    for _ in range(ITEM_THING_COUNT):
        if offset + 8 > len(slot):
            return -1
        unk00, unk04 = struct.unpack_from("<II", slot, offset)
        offset += 8 if unk00 == 0 and unk04 == 0xFFFFFFFF else 60
    return offset if _valid_stats_offset(slot, offset) else -1


def read_stats(path: str | Path, slot: int = 0) -> StatBlock:
    """Read all character stats from the save file."""
    _, slots = read_save(path)
    slot_data = slots[slot]
    if len(slot_data) < 0x120:
        raise ValueError(f"Slot {slot} appears empty")
    so = _find_stats_offset(slot_data)
    if so < 0:
        raise RuntimeError("Could not locate Stats struct in save data")
    d = slot_data

    def _u32(off):
        return struct.unpack_from("<I", d, so + off)[0]

    def _u16(off):
        return struct.unpack_from("<H", d, so + off)[0]

    def _u8(off):
        return d[so + off]

    name_raw = d[so + 0x78 : so + 0x78 + 32]
    name = name_raw.decode("utf-16-le", errors="replace").rstrip("\x00")
    return StatBlock(
        name=name,
        soulLevel=_u32(0x60),
        souls=_u32(0x64),
        vigor=_u32(0x34),
        attunement=_u32(0x38),
        endurance=_u32(0x3C),
        vitality=_u32(0x5C),
        strength=_u32(0x40),
        dexterity=_u32(0x44),
        intelligence=_u32(0x48),
        faith=_u32(0x4C),
        luck=_u32(0x50),
        humanity=_u32(0x58),
        health=_u32(0x08),
        maxHealth=_u32(0x10),
        mana=_u32(0x14),
        maxMana=_u32(0x1C),
        stamina=_u32(0x24),
        maxStamina=_u32(0x2C),
        class_=_u8(0x9E),
        gender=_u8(0x9F),
        embered=_u8(0xF0),
        estusAllocation=_u8(0xF2),
        ashenEstusAllocation=_u8(0xF3),
        maxWeaponReinforcement=_u8(0xA3),
        hollow=_u16(0xEE),
        yoelLevelUpsRemaining=_u8(0xFF),
        charID=_u32(0x100),
        darkmoonPoints=_u8(0xBD),
        sunlightPoints=_u8(0xBE),
        moundmakerPoints=_u8(0xBF),
        fingersPoints=_u8(0xC1),
        watchdogsPoints=_u8(0xC2),
        aldrichPoints=_u8(0xC3),
        wayOfBluePoints=_u8(0x101),
    )


def read_name(path: str | Path, slot: int = 0) -> str:
    return read_stats(path, slot)["name"]


# ---------------------------------------------------------------------------
# Event flag / boss / bonfire readers
# ---------------------------------------------------------------------------


def _boss_flags_supported() -> bool:
    return bool(BOSS_FLAGS) and all(name in BOSS_EVENT_VALUES for name in BOSS_FLAGS)


def _bonfire_flags_supported() -> bool:
    return bool(BONFIRE_BIT_FLAGS)


def _event_flags_supported() -> bool:
    return _boss_flags_supported() or _bonfire_flags_supported()


def _event_flag_start(slot: bytes) -> int:
    """Return the alfi-derived event flag table start for a decrypted character slot."""
    offset = 0x70
    for _ in range(ITEM_THING_COUNT):
        if offset + 8 > len(slot):
            return -1
        gaitem_handle, _item_id = struct.unpack_from("<II", slot, offset)
        type_bits = gaitem_handle & 0xF0000000
        offset += 60 if gaitem_handle and type_bits in (0x80000000, 0x90000000) else 8
    try:
        magic_start = offset + 0x13F
        inventory_start = magic_start + 0x1DD
        inventory_end = inventory_start + 0x8808
        above_storage_counter = inventory_end + 0x11C
        above_storage_size = struct.unpack_from("<I", slot, above_storage_counter)[0]
        table_1_end = above_storage_counter + 4 + above_storage_size * 8
        storage_box_start = table_1_end + 0x18C + 4
        storage_box_end = storage_box_start + 0x8800
        gesture_start = storage_box_end + 0x0C
        gesture_end = gesture_start + 0xA4
        table_2_size = struct.unpack_from("<I", slot, gesture_end)[0]
        table_2_end = gesture_end + 4 + table_2_size * 4
        new_game_plus = table_2_end + 0x92
        event_start = new_game_plus + 0xBCC
    except struct.error:
        return -1
    return event_start if 0 <= event_start < len(slot) else -1


def read_ng_plus(path: str | Path, slot: int = 0) -> int:
    """Return the Journey/NG+ counter stored before the event flag table."""
    _, slots = read_save(path)
    slot_data = slots[slot]
    event_start = _event_flag_start(slot_data)
    ng_offset = event_start - 0xBCC
    if event_start < 0 or not 0 <= ng_offset < len(slot_data):
        return 0
    return slot_data[ng_offset]


def read_bosses(path: str | Path, slot: int = 0) -> list[BossStatus]:
    """Return boss defeat status list from known event flag byte values."""
    _, slots = read_save(path)
    slot_data = slots[slot]
    event_start = _event_flag_start(slot_data)
    if event_start < 0:
        return [
            BossStatus(name=name, defeated=False, offset=offset)
            for name, offset in BOSS_FLAGS.items()
        ]
    base = event_start - 0x12
    bosses: list[BossStatus] = []
    for name, offset in BOSS_FLAGS.items():
        expected = BOSS_EVENT_VALUES.get(name)
        flag_offset = base + offset
        defeated = (
            expected is not None
            and 0 <= flag_offset < len(slot_data)
            and slot_data[flag_offset] == expected
        )
        bosses.append(BossStatus(name=name, defeated=defeated, offset=offset))
    return bosses


def read_bonfire_statuses(path: str | Path, slot: int = 0) -> list[BonfireStatus]:
    """Return exact source-backed bonfire flags from TGA bits mapped into DS30000 bytes."""
    _, slots = read_save(path)
    slot_data = slots[slot]
    event_start = _event_flag_start(slot_data)
    if event_start < 0:
        return [
            BonfireStatus(
                area=item["area"],
                name=item["name"],
                unlocked=False,
                offset=item["offset"],
                bit=item["bit"],
            )
            for item in BONFIRE_BIT_FLAGS
        ]
    base = event_start - 0x12
    bonfires: list[BonfireStatus] = []
    for item in BONFIRE_BIT_FLAGS:
        offset = item["offset"]
        bit = item["bit"]
        flag_offset = base + offset + BONFIRE_SAVE_OFFSET_DELTA
        unlocked = (
            0 <= bit < 8
            and 0 <= flag_offset < len(slot_data)
            and bool(slot_data[flag_offset] & (1 << bit))
        )
        bonfires.append(
            BonfireStatus(
                area=item["area"],
                name=item["name"],
                unlocked=unlocked,
                offset=offset,
                bit=bit,
            )
        )
    return bonfires


def read_bonfires(path: str | Path, slot: int = 0) -> dict[str, bool]:
    """Return exact source-backed bonfire unlock status keyed by area/name."""
    return {
        f"{entry['area']} - {entry['name']}": entry["unlocked"]
        for entry in read_bonfire_statuses(path, slot)
    }


def read_progress(path: str | Path, slot: int = 0) -> ProgressSummary:
    """Return a complete progress summary."""
    s = read_stats(path, slot)
    bosses = read_bosses(path, slot) if _boss_flags_supported() else []
    bonfires = read_bonfires(path, slot) if _bonfire_flags_supported() else {}
    ng = read_ng_plus(path, slot)
    return ProgressSummary(
        stats=s,
        bosses_defeated=[b["name"] for b in bosses if b["defeated"]],
        bosses_total=len(bosses),
        bonfires_unlocked=[n for n, u in bonfires.items() if u],
        ng_plus=ng,
    )


def _read_resource_json(name: str) -> dict[str, object]:
    data = _load_resource_json(name, {})
    if isinstance(data, dict):
        return data
    return {}


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _area_string_lists(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    return {
        key: _string_list(item) for key, item in value.items() if isinstance(key, str)
    }


def _game_areas() -> dict[str, object]:
    areas = _read_resource_json("game_data.json").get("areas")
    if isinstance(areas, dict):
        return areas
    return {}


def read_completion_checklist() -> dict[str, list[str]]:
    """Return the global completion checklist resource, or an empty fallback."""
    data = _read_resource_json("achievement_checklist.json")
    if data:
        return {
            key: _string_list(value)
            for key, value in data.items()
            if isinstance(key, str)
        }

    checklist: dict[str, list[str]] = {}
    areas = _game_areas()
    if not areas:
        return checklist
    for area in areas.values():
        if not isinstance(area, dict):
            continue
        for key in ("bosses", "key_items"):
            checklist.setdefault(key, []).extend(_string_list(area.get(key)))
    return checklist


def read_area_checklists() -> dict[str, dict[str, list[str]]]:
    """Return area checklists keyed by area name, or an empty fallback."""
    data = _read_resource_json("area_checklists.json")
    if data:
        return {
            key: _area_string_lists(value)
            for key, value in data.items()
            if isinstance(key, str)
        }

    areas = _game_areas()
    if not areas:
        return {}
    result: dict[str, dict[str, list[str]]] = {}
    for area_name, area in areas.items():
        if isinstance(area_name, str) and isinstance(area, dict):
            result[area_name] = {
                "bosses": _string_list(area.get("bosses")),
                "key_items": _string_list(area.get("key_items")),
                "estus_shards": [
                    str(item)
                    for item in area.get("estus_shards", [])
                    if isinstance(item, (int, str))
                ],
                "bone_shards": [
                    str(item)
                    for item in area.get("bone_shards", [])
                    if isinstance(item, (int, str))
                ],
            }
    return result


def read_current_area(path: str | Path, slot: int = 0) -> str:
    """Infer latest reached checklist area from exact save-backed bonfire flags."""
    if not _bonfire_flags_supported():
        return ""
    statuses = read_bonfire_statuses(path, slot)
    unlocked_areas = {entry["area"] for entry in statuses if entry["unlocked"]}
    if not unlocked_areas:
        return ""
    areas = _game_areas()
    for area_name, area_data in reversed(list(areas.items())):
        if isinstance(area_data, dict) and area_name in unlocked_areas:
            return area_name
    for entry in reversed(statuses):
        if entry["unlocked"]:
            return entry["area"]
    return ""


def read_missed(path: str | Path, slot: int = 0) -> dict[str, object]:
    """Return live progress plus static checklist hints with ownership labels."""
    current_area = read_current_area(path, slot)
    area_checklists = read_area_checklists()
    area_data = area_checklists.get(current_area, {})
    checklist_available = current_area in area_checklists
    stats = read_stats(path, slot)
    progress = read_progress(path, slot)
    defeated = set(progress["bosses_defeated"])
    missing_bosses = [
        name for name in area_data.get("bosses", []) if name not in defeated
    ]
    total_estus = len(area_data.get("estus_shards", []))
    total_bones = len(area_data.get("bone_shards", []))
    owned_keys = {_completion_key(name) for name in owned_item_names(path, slot)}
    known_keys = {_completion_key(name) for name in _ITEM_NAMES.values()}
    key_items = []
    for name in area_data.get("key_items", []):
        key = _completion_key(name)
        supported = key in known_keys
        owned = supported and key in owned_keys
        key_items.append(
            {
                "name": name,
                "owned": owned,
                "check": supported and not owned,
                "supported": supported,
            }
        )
    return {
        "current_area": current_area,
        "missing_bosses": missing_bosses,
        "key_items": key_items,
        "checklist_available": checklist_available,
        "estus_shards_found": None,
        "estus_shards_total": total_estus if isinstance(total_estus, int) else 0,
        "bone_shards_found": None,
        "bone_shards_total": total_bones if isinstance(total_bones, int) else 0,
        "stats": stats,
        "progress": progress,
    }


def _load_item_names() -> None:
    """Lazy-load catalog item_id -> name mappings from resources JSON.

    Resource files store DS3 catalog IDs as little-endian uint32 byte strings
    (for example ``"80 1A 06 00"`` == item_id ``0x00061A80``).  Save
    inventory rows also include a separate ``gaitem_handle`` instance/type
    value; that handle is not stable enough for catalog name resolution.
    """
    if _ITEM_NAMES:
        return

    def _parse_json(fname: str) -> dict[int, str]:
        data = _load_resource_json(fname, {})
        if not isinstance(data, dict):
            return {}
        result: dict[int, str] = {}
        for name, hex_str in data.items():
            if not isinstance(name, str) or not isinstance(hex_str, str):
                continue
            try:
                raw = bytes(int(part, 16) for part in hex_str.split())
            except ValueError:
                continue
            if len(raw) != 4:
                continue
            result[struct.unpack("<I", raw)[0]] = name
        return result

    for fname, cache in [
        ("weapons.json", _WEAPON_NAMES),
        ("armor.json", _ARMOR_NAMES),
        ("rings.json", _RING_NAMES),
        ("goods_magic.json", _GOODS_NAMES),
    ]:
        cache.update(_parse_json(fname))

    _ITEM_NAMES.update(_WEAPON_NAMES)
    _ITEM_NAMES.update(_ARMOR_NAMES)
    _ITEM_NAMES.update(_RING_NAMES)
    _ITEM_NAMES.update(_GOODS_NAMES)


def _item_name_for_id(item_id: int, fallback: str) -> str:
    _load_item_names()
    return _ITEM_NAMES.get(item_id, fallback)


def _weapon_name_and_reinforcement(item_id: int) -> tuple[str | None, int, int]:
    """Resolve infused/upgraded weapon item IDs.

    DS3 weapon reinforcement is encoded as a small offset from the infused
    base weapon ID. Resource JSON stores the +0 IDs, while saves store the
    reinforced variant, e.g. Raw Sellsword Twinblades +2 as base + 2.
    """
    for reinforcement in range(0, 11):
        base_item_id = item_id - reinforcement
        name = _WEAPON_NAMES.get(base_item_id)
        if name is not None:
            return name, reinforcement, base_item_id
    return None, 0, item_id


def _completion_key(name: str) -> str:
    normalized = " ".join(name.replace(" +", "+").replace("+ ", "+").split())
    normalized = normalized.replace("’", "'")
    normalized = normalized.replace("Dorhy's", "Dorhys").replace("Dorhys'", "Dorhys")
    for suffix in (" Sorcery", " Pyromancy", " Miracle"):
        if normalized.endswith(suffix):
            normalized = normalized.removesuffix(suffix)
            break
    return normalized.casefold()


def _known_item_names(items: list[ItemEntry]) -> set[str]:
    return {item["name"] for item in items if not item["name"].startswith("Unknown ")}


def _known_weapon_base_names(items: list[ItemEntry]) -> set[str]:
    names: set[str] = set()
    for item in items:
        base_name = _WEAPON_NAMES.get(item["base_item_id"])
        if base_name is not None:
            names.add(base_name)
    return names


def _inventory_max_reinforcement(inventory: InventoryResult) -> int:
    return max((item["reinforcement"] for item in inventory["weapons"]), default=0)


def _inventory_owned_by_category(inventory: InventoryResult) -> dict[str, set[str]]:
    goods = _known_item_names(inventory["goods"])
    checklist = read_completion_checklist()
    spell_names = set().union(
        *(
            set(_string_list(checklist.get(key)))
            for key in ("sorceries", "pyromancies", "miracles")
        )
    )
    spell_keys = {_completion_key(name) for name in spell_names}
    spells = {name for name in goods if _completion_key(name) in spell_keys}
    return {
        "weapons": _known_weapon_base_names(inventory["weapons"]),
        "armor": _known_item_names(inventory["armor"]),
        "rings": _known_item_names(inventory["rings"]),
        "spells": spells,
        "goods": goods - spells,
    }


def read_inventory(path: str | Path, slot: int = 0) -> InventoryResult:
    """Parse the full inventory from a save slot."""
    _load_item_names()
    _, slots = read_save(path)
    slot_data = slots[slot]

    ITEM_TYPE_WEAPON = 0x80000000
    ITEM_TYPE_ARMOR = 0x90000000
    ITEM_TYPE_GOOD = 0xB0000000
    ITEM_TYPE_RING = 0xA0000000

    weapons: list[ItemEntry] = []
    armors: list[ItemEntry] = []
    rings: list[ItemEntry] = []
    goods: list[ItemEntry] = []

    category_maps = (
        (ITEM_TYPE_WEAPON, "weapon", _WEAPON_NAMES, weapons),
        (ITEM_TYPE_ARMOR, "armor", _ARMOR_NAMES, armors),
        (ITEM_TYPE_RING, "ring", _RING_NAMES, rings),
        (ITEM_TYPE_GOOD, "goods", _GOODS_NAMES, goods),
    )
    stats_offset = _find_stats_offset(slot_data)
    if stats_offset < 0:
        raise RuntimeError("Could not locate Stats struct in save data")
    items_offset = stats_offset + STATS_SIZE
    count_offset = items_offset + ITEMS_INVENTORY_COUNT_OFFSET
    rows_offset = items_offset + ITEMS_INVENTORY_OFFSET
    if count_offset + 4 > len(slot_data):
        raise RuntimeError("Could not locate Items inventory table in save data")
    item_count = struct.unpack_from("<I", slot_data, count_offset)[0]
    row_count = min(item_count, INVENTORY_CAPACITY)

    for index in range(row_count):
        offset = rows_offset + index * 16
        if offset + 16 > len(slot_data):
            break
        gaitem_handle, item_id, quantity, _index = struct.unpack_from(
            "<IIII", slot_data, offset
        )
        if item_id in (0, 0xFFFFFFFF):
            continue
        type_bits = gaitem_handle & 0xF0000000

        matched = None
        reinforcement = 0
        base_item_id = item_id
        for expected_type, item_type, names, target_list in category_maps:
            if type_bits != expected_type:
                continue
            if item_type == "weapon":
                name, reinforcement, base_item_id = _weapon_name_and_reinforcement(
                    item_id
                )
            else:
                name = names.get(item_id)
            if name is None:
                matched = None
                break
            matched = (item_type, name, target_list)
            break
        if matched is None:
            continue

        if matched[0] in ("goods", "ring") and quantity == 0:
            continue

        display_name = (
            f"{matched[1]} +{reinforcement}"
            if reinforcement and matched[0] == "weapon"
            else matched[1]
        )
        entry: ItemEntry = {
            "slot": index,
            "gaitem_handle": gaitem_handle,
            "item_id": item_id,
            "item_type": matched[0],
            "name": display_name,
            "quantity": quantity
            if matched[0] in ("goods", "ring") and quantity > 0
            else 1,
            "reinforcement": reinforcement,
            "base_item_id": base_item_id,
        }
        matched[2].append(entry)

    return InventoryResult(
        weapons=weapons,
        armor=armors,
        rings=rings,
        goods=goods,
        total_items=len(weapons) + len(armors) + len(rings) + len(goods),
    )


def owned_item_names(path: str | Path, slot: int = 0) -> set[str]:
    """Return all resolved inventory item names owned by the save slot."""
    inventory = read_inventory(path, slot)
    names: set[str] = set()
    for items in (
        inventory["weapons"],
        inventory["armor"],
        inventory["rings"],
        inventory["goods"],
    ):
        for item in items:
            name = item["name"]
            if not name.startswith("Unknown"):
                names.add(name)
    return names


def read_completion_status(path: str | Path, slot: int = 0) -> dict[str, object]:
    """Return save-backed completion progress by checklist category."""
    inventory = read_inventory(path, slot)
    owned_by_category = _inventory_owned_by_category(inventory)
    checklist = read_completion_checklist()
    stats = read_stats(path, slot)

    def _status(category: str, owned_names: set[str]) -> dict[str, object]:
        required = _string_list(checklist.get(category))
        owned_keys = {_completion_key(name) for name in owned_names}
        owned = [name for name in required if _completion_key(name) in owned_keys]
        missing = [name for name in required if _completion_key(name) not in owned_keys]
        return {"owned": owned, "missing": missing, "total": len(required)}

    def _collection_status(
        owned_names: set[str],
        known_names: dict[int, str],
        excluded_keys: set[str] | None = None,
    ) -> dict[str, object]:
        excluded = excluded_keys or set()
        known = sorted(
            {
                name
                for name in known_names.values()
                if _completion_key(name) not in excluded
            },
            key=_completion_key,
        )
        owned_keys = {_completion_key(name) for name in owned_names}
        owned = [name for name in known if _completion_key(name) in owned_keys]
        missing = [name for name in known if _completion_key(name) not in owned_keys]
        return {"owned": owned, "missing": missing, "total": len(known)}

    rings = _status("rings", owned_by_category["rings"])
    sorceries = _status("sorceries", owned_by_category["spells"])
    pyromancies = _status("pyromancies", owned_by_category["spells"])
    miracles = _status("miracles", owned_by_category["spells"])
    spell_keys = {
        _completion_key(name)
        for category in ("sorceries", "pyromancies", "miracles")
        for name in _string_list(checklist.get(category))
    }
    reinforcement_total = len(_string_list(checklist.get("reinforcement")))
    reinforcement_owned = 0
    return {
        "rings": rings,
        "sorceries": sorceries,
        "pyromancies": pyromancies,
        "miracles": miracles,
        "weapons": _collection_status(owned_by_category["weapons"], _WEAPON_NAMES),
        "armor": _collection_status(owned_by_category["armor"], _ARMOR_NAMES),
        "goods": _collection_status(
            owned_by_category["goods"], _GOODS_NAMES, spell_keys
        ),
        "reinforcement": {
            "supported": False,
            "owned": reinforcement_owned,
            "missing": reinforcement_total,
            "total": reinforcement_total,
        },
        "owned_by_category": owned_by_category,
        "inventory": inventory,
        "progress": read_progress(path, slot),
    }


def read_gestures(path: str | Path, slot: int = 0) -> dict[str, object]:
    """Return static gesture checklist data with an explicit unsupported marker.

    Gesture save ownership needs gesture/event-flag offsets that are not present
    in the bundled resources.  Do not infer completion from inventory or return
    fake locked/unlocked rows.
    """
    _ = (path, slot)
    return {
        "supported": False,
        "save_backed": False,
        "reason": "Gesture event offsets are not available in local resources.",
        "gestures": _string_list(read_completion_checklist().get("gestures")),
        "unlocked": [],
    }


__all__ = [
    "read_save",
    "read_stats",
    "read_name",
    "read_bosses",
    "read_bonfires",
    "read_bonfire_statuses",
    "read_progress",
    "read_ng_plus",
    "read_completion_checklist",
    "read_area_checklists",
    "read_current_area",
    "read_missed",
    "read_inventory",
    "owned_item_names",
    "read_completion_status",
    "read_gestures",
    "StatBlock",
    "SlotEntry",
    "BossStatus",
    "BonfireStatus",
    "ProgressSummary",
    "ItemEntry",
    "InventoryResult",
    "MissedSummary",
    "MissedKeyItem",
    "CLASS_NAMES",
    "AES_KEY",
    "SAVE_PATH_DEFAULT",
    "BOSS_FLAGS",
]
