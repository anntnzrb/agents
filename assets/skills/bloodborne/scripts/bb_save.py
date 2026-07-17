from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, TypedDict

USERNAME_TO_INV_OFFSET = 469
UPGRADE_START = 84
UPGRADE_RECORD_SIZE = 40
SLOT_BLOCK_SIZE = 60
GARBAGE_U64 = 0xFFFFFFFF00000000

GEM_TYPE_SHAPES = {(0x01, 0x01), (0x01, 0x02), (0x01, 0x04), (0x01, 0x08), (0x01, 0x3F)}
RUNE_TYPE_SHAPES = {(0x02, 0x01), (0x02, 0x02)}
VALID_TYPE_SHAPES = GEM_TYPE_SHAPES | RUNE_TYPE_SHAPES

SLOT_SHAPE: dict[int, str] = {
    0x80000000: "closed",
    1: "radial",
    2: "triangle",
    4: "waning",
    8: "circle",
    0x3F: "droplet",
}

USERNAME_TO_KEY_INV_OFFSET = 32201
INV_TO_STORAGE_OFFSET = 34268
USERNAME_TO_AOB = 68545
MAX_SLOTS = 1984
RESOURCE_DIR = Path(__file__).resolve().parent / "resources" / "bloodborne_save"

KNOWN_BOSSES = {
    "Cleric Beast",
    "Father Gascoigne",
    "Blood Starved Beast",
    "Vicar Amelia",
    "Witch Of Hemwick",
    "Dark Beast Paarl",
    "Shadow Of Yharnam",
    "Rom",
    "One Reborn",
    "Celestial Emissary",
    "Ebrietas",
    "Martyr Logarius",
}

BOSS_ALIASES = {
    "Witch Of Hemwick": "Witch of Hemwick",
    "Dark Beast Paarl": "Darkbeast Paarl",
    "Shadow Of Yharnam": "Forbidden Woods boss",
    "Rom": "Byrgenwerth boss (Rom)",
    "One Reborn": "Yahar'gul boss",
    "Ebrietas": "Ebrietas, Daughter of the Cosmos",
}

MATERIAL_NAMES = {
    "Blood Stone Shard",
    "Twin Blood Stone Shards",
    "Blood Stone Chunk",
    "Blood Rock",
    "Ritual Blood (1)",
    "Ritual Blood (2)",
    "Ritual Blood (3)",
    "Ritual Blood (4)",
    "Ritual Blood (5)",
    "Pearl Slug",
    "Red Jelly",
}

IMPORTANT_KEY_ITEMS = {
    "Cainhurst Summons",
    "Upper Cathedral Key",
    "Cosmic Eye Watcher Badge",
    "Orphanage Key",
    "Radiant Sword Hunter Badge",
    "Rune Workshop Tool",
    "Blood Gem Workshop Tool",
    "Tonsil Stone",
    "Lecture Theatre Key",
    "Lunarium Key",
}


class StatSpec(TypedDict):
    name: str
    rel_offset: int
    length: int
    times: int


class BossFlag(TypedDict):
    rel_offset: int
    dead_value: int
    alive_value: int
    current_value: int


class BossSpec(TypedDict):
    name: str
    flags: list[BossFlag]


@dataclass(frozen=True)
class SaveLayout:
    face_offset: int
    appearance_offset: int
    inventory_offset: int
    username_offset: int
    key_inventory_offset: int
    storage_offset: int


@dataclass(frozen=True)
class InventoryEntry:
    location: Literal["inventory", "key_inventory", "storage"]
    kind: str
    category: str
    name: str
    amount: int
    item_id: int
    slot_index: int
    reinforcement: int | None = None


@dataclass(frozen=True)
class UpgradeEntry:
    upgrade_id: int
    source: int
    kind: str
    shape: str
    effect_ids: tuple[int, ...]
    name: str
    effect_desc: str
    rating: int
    location: str


@dataclass(frozen=True)
class SlotBlock:
    article_key: int
    slots: tuple[tuple[str, int | None], ...]


