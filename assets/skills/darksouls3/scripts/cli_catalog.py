"""Dark Souls 3 CLI — catalog command handlers.

Large display/formatting functions for weapons, areas, bosses,
routes, achievements, spells, rings, and NPCs.
"""

import sys

from ds3_catalog import *
from ds3_core import *


def _print_static_catalog_note(kind: str) -> None:
    sys.stdout.write(
        f"  Note: bundled {kind} catalog is static scaffold data; "
        "live-check exact locations/routes for source-backed final answers.\n"
    )


def cmd_weapons(args) -> None:
    if args.all or not args.name:
        print("=== Starter Weapons ===\n")
        for name, w in STARTER_WEAPONS.items():
            print(
                f"  {name.title()}: {w['base_damage']} DMG, {w['str_scale']}/{w['dex_scale']} scaling, req {w['str_req']} STR/{w['dex_req']} DEX, {w['weight']} wt ({w['category']})"
            )
        return
    name = args.name.lower()
    if name in STARTER_WEAPONS:
        w = STARTER_WEAPONS[name]
        print(f"=== {name.title()} ===")
        print(f"  Category: {w['category'].title()}")
        print(f"  Base Damage: {w['base_damage']}")
        print(f"  Scaling: STR {w['str_scale']} / DEX {w['dex_scale']}")
        print(f"  Requirements: {w['str_req']} STR / {w['dex_req']} DEX")
        print(f"  Weight: {w['weight']}")
        print(f"  Upgrade: Normal (Titanite)")
        for stats_label, stats in [
            ("base (10/10)", {"str": 10, "dex": 10}),
            ("20/20", {"str": 20, "dex": 20}),
            ("40/40", {"str": 40, "dex": 40}),
        ]:
            ar = weapon_ar(w, stats)
            print(f"  AR at {stats_label}: ~{ar}")
    else:
        print(
            f"  Weapon '{args.name}' not in starter dataset. Use live research for full weapon list."
        )
        print(f"  Known weapons: {', '.join(sorted(STARTER_WEAPONS.keys()))}")


def cmd_calc(args) -> None:
    name = args.weapon.lower()
    if name not in STARTER_WEAPONS:
        print(f"Unknown weapon: {args.weapon}")
        return
    w = STARTER_WEAPONS[name]
    stats = {
        "str": min(args.str, 99),
        "dex": min(args.dex, 99),
        "int": min(args.int, 99),
        "fth": min(args.fth, 99),
    }
    ar = weapon_ar(w, stats)
    print(f"=== {name.title()} AR ===")
    print(
        f"  Stats: STR {stats['str']} / DEX {stats['dex']} / INT {stats['int']} / FTH {stats['fth']}"
    )
    print(f"  Base damage: {w['base_damage']}")
    print(f"  Scaling: STR {w['str_scale']} / DEX {w['dex_scale']}")
    print(f"  Estimated AR: ~{ar}")
    print("  Note: AR shown is for +0 base weapon (not upgraded).")


