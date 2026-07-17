"""Dark Souls 3 core data: constants, catalogs, cache helpers, and spoiler filter.

Leaf module — no internal imports from sibling modules.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CACHE_TTL_HOURS = 24
DATA_SOURCE = (
    "Embedded source-ranked constants plus source registry/cache for live verification."
)
UPDATED = "2026-06-28"
CACHE_ENV = "DS3_CACHE_DIR"
CACHE_DIR = Path(
    os.environ.get(CACHE_ENV, "~/.cache/darksouls3-companion"),
).expanduser()

# ── Source Registry ──────────────────────────────────────────────


@dataclass
class SourceRecord:
    url: str
    license: str
    use: str
    machine: bool = True
    risk: str = ""


SOURCES: dict[str, SourceRecord] = {
    "fextralife-stats": SourceRecord(
        "https://darksouls3.wiki.fextralife.com/Stats",
        "CC BY-NC-SA",
        "Primary source for stat descriptions, softcaps, HP/FP/Stamina/Equip Load tables.",
        risk="Spoiler-heavy; default to mechanics summaries.",
    ),
    "fextralife-classes": SourceRecord(
        "https://darksouls3.wiki.fextralife.com/Classes",
        "CC BY-NC-SA",
        "Starting class comparison table with exact stat values.",
    ),
    "fextralife-weapons": SourceRecord(
        "https://darksouls3.wiki.fextralife.com/Weapons",
        "CC BY-NC-SA",
        "Weapon categories, base damage, scaling, requirements.",
        risk="Late/DLC weapon names are spoilers.",
    ),
    "fextralife-infusions": SourceRecord(
        "https://darksouls3.wiki.fextralife.com/Infusion",
        "CC BY-NC-SA",
        "All 15 infusion types, coal requirements, scaling changes.",
    ),
    "fextralife-upgrades": SourceRecord(
        "https://darksouls3.wiki.fextralife.com/Upgrades",
        "CC BY-NC-SA",
        "Titanite upgrade paths, materials per level, gem farming.",
    ),
    "fextralife-covenants": SourceRecord(
        "https://darksouls3.wiki.fextralife.com/Covenants",
        "CC BY-NC-SA",
        "Covenant mechanics, rank rewards, join methods, farming.",
    ),
    "fextralife-areas": SourceRecord(
        "https://darksouls3.wiki.fextralife.com/Areas",
        "CC BY-NC-SA",
        "Area names, boss lists, bonfire counts, progression order. Spoiler-heavy.",
    ),
    "fextralife-progress": SourceRecord(
        "https://darksouls3.wiki.fextralife.com/Game+Progress+Route",
        "CC BY-NC-SA",
        "Full progression route with NPC questlines, items, and triggers.",
    ),
    "wikidot-stats": SourceRecord(
        "https://darksouls3.wikidot.com/stats",
        "CC BY-SA 3.0",
        "Secondary stat reference with permissive license.",
    ),
    "mugenmonkey": SourceRecord(
        "https://mugenmonkey.com/darksouls3",
        "No license observed",
        "AR calculator and class planner for formula cross-checking.",
    ),
    "soulsplanner": SourceRecord(
        "https://soulsplanner.com/darksouls3",
        "No license observed",
        "Build planner for verifying stat targets.",
    ),
    "cheat-sheet": SourceRecord(
        "https://zkjellberg.github.io/dark-souls-3-cheat-sheet",
        "MIT",
        "Interactive checklist for rings, spells, gestures, and items.",
    ),
    "pcgamingwiki": SourceRecord(
        "https://www.pcgamingwiki.com/wiki/Dark_Souls_III",
        "CC BY-NC-SA",
        "Technical fixes: FPS unlock, stutter fix, crash fixes, modding tools.",
    ),
    "soulsmods": SourceRecord(
        "https://github.com/soulsmods",
        "MIT/GPL",
        "DSMapStudio, SoulsFormats, UXM, WitchyBND — modding toolchain.",
    ),
    "alfizari-save-editor": SourceRecord(
        "https://github.com/alfizari/Dark-Souls-3-Save-Editor-PS4-PC",
        "MIT",
        "Primary embedded provenance for DS30000 save layout, boss bytes, and historical event-layout cross-checks.",
    ),
    "tga-ct": SourceRecord(
        "https://github.com/The-Grand-Archives/Dark-Souls-III-CT-TGA",
        "No license observed",
        "Reference-only cross-check for runtime event flags and tracked per-bonfire SprjEventFlagMan bits.",
        machine=False,
        risk="Do not bulk-copy; reference/cross-check only.",
    ),
    "paramdex-bonfire": SourceRecord(
        "https://raw.githubusercontent.com/soulsmods/Paramdex/master/DS3/Defs/BONFIRE_WARP_PARAM_ST.xml",
        "License unclear",
        "Schema-only reference for DS3 bonfire warp PARAM field names.",
        machine=False,
        risk="Schema source, not save-byte or row-data source.",
    ),
    "soulsmodding-flags": SourceRecord(
        "https://soulsmodding.com/doku.php?id=ds3-refmat:event-flag-list",
        "Community wiki; license not verified",
        "Event flag ID semantics cross-check.",
        machine=False,
        risk="Event IDs are not DS30000 save-byte offsets.",
    ),
    "modengine1": SourceRecord(
        "https://github.com/katalash/ModEngine",
        "No license observed",
        "Mod Engine 1 source (dinput8 passive proxy).",
    ),
    "me3": SourceRecord(
        "https://github.com/garyttierney/me3",
        "No license observed",
        "Mod Engine 3 source (injection-based launcher).",
    ),
}

# ── Cache helpers ─────────────────────────────────────────────────


def cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def cache_get(key: str) -> str | None:
    p = cache_dir() / f"{key}.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    if time.time() - data.get("ts", 0) > CACHE_TTL_HOURS * 3600:
        return None
    return data.get("content")


def cache_put(key: str, content: str, meta: dict | None = None) -> None:
    p = cache_dir() / f"{key}.json"
    p.write_text(
        json.dumps({"ts": time.time(), "content": content, "meta": meta or {}}),
    )


def fetch_cached(key: str, url: str, *, force: bool = False) -> str:
    cached = None if force else cache_get(key)
    if cached:
        return cached
    req = urllib.request.Request(url, headers={"User-Agent": "ds3-companion/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        content = resp.read().decode("utf-8", errors="replace")
    cache_put(
        key,
        content,
        {"url": url, "sha256": hashlib.sha256(content.encode()).hexdigest()},
    )
    return content


# ── Spoiler filter ───────────────────────────────────────────────

# Names the player has already encountered (tracking-file driven or explicitly mentioned)
known_names: set[str] = set()


def mark_known(name: str) -> None:
    known_names.add(name.lower())


def is_known(name: str) -> bool:
    return name.lower() in known_names or name.lower() in {
        "firelink shrine",
        "cemetery of ash",
        "high wall of lothric",
    }


def spoiler_safe(name: str) -> str:
    """Return the name if known, otherwise a generic placeholder."""
    if is_known(name):
        return name.title()
    return "an area you haven't reached yet"


# ── Data Constants ───────────────────────────────────────────────

ORIGINS: dict[str, dict] = {
    "knight": {
        "level": 9,
        "vig": 12,
        "att": 10,
        "end": 11,
        "vit": 15,
        "str": 13,
        "dex": 12,
        "int": 9,
        "fth": 9,
        "lck": 7,
    },
    "mercenary": {
        "level": 8,
        "vig": 11,
        "att": 12,
        "end": 11,
        "vit": 10,
        "str": 10,
        "dex": 16,
        "int": 10,
        "fth": 8,
        "lck": 9,
    },
    "warrior": {
        "level": 7,
        "vig": 14,
        "att": 6,
        "end": 12,
        "vit": 11,
        "str": 16,
        "dex": 9,
        "int": 8,
        "fth": 9,
        "lck": 11,
    },
    "herald": {
        "level": 9,
        "vig": 12,
        "att": 10,
        "end": 9,
        "vit": 12,
        "str": 12,
        "dex": 11,
        "int": 8,
        "fth": 13,
        "lck": 11,
    },
    "thief": {
        "level": 5,
        "vig": 10,
        "att": 11,
        "end": 10,
        "vit": 9,
        "str": 9,
        "dex": 13,
        "int": 10,
        "fth": 8,
        "lck": 14,
    },
    "assassin": {
        "level": 10,
        "vig": 10,
        "att": 14,
        "end": 11,
        "vit": 10,
        "str": 10,
        "dex": 14,
        "int": 11,
        "fth": 9,
        "lck": 10,
    },
    "sorcerer": {
        "level": 6,
        "vig": 9,
        "att": 16,
        "end": 9,
        "vit": 7,
        "str": 7,
        "dex": 12,
        "int": 16,
        "fth": 7,
        "lck": 12,
    },
    "pyromancer": {
        "level": 8,
        "vig": 11,
        "att": 12,
        "end": 10,
        "vit": 8,
        "str": 12,
        "dex": 9,
        "int": 14,
        "fth": 14,
        "lck": 7,
    },
    "cleric": {
        "level": 7,
        "vig": 10,
        "att": 14,
        "end": 8,
        "vit": 7,
        "str": 12,
        "dex": 8,
        "int": 7,
        "fth": 16,
        "lck": 13,
    },
    "deprived": {
        "level": 1,
        "vig": 10,
        "att": 10,
        "end": 10,
        "vit": 10,
        "str": 10,
        "dex": 10,
        "int": 10,
        "fth": 10,
        "lck": 10,
    },
}

SOFTCAPS: dict[str, list[tuple[int, str]]] = {
    "vigor": [
        (27, "1000 HP, +30/lvl"),
        (39, "1200 HP, +15/lvl"),
        (50, "1300 HP, +5/lvl"),
    ],
    "attunement": [
        (24, "4 spell slots"),
        (30, "5 slots"),
        (35, "280 FP"),
        (40, "6 slots"),
        (50, "7 slots, FP softcap"),
    ],
    "endurance": [(40, "Hard cap — no stamina gained past 40")],
    "vitality": [(40, "Softcap for equip load gains per level")],
    "strength": [
        (25, "First softcap"),
        (40, "Second softcap"),
        (60, "Third softcap — two-hand at 66 for effective 99"),
    ],
    "dexterity": [
        (25, "First softcap"),
        (40, "Second softcap"),
        (60, "Third softcap — also max casting speed at 50"),
    ],
    "intelligence": [
        (20, "First softcap"),
        (50, "Second softcap"),
        (60, "Third softcap"),
    ],
    "faith": [(20, "First softcap"), (50, "Second softcap"), (60, "Third softcap")],
    "luck": [(40, "Softcap for item discovery and bleed/poison buildup")],
}

# Vigor → HP (key breakpoints, linear interpolation between)
_VIGOR_HP_POINTS = [
    (10, 403),
    (20, 764),
    (27, 1000),
    (30, 1056),
    (39, 1200),
    (40, 1213),
    (50, 1300),
    (60, 1323),
    (70, 1346),
    (80, 1367),
    (90, 1386),
    (99, 1400),
]


def vigor_hp(vig: int) -> int:
    if vig < 10:
        return 300
    vig = min(vig, 99)
    for i in range(len(_VIGOR_HP_POINTS) - 1):
        lo_lvl, lo_hp = _VIGOR_HP_POINTS[i]
        hi_lvl, hi_hp = _VIGOR_HP_POINTS[i + 1]
        if lo_lvl <= vig <= hi_lvl:
            frac = (vig - lo_lvl) / (hi_lvl - lo_lvl)
            return round(lo_hp + frac * (hi_hp - lo_hp))
    return _VIGOR_HP_POINTS[-1][1]


# Attunement → FP (key breakpoints)
_ATT_FP_POINTS = [
    (10, 93),
    (15, 120),
    (20, 150),
    (25, 189),
    (30, 233),
    (35, 280),
    (40, 296),
    (50, 324),
    (60, 350),
    (70, 377),
    (80, 404),
    (99, 450),
]


def attunement_fp(att: int) -> int:
    if att < 10:
        return 50
    att = min(att, 99)
    for i in range(len(_ATT_FP_POINTS) - 1):
        lo_lvl, lo_fp = _ATT_FP_POINTS[i]
        hi_lvl, hi_fp = _ATT_FP_POINTS[i + 1]
        if lo_lvl <= att <= hi_lvl:
            frac = (att - lo_lvl) / (hi_lvl - lo_lvl)
            return round(lo_fp + frac * (hi_fp - lo_fp))
    return _ATT_FP_POINTS[-1][1]


_ATT_SLOTS = [(10, 1), (14, 2), (18, 3), (24, 4), (30, 5), (40, 6), (50, 7)]


def attunement_slots(att: int) -> int:
    slots = 0
    for threshold, count in _ATT_SLOTS:
        if att >= threshold:
            slots = count
    return slots


# Endurance → Stamina
def endurance_stamina(end: int) -> int:
    if end < 10:
        return 85
    if end >= 99:
        return 170
    points = [
        (10, 85),
        (20, 111),
        (30, 134),
        (40, 160),
        (50, 164),
        (60, 167),
        (70, 169),
        (80, 170),
        (90, 170),
        (99, 170),
    ]
    for i in range(len(points) - 1):
        lo, lo_s = points[i]
        hi, hi_s = points[i + 1]
        if lo <= end <= hi:
            return round(lo_s + (end - lo) / (hi - lo) * (hi_s - lo_s))
    return 170


# Soul cost formula (DS3 cumulative polynomial)
def soul_cost(current: int, target: int) -> int:
    if target <= current:
        return 0
    total = 0
    for x in range(current, target):
        total += round(0.02 * x**3 + 3.06 * x**2 + 105.6 * x - 895)
    return total


# Scaling saturation (weapon AR calculation helper)
# Base multipliers for letter grades at 10/20/30/40/50/60/70/80/90/99 stat
_SAT_BY_GRADE = {
    "S": [0.25, 0.65, 0.88, 1.02, 1.04, 1.06, 1.08, 1.09, 1.10, 1.10],
    "A": [0.20, 0.50, 0.80, 0.98, 0.98, 0.98, 0.98, 0.98, 0.98, 0.98],
    "B": [0.15, 0.40, 0.65, 0.85, 0.90, 0.90, 0.90, 0.90, 0.90, 0.90],
    "C": [0.10, 0.30, 0.50, 0.70, 0.80, 0.80, 0.80, 0.80, 0.80, 0.80],
    "D": [0.05, 0.20, 0.35, 0.50, 0.60, 0.65, 0.65, 0.65, 0.65, 0.65],
    "E": [0.02, 0.10, 0.20, 0.30, 0.40, 0.45, 0.45, 0.45, 0.45, 0.45],
    "-": [0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00],
}


def sat_mult(stat: int, grade: str) -> float:
    """Scaling saturation multiplier for a stat level and letter grade."""
    idx = max(0, min(9, (stat - 10) // 10)) if stat >= 10 else 0
    return _SAT_BY_GRADE.get(grade, _SAT_BY_GRADE["-"])[idx]


def weapon_ar(weapon: dict, stats: dict[str, int]) -> int:
    """Approximate AR: base * (1 + str_scaling * sat + dex_scaling * sat + int_scaling * sat + fth_scaling * sat)."""
    base = weapon.get("base_damage", 100)
    ar = base
    for stat_key, grade_key in [
        ("str", "str_scale"),
        ("dex", "dex_scale"),
        ("int", "int_scale"),
        ("fth", "fth_scale"),
    ]:
        grade = weapon.get(grade_key, "-")
        stat_val = stats.get(stat_key, 10)
        ar += base * weapon.get(f"{stat_key}_coeff", 0.5) * sat_mult(stat_val, grade)
    return round(ar)


# Equipment load
def equip_load_max(vit: int, havels: bool = False, favor: bool = False) -> float:
    base = 40.0 + 1.0 * vit
    if havels:
        base *= 1.15
    if favor:
        base *= 1.05
    return round(base, 1)


def roll_type(weight_ratio: float) -> str:
    if weight_ratio < 30:
        return "fast roll (13 iframes)"
    if weight_ratio < 70:
        return "medium roll (13 iframes, slower recovery)"
    if weight_ratio < 100:
        return "fat roll (12 iframes)"
    return "overencumbered (cannot roll)"


# Upgrade paths
UPGRADE_NORMAL = [
    (0, 1, {"shards": 2}),
    (1, 2, {"shards": 4}),
    (2, 3, {"shards": 6}),
    (3, 4, {"large_shards": 6}),
    (4, 5, {"large_shards": 8}),
    (5, 6, {"large_shards": 8}),
    (6, 7, {"chunks": 6}),
    (7, 8, {"chunks": 6}),
    (8, 9, {"chunks": 6}),
    (9, 10, {"slab": 1}),
]
UPGRADE_TWINKLING = [
    (0, 1, {"twinkling": 1}),
    (1, 2, {"twinkling": 2}),
    (2, 3, {"twinkling": 4}),
    (3, 4, {"twinkling": 8}),
    (4, 5, {"slab": 1}),
]
UPGRADE_SCALE = [
    (0, 1, {"scales": 1}),
    (1, 2, {"scales": 2}),
    (2, 3, {"scales": 4}),
    (3, 4, {"scales": 8}),
    (4, 5, {"slab": 1}),
]

INFUSIONS: list[dict] = [
    {
        "id": "heavy",
        "gem": "Heavy Gem",
        "coal": "Farron Coal",
        "effect": "Adds/improves STR scaling, removes DEX scaling",
        "best_for": "strength builds",
    },
    {
        "id": "sharp",
        "gem": "Sharp Gem",
        "coal": "Farron Coal",
        "effect": "Adds/improves DEX scaling, reduces STR scaling",
        "best_for": "dexterity builds",
    },
    {
        "id": "refined",
        "gem": "Refined Gem",
        "coal": "Farron Coal",
        "effect": "Balances STR/DEX scaling (lower each but both active)",
        "best_for": "quality builds (40/40)",
    },
    {
        "id": "raw",
        "gem": "Raw Gem",
        "coal": "Farron Coal",
        "effect": "Removes all scaling, increases base damage",
        "best_for": "low-level builds, casters",
    },
    {
        "id": "fire",
        "gem": "Fire Gem",
        "coal": "Farron Coal",
        "effect": "Fire damage, removes all scaling",
        "best_for": "early game, low stat investment",
    },
    {
        "id": "deep",
        "gem": "Deep Gem",
        "coal": "Farron Coal",
        "effect": "Dark damage, removes all scaling",
        "best_for": "early game dark damage",
    },
    {
        "id": "crystal",
        "gem": "Crystal Gem",
        "coal": "Sage's Coal",
        "effect": "Magic damage, INT scaling",
        "best_for": "sorcerer builds",
    },
    {
        "id": "simple",
        "gem": "Simple Gem",
        "coal": "Sage's Coal",
        "effect": "Magic damage, INT scaling, passive FP regen",
        "best_for": "off-hand FP regen tool",
    },
    {
        "id": "lightning",
        "gem": "Lightning Gem",
        "coal": "Sage's Coal",
        "effect": "Lightning damage, FTH scaling",
        "best_for": "cleric builds",
    },
    {
        "id": "blessed",
        "gem": "Blessed Gem",
        "coal": "Sage's Coal",
        "effect": "Physical damage, FTH scaling, passive HP regen",
        "best_for": "off-hand HP regen, skellies",
    },
    {
        "id": "chaos",
        "gem": "Chaos Gem",
        "coal": "Profaned Coal",
        "effect": "Fire damage, INT+FTH scaling",
        "best_for": "pyromancer builds",
    },
    {
        "id": "dark",
        "gem": "Dark Gem",
        "coal": "Profaned Coal",
        "effect": "Dark damage, INT+FTH scaling",
        "best_for": "pyromancer/dark builds",
    },
    {
        "id": "blood",
        "gem": "Blood Gem",
        "coal": "Profaned Coal",
        "effect": "Adds bleed buildup, LCK scaling",
        "best_for": "luck/bleed builds",
    },
    {
        "id": "poison",
        "gem": "Poison Gem",
        "coal": "Profaned Coal",
        "effect": "Adds poison buildup, LCK scaling",
        "best_for": "niche poison builds",
    },
    {
        "id": "hollow",
        "gem": "Hollow Gem",
        "coal": "Giant's Coal",
        "effect": "Adds LCK scaling, +5 LCK when hollowed",
        "best_for": "luck/hollow builds",
    },
]

STARTER_WEAPONS: dict[str, dict] = {
    "long sword": {
        "base_damage": 110,
        "str_scale": "D",
        "dex_scale": "D",
        "str_req": 10,
        "dex_req": 10,
        "weight": 3.0,
        "category": "straight sword",
        "str_coeff": 0.55,
        "dex_coeff": 0.55,
    },
    "broadsword": {
        "base_damage": 117,
        "str_scale": "C",
        "dex_scale": "D",
        "str_req": 10,
        "dex_req": 10,
        "weight": 3.0,
        "category": "straight sword",
        "str_coeff": 0.65,
        "dex_coeff": 0.35,
    },
    "claymore": {
        "base_damage": 138,
        "str_scale": "D",
        "dex_scale": "D",
        "str_req": 16,
        "dex_req": 13,
        "weight": 9.0,
        "category": "greatsword",
        "str_coeff": 0.50,
        "dex_coeff": 0.50,
    },
    "zweihander": {
        "base_damage": 145,
        "str_scale": "D",
        "dex_scale": "D",
        "str_req": 19,
        "dex_req": 11,
        "weight": 10.0,
        "category": "ultra greatsword",
        "str_coeff": 0.70,
        "dex_coeff": 0.30,
    },
    "uchigatana": {
        "base_damage": 115,
        "str_scale": "D",
        "dex_scale": "C",
        "str_req": 11,
        "dex_req": 16,
        "weight": 5.5,
        "category": "katana",
        "str_coeff": 0.30,
        "dex_coeff": 0.70,
    },
    "sellsword twinblades": {
        "base_damage": 79,
        "str_scale": "D",
        "dex_scale": "C",
        "str_req": 10,
        "dex_req": 16,
        "weight": 5.5,
        "category": "curved sword (paired)",
        "str_coeff": 0.30,
        "dex_coeff": 0.70,
    },
    "estoc": {
        "base_damage": 102,
        "str_scale": "D",
        "dex_scale": "C",
        "str_req": 10,
        "dex_req": 12,
        "weight": 3.5,
        "category": "thrusting sword",
        "str_coeff": 0.30,
        "dex_coeff": 0.70,
    },
    "mace": {
        "base_damage": 126,
        "str_scale": "B",
        "dex_scale": "-",
        "str_req": 12,
        "dex_req": 7,
        "weight": 5.0,
        "category": "hammer",
        "str_coeff": 0.85,
        "dex_coeff": 0.0,
    },
    "battle axe": {
        "base_damage": 125,
        "str_scale": "C",
        "dex_scale": "D",
        "str_req": 12,
        "dex_req": 8,
        "weight": 4.0,
        "category": "axe",
        "str_coeff": 0.70,
        "dex_coeff": 0.30,
    },
    "rapier": {
        "base_damage": 97,
        "str_scale": "E",
        "dex_scale": "B",
        "str_req": 7,
        "dex_req": 12,
        "weight": 2.0,
        "category": "thrusting sword",
        "str_coeff": 0.15,
        "dex_coeff": 0.85,
    },
}

BUILDS: dict[str, dict] = {
    "quality": {
        "class": "knight",
        "vig": 39,
        "end": 35,
        "str": 40,
        "dex": 40,
        "vit": 20,
        "infusion": "refined",
        "weapons": "claymore, long sword, lothric knight sword",
        "note": "Most versatile. Can use 90% of weapons.",
    },
    "strength": {
        "class": "warrior",
        "vig": 39,
        "end": 35,
        "str": 66,
        "dex": 13,
        "vit": 25,
        "infusion": "heavy",
        "weapons": "zweihander, great club, broadsword, mace",
        "note": "Two-hand for effective 99 STR. Big weapons, big damage.",
    },
    "dexterity": {
        "class": "mercenary",
        "vig": 39,
        "end": 35,
        "str": 16,
        "dex": 70,
        "vit": 20,
        "infusion": "sharp",
        "weapons": "uchigatana, estoc, sellsword twinblades, rapier",
        "note": "Fast attacks, high DPS. 50 DEX = max casting speed.",
    },
    "sorcerer": {
        "class": "sorcerer",
        "vig": 27,
        "att": 30,
        "end": 25,
        "str": 10,
        "dex": 12,
        "int": 60,
        "vit": 10,
        "infusion": "crystal or raw",
        "weapons": "long sword (raw), rapier (crystal), sorcerer's staff",
        "note": "60 INT softcap. Raw weapon + Crystal Magic Weapon buff.",
    },
    "pyromancer": {
        "class": "pyromancer",
        "vig": 35,
        "att": 24,
        "end": 30,
        "str": 12,
        "dex": 10,
        "int": 40,
        "fth": 40,
        "vit": 12,
        "infusion": "chaos or dark",
        "weapons": "long sword (chaos/dark), claymore (chaos)",
        "note": "40/40 INT/FTH is the softcap for pyro/dark. Most FP-efficient caster.",
    },
    "cleric": {
        "class": "cleric",
        "vig": 35,
        "att": 24,
        "end": 25,
        "str": 14,
        "dex": 10,
        "fth": 60,
        "vit": 12,
        "infusion": "lightning or blessed",
        "weapons": "mace (lightning), long sword (blessed), talisman",
        "note": "60 FTH softcap. Blessed infusion gives HP regen.",
    },
    "luck": {
        "class": "thief",
        "vig": 35,
        "end": 30,
        "str": 11,
        "dex": 16,
        "lck": 40,
        "vit": 15,
        "infusion": "hollow or blood",
        "weapons": "uchigatana (blood), warden twinblades (hollow)",
        "note": "40 LCK softcap. Hollow infusion gives +5 LCK at 15+ hollowing.",
    },
}

COVENANTS: list[dict] = [
    {
        "id": "sunlight",
        "name": "Warriors of Sunlight",
        "type": "co-op",
        "item": "Sunlight Medal",
        "rank10": "Sacred Oath (miracle)",
        "rank30": "Great Lightning Spear (miracle)",
        "farm": "Lothric Knights (early-mid area)",
    },
    {
        "id": "way_of_blue",
        "name": "Way of Blue",
        "type": "defense",
        "item": None,
        "rank10": None,
        "rank30": None,
        "farm": "No farming — equips only. Auto-summons defenders when invaded.",
    },
    {
        "id": "blue_sentinels",
        "name": "Blue Sentinels",
        "type": "defense-auto",
        "item": "Proof of Concord Kept",
        "rank10": "Darkmoon Ring",
        "rank30": "Darkmoon Blade (miracle)",
        "farm": "Silver Knights on stairs (mid-game area). 1% base drop. ~6-10 hours.",
    },
    {
        "id": "darkmoon",
        "name": "Blade of the Darkmoon",
        "type": "defense-auto",
        "item": "Proof of Concord Kept",
        "rank10": "Darkmoon Ring",
        "rank30": "Darkmoon Blade (miracle)",
        "farm": "Same as Blue Sentinels. Proofs are the worst covenant grind.",
    },
    {
        "id": "rosaria",
        "name": "Rosaria's Fingers",
        "type": "invasion",
        "item": "Pale Tongue",
        "rank10": "Obscuring Ring",
        "rank30": "Man-Grub's Staff",
        "farm": "Darkwraiths (early swamp area). ~3% drop rate.",
    },
    {
        "id": "mound_makers",
        "name": "Mound-Makers",
        "type": "chaos",
        "item": "Vertebra Shackle",
        "rank10": "Bloodlust (katana)",
        "rank30": "Warmth (pyromancy)",
        "farm": "Skeletons in catacombs (mid-game area). ~1% drop. ~4-6 hours.",
    },
    {
        "id": "watchdogs",
        "name": "Watchdogs of Farron",
        "type": "area-defense",
        "item": "Wolf's Blood Swordgrass",
        "rank10": "Old Wolf Curved Sword",
        "rank30": "Wolf Ring (platinum)",
        "farm": "3 Ghru enemies at Keep Ruins bonfire (early swamp). ~3% drop. ~2-4 hours.",
    },
    {
        "id": "aldrich",
        "name": "Aldrich Faithful",
        "type": "area-defense",
        "item": "Human Dregs",
        "rank10": "Great Deep Soul (sorcery)",
        "rank30": "Archdeacon's Great Staff",
        "farm": "9 Deacons on upper balcony (mid-game castle). ~5% drop. ~1-2 hours.",
    },
    {
        "id": "spears",
        "name": "Spears of the Church",
        "type": "dlc-boss",
        "item": "Filianore's Spear Ornament",
        "rank10": "Young Grass Dew",
        "rank30": "Divine Spear Fragment",
        "farm": "DLC only. Not required for platinum.",
    },
]

ESTUS_SHARDS_MAX = 11
BONE_SHARDS_MAX = 10
