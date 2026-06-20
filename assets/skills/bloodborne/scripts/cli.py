#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Spoiler-safe Bloodborne lookup CLI for agents.

Stateless: stores no player progress. Tracking/save reads require an explicit
path argument or an environment variable supplied by the caller.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, TypedDict
from bb_save import (
    important_key_items,
    materials,
    read_bosses,
    read_gems,
    read_inventory,
    read_runes,
    read_stats,
    safe_boss_name,
    weapon_reinforcement,
    weapons as save_weapons,
)
CACHE_TTL_HOURS = 24

DATA_SOURCE = "Embedded spoiler-safe constants plus source registry/cache for live verification."
UPDATED = "2026-06-15"
CACHE_ENV = "BLOODBORNE_CACHE_DIR"
CACHE_DIR = Path(os.environ.get(CACHE_ENV, "~/.cache/bloodborne-companion")).expanduser()

SOURCES: dict[str, SourceRecord] = {
    "bb-wiki-scaling": {
        "url": "https://www.bloodborne-wiki.com/2017/05/scaling.html",
        "license": "CC BY-SA 3.0",
        "use": "Primary public source for scaling formulas, letter thresholds, numeric weapon scaling values, and attribute saturation tables.",
        "machine": True,
        "risk": "Attribution/share-alike required for copied derived tables; cache with source metadata.",
    },
    "bb-wiki-weapons": {
        "url": "https://www.bloodborne-wiki.com/p/weapons.html",
        "license": "CC BY-SA 3.0",
        "use": "Primary source for weapon base stats, requirements, durability, rally, and gem imprint tables.",
        "machine": True,
        "risk": "Spoiler-heavy names/availability; default CLI should avoid dumping raw page content.",
    },
    "bb-wiki-gems": {
        "url": "https://www.bloodborne-wiki.com/2015/10/blood-gems-gem-effects.html",
        "license": "CC BY-SA 3.0",
        "use": "Gem effect categories, effect ranges, elemental conversion notes, and physical-build rules.",
        "machine": True,
        "risk": "Good for mechanics; not a complete drop/location database.",
    },
    "bb-wiki-runes": {
        "url": "https://www.bloodborne-wiki.com/p/caryll-runes.html",
        "license": "CC BY-SA 3.0",
        "use": "Rune names, slot types, effect values, stacking behavior, and acquisition tables.",
        "machine": True,
        "risk": "Acquisition data can spoil; expose effects by default, locations only on explicit source use.",
    },
    "bb-wiki-insight": {
        "url": "https://www.bloodborne-wiki.com/2015/03/insight.html",
        "license": "CC BY-SA 3.0",
        "use": "Insight thresholds, frenzy/beasthood effects, and acquisition/spend mechanics.",
        "machine": True,
        "risk": "Event/location threshold tables contain spoilers; default to mechanics-only summaries.",
    },
    "dsmapstudio-paramdex": {
        "url": "https://github.com/soulsmods/DSMapStudio/blob/master/src/StudioCore/Assets/Paramdex/BB/Defs/EquipParamWeapon.xml",
        "license": "MIT",
        "use": "Licensed schema reference for Bloodborne weapon PARAM field names.",
        "machine": True,
        "risk": "Schema only; not weapon row data.",
    },
    "hikkaruu-calculator": {
        "url": "https://github.com/Hikkaruu/BloodborneCalculator",
        "license": "No license observed",
        "use": "Formula/schema cross-check for AR and damage calculators.",
        "machine": True,
        "risk": "Do not copy code/data without permission.",
    },
    "pastebin-ar": {
        "url": "https://pastebin.com/raw/zGphv4fF",
        "license": "No license observed",
        "use": "Detailed community AR/gem formula reference and worked examples.",
        "machine": False,
        "risk": "Reference only; informal and unlicensed.",
    },
    "noxde-save-editor": {
        "url": "https://github.com/Noxde/Bloodborne-save-editor",
        "license": "GPL-3.0",
        "use": "Primary Bloodborne userdata layout reference and static resources for read-only shadPS4/decrypted-save parsing: offsets, boss flags, item/weapon/armor IDs, gems/runes.",
        "machine": True,
        "risk": "GPL-3.0 attribution applies to vendored resource JSON. Parser remains read-only and does not copy save-editing/writeback behavior.",
    },
}
ORIGINS = {
    "milquetoast": (10, 11, 10, 12, 10, 9, 8, "Base/undecided"),
    "lone survivor": (10, 14, 11, 11, 10, 7, 7, "Max early VIT"),
    "troubled childhood": (10, 9, 14, 9, 13, 6, 9, "Max early END"),
    "violent past": (10, 12, 11, 15, 9, 6, 7, "Pure STR"),
    "professional": (10, 9, 12, 9, 15, 7, 8, "Pure SKL"),
    "military veteran": (10, 10, 10, 14, 13, 7, 6, "Quality STR+SKL"),
    "noble scion": (10, 7, 8, 9, 13, 14, 9, "Bloodtinge"),
    "cruel fate": (10, 10, 12, 10, 9, 5, 14, "Arcane / STR-ARC"),
    "waste of skin": (4, 10, 9, 10, 9, 7, 9, "Challenge runs only"),
}

SOFTCAPS = {
    "VIT": "30 soft / 50 hard. 30 midgame baseline; 40-50 endgame comfort.",
    "END": "15 comfort / 40 hard. 40->99 gives no stamina. Most builds stop 15-20.",
    "STR": "25 first soft / 50 hard. Efficient to 25, push later if weapon uses it.",
    "SKL": "25 first soft / 50 hard. Also boosts visceral damage.",
    "BLT": "25 first soft / 50 hard. Skip unless using blood weapons/firearms build.",
    "ARC": "25/50 weapon caps; tools keep scaling high. Skip physical builds unless requirement.",
}

