#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Spoiler-safe Dark Souls 3 lookup CLI for agents.

Stateless: stores no player progress. Tracking requires an explicit path argument.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ds3_core import *
from ds3_catalog import *
from cli_catalog import *

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

    np = sp.add_parser("npcs", help="NPC questline guide")
    np.add_argument("name", nargs="?", help="NPC name or key (e.g. greirat, siegward, anri, sirris)")
    np.add_argument("--all", action="store_true", help="Show all NPC questlines")
    np.add_argument("--missable", action="store_true", help="Show only missable questlines")

    fm = sp.add_parser("farm", help="Farming guide for materials and covenant items")
    fm.add_argument("item", nargs="?", help="Item to farm: shards, large-shards, chunks, slabs, twinkling, scales, proofs, shackles, medals, grass, dregs, tongues")

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

    return p

# ── Command handlers ─────────────────────────────────────────────

def cmd_fresh(args) -> None:
    print("Welcome to Dark Souls 3, Ashen One.")
    print()
    print("You are at the Cemetery of Ash. Light the first bonfire.")
    print()
    print("Key commands to get started:")
    print("  ds3 softcaps  — stat breakpoints to plan your build")
    print("  ds3 origins   — view starting classes and their stats")
    print("  ds3 weapons   — weapon lookup and comparison")
    print("  ds3 estus     — flask shard and bone shard details")
    print()
    print("This companion covers: stats, weapons, areas, quests, rings, spells, mods.")

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
    print(f"{'Class':<14} {'LV':>3} {'VGR':>4} {'ATT':>4} {'END':>4} {'VIT':>4} {'STR':>4} {'DEX':>4} {'INT':>4} {'FTH':>4} {'LCK':>4}")
    print("-" * 64)
    for name, o in ORIGINS.items():
        if filt == "" or filt in name:
            print(f"{name.title():<14} {o['level']:>3} {o['vig']:>4} {o['att']:>4} {o['end']:>4} {o['vit']:>4} {o['str']:>4} {o['dex']:>4} {o['int']:>4} {o['fth']:>4} {o['lck']:>4}")
    if filt:
        matching = [n for n in ORIGINS if filt in n]
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
    print(f"=== Soul Cost ===")
    print(f"  From level {args.current} to {args.target}:")
    print(f"  Total: {cost:,} souls")
    print(f"  Levels: {args.target - args.current}")

def cmd_estus(args) -> None:
    print("=== Estus Flask ===")
    print(f"  Max uses: 15 (start with 3 HP + 1 FP = 4)")
    print(f"  Estus Shards: {ESTUS_SHARDS_MAX} total (find in the world)")
    print(f"  Undead Bone Shards: {BONE_SHARDS_MAX} total (burn at Firelink bonfire)")
    print(f"  Max heal potency: +10")
    print(f"  Allotment: talk to the blacksmith to split between HP and FP Estus")

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
                print(f"  Good with: Heavy (STR scaling benefit)")
            if dex_pct > 0.6:
                print(f"  Good with: Sharp (DEX scaling benefit)")
            if 0.4 <= str_pct <= 0.6 and 0.4 <= dex_pct <= 0.6:
                print(f"  Good with: Refined (balanced scaling)")
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

def cmd_covenants(args) -> None:
    if args.id:
        for c in COVENANTS:
            if c["id"] == args.id:
                print(f"=== {c['name']} ===")
                print(f"  Type: {c['type']}")
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
    print("=== Covenants ===\n")
    for c in COVENANTS:
        item = c.get("item") or "N/A"
        r10 = c.get("rank10") or "N/A"
        print(f"  {c['name']} ({c['id']}): {c['type']} — {item}")
        if r10 != "N/A":
            print(f"    Rank 1: {r10}")
    print()
    print("See also: farm, achievements")

def cmd_farm(args) -> None:
    farming: dict[str, tuple[str, str]] = {
        "shards": ("Titanite Shard", "Early-game enemies. The shrine handmaid sells them after you give her an early-game ash."),
        "large-shards": ("Large Titanite Shard", "Mid-game enemies. Handmaid sells after mid-game ash."),
        "chunks": ("Titanite Chunk", "Late-game enemies. Handmaid sells after late-game ash. Rare drop."),
        "slabs": ("Titanite Slab", "Fixed pickups only (8 per NG in base game, more in DLC). Cannot be farmed from enemies."),
        "twinkling": ("Twinkling Titanite", "Crystal lizards throughout the world. Handmaid sells after late-game ash."),
        "scales": ("Titanite Scale", "Crystal lizards near boss areas. Handmaid sells after late-game ash."),
        "proofs": ("Proof of Concord Kept", "Silver Knights on stairs (mid-game cathedral). 1% base drop. Max item discovery reduces farm from ~10 hours to ~6."),
        "shackles": ("Vertebra Shackle", "Skeletons in catacombs (mid-game area). ~1% drop. ~4-6 hours offline."),
        "medals": ("Sunlight Medal", "Lothric Knights (mid-game castle). ~3% drop. Faster via co-op."),
        "grass": ("Wolf's Blood Swordgrass", "3 Ghru enemies at bonfire (early swamp). ~3% drop. ~2-4 hours."),
        "dregs": ("Human Dregs", "9 Deacons on balcony (mid-game castle). ~5% drop. ~1-2 hours."),
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
        if "Silver Knights" in guide:
            print(f"  Optimal setup: Symbol of Avarice + Gold Serpent Ring +3 + Crystal Sage Rapier + Rusted Coins + 60+ LCK = ~500 item discovery")
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
    if issues:
        for i in issues:
            print(f"  FAIL: {i}")
    else:
        print("  All data integrity checks passed.")
    print(f"  Sources: {len(SOURCES)} registered")
    print(f"  Builds: {len(BUILDS)} archetypes")
    print(f"  Starter weapons: {len(STARTER_WEAPONS)}")
    expected_spells = {"sorceries": 34, "miracles": 35, "pyromancies": 27}
    for cat, expected in expected_spells.items():
        actual = len(SPELLS.get(cat, []))
        if actual != expected:
            issues.append(f"SPELLS {cat}: expected {expected}, got {actual}")
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
        print(f"=== Cache Status ===")
        print(f"  Directory: {cdir}")
        print(f"  Cached files: {len(files)}")
        for f in files:
            data = json.loads(f.read_text())
            age_h = (time.time() - data["ts"]) / 3600
            print(f"  {f.stem}: {age_h:.1f}h old ({'stale' if age_h > CACHE_TTL_HOURS else 'fresh'})")
    elif action == "refresh":
        keys = args.keys or list(SOURCES.keys())
        for key in keys:
            if key not in SOURCES:
                print(f"  Unknown source: {key}")
                continue
            try:
                content = fetch_cached(key, SOURCES[key].url)
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
        print(f"  Your damage stats are low. Pick one to push to 20-25.")


def _cmd_areas_with_hint(args) -> None:
    cmd_areas(args)
    print()
    print("See also: bosses, route, npcs")

def _cmd_weapons_with_hint(args) -> None:
    cmd_weapons(args)
    print()
    print("See also: calc, compare, infusions, upgrade")
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
        "track": cmd_track, "recommend": cmd_recommend,
    }
    handler = handlers.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