@dataclass(frozen=True)
class BossState:
    name: str
    defeated: bool
    known: bool


def _load_json(name: str) -> Any:
    return json.loads((RESOURCE_DIR / name).read_text(encoding="utf-8"))


OFFSETS: list[StatSpec] = _load_json("offsets.json")
UPGRADES: dict[str, Any] = _load_json("upgrades.json")
BOSSES: list[BossSpec] = _load_json("bosses.json")
ITEMS: dict[str, dict[str, dict[str, Any]]] = _load_json("items.json")
WEAPONS: dict[str, dict[str, dict[str, Any]]] = _load_json("weapons.json")
ARMORS: dict[str, dict[str, dict[str, Any]]] = _load_json("armors.json")


def _u_le(data: memoryview, offset: int, length: int) -> int:
    if offset < 0 or offset + length > len(data):
        raise ValueError(f"read outside save bounds at 0x{offset:x}+{length}")
    return int.from_bytes(data[offset : offset + length], "little", signed=False)


def _find_layout(data: memoryview) -> SaveLayout:
    face_offset = -1
    start = min(0xF000, max(0, len(data) - 4))
    for offset in range(start, len(data) - 4):
        if data[offset : offset + 4] == b"FACE":
            face_offset = offset
            break
    if face_offset < 0:
        raise ValueError(
            "not a recognized Bloodborne userdata file: FACE marker not found",
        )
    appearance_offset = face_offset + 4
    inventory_offset = face_offset - 34028
    username_offset = inventory_offset - USERNAME_TO_INV_OFFSET
    if username_offset < 0 or inventory_offset < 0:
        raise ValueError(
            "not a recognized Bloodborne userdata file: derived offsets are invalid",
        )
    return SaveLayout(
        face_offset=face_offset,
        appearance_offset=appearance_offset,
        inventory_offset=inventory_offset,
        username_offset=username_offset,
        key_inventory_offset=username_offset + USERNAME_TO_KEY_INV_OFFSET,
        storage_offset=inventory_offset + INV_TO_STORAGE_OFFSET,
    )


def read_save(path: str | Path) -> tuple[bytes, SaveLayout]:
    p = Path(path).expanduser()
    data = p.read_bytes()
    if not data:
        raise ValueError("save file is empty")
    view = memoryview(data)
    return data, _find_layout(view)


def read_stats(path: str | Path) -> dict[str, int]:
    data, layout = read_save(path)
    view = memoryview(data)
    stats: dict[str, int] = {}
    for spec in OFFSETS:
        stats[spec["name"]] = _u_le(
            view,
            layout.username_offset + spec["rel_offset"],
            spec["length"],
        )
    return stats


def read_username(path: str | Path) -> str:
    data, layout = read_save(path)
    raw = memoryview(data)[
        layout.username_offset : layout.username_offset + 64
    ].tobytes()
    nul = raw.find(b"\x00")
    if nul < 0:
        nul = len(raw)
    return raw[:nul].decode("utf-8", errors="replace")


def _lookup_item(item_id: int) -> tuple[str, str] | None:
    key = str(item_id)
    for category, rows in ITEMS.items():
        row = rows.get(key)
        if row:
            return str(row["item_name"]), category
    return None


def _lookup_weapon(item_id: int) -> tuple[str, str] | None:
    key = str(item_id)
    for category, rows in WEAPONS.items():
        row = rows.get(key)
        if row:
            return str(row["item_name"]), category
    return None


def _lookup_armor(item_id: int) -> tuple[str, str] | None:
    key = str(item_id)
    for category, rows in ARMORS.items():
        row = rows.get(key)
        if row:
            return str(row["item_name"]), category
    return None


def _lookup_effect(effect_id: int) -> tuple[str, str, int]:
    key = str(effect_id)
    for section in ("runeEffects", "gemEffects"):
        row = UPGRADES.get(section, {}).get(key)
        if row:
            return (
                str(row.get("name", key)),
                str(row.get("effect", "")),
                int(row.get("rating", 0)),
            )
    return f"Unknown effect {effect_id}", "", 0