def cmd_areas(args) -> None:
    if not args.spoilers:
        print("=== Area Progression (spoiler-safe) ===\n")
        print("  Phase 0: Starter area + early walled zone")
        print("  Phase 1: Settlement → Swamp → Cathedral")
        print("  Phase 2: Catacombs → Lake (optional) → Icy city → Dungeon → Capital")
        print("  Phase 3: Late-game castle → Garden (optional) → Archives → Final area")
        print("  Phase 4: DLC painting world → DLC heap/city")
        print("\n  Use --spoilers for area names.")
        return
    print("=== Area Progression (spoilers on) ===\n")
    areas = [
        ("Cemetery of Ash", 0, [], True, 1),
        ("Firelink Shrine", 0, [], True, 1),
        ("High Wall of Lothric", 0, [], True, 3),
        ("Undead Settlement", 1, ["Curse-rotted Greatwood"], True, 4),
        ("Road of Sacrifices", 1, [], True, 2),
        ("Cathedral of the Deep", 1, ["Deacons of the Deep"], True, 4),
        ("Farron Keep", 1, ["Abyss Watchers"], True, 4),
        ("Catacombs of Carthus", 2, ["High Lord Wolnir"], True, 3),
        ("Smouldering Lake", 2, ["Old Demon King"], False, 2),
        ("Irithyll of the Boreal Valley", 2, ["Pontiff Sulyvahn"], True, 3),
        ("Irithyll Dungeon", 2, [], True, 2),
        ("Profaned Capital", 2, ["Yhorm the Giant"], True, 2),
        ("Anor Londo", 3, ["Aldrich, Devourer of Gods"], True, 1),
        ("Lothric Castle", 3, ["Dragonslayer Armour"], True, 3),
        ("Consumed King's Garden", 3, ["Oceiros, the Consumed King"], False, 1),
        ("Untended Graves", 3, ["Champion Gundyr"], False, 1),
        ("Archdragon Peak", 3, ["Ancient Wyvern", "Nameless King"], False, 2),
        ("Grand Archives", 3, ["Twin Princes"], True, 2),
        ("Kiln of the First Flame", 3, ["Soul of Cinder"], True, 1),
        ("Painted World of Ariandel", 4, ["Sister Friede"], True, 2),
        ("The Dreg Heap", 4, ["Demon Prince"], True, 2),
        (
            "The Ringed City",
            4,
            ["Halflight, Spear of the Church", "Slave Knight Gael", "Darkeater Midir"],
            True,
            3,
        ),
    ]
    for name, phase, bosses, required, bonfires in areas:
        phase_label = ["Starter", "Early", "Mid", "Late", "DLC"][phase]
        req = "REQUIRED" if required else "optional"
        print(
            f"  [{phase_label}] {name} ({req}, {bonfires} bonfire{'s' if bonfires > 1 else ''})"
        )
        if bosses:
            for b in bosses:
                print(f"    Boss: {b}")


def cmd_bosses(args) -> None:
    print("=== Boss List ===")
    print("  Use --spoilers for full names. Use --required for main path only.")
    all_bosses = [
        ("iudex_gundyr", "Starter", True, 0, "Cemetery of Ash"),
        ("vordt", "Starter", True, 0, "High Wall of Lothric"),
        ("greatwood", "Early", False, 1, "Undead Settlement"),
        ("sage", "Early", True, 1, "Road of Sacrifices"),
        ("deacons", "Early", True, 1, "Cathedral of the Deep"),
        ("abyss_watchers", "Early", True, 1, "Farron Keep"),
        ("wolnir", "Mid", True, 2, "Catacombs of Carthus"),
        ("old_demon_king", "Mid", False, 2, "Smouldering Lake"),
        ("pontiff", "Mid", True, 2, "Irithyll of the Boreal Valley"),
        ("aldrich", "Mid", True, 2, "Anor Londo"),
        ("yhorm", "Mid", True, 2, "Profaned Capital"),
        ("dancer", "Late", True, 2, "High Wall of Lothric"),
        ("oceiros", "Late", False, 3, "Consumed King's Garden"),
        ("champion_gundyr", "Late", False, 3, "Untended Graves"),
        ("dragonslayer_armour", "Late", True, 3, "Lothric Castle"),
        ("twin_princes", "Late", True, 3, "Grand Archives"),
        ("ancient_wyvern", "Late", False, 3, "Archdragon Peak"),
        ("nameless_king", "Late", False, 3, "Archdragon Peak"),
        ("soul_of_cinder", "Late", True, 3, "Kiln of the First Flame"),
        ("sister_friede", "DLC", True, 3, "Painted World of Ariandel"),
        ("demon_prince", "DLC", True, 3, "The Dreg Heap"),
        ("halflight", "DLC", True, 3, "The Ringed City"),
        ("gael", "DLC", True, 3, "The Ringed City"),
        ("midir", "DLC", False, 3, "The Ringed City"),
        ("champion_gravetender", "DLC", False, 3, "Painted World of Ariandel"),
    ]
    if args.required:
        all_bosses = [
            (bid, phase, req, sl, area)
            for bid, phase, req, sl, area in all_bosses
            if req
        ]
    if args.area:
        q = args.area.lower()
        all_bosses = [
            (bid, phase, req, sl, area)
            for bid, phase, req, sl, area in all_bosses
            if q in area.lower()
        ]
    if args.spoilers:
        for bid, phase, req, _, _ in all_bosses:
            print(
                f"  [{phase}] {bid.replace('_', ' ').title()} {'(required)' if req else '(optional)'}"
            )
    else:
        for bid, phase, req, spoiler_level, _ in all_bosses:
            if spoiler_level <= 0 or is_known(bid):
                print(
                    f"  [{phase}] {bid.replace('_', ' ').title()} {'(required)' if req else '(optional)'}"
                )
            else:
                print(
                    f"  [{phase}] A boss you haven't encountered yet {'(required)' if req else '(optional)'}"
                )