SAT_POINTS = [
    (5, .025), (6, .030), (7, .035), (8, .040), (9, .045), (10, .050),
    (11, .080), (12, .110), (13, .140), (14, .170), (15, .200),
    (16, .230), (17, .260), (18, .290), (19, .320), (20, .350),
    (21, .380), (22, .410), (23, .440), (24, .470), (25, .500),
    (26, .514), (27, .528), (28, .542), (29, .556), (30, .570),
    (31, .584), (32, .598), (33, .612), (34, .626), (35, .640),
    (36, .654), (37, .668), (38, .682), (39, .696), (40, .710),
    (41, .724), (42, .738), (43, .752), (44, .766), (45, .780),
    (46, .794), (47, .808), (48, .822), (49, .836), (50, .850),
    (51, .853), (52, .856), (53, .859), (54, .862), (55, .865),
    (56, .868), (57, .871), (58, .874), (59, .878), (60, .881),
    (61, .884), (62, .887), (63, .890), (64, .893), (65, .896),
    (66, .899), (67, .902), (68, .905), (69, .908), (70, .911),
    (71, .914), (72, .917), (73, .920), (74, .923), (75, .927),
    (76, .930), (77, .933), (78, .936), (79, .939), (80, .942),
    (81, .945), (82, .948), (83, .951), (84, .954), (85, .957),
    (86, .960), (87, .963), (88, .966), (89, .969), (90, .972),
    (91, .975), (92, .979), (93, .982), (94, .985), (95, .988),
    (96, .991), (97, .994), (98, .997), (99, 1.000),
]

@dataclass(frozen=True)
class Weapon:
    name: str
    req: tuple[int, int, int, int]
    base: tuple[int, int, int]
    scaling: tuple[float, float, float, float]
    style: str
    rally: int

Phase = Literal["start", "evening", "night", "blood-moon", "nightmare", "dlc"]


class SourceRecord(TypedDict):
    url: str
    license: str
    use: str
    machine: bool
    risk: str


class AreaRecord(TypedDict):
    id: str
    name: str
    phase: Phase
    safe: bool
    optional: bool


class BossRecord(TypedDict):
    id: str
    safe: str
    name: str
    area: str
    required: bool
    phase: Phase


WEAPONS = {
    w.name.lower(): w for w in [
        Weapon("Saw Cleaver", (8,7,0,0), (180,0,0), (.60,.40,0,.55), "Quality", 55),
        Weapon("Saw Spear", (7,8,0,0), (170,0,0), (.50,.63,0,.62), "Quality", 55),
        Weapon("Hunter Axe", (9,8,0,0), (196,0,0), (.65,.35,0,.55), "Quality/STR", 125),
        Weapon("Threaded Cane", (7,9,0,0), (156,0,0), (.29,.90,0,.65), "SKL", 65),
        Weapon("Kirkhammer", (16,10,0,0), (210,0,0), (1.00,.29,0,.70), "STR", 120),
        Weapon("Ludwig's Holy Blade", (16,12,0,0), (200,0,0), (.80,.80,0,.88), "Quality", 110),
        Weapon("Rifle Spear", (10,11,9,0), (170,170,0), (.30,.70,.65,0), "SKL/BLT", 70),
        Weapon("Stake Driver", (18,9,0,0), (170,0,0), (.60,.55,0,.63), "Quality", 65),
        Weapon("Blade of Mercy", (7,11,0,0), (120,0,60), (0,1.10,0,.70), "SKL", 40),
        Weapon("Tonitrus", (12,8,0,0), (160,0,80), (.65,.25,0,.49), "STR/ARC", 65),
        Weapon("Chikage", (10,14,12,0), (184,184,0), (.25,.65,1.10,0), "BLT", 60),
        Weapon("Reiterpallasch", (8,12,10,0), (150,150,0), (.20,1.00,.40,0), "SKL/BLT", 80),
        Weapon("Logarius' Wheel", (20,12,0,10), (200,0,50), (1.10,0,0,.60), "STR/ARC", 50),
        Weapon("Burial Blade", (10,12,0,0), (160,0,60), (.30,.75,0,.70), "SKL", 80),
        Weapon("Beast Claw", (14,12,0,0), (150,0,0), (.60,.35,0,.52), "Quality", 35),
        Weapon("Beasthunter Saif", (9,11,0,0), (180,0,0), (.30,.70,0,.55), "SKL", 50),
        Weapon("Beast Cutter", (11,9,0,0), (184,0,0), (.60,.30,0,.49), "Quality/STR", 50),
        Weapon("Church Pick", (9,14,0,0), (176,0,0), (.40,.70,0,.60), "Quality/SKL", 80),
        Weapon("Holy Moonlight Sword", (16,12,0,14), (180,0,100), (.80,.60,0,.49), "Quality/ARC", 110),
        Weapon("Simon's Bowblade", (8,15,9,0), (160,160,0), (0,1.10,1.10,0), "SKL/BLT", 55),
        Weapon("Rakuyo", (10,20,0,0), (164,0,0), (0,1.00,0,.55), "SKL", 60),
        Weapon("Boom Hammer", (14,8,0,0), (180,0,120), (.90,.25,0,.63), "STR", 65),
        Weapon("Whirligig Saw", (18,12,0,0), (190,0,0), (1.10,.30,0,.77), "STR", 120),
        Weapon("Bloodletter", (14,6,16,0), (180,180,0), (1.00,0,1.10,0), "STR/BLT", 80),
        Weapon("Amygdalan Arm", (17,9,0,0), (160,0,80), (.90,.25,0,.63), "STR/ARC", 100),
        Weapon("Kos Parasite", (0,0,0,20), (60,0,60), (0,0,0,1.60), "ARC", 30),
    ]
}

STARTER_WEAPON_NAMES = frozenset({"Saw Cleaver", "Hunter Axe", "Threaded Cane"})


UPGRADES = {1:("Blood Stone Shard",3),2:("Blood Stone Shard",5),3:("Blood Stone Shard",8),4:("Twin Blood Stone Shards",3),5:("Twin Blood Stone Shards",5),6:("Twin Blood Stone Shards",8),7:("Blood Stone Chunk",3),8:("Blood Stone Chunk",5),9:("Blood Stone Chunk",8),10:("Blood Rock",1)}

INSIGHT = [
    "1 Insight: leveling is enabled.",
    "Hold Madman's Knowledge in inventory until you need Insight; inventory is safe.",
    "Above 15 Insight: enemies/world can become harsher. Spending down can make play smoother.",
    "Spend Insight on consumables/materials/gear you can already see in the shop; avoid hoarding at 40+ unless you want difficulty.",
]

RUNES = {
    "Moon": "More echoes. Excellent default while farming/progressing.",
    "Eye": "More item discovery. Situational for material/item farming.",
    "Beast": "Raises Beasthood risk/reward mechanics. Not a beginner default.",
    "Clockwise Metamorphosis": "More HP. Strong comfort rune.",
    "Anti-Clockwise Metamorphosis": "More stamina. Useful if weapon feels stamina-hungry.",
    "Communion": "More vial capacity. Good when learning bosses/routes.",
}

