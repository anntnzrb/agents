# -*- coding: utf-8 -*-
"""Dark Souls 3 save file parser -- read-only .sl2 decryptor + stat reader.

BND4 structure: tremwil/DS3SaveUnpacker (MIT).
Stats layout: JKAnderson/SoulsTemplates USER_DATA000_DS3.bt.
AES key: Atvaark/DarkSoulsIII.FileFormats.
"""
from __future__ import annotations

import json as _json
import struct
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from Crypto.Cipher import AES

AES_KEY: bytes = bytes.fromhex("FD464D695E69A39A10E319A7ACE8B7FA")

_resources_dir = Path(__file__).resolve().parent.parent / "resources"
try:
    _event_flags = _json.loads((_resources_dir / "event_flags.json").read_text())
except (FileNotFoundError, OSError):
    _event_flags = {"bosses": {}, "bonfires": {}}
BOSS_FLAGS: dict[str, int] = _event_flags["bosses"]
BONFIRE_FLAGS: dict[str, int] = _event_flags["bonfires"]

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
    0: "Deprived", 1: "Knight", 2: "Mercenary", 3: "Warrior",
    4: "Herald", 5: "Thief", 6: "Assassin", 7: "Sorcerer",
    8: "Pyromancer", 9: "Cleric",
}

SAVE_PATH_DEFAULT: Path = Path.home() / "AppData" / "Roaming" / "DarkSoulsIII"


class BossStatus(TypedDict):
    name: str
    defeated: bool
    offset: int


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

def _find_stats_offset(slot: bytes) -> int:
    """Locate the Stats struct via name-anchored scan."""
    limit = min(len(slot) - 0xA0, 0x60000)
    for offset in range(0x78, limit, 2):
        raw = slot[offset : offset + 32]
        if any(raw[i] for i in range(1, 32, 2)):
            continue
        chars = bytes(raw[i] for i in range(0, 32, 2))
        trimmed = chars.rstrip(b"\x00")
        if len(trimmed) < 2:
            continue
        if not all(32 <= c < 127 for c in trimmed):
            continue
        so = offset - 0x78
        if so < 0:
            continue
        try:
            vals = struct.unpack_from("<8I", slot, so + 0x34)
        except struct.error:
            continue
        if not all(1 <= v <= 99 for v in vals):
            continue
        sl = struct.unpack_from("<I", slot, so + 0x60)[0]
        cls = slot[so + 0x9E]
        if 1 <= sl <= 999 and cls <= 9:
            return so
    for offset in range(0, limit, 4):
        try:
            vals = struct.unpack_from("<8I", slot, offset)
        except struct.error:
            continue
        if not all(1 <= v <= 99 for v in vals):
            continue
        so = offset - 0x34
        if so < 0:
            continue
        sl = struct.unpack_from("<I", slot, so + 0x60)[0]
        cls = slot[so + 0x9E]
        if 1 <= sl <= 999 and cls <= 9:
            return so
    return -1


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
    def _u32(off): return struct.unpack_from("<I", d, so + off)[0]
    def _u8(off): return d[so + off]
    name_raw = d[so + 0x78 : so + 0x78 + 32]
    name = name_raw.decode("utf-16-le", errors="replace").rstrip("\x00")
    return StatBlock(
        name=name,
        soulLevel=_u32(0x60), souls=_u32(0x64),
        vigor=_u32(0x34), attunement=_u32(0x38), endurance=_u32(0x3C),
        vitality=_u32(0x5C), strength=_u32(0x40), dexterity=_u32(0x44),
        intelligence=_u32(0x48), faith=_u32(0x4C), luck=_u32(0x50),
        humanity=_u32(0x58),
        health=_u32(0x08), maxHealth=_u32(0x10),
        mana=_u32(0x14), maxMana=_u32(0x1C),
        stamina=_u32(0x24), maxStamina=_u32(0x2C),
        class_=_u8(0x9E), gender=_u8(0x9F),
        embered=_u8(0xF0),
        estusAllocation=_u8(0xF2), ashenEstusAllocation=_u8(0xF3),
        maxWeaponReinforcement=_u8(0xA2),
        hollow=_u8(0xFC), yoelLevelUpsRemaining=_u8(0xFF),
        charID=_u32(0x100),
        darkmoonPoints=_u8(0xBD), sunlightPoints=_u8(0xBE),
        moundmakerPoints=_u8(0xBF), fingersPoints=_u8(0xC1),
        watchdogsPoints=_u8(0xC2), aldrichPoints=_u8(0xC3),
        wayOfBluePoints=_u8(0x101),
    )


def read_name(path: str | Path, slot: int = 0) -> str:
    return read_stats(path, slot)["name"]


# ---------------------------------------------------------------------------
# Event flag / boss / bonfire readers
# ---------------------------------------------------------------------------