def cmd_route(args) -> None:
    print("=== Route Planning ===\n")
    # Boss data: (id, phase, required, spoiler_level)
    all_bosses = [
        ("iudex_gundyr", "Starter", True, 0),
        ("vordt", "Starter", True, 0),
        ("greatwood", "Early", False, 1),
        ("sage", "Early", True, 1),
        ("deacons", "Early", True, 1),
        ("abyss_watchers", "Early", True, 1),
        ("wolnir", "Mid", True, 2),
        ("old_demon_king", "Mid", False, 2),
        ("pontiff", "Mid", True, 2),
        ("aldrich", "Mid", True, 2),
        ("yhorm", "Mid", True, 2),
        ("dancer", "Late", True, 2),
        ("oceiros", "Late", False, 3),
        ("champion_gundyr", "Late", False, 3),
        ("dragonslayer_armour", "Late", True, 3),
        ("twin_princes", "Late", True, 3),
        ("ancient_wyvern", "Late", False, 3),
        ("nameless_king", "Late", False, 3),
        ("soul_of_cinder", "Late", True, 3),
        ("sister_friede", "DLC", True, 3),
        ("demon_prince", "DLC", True, 3),
        ("halflight", "DLC", True, 3),
        ("gael", "DLC", True, 3),
        ("midir", "DLC", False, 3),
        ("champion_gravetender", "DLC", False, 3),
    ]
    if args.defeated:
        defeated_ids = set(bid.strip().lower() for bid in args.defeated.split(","))
        # Show already defeated
        print("  Already defeated:")
        for bid, phase, req, sl in all_bosses:
            if bid in defeated_ids:
                print(f"    ✓ {bid.replace('_', ' ').title()} ({phase})")
        for bid in defeated_ids:
            if bid not in {b[0] for b in all_bosses}:
                print(f"    ? {bid} (unknown ID)")
        # Find next required bosses not yet defeated
        required_bosses = [
            (bid, phase, sl) for bid, phase, req, sl in all_bosses if req
        ]
        next_bosses = [
            (bid, phase, sl)
            for bid, phase, sl in required_bosses
            if bid not in defeated_ids
        ]
        if next_bosses:
            print("\n  Next required boss(es):")
            if args.spoilers:
                for bid, phase, sl in next_bosses[:3]:
                    print(f"    → {bid.replace('_', ' ').title()} ({phase})")
            else:
                phase_hints = {
                    "Starter": "phase 1 (starting area)",
                    "Early": "phase 2 (settlement → cathedral)",
                    "Mid": "phase 3 (catacombs → capital)",
                    "Late": "phase 4 (archives → final area)",
                    "DLC": "the DLC areas",
                }
                hinted = set()
                for bid, phase, sl in next_bosses[:3]:
                    if phase not in hinted:
                        hinted.add(phase)
                        print(
                            f"    → The next required boss awaits in {phase_hints.get(phase, 'an upcoming area')}"
                        )
        else:
            print("\n  All required bosses defeated! Only optional/DLC bosses remain.")
        if not args.spoilers:
            print("\n  Use --spoilers for boss names.")
        return
    if not args.spoilers:
        print("  Route hints (spoiler-safe):")
        print("  1. Starter area → early walled zone")
        print("  2. Settlement → Swamp → Cathedral")
        print("  3. Catacombs → Icy city → Capital")
        print("  4. Late-game castle → Archives → Final area")
        print("  5. DLC accessible from early cathedral and late-game area")
        print(
            "\n  Use --spoilers for full route. Use --defeated for personalized path."
        )
        return
    print(
        "  [Spoiler route omitted — too long for CLI. Use Fextralife Game Progress Route.]"
    )


