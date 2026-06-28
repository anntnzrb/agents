#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pycryptodome"]
# ///

"""Spoiler-safe Dark Souls 3 lookup CLI for agents.

Stateless: stores no player progress. Tracking requires an explicit path argument.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from cli_catalog import *
from ds3_catalog import *
from ds3_core import *
from ds3_save import (
    CLASS_NAMES,
    read_bonfires,
    read_bosses,
    read_name,
    read_ng_plus,
    read_stats,
)
try:
    from ds3_save import read_gestures, read_inventory
except ImportError:
    read_inventory = None
    read_gestures = None
try:
    from ds3_save import read_missed
except ImportError:
    read_missed = None
try:
    from ds3_save import owned_item_names
except ImportError:
    owned_item_names = None
try:
    from ds3_save import read_completion_status
except ImportError:
    read_completion_status = None

# ── argparse ─────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ds3", description="Spoiler-safe Dark Souls 3 companion CLI",
        epilog="Quick start: ds3 fresh | ds3 softcaps | ds3 origins\nExplore: ds3 build quality | ds3 weapons claymore | ds3 rings havel\nCompletion: ds3 achievements --missable | ds3 covenants darkmoon | ds3 farm proofs",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="command")

    sp.add_parser("fresh", help="Show a fresh-start overview")
    sp.add_parser("softcaps", help="Show stat softcap breakpoints")
    op = sp.add_parser("origins", help="List starting classes")
    op.add_argument("filter", nargs="?", help="Build type filter: quality, str, dex, int, fth, pyro, luck")

    up = sp.add_parser("upgrade", help="Show materials needed for a weapon upgrade level")
    up.add_argument("level", type=int, help="Target upgrade level (1-10)")
    up.add_argument("--type", choices=["normal", "twinkling", "scale"], default="normal", help="Weapon upgrade type")

    wp = sp.add_parser("weapons", help="Show weapon info")
    wp.add_argument("name", nargs="?", help="Weapon name to look up")
    wp.add_argument("--all", action="store_true", help="Show all starter weapons")

    ca = sp.add_parser("calc", help="Calculate approximate weapon AR")
    ca.add_argument("weapon", help="Weapon name")
    ca.add_argument("str", type=int, help="Strength")
    ca.add_argument("dex", type=int, help="Dexterity")
    ca.add_argument("int", type=int, nargs="?", default=10, help="Intelligence (default 10)")
    ca.add_argument("fth", type=int, nargs="?", default=10, help="Faith (default 10)")

    sc = sp.add_parser("soul-cost", help="Calculate souls needed to level")
    sc.add_argument("current", type=int, help="Current soul level")
    sc.add_argument("target", type=int, help="Target soul level")

    es = sp.add_parser("estus", help="Estus Flask information")
    es.add_argument("sub", nargs="?", choices=["shards", "bones", "allotment", "max"], default="max")

    inf = sp.add_parser("infusions", help="Infusion guide")
    inf.add_argument("weapon", nargs="?", help="Weapon name for specific recommendations")
    inf.add_argument("--build", choices=["quality", "strength", "dexterity", "sorcerer", "pyromancer", "cleric", "luck"], help="Filter by build")

    el = sp.add_parser("equip-load", help="Calculate equip load")
    el.add_argument("--vitality", type=int, default=15, help="Vitality stat level (default 15)")
    el.add_argument("--havels", action="store_true", help="Include Havel's Ring")
    el.add_argument("--favor", action="store_true", help="Include Ring of Favor")

    cv = sp.add_parser("covenants", help="Covenant overview")
    cv.add_argument("id", nargs="?", help="Covenant ID (sunlight, darkmoon, etc.)")
    cv.add_argument("--achievement", "--platinum", action="store_true", help="Show only platinum-relevant covenant rewards")

    np = sp.add_parser("npcs", help="NPC questline guide")
    np.add_argument("name", nargs="?", help="NPC name or key (e.g. greirat, siegward, anri, sirris)")
    np.add_argument("--all", action="store_true", help="Show all NPC questlines")
    np.add_argument("--missable", action="store_true", help="Show only missable questlines")

    fm = sp.add_parser("farm", help="Farming guide for souls, materials, and covenant items")
    fm.add_argument("item", nargs="?", help="Item to farm: souls, shards, large-shards, chunks, slabs, twinkling, scales, proofs, shackles, medals, grass, dregs, tongues")

    bd = sp.add_parser("build", help="Show build archetype")
    bd.add_argument("type", nargs="?", choices=["quality", "strength", "dexterity", "sorcerer", "pyromancer", "cleric", "luck"], help="Build type")
    bd.add_argument("--level", type=int, default=120, help="Target soul level (default 120)")

    cp = sp.add_parser("compare", help="Compare two weapons")
    cp.add_argument("weapon_a", help="First weapon")
    cp.add_argument("weapon_b", help="Second weapon")
    cp.add_argument("--str", type=int, default=40, help="Strength")
    cp.add_argument("--dex", type=int, default=40, help="Dexterity")
    cp.add_argument("--int", type=int, default=10, help="Intelligence")
    cp.add_argument("--fth", type=int, default=10, help="Faith")

    ar = sp.add_parser("areas", help="Area progression")
    ar.add_argument("--spoilers", action="store_true", help="Show area/boss names")

    bo = sp.add_parser("bosses", help="Boss list")
    bo.add_argument("--area", help="Filter by area (spoiler-safe)")
    bo.add_argument("--required", action="store_true", help="Only required bosses")
    bo.add_argument("--spoilers", action="store_true", help="Show all boss names")

    ro = sp.add_parser("route", help="Route planning")
    ro.add_argument("--defeated", help="Comma-separated list of defeated boss IDs")
    ro.add_argument("--spoilers", action="store_true", help="Show full route with boss names")

    ach = sp.add_parser("achievements", help="Achievement guide")
    ach.add_argument("--missable", action="store_true", help="Show only missable achievements")
    ach.add_argument("--plat-route", action="store_true", help="Show optimal platinum route overview")

    md = sp.add_parser("mods", help="Mod recommendations")
    md.add_argument("--current", action="store_true", help="Show current mod awareness (legit vs cracked)")

    sp2 = sp.add_parser("spells", help="Spell catalog")
    sp2.add_argument("name", nargs="?", help="Spell name to look up")
    sp2.add_argument("--type", choices=["sorcery", "miracle", "pyromancy"], help="Filter by spell type")
    sp2.add_argument("--achievement", action="store_true", help="List all spells needed for platinum Master achievements")

    sp.add_parser("audit", help="Run self-consistency checks")

    tr = sp.add_parser("track", help="Show tracking file summary")
    tr.add_argument("section", nargs="?", choices=["summary", "stats", "gear", "next"], help="Section to show")
    tr.add_argument("--path", required=True, help="Path to tracking JSON file")

    rc = sp.add_parser("recommend", help="Recommendations based on tracking file")
    rc.add_argument("--path", required=True, help="Path to tracking JSON file")

    src = sp.add_parser("sources", help="Source registry")
    src_sub = src.add_subparsers(dest="sources_action")
    src_sub.add_parser("list", help="List all registered sources")
    src_st = src_sub.add_parser("status", help="Show cache status")
    src_rf = src_sub.add_parser("refresh", help="Refresh cached sources")
    src_rf.add_argument("keys", nargs="*", help="Source keys to refresh (all if omitted)")
    src_rf.add_argument("--force", action="store_true", help="Force refresh even if not stale")

    ri = sp.add_parser("rings", help="Rings catalog: browse, search, or filter by build")
    ri.add_argument("name", nargs="?", help="Ring name to search (case-insensitive substring match)")
    ri.add_argument("--build", choices=["quality", "strength", "dex", "sorcerer", "pyro", "cleric", "luck"], help="Filter rings by build archetype")
    ri.add_argument("--spoilers", action="store_true", help="Show exact locations, including future/DLC areas")


    sp_save = sp.add_parser("save", help="Read save file data")
    sp_save.add_argument("save_path", nargs="?", default="auto", help="Path to DS30000.sl2 file (or 'auto' to auto-detect)")
    sp_save.add_argument("action", nargs="?", default="summary",
        choices=["summary", "stats", "name", "level", "covenants", "bosses", "bonfires", "progress", "inventory", "gestures", "missed", "achievements", "checklist", "owned", "completion"],
        help="Action to perform")
    sp_save.add_argument("--spoilers", action="store_true", help="Show locked/remaining future names in save-backed progress")
    return p

# ── Command handlers ─────────────────────────────────────────────

def cmd_fresh(args) -> None:
    print("Welcome to Dark Souls 3, Ashen One.")
    print()
    print("You are at the Cemetery of Ash. Light the first bonfire.")
    print()
    print("Immediate priorities:")
    print("  - Level VGR early; 20 is comfortable, 27 is the first big HP target.")
    print("  - Keep equip load under 70% for a medium roll.")
    print("  - Meet weapon requirements, then upgrade one main weapon before spreading stats/materials.")
    print("  - Avoid LCK/INT/FTH/ATT unless you are deliberately building bleed/casting/FP.")
    print("  - Do not level every stat evenly; pick one damage lane.")
    print()
    print("Key commands to get started:")
    print("  ds3 softcaps  — stat breakpoints to plan your build")
    print("  ds3 origins   — view starting classes and their stats")
    print("  ds3 weapons   — weapon lookup and comparison")
    print("  ds3 estus     — flask shard and bone shard details")

def cmd_softcaps(args) -> None:
    print("=== Stat Softcaps ===\n")
    for stat, caps in SOFTCAPS.items():
        print(f"  {stat.title()}:")
        for level, desc in caps:
            print(f"    {level}: {desc}")
        print()
    print("See also: origins, build, soul-cost")

def cmd_origins(args) -> None:
    filt = (args.filter or "").lower()
    build_to_class = {
        "quality": "knight",
        "str": "warrior", "strength": "warrior",
        "dex": "mercenary", "dexterity": "mercenary",
        "int": "sorcerer",
        "fth": "cleric", "faith": "cleric",
        "pyro": "pyromancer", "pyromancer": "pyromancer",
        "luck": "thief",
    }
    target_class = build_to_class.get(filt, "")
    print(f"{'Class':<14} {'LV':>3} {'VGR':>4} {'ATT':>4} {'END':>4} {'VIT':>4} {'STR':>4} {'DEX':>4} {'INT':>4} {'FTH':>4} {'LCK':>4}")
    print("-" * 64)
    for name, o in ORIGINS.items():
        if filt == "" or name == target_class or filt in name:
            print(f"{name.title():<14} {o['level']:>3} {o['vig']:>4} {o['att']:>4} {o['end']:>4} {o['vit']:>4} {o['str']:>4} {o['dex']:>4} {o['int']:>4} {o['fth']:>4} {o['lck']:>4}")
    if filt:
        matching = [n for n in ORIGINS if n == target_class or filt in n]
        if not matching:
            print(f"\nNo class matches '{args.filter}'. Available filters: quality, str, dex, int, fth, pyro, luck")

def cmd_upgrade(args) -> None:
    path = {"normal": UPGRADE_NORMAL, "twinkling": UPGRADE_TWINKLING, "scale": UPGRADE_SCALE}[args.type]
    max_lvl = len(path)
    level = min(args.level, max_lvl)
    print(f"=== Upgrade path: {args.type} ===")
    if args.level > max_lvl:
        print(f"  Warning: Max upgrade for {args.type} is +{max_lvl}. Showing cost to max.")
    cumulative: dict[str, int] = {}
    for from_lvl, to_lvl, mats in path:
        for k, v in mats.items():
            cumulative[k] = cumulative.get(k, 0) + v
        if to_lvl == level:
            print(f"  To reach +{to_lvl}, you need:")
            for k, v in cumulative.items():
                print(f"    {v}x {k.replace('_', ' ').title()}")
            return
    print(f"  Level {level} is beyond max upgrade.")

def cmd_soul_cost(args) -> None:
    if args.current < 1 or args.target <= args.current or args.current < 0 or args.target < 0:
        print("Invalid: current level must be 1 or higher, target must be greater than current.")
        return
    cost = max(0, soul_cost(args.current, args.target))
    print("=== Soul Cost ===")
    print(f"  From level {args.current} to {args.target}:")
    print(f"  Total: {cost:,} souls")
    print(f"  Levels: {args.target - args.current}")

def cmd_estus(args) -> None:
    sub = args.sub
    print("=== Estus Flask ===")
    if sub == "shards":
        print(f"  Estus Shards: {ESTUS_SHARDS_MAX} total. Each shard adds one flask use, up to 15 total flasks.")
        print("  Early checklist: Firelink rafters, High Wall anvil room, Undead Settlement burning tree, Road/woods ruins, Farron swamp fallen tower.")
        print("  Use save auto summary for current flask count; exact shard pickup flags are not save-backed.")
        return
    if sub == "bones":
        print(f"  Undead Bone Shards: {BONE_SHARDS_MAX} total. Burn at Firelink bonfire to improve healing, up to Estus +10.")
        print("  Early checklist: Undead Settlement white birch tree, Farron Keep slug tower, Cathedral graveyard route.")
        print("  Use save auto missed for current-area checklist hints; exact bone pickup flags are not save-backed.")
        return
    if sub == "allotment":
        print("  Allotment: talk to the blacksmith to split total flasks between HP Estus and FP/Ashen Estus.")
        print("  Pure melee usually wants mostly/all HP Estus; casters and weapon-art-heavy builds may reserve FP flasks.")
        return
    print("  Max uses: 15 (start with 3 HP + 1 FP = 4)")
    print(f"  Estus Shards: {ESTUS_SHARDS_MAX} total")
    print(f"  Undead Bone Shards: {BONE_SHARDS_MAX} total")
    print("  Max heal potency: +10")
    print("  Use: estus shards | estus bones | estus allotment")

def cmd_infusions(args) -> None:
    build_filter = args.build
    infusions = INFUSIONS
    if build_filter:
        infusions = [i for i in infusions if build_filter in i.get("best_for", "")]
    print(f"=== Infusions ({len(infusions)} shown) ===")
    for i in infusions:
        print(f"\n  {i['id'].title()}: {i['effect']}")
        print(f"    Gem: {i['gem']}, Coal: {i['coal']}")
        print(f"    Best for: {i['best_for']}")
    if args.weapon:
        wname = args.weapon.lower()
        if wname in STARTER_WEAPONS:
            w = STARTER_WEAPONS[wname]
            print(f"\n  --- {wname.title()} specific ---")
            str_pct = w.get("str_coeff", 0.5)
            dex_pct = w.get("dex_coeff", 0.5)
            if str_pct > 0.6:
                print("  Good with: Heavy (STR scaling benefit)")
            if dex_pct > 0.6:
                print("  Good with: Sharp (DEX scaling benefit)")
            if 0.4 <= str_pct <= 0.6 and 0.4 <= dex_pct <= 0.6:
                print("  Good with: Refined (balanced scaling)")
    print()
    print("See also: build, weapons, compare")

def cmd_equip_load(args) -> None:
    vit = args.vitality
    if vit < 10:
        print("VIT must be at least 10.")
        return
    max_load = equip_load_max(vit, args.havels, args.favor)
    print(f"=== Equip Load (VIT {vit}) ===")
    print(f"  Max equip load: {max_load:.1f}")
    print(f"  Fast roll (<30%):  under {max_load * 0.3:.1f}")
    print(f"  Medium roll (30-70%): {max_load * 0.3:.1f} - {max_load * 0.7:.1f}")
    print(f"  Fat roll (70-100%):  {max_load * 0.7:.1f} - {max_load:.1f}")
    if args.havels or args.favor:
        rings = []
        if args.havels: rings.append("Havel's Ring (+15%)")
        if args.favor: rings.append("Ring of Favor (+5%)")
        print(f"  Rings: {', '.join(rings)}")

def _covenant_achievement_rewards(covenant: dict) -> list[tuple[str, str]]:
    """Return covenant rank rewards that count toward base-game achievements."""
    rewards: list[tuple[str, str]] = []
    for rank, label in (("rank10", "Rank 1"), ("rank30", "Rank 2")):
        reward = covenant.get(rank)
        if not reward:
            continue
        text = str(reward).lower()
        if any(token in text for token in ("ring", "miracle", "sorcery", "pyromancy", "platinum")):
            rewards.append((label, str(reward)))
    return rewards


def cmd_covenants(args) -> None:
    achievement_only = getattr(args, "achievement", False)
    if args.id:
        for c in COVENANTS:
            if c["id"] == args.id:
                rewards = _covenant_achievement_rewards(c)
                print(f"=== {c['name']} ===")
                print(f"  Type: {c['type']}")
                if achievement_only:
                    if not rewards:
                        print("  Base-game platinum: no covenant rank reward required.")
                    else:
                        print(f"  Turn-in item: {c.get('item') or 'N/A'}")
                        for label, reward in rewards:
                            print(f"  {label}: {reward}")
                        if c.get("farm"):
                            print(f"  Offline farm: {c['farm']}")
                else:
                    if c.get("rank10"):
                        print(f"  Rank 1 (10 {c['item']}): {c['rank10']}")
                    if c.get("rank30"):
                        print(f"  Rank 2 (30 {c['item']}): {c['rank30']}")
                    if c.get("farm"):
                        print(f"  Offline farm: {c['farm']}")
                print()
                print("See also: farm, achievements")
                return
        print(f"Covenant '{args.id}' not found. IDs: {', '.join(c['id'] for c in COVENANTS)}")
        return
    title = "Covenants — base-game platinum rewards" if achievement_only else "Covenants"
    print(f"=== {title} ===\n")
    not_required: list[dict] = []
    for c in COVENANTS:
        rewards = _covenant_achievement_rewards(c)
        if achievement_only and not rewards:
            not_required.append(c)
            continue
        item = c.get("item") or "N/A"
        print(f"  {c['name']} ({c['id']}): {c['type']} — {item}")
        if achievement_only:
            for label, reward in rewards:
                print(f"    {label}: {reward}")
        elif c.get("rank10"):
            print(f"    Rank 1: {c['rank10']}")
    if achievement_only and not_required:
        print("\n  No base-game platinum rank reward:")
        for c in not_required:
            note = "DLC covenant; not base-platinum" if c["id"] == "spears" else "not rank-reward relevant"
            print(f"    {c['name']} ({c['id']}): {note}")
    print()
    print("See also: farm, achievements")
def cmd_farm(args) -> None:
    farming: dict[str, tuple[str, str]] = {
        "souls": ("Souls", "Early: Tower on the Wall Lothric Knight loop for safe souls plus titanite practice. Early-mid: giant-arrow cleanup in the settlement if unlocked; lazy but effective. Mid: Farron Keep Perimeter enemy-vs-enemy loop; rest, repeat, and let enemies damage each other. Equip Covetous Silver Serpent Ring if owned. Farm only to cover Vigor breakpoints, weapon upgrades, infusion fees, or a specific level gap; upgrades usually beat grinding raw levels."),
        "shards": ("Titanite Shard", "Early-game pickups and common early enemies. Handmaid sells after the early ash; use guaranteed pickups before farming."),
        "large-shards": ("Large Titanite Shard", "Mid-game pickups/enemies. Handmaid sells after the mid-game ash; farm only after guaranteed pickups dry up."),
        "chunks": ("Titanite Chunk", "Late-game enemies. Handmaid sells after late-game ash. Rare drop."),
        "slabs": ("Titanite Slab", "Fixed pickups only (8 per NG in base game, more in DLC). Cannot be farmed from enemies."),
        "twinkling": ("Twinkling Titanite", "Crystal lizards throughout the world. Handmaid sells after late-game ash."),
        "scales": ("Titanite Scale", "Crystal lizards near boss areas. Handmaid sells after late-game ash."),
        "proofs": ("Proof of Concord Kept", "Silver Knight stair farm. ~1% base drop. Base-game setup: Symbol of Avarice + Gold Serpent Ring + Crystal Sage Rapier + Rusted Coins + LCK. DLC +3 ring is optional, not platinum-required."),
        "shackles": ("Vertebra Shackle", "Skeletons in catacombs (mid-game area). ~1% drop. ~4-6 hours offline."),
        "medals": ("Sunlight Medal", "Lothric Knights (mid-game castle). ~3% drop. Faster via co-op."),
        "grass": ("Wolf's Blood Swordgrass", "3 Ghru enemies at bonfire (early swamp). ~3% drop. ~2-4 hours."),
        "dregs": ("Human Dregs", "Deacons on an upper balcony (mid-game castle). ~5% drop. ~1-2 hours."),
        "tongues": ("Pale Tongue", "Darkwraiths (early swamp). ~3% drop. ~2-3 hours."),
    }
    if not args.item:
        print("=== Farm Targets ===\n")
        for key, (name, guide) in farming.items():
            print(f"  {name} ({key}): {guide.split('.')[0]}.")
        print(f"\n  Use 'ds3 farm <item>' for details. Items: {', '.join(sorted(farming.keys()))}")
        return
    item = args.item.lower()
    if item in farming:
        name, guide = farming[item]
        print(f"=== {name} Farm ===")
        print(f"  {guide}")
        if item == "proofs":
            print("  Best optional boost if DLC is available: Gold Serpent Ring +3. DLC gear is not required for platinum.")
    else:
        print(f"Unknown item: {args.item}")
        print(f"Try: {', '.join(sorted(farming.keys()))}")

def cmd_build(args) -> None:
    if not args.type:
        print("=== Build Archetypes ===\n")
        for name, b in BUILDS.items():
            print(f"  {name.title()}: {b['class'].title()} start -> {b['note']}")
        print("\n  Use `build <type>` for stat targets.")
        print()
        print("See also: softcaps, origins, infusions, weapons")
        return
    b = BUILDS.get(args.type)
    if not b:
        print(f"Unknown build: {args.type}")
        return
    print(f"=== {args.type.title()} Build (target SL{args.level}) ===\n")
    print(f"  Starting class: {b['class'].title()}")
    print(f"  Core stats: VGR {b['vig']} / ATT {b.get('att', 10)} / END {b['end']}")
    print(f"  Damage: STR {b.get('str', 10)} / DEX {b.get('dex', 10)} / INT {b.get('int', 10)} / FTH {b.get('fth', 10)}")
    print(f"  Infusion: {b['infusion']}")
    print(f"  Weapons: {b['weapons']}")
    print(f"  {b['note']}")
    print()
    print("See also: softcaps, origins, infusions, weapons")

def cmd_compare(args) -> None:
    wa = args.weapon_a.lower()
    wb = args.weapon_b.lower()
    if wa not in STARTER_WEAPONS or wb not in STARTER_WEAPONS:
        print("One or both weapons not found in starter dataset.")
        return
    a = STARTER_WEAPONS[wa]; b = STARTER_WEAPONS[wb]
    stats = {"str": args.str, "dex": args.dex, "int": args.int, "fth": args.fth}
    ar_a = weapon_ar(a, stats); ar_b = weapon_ar(b, stats)
    print(f"=== {wa.title()} vs {wb.title()} ===")
    print(f"  Stats: STR {stats['str']} / DEX {stats['dex']} / INT {stats['int']} / FTH {stats['fth']}")
    print(f"  {wa.title()}: {a['base_damage']} base, {a['str_scale']}/{a['dex_scale']}, ~{ar_a} AR, {a['weight']} wt")
    print(f"  {wb.title()}: {b['base_damage']} base, {b['str_scale']}/{b['dex_scale']}, ~{ar_b} AR, {b['weight']} wt")
    print(f"  Winner: {wa.title() if ar_a >= ar_b else wb.title()} ({abs(ar_a - ar_b)} AR difference)")

def cmd_mods(args) -> None:
    print("=== Mod Tools & Launchers ===\n")
    print("  Mod Engine 1 (dinput8.dll passive proxy)")
    print("    Mechanism: game loads dinput8.dll from folder; loads mod/ overrides")
    print("    Compatibility: works with cracked + legit copies, no injection")
    print("    Repo: github.com/katalash/ModEngine (GPL-3.0)")
    print()
    print("  Mod Engine 2 (ME2, external launcher)")
    print("    Mechanism: launcher injects modengine2.dll via CreateRemoteThread")
    print("    Compatibility: legit Steam copies; may fail on cracked (CODEX blocks)")
    print("    Repo: github.com/soulsmods/ModEngine2")
    print()
    print("  Mod Engine 3 (ME3, external launcher)")
    print("    Mechanism: profile-based mod loading, DLL injection")
    print("    Compatibility: legit Steam copies only; CODEX blocks CreateRemoteThread")
    print("    Repo: github.com/garyttierney/me3 (MIT)")
    print()
    print("=== Common Utility Mods ===\n")
    print("  Proper PC Experience (#1545): FPS unlock, FoV, refresh rate, skip intros")
    print("  FromStutterFix: general FromSoft frame-pacing fix (github.com/kh0nsu)")
    print("  Blue Sentinel (#723): anti-cheat + player overlay + save backups (online-safe)")
    print("  Camera Fix (#2028): disable auto camera rotation (requires ME2/ME3)")
    print("  PS4 Controller Icons (#278): replace Xbox glyphs with PlayStation glyphs")
    print()
    print("  All mod data from Nexus Mods + GitHub. Use live research for latest versions.")

def cmd_audit(args) -> None:
    print("=== Audit ===")
    issues = []
    if len(ORIGINS) != 10:
        issues.append(f"ORIGINS: expected 10 classes, got {len(ORIGINS)}")
    for name, o in ORIGINS.items():
        keys = {"level", "vig", "att", "end", "vit", "str", "dex", "int", "fth", "lck"}
        if set(o.keys()) != keys:
            issues.append(f"ORIGINS {name}: unexpected keys {set(o.keys()) ^ keys}")
    expected_stats = {"vigor", "attunement", "endurance", "vitality", "strength", "dexterity", "intelligence", "faith", "luck"}
    if set(SOFTCAPS.keys()) != expected_stats:
        issues.append(f"SOFTCAPS keys mismatch: {set(SOFTCAPS.keys()) ^ expected_stats}")
    if len(INFUSIONS) != 15:
        issues.append(f"INFUSIONS: expected 15, got {len(INFUSIONS)}")
    if len(COVENANTS) != 9:
        issues.append(f"COVENANTS: expected 9, got {len(COVENANTS)}")
    expected_spells = {"sorceries": 34, "miracles": 35, "pyromancies": 27}
    for cat, expected in expected_spells.items():
        actual = len(SPELLS.get(cat, []))
        if actual != expected:
            issues.append(f"SPELLS {cat}: expected {expected}, got {actual}")
    if issues:
        for i in issues:
            print(f"  FAIL: {i}")
    else:
        print("  All data integrity checks passed.")
    print(f"  Sources: {len(SOURCES)} registered")
    print(f"  Builds: {len(BUILDS)} archetypes")
    print(f"  Starter weapons: {len(STARTER_WEAPONS)}")
    print(f"  Spells: {sum(len(v) for v in SPELLS.values())} total "
          f"({len(SPELLS['sorceries'])} sorceries, {len(SPELLS['miracles'])} miracles, "
          f"{len(SPELLS['pyromancies'])} pyromancies)")
    print(f"  Rings: {len(RINGS)} total")

def cmd_sources(args) -> None:
    action = args.sources_action
    if action == "list":
        print(f"=== Registered Sources ({len(SOURCES)}) ===\n")
        for key, s in SOURCES.items():
            print(f"  {key}: {s.url} ({s.license})")
    elif action == "status":
        cdir = cache_dir()
        files = list(cdir.glob("*.json"))
        print("=== Cache Status ===")
        print(f"  Directory: {cdir}")
        print(f"  Cached files: {len(files)}")
        for f in files:
            try:
                data = json.loads(f.read_text())
                ts = data.get("ts")
                if not isinstance(ts, (int, float)):
                    raise ValueError("missing numeric ts")
                age_h = (time.time() - ts) / 3600
                print(f"  {f.stem}: {age_h:.1f}h old ({'stale' if age_h > CACHE_TTL_HOURS else 'fresh'})")
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                print(f"  {f.stem}: invalid cache entry ({exc})")
    elif action == "refresh":
        keys = args.keys or list(SOURCES.keys())
        for key in keys:
            if key not in SOURCES:
                print(f"  Unknown source: {key}")
                continue
            try:
                content = fetch_cached(key, SOURCES[key].url, force=args.force)
                print(f"  Refreshed: {key} ({len(content)} bytes)")
            except Exception as e:
                print(f"  Failed: {key} — {e}")
    else:
        print("Use: sources list | status | refresh [keys...]")

def cmd_track(args) -> None:
    path = Path(args.path)
    if not path.exists():
        print(f"Tracking file not found: {args.path}")
        return
    data = json.loads(path.read_text())
    section = args.section or "summary"
    if section == "summary":
        print(f"=== Tracking: {data.get('name', path.stem)} ===")
        print(f"  Soul Level: {data.get('soul_level', '?')}")
        s = data.get("stats", {})
        print(f"  Stats: VGR {s.get('vig', '?')} / ATT {s.get('att', '?')} / END {s.get('end', '?')}")
        print(f"         VIT {s.get('vit', '?')} / STR {s.get('str', '?')} / DEX {s.get('dex', '?')}")
        print(f"         INT {s.get('int', '?')} / FTH {s.get('fth', '?')} / LCK {s.get('lck', '?')}")
        print(f"  Estus: {data.get('estus_shards', 0)}/11 shards, {data.get('bone_shards', 0)}/10 bones")
        print(f"  Defeated: {len(data.get('defeated_bosses', []))} bosses")
    elif section == "stats":
        s = data.get("stats", {})
        for stat in ["vig", "att", "end", "vit", "str", "dex", "int", "fth", "lck"]:
            val = s.get(stat, 0)
            bar = "\u2588" * (val // 5) + "\u2591" * (20 - val // 5)
            print(f"  {stat.upper():>4}: {val:>3} {bar}")
    elif section == "gear":
        gear = data.get("gear", {})
        for slot, item in gear.items():
            print(f"  {slot}: {item}")
    elif section == "next":
        defeated = set(data.get("defeated_bosses", []))
        print("Route suggestions based on tracking file... (needs boss ID cross-reference)")

def cmd_recommend(args) -> None:
    path = Path(args.path)
    if not path.exists():
        print(f"Tracking file not found: {args.path}")
        return
    data = json.loads(path.read_text())
    stats = data.get("stats", {})
    sl = data.get("soul_level", 0)
    print(f"=== Recommendations (SL{sl}) ===")
    if stats.get("vig", 0) < 27:
        print(f"  Priority: Level VGR to 27 (currently {stats.get('vig', 0)}). That's the first softcap.")
    if stats.get("end", 0) < 20 and sl > 30:
        print(f"  Consider leveling END to 20+ (currently {stats.get('end', 0)}).")
    highest_dmg = max(stats.get("str", 0), stats.get("dex", 0), stats.get("int", 0), stats.get("fth", 0))
    if highest_dmg < 20 and sl > 30:
        print("  Your damage stats are low. Pick one to push to 20-25.")


def _cmd_areas_with_hint(args) -> None:
    cmd_areas(args)
    print()
    print("See also: bosses, route, npcs")

def _cmd_weapons_with_hint(args) -> None:
    cmd_weapons(args)
    print()
    print("See also: calc, compare, infusions, upgrade")

SAVE_AUTO = Path.home() / "AppData" / "Roaming" / "DarkSoulsIII"

def _find_save_path() -> str | None:
    """Find the DS30000.sl2 file in the default save directory."""
    if not SAVE_AUTO.exists():
        return None
    for user_dir in SAVE_AUTO.iterdir():
        if user_dir.is_dir():
            sl2 = user_dir / "DS30000.sl2"
            if sl2.exists():
                return str(sl2)
    return None



def _status_counts(value: object) -> tuple[int | None, int | None]:
    if not isinstance(value, dict):
        return (None, None)
    found = value.get("found", value.get("owned", value.get("complete")))
    total = value.get("total")
    if isinstance(found, bool):
        found = 1 if found else 0
    if isinstance(found, (set, list, tuple)) and isinstance(total, int):
        return (len(found), total)
    if isinstance(found, int) and isinstance(total, int):
        return (found, total)
    owned_items = value.get("owned")
    missing_items = value.get("missing")
    if isinstance(owned_items, list) and isinstance(missing_items, list):
        return (len(owned_items), len(owned_items) + len(missing_items))
    return (None, None)


def _print_completion_status(save_path: str) -> bool:
    if read_completion_status is None:
        return False
    status = read_completion_status(save_path)
    if not isinstance(status, dict):
        return False
    order = (
        ("rings", "Rings", "save"),
        ("sorceries", "Sorceries", "save"),
        ("pyromancies", "Pyromancies", "save"),
        ("miracles", "Miracles", "save"),
        ("reinforcement", "Weapon reinforcement", "static"),
        ("gestures", "Gestures", "static"),
        ("infusions", "Infusions", "static"),
    )
    checklist = _completion_checklist()
    rows: list[tuple[str, int, int, str]] = []
    static_rows: list[tuple[str, int]] = []
    for key, label, source in order:
        if source == "static":
            values = checklist.get(key, [])
            if isinstance(values, list) and values:
                static_rows.append((label, len(values)))
            continue
        if key not in status:
            continue
        found, total = _status_counts(status[key])
        if found is None or total is None or total == 0:
            continue
        rows.append((label, found, total, source))
    if not rows and not static_rows:
        return False
    print("=== Completion ===")
    for label, found, total, source in rows:
        print(f"  {label}: {found}/{total} (save-backed)")
    for label, total in static_rows:
        print(f"  {label}: {total} checklist entries (not save-backed)")
    return True


def _owned_name_set(save_path: str) -> set[str]:
    if owned_item_names is None:
        return set()
    names = owned_item_names(save_path)
    if isinstance(names, dict):
        flattened: set[str] = set()
        for values in names.values():
            if isinstance(values, (set, list, tuple)):
                flattened.update(str(value).casefold() for value in values)
        return flattened
    if isinstance(names, (set, list, tuple)):
        return {str(name).casefold() for name in names}
    return set()


def _print_owned_items(save_path: str) -> None:
    if owned_item_names is None:
        print("  Owned item tracking not yet available.")
        return
    names = owned_item_names(save_path)
    print("=== Owned Items ===")
    if isinstance(names, dict):
        for key in ("rings", "spells", "goods", "weapons"):
            values = names.get(key, [])
            if not isinstance(values, (set, list, tuple)):
                continue
            ordered = sorted(str(value) for value in values)
            label = key.replace("_", " ").title()
            print(f"  {label}: {len(ordered)} owned")
            if ordered:
                print("    " + ", ".join(ordered[:12]) + (" ..." if len(ordered) > 12 else ""))
        return
    if isinstance(names, (set, list, tuple)):
        ordered = sorted(str(value) for value in names)
        print(f"  Items: {len(ordered)} owned")
        if ordered:
            print("    " + ", ".join(ordered[:20]) + (" ..." if len(ordered) > 20 else ""))
        return
    print("  Owned item helper returned no printable data.")

def _completion_checklist() -> dict[str, list[str]]:
    from ds3_save import read_completion_checklist
    return read_completion_checklist()


def _print_name_sample(items: list[dict], limit: int = 12) -> None:
    names = sorted(str(item.get("name", "Unknown")) for item in items)
    if names:
        print("    " + ", ".join(names[:limit]) + (" ..." if len(names) > limit else ""))


def _print_inventory(save_path: str) -> None:
    if read_inventory is None:
        print("  Inventory parsing is not available.")
        return
    inv = read_inventory(save_path)
    print(f"=== Inventory: {inv['total_items']} resolved items ===")
    for label, key in (("Weapons", "weapons"), ("Armor", "armor"), ("Rings", "rings"), ("Goods", "goods")):
        items = inv.get(key, [])
        print(f"  {label}: {len(items)}")
        _print_name_sample(items)


def _boss_flags_supported(save_path: str) -> bool:
    del save_path
    try:
        from ds3_save import _boss_flags_supported as parser_boss_flags_supported
    except ImportError:
        return False
    return parser_boss_flags_supported()


def _bonfire_flags_supported(save_path: str) -> bool:
    del save_path
    try:
        from ds3_save import _bonfire_flags_supported as parser_bonfire_flags_supported
    except ImportError:
        return False
    return parser_bonfire_flags_supported()

def _tracked_boss_names() -> list[str]:
    try:
        from ds3_save import BOSS_FLAGS
    except ImportError:
        return []
    return [str(name) for name in BOSS_FLAGS]


def _tracked_bonfire_names() -> list[str]:
    try:
        from ds3_save import BONFIRE_BIT_FLAGS
    except ImportError:
        return []
    return sorted(f"{item['area']} - {item['name']}" for item in BONFIRE_BIT_FLAGS)


def _print_unsupported_event_flags(kind: str, names: list[str], *, spoilers: bool = False) -> None:
    print(f"  {kind}: save-backed event flag region unsupported")
    if names and spoilers:
        print("  Tracked names (status unknown):")
        for name in names:
            print(f"    - {name}")
    elif names:
        print(f"  {len(names)} tracked names hidden. Use --spoilers to show unknown/future names.")

def _print_save_flag_caveat() -> None:
    print("  Note: read-only save parse; boss/bonfire status uses known event flags only.")
    print("  Remaining/locked means not observed in tracked flags, not a miss/lockout proof.")


def _max_weapon_label(stats: dict) -> str:
    value = stats.get("maxWeaponReinforcement")
    if isinstance(value, int):
        return f"+{value}"
    return "unsupported"


def _print_save_overview(save_path: str, stats: dict, *, include_stats: bool) -> None:
    boss_flags_supported = _boss_flags_supported(save_path)
    bonfire_flags_supported = _bonfire_flags_supported(save_path)
    print(f"=== {read_name(save_path)} ===")
    journey = read_ng_plus(save_path)
    journey_label = "NG" if journey == 0 else f"NG+{journey}"
    print(f"  Class: {CLASS_NAMES.get(stats['class_'], 'Unknown')}  |  SL: {stats['soulLevel']}  |  Journey: {journey_label}  |  Souls: {stats['souls']:,}")
    print(f"  Estus: {stats['estusAllocation']} HP / {stats['ashenEstusAllocation']} FP  |  Max weapon: {_max_weapon_label(stats)}")
    if boss_flags_supported:
        bosses = read_bosses(save_path)
        defeated = sum(1 for boss in bosses if boss["defeated"])
        print(f"  Bosses: {defeated}/{len(bosses)} defeated")
    else:
        print("  Bosses: unsupported (event flag region not verified)")
    if bonfire_flags_supported:
        bonfires = read_bonfires(save_path)
        unlocked = sum(1 for unlocked_flag in bonfires.values() if unlocked_flag)
        print(f"  Tracked bonfires: {unlocked}/{len(bonfires)} unlocked")
    else:
        print("  Bonfires: unsupported (event flag region not verified)")
    if boss_flags_supported or bonfire_flags_supported:
        _print_save_flag_caveat()
    print(f"  Embered: {'Yes' if stats['embered'] else 'No'}")
    stat_names = [("VGR", "vigor"), ("ATT", "attunement"), ("END", "endurance"),
                  ("VIT", "vitality"), ("STR", "strength"), ("DEX", "dexterity"),
                  ("INT", "intelligence"), ("FTH", "faith"), ("LCK", "luck")]
    if include_stats:
        print("  Stats: " + "  ".join(f"{label} {stats[key]}" for label, key in stat_names))
        print(f"  HP: {stats['health']}/{stats['maxHealth']}  |  FP: {stats['mana']}/{stats['maxMana']}  |  Stamina: {stats['stamina']}/{stats['maxStamina']}")
        print(f"  Hollowing: {stats['hollow']}  |  Base item discovery: {100 + stats['luck']}")
    else:
        first = stat_names[:5]
        second = stat_names[5:]
        print("  " + "  ".join(f"{label}: {stats[key]:>2}" for label, key in first))
        print("  " + "  ".join(f"{label}: {stats[key]:>2}" for label, key in second))


def _print_missed_result(missed: dict[str, object]) -> None:
    area = missed.get("current_area") or "Unknown"
    print(f"=== Missed: {area} ===")
    checklist_available = missed.get("checklist_available", True)
    missing_bosses = [str(boss) for boss in missed.get("missing_bosses", []) if isinstance(boss, str)]
    if checklist_available is False:
        print("  Area checklist: not available; boss/item missability unknown")
    elif missing_bosses:
        print("  Defeat/check:")
        for boss in missing_bosses:
            print(f"    - {boss}")
    else:
        print("  Bosses: clear")
    key_items = missed.get("key_items", [])
    if isinstance(key_items, list) and key_items:
        print("  Key items:")
        for item in key_items:
            if isinstance(item, dict):
                name = str(item.get("name", "Unknown"))
                owned = item.get("owned")
                supported = item.get("supported")
                check = item.get("check")
            else:
                name = str(item)
                owned = None
                supported = None
                check = None
            if supported is False:
                status = "static"
            elif owned is True:
                status = "owned"
            elif check is True:
                status = "check"
            else:
                status = "unknown"
            print(f"    - {name} [{status}]")
    estus_found = missed.get("estus_shards_found")
    estus_total = missed.get("estus_shards_total")
    if missed.get("estus_shards_supported") is True and isinstance(estus_found, int) and isinstance(estus_total, int):
        print(f"  Estus shards: {estus_found}/{estus_total} found (save-backed)")
    elif isinstance(estus_total, int) and estus_total > 0:
        print(f"  Estus shards: {estus_total} checklist entries (save-backed count unsupported)")
    else:
        print("  Estus shards: save-backed count unsupported")
    bones_found = missed.get("bone_shards_found")
    bones_total = missed.get("bone_shards_total")
    if missed.get("bone_shards_supported") is True and isinstance(bones_found, int) and isinstance(bones_total, int):
        print(f"  Undead bone shards: {bones_found}/{bones_total} found (save-backed)")
    elif isinstance(bones_total, int) and bones_total > 0:
        print(f"  Undead bone shards: {bones_total} checklist entries (save-backed count unsupported)")
    else:
        print("  Undead bone shards: save-backed count unsupported")


def _print_save_achievements(save_path: str) -> None:
    from ds3_save import read_completion_checklist
    has_status = _print_completion_status(save_path)
    checklist = read_completion_checklist()
    print("=== Completion Checklist ===" if not has_status else "\n=== Completion Checklist ===")
    if _boss_flags_supported(save_path):
        bosses = read_bosses(save_path)
        defeated = [boss for boss in bosses if boss["defeated"]]
        print(f"  Bosses: {len(defeated)}/{len(bosses)} defeated")
        print("    " + ", ".join(boss["name"] for boss in defeated[:8]) if defeated else "    None recorded yet")
    else:
        print("  Bosses: unsupported (event flag region not verified)")

    if _bonfire_flags_supported(save_path):
        bonfires = read_bonfires(save_path)
        unlocked = [name for name, is_unlocked in bonfires.items() if is_unlocked]
        print(f"  Tracked bonfires: {len(unlocked)}/{len(bonfires)} unlocked")
        print("    " + ", ".join(sorted(unlocked)[:8]) if unlocked else "    None recorded yet")
    else:
        print("  Bonfires: unsupported (event flag region not verified)")

    for label, key in (
        ("Rings", "rings"),
        ("Sorceries", "sorceries"),
        ("Pyromancies", "pyromancies"),
        ("Miracles", "miracles"),
        ("Gestures (static checklist; not save-backed)", "gestures"),
        ("Infusions (static checklist; not save-backed)", "infusions"),
        ("Weapon reinforcement (static checklist; not save-backed)", "reinforcement"),
    ):
        values = checklist.get(key, [])
        unit = "checklist entries" if key in {"gestures", "infusions", "reinforcement"} else "tracked"
        print(f"  {label}: {len(values)} {unit}")
        if values:
            print("    " + ", ".join(values[:8]) + (" ..." if len(values) > 8 else ""))


def _print_save_checklist(save_path: str, stats: dict) -> None:
    from ds3_save import read_area_checklists, read_current_area
    area_name = read_current_area(save_path)
    area_data = read_area_checklists().get(area_name, {}) if area_name else {}
    print(f"=== Current Area: {area_name or 'Unknown'} ===")
    if not area_data:
        print("  Area checklist: unavailable; current area is unknown because bonfire event flags are unsupported.")
        return

    bosses = area_data.get("bosses", [])
    if bosses:
        print(f"  Bosses ({len(bosses)}):")
        for name in bosses:
            print(f"    - {name}")

    for label, key in (("Key items", "key_items"), ("NPCs", "npcs")):
        values = area_data.get(key, [])
        if values:
            print(f"  {label} ({len(values)}):")
            for value in values:
                print(f"    - {value}")

    print(f"  Estus shards: {len(area_data.get('estus_shards', []))}")
    print(f"  Undead bone shards: {len(area_data.get('bone_shards', []))}")
    print(f"  Current flask split: {stats['estusAllocation']} HP / {stats['ashenEstusAllocation']} FP")


def cmd_save(args) -> None:
    save_path = args.save_path
    if save_path in ("auto", "~"):
        save_path = _find_save_path()
        if save_path is None:
            print("No save file found in %APPDATA%/DarkSoulsIII/")
            return
    stats = read_stats(save_path)
    action = args.action

    if action == "name":
        print(f"  Character: {read_name(save_path)}")
        return

    if action == "level":
        print(f"  Soul Level: {stats['soulLevel']}")
        print(f"  Souls: {stats['souls']:,}")
        return

    if action == "bosses":
        print("=== BOSSES ===")
        if not _boss_flags_supported(save_path):
            _print_unsupported_event_flags("Bosses", _tracked_boss_names(), spoilers=args.spoilers)
            return
        bosses = read_bosses(save_path)
        defeated = [b for b in bosses if b["defeated"]]
        alive = [b for b in bosses if not b["defeated"]]
        if defeated:
            print(f"  Defeated ({len(defeated)}/{len(bosses)}):")
            for b in defeated:
                print(f"    + {b['name']}")
        if args.spoilers:
            print(f"  Remaining ({len(alive)}/{len(bosses)}):")
        else:
            print(f"  Remaining: {len(alive)}/{len(bosses)} hidden by default")
        if alive and args.spoilers:
            for b in alive:
                print(f"    - {b['name']}")
        elif alive:
            print("  Use --spoilers to show remaining boss names.")
        _print_save_flag_caveat()
        return

    if action == "bonfires":
        print("=== TRACKED BONFIRES ===")
        if not _bonfire_flags_supported(save_path):
            _print_unsupported_event_flags("Tracked bonfires", _tracked_bonfire_names(), spoilers=args.spoilers)
            return
        bonfires = read_bonfires(save_path)
        unlocked = {n for n, u in bonfires.items() if u}
        locked = {n for n, u in bonfires.items() if not u}
        if unlocked:
            print(f"  Unlocked ({len(unlocked)}/{len(bonfires)} tracked):")
            for n in sorted(unlocked):
                print(f"    + {n}")
        if args.spoilers:
            print(f"  Locked ({len(locked)}/{len(bonfires)} tracked):")
        else:
            print(f"  Locked: {len(locked)}/{len(bonfires)} hidden by default")
        if locked and args.spoilers:
            for n in sorted(locked):
                print(f"    - {n}")
        elif locked:
            print("  Use --spoilers to show locked/future bonfire names.")
        _print_save_flag_caveat()
        return

    if action == "progress":
        _print_save_overview(save_path, stats, include_stats=False)
        return

    if action == "covenants":
        cov = {k: v for k, v in stats.items() if k.endswith('Points') and v > 0}
        for name, pts in cov.items():
            print(f"  {name}: {pts}")
        if not cov:
            print("  No covenant ranks yet.")
        return

    if action == "inventory":
        _print_inventory(save_path)
        return

    if action == "gestures":
        try:
            from ds3_save import read_gestures
            result = read_gestures(save_path)
            if isinstance(result, dict) and result.get("supported") is False:
                gestures = result.get("gestures", [])
                names = [name for name in gestures if isinstance(name, str)]
                print(f"=== Gestures ({len(names)} checklist entries; not save-backed) ===")
                reason = result.get("reason")
                if isinstance(reason, str) and reason:
                    print(f"  Save ownership unsupported: {reason}")
                if names:
                    print("  Static checklist:")
                    for name in names:
                        print(f"    - {name}")
                return
            if isinstance(result, list):
                unlocked = [g for g in result if isinstance(g, dict) and g.get("unlocked")]
                locked = [g for g in result if isinstance(g, dict) and not g.get("unlocked")]
                print(f"=== Gestures ({len(unlocked)}/{len(result)} unlocked) ===")
                if unlocked:
                    print("  Unlocked:")
                    for g in unlocked:
                        print(f"    + {g['name']}")
                if locked:
                    print("  Locked:")
                    for g in locked:
                        print(f"    - {g['name']}")
            else:
                print("  Gesture save ownership is not available.")
        except ImportError:
            print("  Gesture tracking not yet available.")
        return

    if action == "owned":
        _print_owned_items(save_path)
        return

    if action == "completion":
        if not _print_completion_status(save_path):
            _print_save_achievements(save_path)
        return

    if action == "achievements":
        _print_save_achievements(save_path)
        return

    if action == "checklist":
        _print_save_checklist(save_path, stats)
        return

    if action == "missed":
        if read_missed is not None:
            _print_missed_result(read_missed(save_path))
            return
        _print_missed_result({
            "current_area": "",
            "missing_bosses": [],
            "key_items": [],
            "checklist_available": False,
            "estus_shards_found": None,
            "estus_shards_total": 0,
            "bone_shards_found": None,
            "bone_shards_total": 0,
        })
        return

    _print_save_overview(save_path, stats, include_stats=(action == "stats"))


# ── Entry point ──────────────────────────────────────────────────

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        cmd_fresh(args)
        return
    handlers = {
        "fresh": cmd_fresh, "softcaps": cmd_softcaps, "origins": cmd_origins,
        "upgrade": cmd_upgrade, "weapons": _cmd_weapons_with_hint, "calc": cmd_calc,
        "soul-cost": cmd_soul_cost, "estus": cmd_estus, "infusions": cmd_infusions,
        "equip-load": cmd_equip_load, "covenants": cmd_covenants, "npcs": cmd_npcs,
        "farm": cmd_farm, "build": cmd_build, "compare": cmd_compare,
        "areas": _cmd_areas_with_hint, "bosses": cmd_bosses, "route": cmd_route,
        "achievements": cmd_achievements, "mods": cmd_mods, "audit": cmd_audit,
        "sources": cmd_sources, "spells": cmd_spells, "rings": cmd_rings,
        "track": cmd_track, "recommend": cmd_recommend, "save": cmd_save,
    }
    handler = handlers.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