def _find_event_flag_start(slot: bytes) -> int:
    """Return the DS3 1.15.2 event flag base if this slot can contain it.

    The save slot does not expose a lightweight signature here.  Treat the
    known base as a version-specific layout constant, and validate every byte
    this module will read from it instead of pretending to scan.
    """
    event_flag_start = 0x56ED0
    max_flag_offset = -1
    for offset in BOSS_FLAGS.values():
        if offset > max_flag_offset:
            max_flag_offset = offset
    for offset in BONFIRE_FLAGS.values():
        if offset > max_flag_offset:
            max_flag_offset = offset
    if max_flag_offset < 0:
        return -1
    max_flag_byte = max_flag_offset >> 3
    if event_flag_start < 0 or event_flag_start + max_flag_byte >= len(slot):
        return -1
    ng_plus_offset = event_flag_start - 0xBCC
    if not 0 <= ng_plus_offset < len(slot):
        return -1
    return event_flag_start


def read_bosses(path: str | Path, slot: int = 0) -> list[BossStatus]:
    """Return boss defeat status list from the save file."""
    _, slots = read_save(path)
    slot_data = slots[slot]
    efs = _find_event_flag_start(slot_data)
    if efs < 0:
        return [
            BossStatus(name=n, defeated=False, offset=off)
            for n, off in BOSS_FLAGS.items()
        ]
    results: list[BossStatus] = []
    for name, offset in BOSS_FLAGS.items():
        byte_idx = offset >> 3
        bit_idx = offset & 7
        flag_idx = efs + byte_idx
        if not 0 <= flag_idx < len(slot_data):
            defeated = False
        else:
            defeated = bool((slot_data[flag_idx] >> bit_idx) & 1)
        results.append(BossStatus(name=name, defeated=defeated, offset=offset))
    return results


def read_bonfires(path: str | Path, slot: int = 0) -> dict[str, bool]:
    """Return bonfire unlock status dict."""
    _, slots = read_save(path)
    slot_data = slots[slot]
    efs = _find_event_flag_start(slot_data)
    if efs < 0:
        return {n: False for n in BONFIRE_FLAGS}
    result = {}
    for name, offset in BONFIRE_FLAGS.items():
        byte_idx = offset >> 3
        bit_idx = offset & 7
        flag_idx = efs + byte_idx
        if not 0 <= flag_idx < len(slot_data):
            result[name] = False
        else:
            result[name] = bool((slot_data[flag_idx] >> bit_idx) & 1)
    return result


def read_ng_plus(path: str | Path, slot: int = 0) -> int:
    """Return New Game cycle (0=NG, 1=NG+, etc)."""
    _, slots = read_save(path)
    slot_data = slots[slot]
    efs = _find_event_flag_start(slot_data)
    if efs < 0:
        return 0
    ng_off = efs - 0xBCC
    if 0 <= ng_off < len(slot_data):
        return slot_data[ng_off]
    return 0


def read_progress(path: str | Path, slot: int = 0) -> ProgressSummary:
    """Return a complete progress summary."""
    s = read_stats(path, slot)
    bosses = read_bosses(path, slot)
    bonfires = read_bonfires(path, slot)
    ng = read_ng_plus(path, slot)
    return ProgressSummary(
        stats=s,
        bosses_defeated=[b["name"] for b in bosses if b["defeated"]],
        bosses_total=len(bosses),
        bonfires_unlocked=[n for n, u in bonfires.items() if u],
        ng_plus=ng,
    )


def _read_resource_json(name: str) -> dict[str, object]:
    try:
        data = _json.loads((_resources_dir / name).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, _json.JSONDecodeError):
        return {}
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
    return {key: _string_list(item) for key, item in value.items() if isinstance(key, str)}


def _game_areas() -> dict[str, object]:
    areas = _read_resource_json("game_data.json").get("areas")
    if isinstance(areas, dict):
        return areas
    return {}


def read_completion_checklist() -> dict[str, list[str]]:
    """Return the global completion checklist resource, or an empty fallback."""
    data = _read_resource_json("achievement_checklist.json")
    if data:
        return {key: _string_list(value) for key, value in data.items() if isinstance(key, str)}

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
        return {key: _area_string_lists(value) for key, value in data.items() if isinstance(key, str)}

    areas = _game_areas()
    if not areas:
        return {}
    result: dict[str, dict[str, list[str]]] = {}
    for area_name, area in areas.items():
        if isinstance(area_name, str) and isinstance(area, dict):
            result[area_name] = {
                "bosses": _string_list(area.get("bosses")),
                "key_items": _string_list(area.get("key_items")),
                "estus_shards": [str(item) for item in area.get("estus_shards", []) if isinstance(item, (int, str))],
                "bone_shards": [str(item) for item in area.get("bone_shards", []) if isinstance(item, (int, str))],
            }
    return result


def read_current_area(path: str | Path, slot: int = 0) -> str:
    """Infer the furthest unlocked checklist area from bonfire flags."""
    checklist_areas = read_area_checklists()
    game_areas = _game_areas()
    ordered_area_names = list(checklist_areas)
    ordered_area_names.extend(name for name in game_areas if isinstance(name, str) and name not in checklist_areas)
    ordered_area_names.extend(name for name in BONFIRE_FLAGS if name not in ordered_area_names)
    if not ordered_area_names:
        return ""
    bonfires = read_bonfires(path, slot)
    unlocked = {name for name, is_unlocked in bonfires.items() if is_unlocked}
    current_area = ""
    for area_name in ordered_area_names:
        area = game_areas.get(area_name)
        bonfire = area.get("bonfire") if isinstance(area, dict) else None
        if area_name in unlocked or (isinstance(bonfire, str) and bonfire in unlocked):
            current_area = area_name
    return current_area


