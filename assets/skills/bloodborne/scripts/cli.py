#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Spoiler-safe Bloodborne lookup CLI for agents.

Stateless: stores no player progress. When run in a workspace with tracking.md,
read-only commands can summarize that local state.
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
from typing import Iterable

CACHE_TTL_HOURS = 24
DATA_SOURCE = "Embedded spoiler-safe constants plus source registry/cache for live verification."
UPDATED = "2026-06-14"
CACHE_ENV = "BLOODBORNE_CACHE_DIR"
CACHE_DIR = Path(os.environ.get(CACHE_ENV, "~/.cache/bloodborne-companion")).expanduser()

SOURCES = {
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

SAT_POINTS = [(10, .05), (15, .12), (20, .20), (25, .35), (30, .45), (35, .55), (40, .65), (45, .75), (50, .85), (60, .90), (70, .94), (80, .97), (99, 1.00)]

@dataclass(frozen=True)
class Weapon:
    name: str
    req: tuple[int, int, int, int]
    base: tuple[int, int, int]
    scaling: tuple[float, float, float, float]
    style: str
    rally: int

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
        Weapon("Beast Claw", (14,12,0,0), (150,0,0), (.62,.34,0,.52), "Quality", 35),
        Weapon("Beasthunter Saif", (9,11,0,0), (180,0,0), (.30,.70,0,.55), "SKL", 50),
        Weapon("Beast Cutter", (11,9,0,0), (184,0,0), (.60,.30,0,.49), "Quality/STR", 50),
        Weapon("Church Pick", (9,14,0,0), (176,0,0), (.40,.70,0,.60), "Quality/SKL", 80),
        Weapon("Holy Moonlight Sword", (16,12,0,14), (180,0,100), (.80,.60,0,1.00), "Quality/ARC", 110),
        Weapon("Simon's Bowblade", (8,15,9,0), (160,160,0), (0,1.10,1.10,0), "SKL/BLT", 55),
        Weapon("Rakuyo", (10,20,0,0), (164,0,0), (0,1.00,0,.55), "SKL", 60),
        Weapon("Boom Hammer", (14,8,0,0), (180,0,120), (.90,.25,0,.63), "STR", 65),
        Weapon("Whirligig Saw", (18,12,0,0), (190,0,0), (1.10,.30,0,.77), "STR", 120),
        Weapon("Bloodletter", (14,6,16,0), (180,180,0), (1.00,0,1.10,0), "STR/BLT", 80),
        Weapon("Amygdalan Arm", (17,9,0,0), (160,0,80), (.90,.25,0,.63), "STR/ARC", 100),
        Weapon("Kos Parasite", (0,0,0,20), (60,0,60), (0,0,0,1.60), "ARC", 30),
    ]
}

UPGRADES = {1:("Blood Stone Shard",3),2:("Blood Stone Shard",5),3:("Blood Stone Shard",8),4:("Twin Blood Stone Shard",3),5:("Twin Blood Stone Shard",5),6:("Twin Blood Stone Shard",8),7:("Blood Stone Chunk",3),8:("Blood Stone Chunk",5),9:("Blood Stone Chunk",8),10:("Blood Rock",1)}

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
    p = Path(path or "tracking.md")
    return p if p.exists() else None


def read_tracking(path: str | None = None) -> str:
    p = tracking_path(path)
    if not p:
        raise SystemExit("No tracking.md found in this workspace.")
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
        print(f"{w.name}: req STR/SKL/BLT/ARC {w.req}; base phys/blood/arc {w.base}; scaling {w.scaling}; style {w.style}; rally {w.rally}")
        return
    for w in WEAPONS.values():
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bloodborne spoiler-safe companion CLI")
    sub = p.add_subparsers(required=True)
    for name, fn in [("fresh", cmd_fresh), ("softcaps", cmd_softcaps), ("runes", cmd_runes), ("gems", cmd_gems), ("recommend", cmd_recommend)]:
        sp = sub.add_parser(name); sp.set_defaults(func=fn)
        if name == "recommend": sp.add_argument("--path")
    sp = sub.add_parser("origins"); sp.add_argument("filter", nargs="?"); sp.set_defaults(func=cmd_origins)
    sp = sub.add_parser("upgrade"); sp.add_argument("level", type=int); sp.set_defaults(func=cmd_upgrade)
    sp = sub.add_parser("weapons"); sp.add_argument("name", nargs="*"); sp.set_defaults(func=cmd_weapons)
    sp = sub.add_parser("calc"); sp.add_argument("weapon"); sp.add_argument("str", type=int); sp.add_argument("skl", type=int); sp.add_argument("blt", type=int); sp.add_argument("arc", type=int); sp.set_defaults(func=cmd_calc)
    sp = sub.add_parser("echo-cost"); sp.add_argument("current", type=int); sp.add_argument("target", type=int); sp.set_defaults(func=cmd_echo_cost)
    sp = sub.add_parser("insight"); sp.add_argument("current", nargs="?", type=int); sp.set_defaults(func=cmd_insight)
    sp = sub.add_parser("farm"); sp.add_argument("kind", choices=sorted(FARMS)); sp.set_defaults(func=cmd_farm)
    sp = sub.add_parser("track"); sp.add_argument("section", nargs="?", choices=["summary", "stats", "gear", "next"], default="summary"); sp.add_argument("--path"); sp.set_defaults(func=cmd_track)
    sp = sub.add_parser("sources"); sp.add_argument("action", choices=["list", "status", "refresh"]); sp.add_argument("keys", nargs="*"); sp.add_argument("--force", action="store_true"); sp.set_defaults(func=cmd_sources)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