def cmd_achievements(args) -> None:
    if args.missable:
        print("=== Missable Achievements ===\n")
        print("  These achievements can be permanently missed in a playthrough.")
        print("  Plan ahead or you'll need another NG cycle.\n")

        # Covenant items — all missable since offline farming is the only reliable path
        print(f"  Covenant Items (all missable — offline farming required):")
        print(f"    Proof of Concord Kept x30 (hardest — ~6-10 hours farming)")
        print(f"    Vertebra Shackle x30 (~4-6 hours)")
        print(f"    Sunlight Medal x30 (~1-2 hours via co-op)")
        print(f"    Wolf's Blood Swordgrass x30 (~2-4 hours)")
        print(f"    Human Dregs x10 (~1-2 hours)")
        print(f"    Pale Tongue x10 (~2-3 hours)")

        # Gestures from NPC questlines
        gesture_map: dict[str, str] = {}
        for k, v in NPC_QUESTS.items():
            for p in v.get("provides", []):
                pl = p.lower()
                if "gesture" in pl:
                    for g in p.split(":", 1)[-1].split(","):
                        g = g.strip()
                        if g:
                            gesture_map[g] = v["name"]
        print(
            f"\n  Gestures ({len(gesture_map)} NPC-questline dependent, all missable):"
        )
        for g in sorted(gesture_map):
            print(f"    {g} — {gesture_map[g]}")

        # Rings — +1/+2 variants and covenant rings missable per cycle
        ng_plus = sum(1 for r in RINGS if r.get("ng") == "NG+")
        ng_plus2 = sum(1 for r in RINGS if r.get("ng") == "NG++")
        covenant_rings = [r for r in RINGS if r.get("category") == "covenant"]
        print(f"\n  Rings (missable per NG cycle):")
        print(f"    {ng_plus} +1 rings — only in NG+, missable if not collected")
        print(
            f"    {ng_plus2} NG++ rings — +2 variants plus Life Ring +3, missable if not collected"
        )
        print(
            f"    {len(covenant_rings)} covenant rank rings — rank-locked, offline farming required"
        )
        print(
            f"    Master of Rings requires all 107 base-game rings across 3 NG cycles"
        )

        # Endings — three of four missable per playthrough
        print(f"\n  Endings (3 of 4 missable per playthrough):")
        print(
            f"    1. To Link the First Flame — walk to bonfire after final boss (default)"
        )
        print(
            f"    2. The End of Fire — give Fire Keeper Eyes to Fire Keeper, summon her at end"
        )
        print(f"    3. The Usurpation of Fire — Yuria's questline, need 8 Dark Sigils")
        print(
            f"    4. Unkindled Ending — attack Fire Keeper during End of Fire cutscene"
        )
        print(
            f"  Tip: Save-scum at the final boss for all 3 achievement endings from one kill."
        )

        if args.plat_route:
            print(f"\n  Optimal plat route (missable-aware):")
            print(
                f"  Playthrough 1: Full explore. Get Usurpation ending. Farm covenants."
            )
            print(
                f"  Playthrough 2: Boss rush. Get Link the Fire ending. Collect all +1 rings."
            )
            print(
                f"  Playthrough 3: Boss rush to end. Collect all +2 rings plus the base-game Life Ring +3. Get End of Fire ending."
            )
            print(f"  Save-scum at final boss for all 3 endings from one kill.")
        return

    print(
        "=== Achievements (43 total, base game only) ===\n\n"
        "  DLCs have NO achievements. Platinum is base game only.\n"
        "  Covenant items needed:\n"
        "    Proof of Concord Kept x30 (hardest — ~6-10 hours farming)\n"
        "    Vertebra Shackle x30 (~4-6 hours)\n"
        "    Sunlight Medal x30 (~1-2 hours via co-op)\n"
        "    Wolf's Blood Swordgrass x30 (~2-4 hours)\n"
        "    Human Dregs x10 (~1-2 hours)\n"
        "    Pale Tongue x10 (~2-3 hours)\n"
        "  NG cycles needed: 3 (base rings, NG+ +1 rings, NG++ +2 rings plus Life Ring +3)\n"
        "  Master achievements (spell collections):\n"
        "    Master of Sorcery: 34 base-game sorceries\n"
        "    Master of Miracles: 35 base-game miracles\n"
        "    Master of Pyromancy: 27 base-game pyromancies\n"
        "    DLC spells do NOT count. Use `spells --achievement` for full lists.\n"
        "  Master of Rings: all 107 base-game rings (+0, +1, +2, and NG++ Life Ring +3; DLC +3 rings do not count)"
    )
    if args.plat_route:
        print(f"\n  Optimal plat route:")
        print(f"  Playthrough 1: Full explore. Get Usurpation ending. Farm covenants.")
        print(f"  Playthrough 2: Boss rush. Get Link the Fire ending.")
        print(
            f"  Playthrough 3: Boss rush to end. Collect all +2 rings plus the base-game Life Ring +3. Get End of Fire ending."
        )
        print(f"  Save-scum at final boss for all 3 endings from one kill.")