def _upgrades_end(data: memoryview, start: int, end: int) -> int:
    limit = min(end, len(data))
    offset = start
    while offset + UPGRADE_RECORD_SIZE <= limit:
        pair = (data[offset + 8], data[offset + 12])
        if pair not in VALID_TYPE_SHAPES:
            break
        offset += UPGRADE_RECORD_SIZE
    return offset


def _parse_upgrades(data: memoryview, start: int, end: int) -> dict[int, UpgradeEntry]:
    out: dict[int, UpgradeEntry] = {}
    offset = start
    limit = _upgrades_end(data, start, end)
    while offset + UPGRADE_RECORD_SIZE <= limit:
        type_id = data[offset + 8]
        shape_id = data[offset + 12]
        kind = "gem" if type_id == 1 else "rune"
        shape = (
            SLOT_SHAPE.get(shape_id, "-")
            if kind == "gem"
            else ("oath" if shape_id == 2 else "-")
        )
        effect_ids = tuple(
            _u_le(data, offset + 16 + index * 4, 4) for index in range(6)
        )
        name, effect_desc, rating = _lookup_effect(effect_ids[0])
        upgrade_id = _u_le(data, offset, 4)
        out[upgrade_id] = UpgradeEntry(
            upgrade_id=upgrade_id,
            source=_u_le(data, offset + 4, 4),
            kind=kind,
            shape=shape,
            effect_ids=effect_ids,
            name=name,
            effect_desc=effect_desc,
            rating=rating,
            location="inventory",
        )
        offset += UPGRADE_RECORD_SIZE
    return out


def _parse_slot_blocks(
    data: memoryview,
    upgrades_end: int,
    username_offset: int,
) -> dict[int, list[tuple[str, int | None]]]:
    out: dict[int, list[tuple[str, int | None]]] = {}
    offset = upgrades_end
    limit = min(username_offset - 147, len(data))
    while offset + 8 <= limit:
        if _u_le(data, offset, 8) == GARBAGE_U64:
            offset += 8
            continue
        if offset + SLOT_BLOCK_SIZE > limit:
            break
        slots: list[tuple[str, int | None]] = []
        for slot_offset in range(offset + 20, offset + SLOT_BLOCK_SIZE, 8):
            shape_id = _u_le(data, slot_offset, 4)
            shape = SLOT_SHAPE.get(shape_id)
            if shape is None:
                break
            upgrade_id = _u_le(data, slot_offset + 4, 4)
            slots.append(
                (
                    shape,
                    upgrade_id
                    if shape != "closed" and upgrade_id not in (0, 0xFFFFFFFF)
                    else None,
                ),
            )
        if len(slots) != 5:
            break
        out[_u_le(data, offset, 8)] = slots
        offset += SLOT_BLOCK_SIZE
    return out


def _read_upgrades(path: str | Path) -> dict[int, UpgradeEntry]:
    data, layout = read_save(path)
    view = memoryview(data)
    upgrades = _parse_upgrades(view, UPGRADE_START, layout.username_offset)
    blocks = _parse_slot_blocks(
        view,
        _upgrades_end(view, UPGRADE_START, layout.username_offset),
        layout.username_offset,
    )
    equipped = {
        upgrade_id
        for slots in blocks.values()
        for _, upgrade_id in slots
        if upgrade_id is not None
    }
    for upgrade_id in equipped:
        entry = upgrades.get(upgrade_id)
        if entry is not None:
            upgrades[upgrade_id] = replace(entry, location="equipped")
    return upgrades


def read_runes(path: str | Path) -> list[UpgradeEntry]:
    return [entry for entry in _read_upgrades(path).values() if entry.kind == "rune"]


def read_gems(path: str | Path) -> list[UpgradeEntry]:
    return [entry for entry in _read_upgrades(path).values() if entry.kind == "gem"]