def read_missed(path: str | Path, slot: int = 0) -> dict[str, object]:
    """Return live progress plus static checklist hints with ownership labels."""
    current_area = read_current_area(path, slot)
    area_checklists = read_area_checklists()
    area_data = area_checklists.get(current_area, {})
    checklist_available = current_area in area_checklists
    game_data = _read_resource_json("game_data.json")
    stats = read_stats(path, slot)
    progress = read_progress(path, slot)
    defeated = set(progress["bosses_defeated"])
    missing_bosses = [name for name in area_data.get("bosses", []) if name not in defeated]
    total_estus = game_data.get("total_estus_shards", 0)
    total_bones = game_data.get("total_bone_shards", 0)
    owned_keys = {_completion_key(name) for name in owned_item_names(path, slot)}
    key_items = []
    for name in area_data.get("key_items", []):
        owned = _completion_key(name) in owned_keys
        key_items.append({"name": name, "owned": owned, "check": not owned})
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
    rdir = Path(__file__).resolve().parent.parent / "resources"

    def _parse_json(fname: str) -> dict[int, str]:
        try:
            data = _json.loads((rdir / fname).read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, _json.JSONDecodeError):
            return {}
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
        ("weapons.json", _WEAPON_NAMES), ("armor.json", _ARMOR_NAMES),
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


def _completion_key(name: str) -> str:
    normalized = " ".join(name.replace(" +", "+").replace("+ ", "+").split())
    for suffix in (" Sorcery", " Pyromancy", " Miracle"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized.casefold()


def _known_item_names(items: list[ItemEntry]) -> set[str]:
    return {item["name"] for item in items if not item["name"].startswith("Unknown ")}


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
        "weapons": _known_item_names(inventory["weapons"]),
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
    ITEM_TYPE_ARMOR  = 0x90000000
    ITEM_TYPE_GOOD   = 0xB0000000
    ITEM_TYPE_RING   = 0xA0000000

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
    seen_offsets: set[int] = set()
    seen_entries: set[tuple[str, int]] = set()

    for offset in range(0x70, max(0x70, len(slot_data) - 15), 4):
        gaitem_handle, item_id, quantity, _index = struct.unpack_from("<IIII", slot_data, offset)
        if item_id in (0, 0xFFFFFFFF):
            continue
        type_bits = gaitem_handle & 0xF0000000

        matched = None
        for expected_type, item_type, names, target_list in category_maps:
            if type_bits != expected_type:
                continue
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

        dedupe_key = (matched[0], item_id)
        if offset in seen_offsets or dedupe_key in seen_entries:
            continue
        seen_offsets.add(offset)
        seen_entries.add(dedupe_key)

        entry: ItemEntry = {
            "slot": offset,
            "gaitem_handle": gaitem_handle,
            "item_id": item_id,
            "item_type": matched[0],
            "name": matched[1],
            "quantity": quantity if matched[0] in ("goods", "ring") and quantity > 0 else 1,
        }
        matched[2].append(entry)

    return InventoryResult(
        weapons=weapons, armor=armors, rings=rings, goods=goods,
        total_items=len(weapons) + len(armors) + len(rings) + len(goods),
    )


def owned_item_names(path: str | Path, slot: int = 0) -> set[str]:
    """Return all resolved inventory item names owned by the save slot."""
    inventory = read_inventory(path, slot)
    names: set[str] = set()
    for items in (inventory["weapons"], inventory["armor"], inventory["rings"], inventory["goods"]):
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
            {name for name in known_names.values() if _completion_key(name) not in excluded},
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
    reinforcement_owned = min(stats["maxWeaponReinforcement"], reinforcement_total)
    return {
        "rings": rings,
        "sorceries": sorceries,
        "pyromancies": pyromancies,
        "miracles": miracles,
        "weapons": _collection_status(owned_by_category["weapons"], _WEAPON_NAMES),
        "armor": _collection_status(owned_by_category["armor"], _ARMOR_NAMES),
        "goods": _collection_status(owned_by_category["goods"], _GOODS_NAMES, spell_keys),
        "reinforcement": {
            "owned": reinforcement_owned,
            "missing": max(0, reinforcement_total - reinforcement_owned),
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
    "read_save", "read_stats", "read_name",
    "read_bosses", "read_bonfires", "read_progress", "read_ng_plus",
    "read_completion_checklist", "read_area_checklists",
    "read_current_area", "read_missed",
    "read_inventory", "owned_item_names", "read_completion_status", "read_gestures",
    "StatBlock", "SlotEntry", "BossStatus", "ProgressSummary",
    "ItemEntry", "InventoryResult", "MissedSummary", "MissedKeyItem",
    "CLASS_NAMES", "AES_KEY", "SAVE_PATH_DEFAULT",
    "BOSS_FLAGS", "BONFIRE_FLAGS",
]