def cmd_spells(args) -> None:
    """List spells by type, search by name, or filter for achievements."""
    type_key = {
        "sorcery": "sorceries",
        "miracle": "miracles",
        "pyromancy": "pyromancies",
    }

    if args.achievement:
        print("=== Spells for Platinum Achievements ===\n")
        print("  Master of Sorcery (34 sorceries)")
        print("  Master of Miracles (35 miracles)")
        print("  Master of Pyromancy (27 pyromancies)")
        print(f"  Total: 96 spells across 3 achievements\n")
        for cat_key, cat_label in [
            ("sorceries", "Sorceries"),
            ("miracles", "Miracles"),
            ("pyromancies", "Pyromancies"),
        ]:
            spells = SPELLS[cat_key]
            covenant_count = sum(1 for s in spells if s["covenant_locked"])
            print(f"  === {cat_label} ({len(spells)}) ===")
            print(f"  Covenant-locked: {covenant_count}")
            for s in spells:
                cov_mark = " [COVENANT]" if s["covenant_locked"] else ""
                loc = (
                    spoiler_safe(s["location"])
                    if not is_known(s["name"])
                    else s["location"]
                )
                reqs = f"INT {s['int_req']}" if s["int_req"] else ""
                if s["fth_req"]:
                    reqs = (
                        f"{reqs} / FTH {s['fth_req']}"
                        if reqs
                        else f"FTH {s['fth_req']}"
                    )
                if not reqs:
                    reqs = "—"
                print(f"    {s['name']}{cov_mark} [{reqs}] — {s['effect']}")
        _print_static_catalog_note("spell")
        return

    if args.type:
        filtered = []
        for cat_key in [type_key[args.type]]:
            filtered.extend(SPELLS[cat_key])
        print(f"=== {args.type.title()} Spells ({len(filtered)}) ===\n")
        for s in filtered:
            cov_mark = " [COVENANT]" if s["covenant_locked"] else ""
            reqs = f"INT {s['int_req']}" if s["int_req"] else ""
            if s["fth_req"]:
                reqs = f"{reqs} / FTH {s['fth_req']}" if reqs else f"FTH {s['fth_req']}"
            if not reqs:
                reqs = "—"
            print(
                f"  {s['name']}{cov_mark}  [{reqs}]  {s['slots']} slot(s) — {s['fp_cost']} FP"
            )
            print(f"    {s['effect']}")
            print(f"    Location: {s['location']}")
        _print_static_catalog_note("spell")
        return

    if args.name:
        target = args.name.lower()
        for cat_key, cat_label in [
            ("sorceries", "Sorcery"),
            ("miracles", "Miracle"),
            ("pyromancies", "Pyromancy"),
        ]:
            for s in SPELLS[cat_key]:
                if s["name"].lower() == target or target in s["name"].lower():
                    print(f"=== {s['name']} ({cat_label}) ===\n")
                    print(f"  Type: {cat_label}")
                    print(f"  Requirements: INT {s['int_req']} / FTH {s['fth_req']}")
                    print(f"  Slots: {s['slots']}  |  FP Cost: {s['fp_cost']}")
                    print(f"  Effect: {s['effect']}")
                    loc = (
                        spoiler_safe(s["location"])
                        if not is_known(s["name"])
                        else s["location"]
                    )
                    print(f"  Location: {loc}")
                    if s["covenant_locked"]:
                        print(
                            f"  ⚠ Covenant-locked — requires online or offline farming"
                        )
                    _print_static_catalog_note("spell")
                    return
        print(
            f"Spell '{args.name}' not found. Try: spells (to list all) or spells <partial-name>"
        )
        return

    print("=== Spell Catalog ===\n")
    total_spells = 0
    for cat_key, cat_label in [
        ("sorceries", "Sorceries"),
        ("miracles", "Miracles"),
        ("pyromancies", "Pyromancies"),
    ]:
        spells = SPELLS[cat_key]
        total_spells += len(spells)
        covenant_count = sum(1 for s in spells if s["covenant_locked"])
        print(f"  {cat_label}: {len(spells)} ({covenant_count} covenant-locked)")
        for s in spells:
            cov_mark = " ⚑" if s["covenant_locked"] else ""
            reqs = f"INT {s['int_req']}" if s["int_req"] else ""
            if s["fth_req"]:
                reqs = f"{reqs} / FTH {s['fth_req']}" if reqs else f"FTH {s['fth_req']}"
            if not reqs:
                reqs = "—"
            print(
                f"    {s['name']}{cov_mark}  [{reqs} | {s['slots']} slot(s) | {s['fp_cost']} FP]"
            )
    print(f"\n  Total: {total_spells} spells")
    print(
        f"  Use `spells <name>` for details, `spells --type` to filter, `spells --achievement` for plat list"
    )
    _print_static_catalog_note("spell")