GEMS = [
    "+1/+3/+6 unlock weapon gem slots 1/2/3.",
    "Tempering = physical ATK up; default for STR/SKL quality builds.",
    "Use highest positive physical %/flat physical gems that fit the slot shapes.",
    "Avoid elemental gems on physical builds: they convert weapon damage and disable STR/SKL physical scaling.",
    "Replacing/removing gems is free. Experiment; do not overthink low-tier gems.",
]

FARMS = {
    "echoes": ["Equip Moon rune if available.", "Use the safest high-density route already unlocked; spend leftovers on vials/bullets.", "If enemies die in 1-2 hits, route speed beats theoretical payout."],
    "vials": ["Usually buy vials with farmed echoes instead of farming drops.", "If broke, kill large humanoid enemies on a short known route, then buy vials with echoes."],
    "twins": ["Twin Blood Stone Shards are the +4 to +6 tier.", "If shop does not sell them yet, progress/explore already-unlocked routes and loot thoroughly.", "Do not split twins across side weapons until main weapon reaches +6."],
    "chunks": ["Chunks are +7 to +9 and scarce. Main weapon first.", "Do not chunk backup weapons on first playthrough unless main is already +9."],
    "gems": ["Farm only if stuck. Otherwise slot best Tempering gems found naturally.", "Physical ATK up beats fancy effects for quality builds."],
}

AREAS: list[AreaRecord] = [
    {"id": "hunters-dream", "name": "Hunter's Dream", "phase": "start", "safe": True, "optional": False},
    {"id": "central-yharnam", "name": "Central Yharnam", "phase": "start", "safe": True, "optional": False},
    {"id": "cathedral-ward", "name": "Cathedral Ward", "phase": "evening", "safe": True, "optional": False},
    {"id": "old-yharnam", "name": "Old Yharnam", "phase": "evening", "safe": True, "optional": True},
    {"id": "healing-church-workshop", "name": "Healing Church Workshop", "phase": "evening", "safe": False, "optional": True},
    {"id": "hemwick-charnel-lane", "name": "Hemwick Charnel Lane", "phase": "night", "safe": False, "optional": True},
    {"id": "forbidden-woods", "name": "Forbidden Woods", "phase": "night", "safe": False, "optional": False},
    {"id": "byrgenwerth", "name": "Byrgenwerth", "phase": "night", "safe": False, "optional": False},
    {"id": "yahargul", "name": "Yahar'gul", "phase": "blood-moon", "safe": False, "optional": False},
    {"id": "upper-cathedral-ward", "name": "Upper Cathedral Ward", "phase": "blood-moon", "safe": False, "optional": True},
    {"id": "cainhurst", "name": "Cainhurst", "phase": "blood-moon", "safe": False, "optional": True},
    {"id": "lecture-building", "name": "Lecture Building", "phase": "nightmare", "safe": False, "optional": False},
    {"id": "nightmare-frontier", "name": "Nightmare Frontier", "phase": "nightmare", "safe": False, "optional": True},
    {"id": "nightmare-of-mensis", "name": "Nightmare of Mensis", "phase": "nightmare", "safe": False, "optional": False},
    {"id": "hypogean-gaol", "name": "Hypogean Gaol", "phase": "evening", "safe": False, "optional": True},
    {"id": "dlc", "name": "DLC route", "phase": "dlc", "safe": False, "optional": True},
]

AREA_ALIASES = {
    "dream": "hunters-dream",
    "central": "central-yharnam",
    "cathedral": "cathedral-ward",
    "old": "old-yharnam",
    "workshop": "healing-church-workshop",
    "hemwick": "hemwick-charnel-lane",
    "woods": "forbidden-woods",
    "forbidden": "forbidden-woods",
    "gaol": "hypogean-gaol",
    "jail": "hypogean-gaol",
    "yahargul": "yahargul",
    "upper": "upper-cathedral-ward",
    "cainhurst": "cainhurst",
    "lecture": "lecture-building",
    "frontier": "nightmare-frontier",
    "mensis": "nightmare-of-mensis",
    "dlc": "dlc",
}

BOSSES: list[BossRecord] = [
    {"id": "cleric-beast", "safe": "early optional beast boss", "name": "Cleric Beast", "area": "central-yharnam", "required": False, "phase": "start"},
    {"id": "father-gascoigne", "safe": "first mandatory hunter boss", "name": "Father Gascoigne", "area": "central-yharnam", "required": True, "phase": "start"},
    {"id": "blood-starved-beast", "safe": "early optional poison beast boss", "name": "Blood-starved Beast", "area": "old-yharnam", "required": False, "phase": "evening"},
    {"id": "vicar-amelia", "safe": "Cathedral Ward mandatory boss", "name": "Vicar Amelia", "area": "cathedral-ward", "required": True, "phase": "evening"},
    {"id": "witch-of-hemwick", "safe": "optional utility boss", "name": "Witch of Hemwick", "area": "hemwick-charnel-lane", "required": False, "phase": "night"},
    {"id": "shadows-of-yharnam", "safe": "midgame mandatory boss", "name": "Shadows of Yharnam", "area": "forbidden-woods", "required": True, "phase": "night"},
    {"id": "darkbeast-paarl", "safe": "optional electric beast boss", "name": "Darkbeast Paarl", "area": "hypogean-gaol", "required": False, "phase": "evening"},
    {"id": "the-one-reborn", "safe": "blood-moon mandatory boss", "name": "The One Reborn", "area": "yahargul", "required": True, "phase": "blood-moon"},
    {"id": "celestial-emissary", "safe": "late optional boss", "name": "Celestial Emissary", "area": "upper-cathedral-ward", "required": False, "phase": "blood-moon"},
    {"id": "ebrietas", "safe": "late optional boss", "name": "Ebrietas", "area": "upper-cathedral-ward", "required": False, "phase": "blood-moon"},
    {"id": "martyr-logarius", "safe": "late optional boss", "name": "Martyr Logarius", "area": "cainhurst", "required": False, "phase": "blood-moon"},
    {"id": "amygdala", "safe": "nightmare optional boss", "name": "Amygdala", "area": "nightmare-frontier", "required": False, "phase": "nightmare"},
    {"id": "micolash", "safe": "nightmare mandatory boss", "name": "Micolash", "area": "nightmare-of-mensis", "required": True, "phase": "nightmare"},
    {"id": "mergos-wet-nurse", "safe": "late mandatory boss", "name": "Mergo's Wet Nurse", "area": "nightmare-of-mensis", "required": True, "phase": "nightmare"},
]