def _parse_slots(
    data: memoryview,
    start: int,
    location: Literal["inventory", "key_inventory", "storage"],
    max_slots: int,
) -> list[InventoryEntry]:
    out: list[InventoryEntry] = []
    end = min(start + max_slots * 16, len(data) - 16)
    for slot_index, offset in enumerate(range(start, end, 16)):
        slot = data[offset : offset + 16]
        if slot[4:8] == b"\xff\xff\xff\xff" and slot[8:12] == b"\x00\x00\x00\x00":
            continue
        amount = int.from_bytes(slot[12:16], "little", signed=False)
        if amount == 0:
            continue
        if slot[7] == 0xB0 and slot[11] == 0x40:
            item_id = int.from_bytes(
                slot[8:11].tobytes() + b"\x00",
                "little",
                signed=False,
            )
            found = _lookup_item(item_id)
            if found:
                name, category = found
                out.append(
                    InventoryEntry(
                        location,
                        "item",
                        category,
                        name,
                        amount,
                        item_id,
                        slot_index,
                    ),
                )
        elif slot[11] == 0x10:
            item_id = int.from_bytes(
                slot[8:11].tobytes() + b"\x00",
                "little",
                signed=False,
            )
            found = _lookup_armor(item_id)
            if found:
                name, category = found
                out.append(
                    InventoryEntry(
                        location,
                        "armor",
                        category,
                        name,
                        amount,
                        item_id,
                        slot_index,
                    ),
                )
        else:
            item_id = int.from_bytes(slot[8:12], "little", signed=False)
            found = _lookup_weapon(item_id)
            if found:
                name, category = found
                reinforcement = (item_id % 10000) // 100
                out.append(
                    InventoryEntry(
                        location,
                        "weapon",
                        category,
                        name,
                        amount,
                        item_id,
                        slot_index,
                        reinforcement=reinforcement,
                    ),
                )
    return out


def read_inventory(path: str | Path) -> list[InventoryEntry]:
    data, layout = read_save(path)
    view = memoryview(data)
    return [
        *_parse_slots(view, layout.inventory_offset, "inventory", MAX_SLOTS),
        *_parse_slots(view, layout.key_inventory_offset, "key_inventory", 512),
        *_parse_slots(view, layout.storage_offset, "storage", MAX_SLOTS),
    ]


def read_bosses(path: str | Path) -> list[BossState]:
    data, layout = read_save(path)
    view = memoryview(data)
    states: list[BossState] = []
    for boss in BOSSES:
        defeated = True
        for flag in boss["flags"]:
            current = view[
                layout.username_offset + USERNAME_TO_AOB + flag["rel_offset"]
            ]
            if (current & flag["dead_value"]) != flag["dead_value"]:
                defeated = False
                break
        name = boss["name"]
        states.append(
            BossState(name=name, defeated=defeated, known=name in KNOWN_BOSSES),
        )
    return states


def safe_boss_name(name: str) -> str:
    return BOSS_ALIASES.get(name, name)


def materials(entries: list[InventoryEntry]) -> list[InventoryEntry]:
    return [
        entry
        for entry in entries
        if entry.kind == "item" and entry.name in MATERIAL_NAMES
    ]


def important_key_items(entries: list[InventoryEntry]) -> list[InventoryEntry]:
    return [
        entry
        for entry in entries
        if entry.location == "key_inventory" and entry.name in IMPORTANT_KEY_ITEMS
    ]


def weapons(entries: list[InventoryEntry]) -> list[InventoryEntry]:
    return [
        entry
        for entry in entries
        if entry.kind == "weapon" and entry.location == "inventory"
    ]


def weapon_reinforcement(entries: list[InventoryEntry]) -> dict[str, int]:
    """Return dict of weapon name -> reinforcement level (+0 to +10)."""
    return {
        e.name: e.reinforcement
        for e in entries
        if e.kind == "weapon"
        and e.location == "inventory"
        and e.reinforcement is not None
    }