def cmd_rings(args) -> None:
    """Rings catalog: list by category, search by name, or filter by build."""
    build_rings = {
        "quality": {
            "Chloranthy Ring",
            "Ring of Favor",
            "Havel's Ring",
            "Ring of Steel Protection",
            "Prisoner's Chain",
            "Life Ring",
            "Wolf Ring",
            "Knight's Ring",
            "Hunter's Ring",
            "Lloyd's Sword Ring",
            "Lloyd's Shield Ring",
            "Pontiff's Right Eye",
            "Pontiff's Left Eye",
            "Hornet Ring",
            "Covetous Silver Serpent Ring",
            "Horsehoof Ring",
            "Leo Ring",
        },
        "strength": {
            "Chloranthy Ring",
            "Ring of Favor",
            "Havel's Ring",
            "Ring of Steel Protection",
            "Prisoner's Chain",
            "Knight's Ring",
            "Wolf Ring",
            "Red Tearstone Ring",
            "Pontiff's Right Eye",
            "Hornet Ring",
            "Covetous Silver Serpent Ring",
            "Horsehoof Ring",
            "Knight Slayer's Ring",
        },
        "dex": {
            "Chloranthy Ring",
            "Ring of Favor",
            "Havel's Ring",
            "Ring of Steel Protection",
            "Prisoner's Chain",
            "Hunter's Ring",
            "Carthus Milkring",
            "Pontiff's Right Eye",
            "Pontiff's Left Eye",
            "Hornet Ring",
            "Flynn's Ring",
            "Leo Ring",
            "Wood Grain Ring",
            "Covetous Silver Serpent Ring",
        },
        "sorcerer": {
            "Bellowing Dragoncrest Ring",
            "Young Dragon Ring",
            "Scholar Ring",
            "Sage Ring",
            "Dusk Crown Ring",
            "Magic Clutch Ring",
            "Darkmoon Ring",
            "Lingering Dragoncrest Ring",
            "Lloyd's Sword Ring",
            "Red Tearstone Ring",
            "Covetous Silver Serpent Ring",
            "Ashen Estus Ring",
            "Aldrich's Sapphire",
            "Deep Ring",
        },
        "pyro": {
            "Great Swamp Ring",
            "Witch's Ring",
            "Sage Ring",
            "Fire Clutch Ring",
            "Dark Clutch Ring",
            "Darkmoon Ring",
            "Lingering Dragoncrest Ring",
            "Lloyd's Sword Ring",
            "Covetous Silver Serpent Ring",
            "Ashen Estus Ring",
        },
        "cleric": {
            "Morne's Ring",
            "Ring of the Sun's First Born",
            "Priestess Ring",
            "Sage Ring",
            "Lightning Clutch Ring",
            "Darkmoon Ring",
            "Lingering Dragoncrest Ring",
            "Lloyd's Sword Ring",
            "Covetous Silver Serpent Ring",
            "Ashen Estus Ring",
            "Saint's Ring",
            "Deep Ring",
            "Aldrich's Sapphire",
        },
        "luck": {
            "Covetous Gold Serpent Ring",
            "Covetous Silver Serpent Ring",
            "Prisoner's Chain",
            "Ring of Favor",
            "Chloranthy Ring",
            "Wolf Ring",
            "Bloodbite Ring",
            "Poisonbite Ring",
        },
    }
    if args.build:
        family = build_rings.get(args.build, set())
        filtered = [
            r for r in RINGS if any(r["name"].startswith(fam) for fam in family)
        ]
        if not filtered:
            print(f"No rings found for build '{args.build}'.")
            return
        print(f"=== Rings for {args.build} build ===\n")
        for r in sorted(filtered, key=lambda x: x["category"] + x["name"]):
            ng_tag = f"[{r['ng']}]" if r["ng"] != "base" else ""
            print(f"  {r['name']:<38} wt={r['weight']:<5} {ng_tag}")
            print(f"    {r['effect']}")
            print(f"    Location: {r['location']}")
            print()
        print(f"  {len(filtered)} rings shown.")
        _print_static_catalog_note("ring")
        return

    if args.name:
        query = args.name.lower()
        matches = [r for r in RINGS if query in r["name"].lower()]
        if not matches:
            print(f"No ring matching '{args.name}' found.")
            return
        if len(matches) > 1:
            print(f"=== {len(matches)} rings matching '{args.name}' ===\n")
        for r in matches:
            ng_tag = f"[{r['ng']}]" if r["ng"] != "base" else "[base]"
            print(f"  {r['name']}")
            print(f"    Effect: {r['effect']}")
            print(f"    Weight: {r['weight']}")
            print(f"    NG cycle: {ng_tag}")
            print(f"    Location: {r['location']}")
            print()
        _print_static_catalog_note("ring")
        return

    print("=== Rings Catalog ===\n")
    category_order = [
        "hp",
        "stamina",
        "equip_load",
        "defense",
        "elemental",
        "damage",
        "covenant",
        "stat",
        "spell",
        "discovery",
        "recovery",
        "utility",
        "resistance",
    ]
    cat_names = {
        "hp": "HP / Life",
        "stamina": "Stamina / Roll",
        "equip_load": "Equip Load / Favor",
        "defense": "Physical Defense",
        "elemental": "Elemental Defense",
        "damage": "Damage Boost (Clutch)",
        "covenant": "Covenant Rewards",
        "stat": "Stat Boost",
        "spell": "Spell Enhancement",
        "discovery": "Item Discovery & Souls",
        "recovery": "HP / FP Recovery",
        "utility": "Combat & General Utility",
        "resistance": "Status Resistance",
    }
    by_cat: dict[str, list[dict]] = {c: [] for c in category_order if c in cat_names}
    for r in RINGS:
        cat = r.get("category", "utility")
        if cat in by_cat:
            by_cat[cat].append(r)
    for cat in category_order:
        rings = by_cat.get(cat, [])
        if not rings:
            continue
        print(f"── {cat_names[cat]} ──")
        for r in rings:
            ng_tag = f" [{r['ng']}]" if r["ng"] != "base" else ""
            print(f"  {r['name']:<38} wt={r['weight']}{ng_tag}")
        print()
    print(
        f"Total: {len(RINGS)} rings. Use 'rings <name>' for detail, 'rings --build <type>' to filter."
    )
    _print_static_catalog_note("ring")