ITEMS = {
    "Blood Gem Workshop Tool": "Unlocks Blood Gem Fortification. Use physical/Tempering gems for quality weapons.",
    "Rune Workshop Tool": "Unlocks Caryll Runes. Equip Moon for echoes, Clockwise for HP, Anti-Clockwise for stamina.",
    "Radiant Sword Hunter Badge": "Unlocks Ludwig's Holy Blade and related shop stock.",
    "Sword Hunter Badge": "Unlocks early weapon/shop stock.",
    "Cosmic Eye Watcher Badge": "Unlocks late shop stock after Upper Cathedral progress.",
    "Cainhurst Summons": "Optional route invitation used from the Hemwick obelisk.",
    "Upper Cathedral Key": "Opens the Upper Cathedral route.",
    "Tonsil Stone": "Unlocks an optional nightmare-side route.",
    "Lecture Theatre Key": "Opens Lecture Building access.",
    "Blood Rock": "Final +10 weapon material. Scarce; spend on the main weapon.",
    "Madman's Knowledge": "Consumable Insight. Hold until needed; inventory is safe.",
    "Gold Pendant": "Consume to receive a blood gem.",
    "Tear Stone": "Consume to receive a blood gem.",
}

CHECKLISTS = {
    "hunters-dream": ["Equip right-hand and left-hand weapons.", "Use workshop functions only after the relevant tool/menu appears.", "Return here to level, fortify, repair, and manage storage."],
    "central-yharnam": ["Choose main weapon/firearm.", "Open shortcuts before pushing bosses.", "Upgrade main weapon to +2/+3 when materials allow.", "Practice parry on large humanoids."],
    "cathedral-ward": ["Use the workshop: fortify weapon, slot Tempering gems, repair only when warned.", "Prioritize VIT/END baseline before damage stats.", "Open gates/shortcuts before boss attempts."],
    "old-yharnam": ["Bring antidotes.", "Use short safe farming loops if vial/antidote-starved.", "Fire/serrated pressure helps beasts.", "Finish the area before over-investing in side weapons."],
    "hypogean-gaol": ["Optional side route.", "Open shortcuts before committing.", "Electric beast route links back to Old Yharnam."],
    "hemwick-charnel-lane": ["Clear for the rune tool if not already done.", "After getting the tool, equip Moon/Clockwise/Anti-Clockwise as needed.", "Use the obelisk route only if carrying Cainhurst Summons."],
    "forbidden-woods": ["Keep weapon at +6 or better if possible.", "Unlock shortcuts aggressively.", "Do not dump points into BLT/ARC on quality unless meeting a specific requirement."],
    "byrgenwerth": ["Expect a world-state gate.", "Before triggering major progress, spend Insight if current enemies feel overtuned."],
    "yahargul": ["Clear side cells and shortcuts.", "Check for late upgrade materials.", "After boss, treat the area as done unless chasing specific loot."],
    "upper-cathedral-ward": ["Use frenzy/bolt caution.", "Clear both bosses if doing optional completion.", "Cosmic Eye Watcher Badge is the key shop unlock."],
    "lecture-building": ["Clear both floors.", "Use dense enemies as an echo farm if safe.", "Touch both nightmare entry lamps before committing."],
    "cainhurst": ["Optional, harder route.", "Good before late nightmares if your weapon is +8/+9.", "Proceed from Hemwick obelisk with Cainhurst Summons."],
    "nightmare-frontier": ["Optional nightmare route.", "Bring poison/frenzy awareness.", "Do after lower-level optional routes if minmaxing."],
    "nightmare-of-mensis": ["Main late route.", "Aim to collect Blood Rock before final +10.", "Spend Insight down if frenzy pressure is obnoxious."],
    "dlc": ["Optional high-difficulty route.", "Delay until the main weapon and stats feel stable.", "Use explicit spoiler permission before asking for exact area/boss names."],
}

BUILD_ARCHETYPES = {
    "quality": ["Origin: Military Veteran.", "Starter-safe weapons: Saw Cleaver, Ludwig's Holy Blade.", "Targets: VIT 30-40, END 15-20, STR 25, SKL 25, then STR/SKL toward 50.", "Gems: Tempering physical."],
    "strength": ["Origin: Violent Past.", "Targets: VIT 30-40, END 15-20, STR 25 then 50, SKL only for requirements.", "Gems: Tempering/Adept only when you understand moveset damage types."],
    "skill": ["Origin: Professional.", "Targets: VIT 30-40, END 15-20, SKL 25 then 50, STR only for requirements.", "Bonus: stronger viscerals."],
    "bloodtinge": ["Origin: Noble Scion.", "Not beginner-default. BLT 25/50 only if using blood weapons/firearm scaling."],
    "arcane": ["Origin: Cruel Fate.", "Not quality-default. ARC 25/50 for converted weapons; tools keep scaling high."],
}


def sat(stat: int) -> float:
    if stat <= SAT_POINTS[0][0]:
        return SAT_POINTS[0][1]
    for (a, av), (b, bv) in zip(SAT_POINTS, SAT_POINTS[1:]):
        if stat <= b:
            return av + (bv - av) * ((stat - a) / (b - a))
    return SAT_POINTS[-1][1]


def find_weapon(name: str) -> Weapon:
    key = name.lower().strip()
    if key in WEAPONS:
        return WEAPONS[key]
    matches = [w for k, w in WEAPONS.items() if key in k]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise SystemExit("Ambiguous weapon: " + ", ".join(w.name for w in matches))
    raise SystemExit(f"Unknown weapon: {name}")


def ar(w: Weapon, stats: tuple[int, int, int, int]) -> int:
    str_, skl, blt, arc_ = stats
    sats = (sat(str_), sat(skl), sat(blt), sat(arc_))
    total = 0.0
    # physical, blood, arcane buckets use relevant scalings.
    for base in w.base:
        if base:
            total += base * (1 + sum(s * c for s, c in zip(sats, w.scaling)))
    return round(total)


def echo_cost(current: int, target: int) -> int:
    def cost(lvl: int) -> float:
        return 0.02 * lvl**3 + 3.06 * lvl**2 + 105.6 * lvl - 895
    return max(0, round(sum(cost(l) for l in range(current, target))))


def tracking_path(path: str | None) -> Path | None:
    selected = path or os.environ.get("BLOODBORNE_TRACKING_FILE")
    if not selected:
        return None
    p = Path(selected).expanduser()
    return p if p.exists() else None