def cmd_npcs(args) -> None:
    if args.name:
        key = args.name.lower()
        if key in NPC_QUESTS:
            n = NPC_QUESTS[key]
            print(f"=== {n['name']} ===")
            print(f"  Location: {spoiler_safe(n.get('location', 'unknown'))}")
            print(f"  Missable: {'Yes' if n.get('missable') else 'No'}")
            if n.get("cutoff"):
                print(f"  Cutoff: {n['cutoff']}")
            if n.get("provides"):
                print(f"  Provides:")
                for p in n["provides"]:
                    print(f"    - {p}")
            if n.get("steps"):
                print(f"  Quest Steps:")
                for i, step in enumerate(n["steps"], 1):
                    print(f"    {i}. {step}")
            _print_static_catalog_note("NPC quest")
            return
        matches = [k for k in NPC_QUESTS if key in k]
        if len(matches) == 1:
            key = matches[0]
            n = NPC_QUESTS[key]
            print(f"=== {n['name']} ===")
            print(f"  Location: {n.get('location', 'unknown')}")
            print(f"  Missable: {'Yes' if n.get('missable') else 'No'}")
            if n.get("cutoff"):
                print(f"  Cutoff: {n['cutoff']}")
            if n.get("provides"):
                print(f"  Provides:")
                for p in n["provides"]:
                    print(f"    - {p}")
            if n.get("steps"):
                print(f"  Quest Steps:")
                for i, step in enumerate(n["steps"], 1):
                    print(f"    {i}. {step}")
            _print_static_catalog_note("NPC quest")
            return
        if matches:
            print(f"Multiple matches for '{args.name}': {', '.join(matches)}")
            return
        print(
            f"NPC '{args.name}' not found. Known NPCs: {', '.join(sorted(NPC_QUESTS.keys()))}"
        )
        return
    if args.missable:
        print("=== Missable NPC Questlines ===\n")
        for key, n in sorted(NPC_QUESTS.items()):
            if n.get("missable"):
                print(f"  {n['name']} ({key}): {n.get('location', 'unknown')}")
                if n.get("cutoff"):
                    print(f"    Cutoff: {n['cutoff']}")
        _print_static_catalog_note("NPC quest")
        return
    print("=== NPC Questlines ===\n")
    for key, n in sorted(NPC_QUESTS.items()):
        miss = " [MISSABLE]" if n.get("missable") else ""
        print(f"  {n['name']} ({key}): {n.get('location', 'unknown')}{miss}")
    print(f"\nUse `npcs <name>` for full questline details.")
    print(f"Use `npcs --missable` for missable-only list.")
    _print_static_catalog_note("NPC quest")