def read_tracking(path: str | None = None) -> str:
    p = tracking_path(path)
    if not p:
        raise SystemExit("Tracking file not found. Pass --path or set BLOODBORNE_TRACKING_FILE.")
    return p.read_text(encoding="utf-8")


def extract_stats(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    aliases = {"vit":"VIT", "vitality":"VIT", "end":"END", "endurance":"END", "str":"STR", "strength":"STR", "skl":"SKL", "skill":"SKL", "skills":"SKL", "blt":"BLT", "blood":"BLT", "bloodtinge":"BLT", "arc":"ARC", "arcane":"ARC", "level":"LVL", "lvl":"LVL", "insight":"Insight"}
    for line in text.splitlines():
        clean = re.sub(r"[*`|:-]", " ", line).strip()
        m = re.match(r"([A-Za-z ]+?)\s+(\d{1,3})\b", clean)
        if not m:
            continue
        k = aliases.get(m.group(1).strip().lower())
        if k:
            out[k] = int(m.group(2))
    # Also catch compact stat row: VIT 30 | END 17 ...
    for k, v in re.findall(r"\b(VIT|END|STR|SKL|BLT|ARC|LVL|Insight)\b\s*[:=]?\s*(\d{1,3})", text, re.I):
        out[aliases.get(k.lower(), k.upper())] = int(v)
    return out


def extract_gear(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        if re.search(r"\+\d|Saw Cleaver|Ludwig|Pistol|Sprayer|Hunter Axe|Threaded Cane", line, re.I):
            lines.append(line.strip(" -|"))
    return lines[:8]


def print_bullets(title: str, items: Iterable[str]) -> None:
    print(title)
    for item in items:
        print(f"- {item}")


def cache_root() -> Path:
    root = CACHE_DIR / "sources"
    root.mkdir(parents=True, exist_ok=True)
    return root


def source_paths(key: str) -> tuple[Path, Path]:
    slug = re.sub(r"[^a-z0-9_.-]+", "-", key.lower()).strip("-")
    digest = hashlib.sha256(SOURCES[key]["url"].encode("utf-8")).hexdigest()[:10]
    base = cache_root() / f"{slug}-{digest}"
    return base.with_suffix(".html"), base.with_suffix(".json")


def cache_meta(key: str) -> dict[str, object] | None:
    _, meta_path = source_paths(key)
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def cache_age_hours(meta: dict[str, object] | None) -> float | None:
    if not meta or not isinstance(meta.get("fetched_at_epoch"), (int, float)):
        return None
    return (time.time() - float(meta["fetched_at_epoch"])) / 3600


def fetch_source(key: str, force: bool = False) -> dict[str, object]:
    html_path, meta_path = source_paths(key)
    src = SOURCES[key]
    old = cache_meta(key)
    age = cache_age_hours(old)
    if html_path.exists() and old and age is not None and age < CACHE_TTL_HOURS and not force:
        return {**old, "status": "fresh-cache"}

    req = urllib.request.Request(
        str(src["url"]),
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        body = response.read()
        final_url = response.geturl()
        content_type = response.headers.get("content-type", "")
    html_path.write_bytes(body)
    meta = {
        "key": key,
        "url": src["url"],
        "final_url": final_url,
        "license": src["license"],
        "use": src["use"],
        "risk": src["risk"],
        "machine_readable": src["machine"],
        "fetched_at_epoch": time.time(),
        "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ttl_hours": CACHE_TTL_HOURS,
        "content_type": content_type,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "path": str(html_path),
        "status": "refreshed",
    }
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return meta


def source_keys(requested: list[str] | None) -> list[str]:
    if not requested:
        return list(SOURCES)
    unknown = [k for k in requested if k not in SOURCES]
    if unknown:
        raise SystemExit("Unknown source(s): " + ", ".join(unknown))
    return requested


def cmd_sources(args: argparse.Namespace) -> None:
    keys = source_keys(args.keys)
    if args.action == "list":
        for key in keys:
            src = SOURCES[key]
            print(f"{key}: {src['url']}")
            print(f"  license: {src['license']}")
            print(f"  use: {src['use']}")
            print(f"  risk: {src['risk']}")
        return
    if args.action == "status":
        for key in keys:
            meta = cache_meta(key)
            age = cache_age_hours(meta)
            state = "missing" if age is None else ("fresh" if age < CACHE_TTL_HOURS else "stale")
            suffix = "" if age is None else f", age {age:.1f}h, sha256 {str(meta.get('sha256', ''))[:12]}"
            print(f"{key}: {state}{suffix}")
        return
    if args.action == "refresh":
        for key in keys:
            meta = fetch_source(key, force=args.force)
            print(f"{key}: {meta['status']}, {meta['bytes']} bytes, {meta['fetched_at_utc']}, {meta['path']}")


def cmd_fresh(_: argparse.Namespace) -> None:
    print(f"Data source: {DATA_SOURCE}")
    print(f"Updated: {UPDATED}")
    print(f"Cache policy: refresh live research notes every {CACHE_TTL_HOURS}h when a question depends on external/source freshness.")
    print(f"Sources registered: {len(SOURCES)}")
    print(f"Cache dir: {CACHE_DIR}")


def cmd_softcaps(_: argparse.Namespace) -> None:
    print_bullets("Softcaps", (f"{k}: {v}" for k, v in SOFTCAPS.items()))


def cmd_origins(args: argparse.Namespace) -> None:
    rows = ORIGINS.items()
    filt = (args.filter or "").lower()
    if filt:
        rows = [(k, v) for k, v in rows if filt in k or filt in v[-1].lower()]
    for name, (lvl, vit, end, str_, skl, blt, arc_, best) in rows:
        print(f"{name.title()}: LVL {lvl}, VIT {vit}, END {end}, STR {str_}, SKL {skl}, BLT {blt}, ARC {arc_} — {best}")


def cmd_upgrade(args: argparse.Namespace) -> None:
    target = args.level
    if not 1 <= target <= 10:
        raise SystemExit("level must be 1..10")
    totals: dict[str, int] = {}
    for lvl in range(1, target + 1):
        mat, qty = UPGRADES[lvl]
        totals[mat] = totals.get(mat, 0) + qty
        print(f"+{lvl}: {qty} {mat}")
    print("Totals: " + ", ".join(f"{qty} {mat}" for mat, qty in totals.items()))


def cmd_weapons(args: argparse.Namespace) -> None:
    if args.name:
        w = find_weapon(" ".join(args.name))
        print(f"{w.name}: req STR/SKL/BLT/ARC {w.req}; +10 atk phys/blood/element {w.base}; scaling {w.scaling}; style {w.style}; rally {w.rally}")
        return
    rows = WEAPONS.values() if getattr(args, "spoilers", False) else [w for w in WEAPONS.values() if w.name in STARTER_WEAPON_NAMES]
    for w in rows:
        print(f"{w.name}: {w.style}, req {w.req}")


def cmd_calc(args: argparse.Namespace) -> None:
    w = find_weapon(args.weapon)
    stats = (args.str, args.skl, args.blt, args.arc)
    print(f"{w.name} +10 AR estimate at STR/SKL/BLT/ARC {stats}: {ar(w, stats)}")


def cmd_echo_cost(args: argparse.Namespace) -> None:
    print(echo_cost(args.current, args.target))


def cmd_insight(args: argparse.Namespace) -> None:
    items = list(INSIGHT)
    if args.current is not None:
        if args.current >= 40:
            items.insert(0, f"Current {args.current}: high. Spend some if you want a smoother run.")
        elif args.current > 15:
            items.insert(0, f"Current {args.current}: above difficulty threshold; spend if struggling.")
        else:
            items.insert(0, f"Current {args.current}: normal/low. Fine to hold.")
    print_bullets("Insight", items)


def cmd_runes(_: argparse.Namespace) -> None:
    print_bullets("Runes", (f"{k}: {v}" for k, v in RUNES.items()))


def cmd_gems(_: argparse.Namespace) -> None:
    print_bullets("Blood gems", GEMS)


def cmd_farm(args: argparse.Namespace) -> None:
    print_bullets(f"Farm: {args.kind}", FARMS[args.kind])


def cmd_track(args: argparse.Namespace) -> None:
    text = read_tracking(args.path)
    stats = extract_stats(text)
    if args.section in ("summary", "stats"):
        wanted = ["LVL", "Insight", "VIT", "END", "STR", "SKL", "BLT", "ARC"]
        print("Stats: " + ", ".join(f"{k} {stats[k]}" for k in wanted if k in stats))
    if args.section in ("summary", "gear"):
        gear = extract_gear(text)
        print_bullets("Gear", gear or ["No gear parsed."])
    if args.section == "next":
        cmd_recommend(args)


def cmd_recommend(args: argparse.Namespace) -> None:
    text = read_tracking(getattr(args, "path", None))
    s = extract_stats(text)
    vit, end, str_, skl, blt, arc_ = (s.get(k, 0) for k in ("VIT", "END", "STR", "SKL", "BLT", "ARC"))
    recs = []
    if vit and vit < 30:
        recs.append("Level VIT toward 30 first if dying fast.")
    elif end and end < 15:
        recs.append("Bring END to 15, then stop for a while.")
    elif str_ < 25:
        recs.append("Push STR to 25 for quality weapon efficiency.")
    elif skl < 25:
        recs.append("Push SKL to 25 next; helps quality AR and viscerals.")
    elif vit < 40:
        recs.append("Next comfort target: VIT 40.")
    else:
        recs.append("Damage target: STR/SKL toward 50/50, main weapon upgrades first.")
    if blt and blt > 7:
        recs.append("BLT was raised; only continue if committing to blood weapons/firearm damage.")
    if arc_ and arc_ <= 8:
        recs.append("ARC 8 is only for basic tool/Flame Sprayer access; do not keep leveling ARC for a physical quality build.")
    recs.append("Upgrade priority: main weapon first; backup only after main hits current material ceiling.")
    recs.append("Supply rule: farm echoes, then buy vials/bullets; do not rely on vial drops unless broke.")
    print_bullets("Recommendation", recs)


def print_entries(title: str, entries: Iterable[object]) -> None:
    rows = list(entries)
    if not rows:
        return
    print(title)
    for entry in rows:
        print(f"  {entry.name}: {entry.amount}")


SAVE_INVENTORY_SECTIONS = frozenset({"summary", "materials", "weapons", "keys"})
SAVE_BOSS_SECTIONS = frozenset({"summary", "bosses"})


def _upgrade_sort_key(entry: object) -> tuple[int, str, str]:
    location = getattr(entry, "location")
    return (0 if location == "equipped" else 1, location, getattr(entry, "name"))


def print_save_runes(path: str) -> None:
    rows = sorted(read_runes(path), key=_upgrade_sort_key)
    print("Runes")
    if not rows:
        print("  None found")
        return
    for entry in rows:
        tier = f"tier {entry.rating}" if entry.rating else "tier 0"
        effect = f": {entry.effect_desc}" if entry.effect_desc else ""
        print(f"  [{entry.location}] {entry.name} ({tier}){effect}")


def print_save_gems(path: str) -> None:
    rows = sorted(read_gems(path), key=_upgrade_sort_key)
    counts: dict[str, int] = {}
    for entry in rows:
        counts[entry.shape] = counts.get(entry.shape, 0) + 1
    print("Blood gems")
    if counts:
        print("  Owned by type: " + ", ".join(f"{shape} {count}" for shape, count in sorted(counts.items())))
    else:
        print("  None found")
        return
    equipped = [entry for entry in rows if entry.location == "equipped"]
    if equipped:
        print("  Equipped gems")
        for entry in equipped:
            tier = f"tier {entry.rating}" if entry.rating else "tier 0"
            effect = f": {entry.effect_desc}" if entry.effect_desc else ""
            print(f"    {entry.shape} {entry.name} ({tier}){effect}")


def cmd_save(args: argparse.Namespace) -> None:
    save_path = args.path
    if args.section == "runes":
        print_save_runes(save_path)
        return

    if args.section == "gems":
        print_save_gems(save_path)
        return

    stats = read_stats(save_path)
    print("Save stats")
    print(
        "  "
        + ", ".join(
            f"{name} {stats[name]}"
            for name in ("Level", "Health", "Stamina", "Echoes", "Insight", "Vitality", "Endurance", "Strength", "Skill", "Bloodtinge", "Arcane", "Ng")
            if name in stats
        )
    )

    entries = read_inventory(save_path) if args.section in SAVE_INVENTORY_SECTIONS else []

    if args.section in ("summary", "materials"):
        print_entries("Materials", materials(entries))

    if args.section in ("summary", "keys"):
        print_entries("Important key items", important_key_items(entries))

    if args.section in ("summary", "weapons"):
        entries = read_inventory(save_path)
        wr = weapon_reinforcement(entries)
        weapon_rows = save_weapons(entries)
        if weapon_rows:
            print("Weapons")
            for w in sorted(weapon_rows, key=lambda e: e.name):
                level = wr.get(w.name)
                level_str = f" +{level}" if level is not None and level > 0 else ""
                print(f"  {w.name}{level_str}: {w.amount}")
    if args.section in SAVE_BOSS_SECTIONS:
        bosses = read_bosses(save_path)
        known = [boss for boss in bosses if boss.known and boss.defeated]
        unknown_defeated = sum(1 for boss in bosses if not boss.known and boss.defeated)
        if known:
            print("Known defeated bosses")
            for boss in known:
                print(f"  {safe_boss_name(boss.name)}")
        print(f"Unknown future bosses defeated: {unknown_defeated}")



def consistency_issues(check_sources: bool = False) -> list[str]:
    issues: list[str] = []
    source_required = {"url", "license", "use", "machine", "risk"}
    for key, src in SOURCES.items():
        missing = source_required - set(src)
        if missing:
            issues.append(f"source {key} missing fields: {', '.join(sorted(missing))}")
        if not re.fullmatch(r"[a-z0-9_.-]+", key):
            issues.append(f"source {key} has non-slug key")
    source_scaling = {
        "saw cleaver": (.60, .40, 0, .55),
        "ludwig's holy blade": (.80, .80, 0, .88),
        "beast claw": (.60, .35, 0, .52),
        "holy moonlight sword": (.80, .60, 0, .49),
    }
    for key, expected in source_scaling.items():
        actual = WEAPONS[key].scaling
        if actual != expected:
            issues.append(f"weapon scaling mismatch for {WEAPONS[key].name}: {actual} != {expected}")
    source_saturation = {15: .200, 20: .350, 25: .500, 30: .570, 40: .710, 50: .850, 99: 1.000}
    sat_by_level = dict(SAT_POINTS)
    for level, expected in source_saturation.items():
        actual = sat_by_level.get(level)
        if actual != expected:
            issues.append(f"saturation mismatch at {level}: {actual} != {expected}")
    if len(WEAPONS) != 26:
        issues.append(f"weapon catalog expected 26 trick weapons, got {len(WEAPONS)}")
    expected_upgrade_totals = {
        "Blood Stone Shard": 16,
        "Twin Blood Stone Shards": 16,
        "Blood Stone Chunk": 16,
        "Blood Rock": 1,
    }
    totals: dict[str, int] = {}
    for material, quantity in UPGRADES.values():
        totals[material] = totals.get(material, 0) + quantity
    if totals != expected_upgrade_totals:
        issues.append(f"upgrade totals mismatch: {totals}")
    area_ids = {area["id"] for area in AREAS}
    for alias, target in AREA_ALIASES.items():
        if target not in area_ids:
            issues.append(f"area alias {alias} points to unknown area {target}")
    for boss in BOSSES:
        if boss["area"] not in area_ids:
            issues.append(f"boss {boss['id']} points to unknown area {boss['area']}")
        area_phase = next(area["phase"] for area in AREAS if area["id"] == boss["area"])
        if boss["phase"] != area_phase:
            issues.append(f"boss {boss['id']} phase {boss['phase']} differs from area phase {area_phase}")
    for checklist_area in CHECKLISTS:
        if checklist_area not in area_ids:
            issues.append(f"checklist points to unknown area {checklist_area}")
    for style, lines in BUILD_ARCHETYPES.items():
        joined = " ".join(lines)
        if style in {"quality", "strength", "skill"} and "VIT 30-40" not in joined:
            issues.append(f"build {style} missing VIT baseline")
    if check_sources:
        for key in SOURCES:
            meta = cache_meta(key)
            age = cache_age_hours(meta)
            if age is None:
                issues.append(f"source cache {key} missing")
            elif age >= CACHE_TTL_HOURS:
                issues.append(f"source cache {key} stale: {age:.1f}h")
    return issues


def cmd_audit(args: argparse.Namespace) -> None:
    issues = consistency_issues(check_sources=args.sources)
    if issues:
        print_bullets("Consistency issues", issues)
        raise SystemExit(1)
    suffix = " + fresh source cache" if args.sources else ""
    print(f"Consistency audit OK{suffix}.")



def boss_name(record: BossRecord, spoilers: bool) -> str:
    return record["name"] if spoilers else record["safe"]


def area_name(record: AreaRecord, spoilers: bool) -> str:
    if spoilers or record["safe"]:
        return record["name"]
    route_kind = "optional" if record["optional"] else "main"
    return f"{record['phase']} {route_kind} route"


def area_id(text: str) -> str:
    key = text.lower().strip().replace("_", "-")
    if key in {str(a["id"]) for a in AREAS}:
        return key
    if key in AREA_ALIASES:
        return AREA_ALIASES[key]
    for area in AREAS:
        name = str(area["name"]).lower()
        if key in name or name.replace("'", "").replace(" ", "-") == key:
            return str(area["id"])
    raise SystemExit(f"Unknown area: {text}")


def cmd_areas(args: argparse.Namespace) -> None:
    rows = AREAS if args.spoilers else [a for a in AREAS if a["safe"] or args.phase]
    print("Areas")
    hidden_index = 1
    for area in rows:
        if args.phase and area["phase"] != args.phase:
            continue
        opt = "optional" if area["optional"] else "main"
        ident = area["id"] if args.spoilers or area["safe"] else f"hidden-{hidden_index}"
        if ident.startswith("hidden-"):
            hidden_index += 1
        print(f"- {ident}: {area_name(area, args.spoilers)} ({area['phase']}, {opt})")


def cmd_bosses(args: argparse.Namespace) -> None:
    rows = [b for b in BOSSES if not args.required or b["required"]]
    print("Bosses")
    hidden_index = 1
    areas_by_id = {area["id"]: area for area in AREAS}
    for boss in rows:
        if args.area and boss["area"] != area_id(args.area):
            continue
        area = areas_by_id[boss["area"]]
        introduced = bool(args.area)
        ident = boss["id"] if args.spoilers or introduced else f"hidden-{hidden_index}"
        if ident.startswith("hidden-"):
            hidden_index += 1
        area_label = area["id"] if args.spoilers or introduced or area["safe"] else area_name(area, False)
        print(f"- {ident}: {boss_name(boss, args.spoilers or introduced)}; area {area_label}; {'required' if boss['required'] else 'optional'}")


def cmd_items(args: argparse.Namespace) -> None:
    if not args.query and not args.spoilers:
        raise SystemExit("Provide an item query, or pass --spoilers to list all indexed items.")
    q = " ".join(args.query).lower()
    rows = [(name, text) for name, text in ITEMS.items() if not q or q in name.lower() or q in text.lower()]
    if not rows:
        raise SystemExit("No item match.")
    print("Items")
    for name, text in rows:
        print(f"- {name}: {text}")


def cmd_checklist(args: argparse.Namespace) -> None:
    aid = area_id(args.area)
    items = CHECKLISTS.get(aid)
    if not items:
        raise SystemExit(f"No checklist for area: {aid}")
    print_bullets(f"Checklist: {aid}", items)


def cmd_build(args: argparse.Namespace) -> None:
    key = args.style.lower()
    if key not in BUILD_ARCHETYPES:
        raise SystemExit(f"Unknown build style: {args.style}")
    items = list(BUILD_ARCHETYPES[key])
    if args.level:
        items.append(f"Level {args.level}: obey softcaps; weapon upgrades beat damage stats until requirements/25 caps.")
    print_bullets(f"Build: {key}", items)


def cmd_compare(args: argparse.Namespace) -> None:
    stats = (args.str, args.skl, args.blt, args.arc)
    rows = []
    for name in args.weapons:
        weapon = find_weapon(name)
        rows.append((ar(weapon, stats), weapon.name, weapon.req, weapon.style))
    rows.sort(reverse=True)
    print(f"Compare at STR/SKL/BLT/ARC {stats}")
    for value, name, req, style in rows:
        print(f"- {name}: AR {value}; req {req}; {style}")


def cmd_route(args: argparse.Namespace) -> None:
    defeated = {x.strip().lower().replace("_", "-") for x in args.defeated.split(",") if x.strip()}
    required = [b for b in BOSSES if b["required"]]
    next_boss = next((b for b in required if b["id"] not in defeated), None)
    if next_boss:
        name = boss_name(next_boss, args.spoilers)
        area = next_boss["area"] if args.spoilers else "current main route"
        print(f"Next required pressure point: {name} ({area}).")
    else:
        print("Required boss list exhausted in this lightweight route table.")
    print("Safe optional check before late push: Hemwick/rune tool, Cainhurst invitation route, Upper Cathedral route, main weapon upgrades.")
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bloodborne spoiler-safe companion CLI")
    sub = p.add_subparsers(required=True)
    for name, fn in [("fresh", cmd_fresh), ("softcaps", cmd_softcaps), ("runes", cmd_runes), ("gems", cmd_gems)]:
        sp = sub.add_parser(name); sp.set_defaults(func=fn)
    sp = sub.add_parser("recommend"); sp.add_argument("--path"); sp.set_defaults(func=cmd_recommend)
    sp = sub.add_parser("origins"); sp.add_argument("filter", nargs="?"); sp.set_defaults(func=cmd_origins)
    sp = sub.add_parser("upgrade"); sp.add_argument("level", type=int); sp.set_defaults(func=cmd_upgrade)
    sp = sub.add_parser("weapons"); sp.add_argument("name", nargs="*"); sp.add_argument("--spoilers", action="store_true"); sp.set_defaults(func=cmd_weapons)
    sp = sub.add_parser("calc"); sp.add_argument("weapon"); sp.add_argument("str", type=int); sp.add_argument("skl", type=int); sp.add_argument("blt", type=int); sp.add_argument("arc", type=int); sp.set_defaults(func=cmd_calc)
    sp = sub.add_parser("compare"); sp.add_argument("weapons", nargs="+"); sp.add_argument("--str", type=int, required=True); sp.add_argument("--skl", type=int, required=True); sp.add_argument("--blt", type=int, default=0); sp.add_argument("--arc", type=int, default=0); sp.set_defaults(func=cmd_compare)
    sp = sub.add_parser("echo-cost"); sp.add_argument("current", type=int); sp.add_argument("target", type=int); sp.set_defaults(func=cmd_echo_cost)
    sp = sub.add_parser("insight"); sp.add_argument("current", nargs="?", type=int); sp.set_defaults(func=cmd_insight)
    sp = sub.add_parser("farm"); sp.add_argument("kind", choices=sorted(FARMS)); sp.set_defaults(func=cmd_farm)
    sp = sub.add_parser("build"); sp.add_argument("style", choices=sorted(BUILD_ARCHETYPES)); sp.add_argument("--level", type=int); sp.set_defaults(func=cmd_build)
    sp = sub.add_parser("areas"); sp.add_argument("--phase", choices=["start", "evening", "night", "blood-moon", "nightmare", "dlc"]); sp.add_argument("--spoilers", action="store_true"); sp.set_defaults(func=cmd_areas)
    sp = sub.add_parser("bosses"); sp.add_argument("--area"); sp.add_argument("--required", action="store_true"); sp.add_argument("--spoilers", action="store_true"); sp.set_defaults(func=cmd_bosses)
    sp = sub.add_parser("items"); sp.add_argument("query", nargs="*"); sp.add_argument("--spoilers", action="store_true"); sp.set_defaults(func=cmd_items)
    sp = sub.add_parser("checklist"); sp.add_argument("area"); sp.add_argument("--spoilers", action="store_true"); sp.set_defaults(func=cmd_checklist)
    sp = sub.add_parser("route"); sp.add_argument("--defeated", default=""); sp.add_argument("--spoilers", action="store_true"); sp.set_defaults(func=cmd_route)
    sp = sub.add_parser("audit"); sp.add_argument("--sources", action="store_true"); sp.set_defaults(func=cmd_audit)
    sp = sub.add_parser("track"); sp.add_argument("section", nargs="?", choices=["summary", "stats", "gear", "next"], default="summary"); sp.add_argument("--path"); sp.set_defaults(func=cmd_track)
    sp = sub.add_parser("sources"); sp.add_argument("action", choices=["list", "status", "refresh"]); sp.add_argument("keys", nargs="*"); sp.add_argument("--force", action="store_true"); sp.set_defaults(func=cmd_sources)
    sp = sub.add_parser("save"); sp.add_argument("path"); sp.add_argument("section", nargs="?", choices=["summary", "stats", "materials", "weapons", "keys", "bosses", "runes", "gems"], default="summary"); sp.set_defaults(func=cmd_save)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
