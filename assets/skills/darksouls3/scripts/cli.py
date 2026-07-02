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
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from cli_catalog import *
from ds3_catalog import *
from ds3_core import *
from ds3_core import CACHE_TTL_HOURS
from ds3_save import (
    BONFIRE_BIT_FLAGS,
    BOSS_FLAGS,
    CLASS_NAMES,
    _bonfire_flags_supported,
    _boss_flags_supported,
    owned_item_names,
    read_bonfires,
    read_bosses,
    read_completion_status,
    read_gestures,
    read_inventory,
    read_missed,
    read_name,
    read_ng_plus,
    read_stats,
)

HEX_BYTE_WIDTH = 2
GUIDE_SEARCH_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
    }
)
SOURCE_USAGE = "Use: sources list | status | policy | explain <key> | refresh [keys...]"
SOURCE_POLICY_LINES: tuple[str, ...] = (
    "=== Source Policy ===",
    "  Local deterministic kernel:",
    (
        "    save parsing, boss/bonfire event flags, spoiler gates, command routing, "
        "stable mechanics, eval fixtures, conservative inventory ID resolution"
    ),
    "  Live or fresh-cache required:",
    (
        "    exact item locations, route/checklist gaps, NPC quest details, "
        "current PC mod/tool status, contested facts, citation/currentness requests"
    ),
    "  Cache semantics:",
    (
        f"    transport cache only; TTL {CACHE_TTL_HOURS}h; "
        "cite source URLs/keys, not cache filenames"
    ),
    "  Bundled catalogs:",
    (
        "    scaffolds for deterministic output and inventory resolution, "
        "not an offline encyclopedia"
    ),
)
THIN_CATALOG_FILES: tuple[str, ...] = (
    "weapons.json",
    "armor.json",
    "rings.json",
    "goods_magic.json",
)
REQUIRED_SOURCE_METADATA_FIELDS: tuple[str, ...] = (
    "name",
    "url",
    "license",
    "source_type",
    "allowed_use",
    "not_allowed_for",
    "risk",
    "machine_readable",
    "copyable",
)
NO_COPY_LICENSE_MARKERS: tuple[str, ...] = (
    "no license",
    "unclear",
    "not verified",
    "community wiki",
)
NON_SAVE_SOURCE_TYPES: tuple[str, ...] = (
    "wiki",
    "calculator",
    "checklist",
    "compatibility-wiki",
    "community-reference",
    "mod-tool",
    "modding-toolchain",
    "reverse-engineering-reference",
    "schema-reference",
)
SAVE_TRUTH_MARKERS: tuple[str, ...] = (
    "save-backed",
    "save backed",
    "save truth",
    "ds30000 truth",
    "parser truth",
)


def _print_source_policy() -> None:
    for line in SOURCE_POLICY_LINES:
        sys.stdout.write(f"{line}\n")


def _resources_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "resources"


def _resource_path(name: str) -> Path:
    return _resources_dir() / name


def _resource_json(name: str) -> object:
    return json.loads(_resource_path(name).read_text(encoding="utf-8"))


GUIDE_DIR = _resources_dir() / "guides" / "ds3_plat_guide"
GUIDE_MANIFEST_PATH = GUIDE_DIR / "ds3-plat-guide.manifest.json"
GUIDE_CHUNKS_PATH = GUIDE_DIR / "ds3-plat-guide.chunks.jsonl"


@dataclass(frozen=True, slots=True)
class GuideChunk:
    row: int
    h: list[str]
    k: str
    t: str

    @property
    def heading_path(self) -> str:
        return " > ".join(self.h) if self.h else "(no heading)"

    def as_json(self) -> dict[str, object]:
        return {"row": self.row, "h": self.h, "k": self.k, "t": self.t}


def _guide_missing(path: Path) -> None:
    print(
        f"Missing DS3 platinum guide corpus: {path}",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _load_guide_manifest() -> dict[str, object]:
    if not GUIDE_MANIFEST_PATH.exists():
        _guide_missing(GUIDE_MANIFEST_PATH)
    data = json.loads(GUIDE_MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print(
            "Invalid DS3 platinum guide manifest: expected JSON object", file=sys.stderr
        )
        raise SystemExit(2)
    return data


def _coerce_guide_chunk(row: int, value: object) -> GuideChunk:
    if not isinstance(value, dict):
        print(
            f"Invalid DS3 platinum guide chunk at row {row}: expected object",
            file=sys.stderr,
        )
        raise SystemExit(2)
    headings = value.get("h")
    kind = value.get("k")
    text = value.get("t")
    if (
        not isinstance(headings, list)
        or not all(isinstance(item, str) for item in headings)
        or not isinstance(kind, str)
        or not isinstance(text, str)
    ):
        print(
            f"Invalid DS3 platinum guide chunk at row {row}: expected h/k/t strings",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return GuideChunk(row=row, h=headings, k=kind, t=text)


def _load_guide_chunks() -> list[GuideChunk]:
    if not GUIDE_CHUNKS_PATH.exists():
        _guide_missing(GUIDE_CHUNKS_PATH)
    chunks: list[GuideChunk] = []
    with GUIDE_CHUNKS_PATH.open("r", encoding="utf-8") as handle:
        for row, line in enumerate(handle, start=1):
            if line.strip():
                chunks.append(_coerce_guide_chunk(row, json.loads(line)))
    return chunks


def _guide_snippet(
    text: str, terms: list[str] | None = None, *, width: int = 240
) -> str:
    compact = " ".join(text.split())
    if len(compact) <= width:
        return compact
    start = 0
    for term in terms or []:
        found = compact.lower().find(term.lower())
        if found >= 0:
            start = max(0, found - 60)
            break
    end = min(len(compact), start + width)
    prefix = "..." if start else ""
    suffix = "..." if end < len(compact) else ""
    return f"{prefix}{compact[start:end]}{suffix}"


def _guide_header() -> str:
    return "Source: Dark Souls III - Platinum Walkthrough (local generated corpus; spoiler-heavy, non-authoritative)."


def _guide_tokens(query: str) -> list[str]:
    tokens = [token.lower() for token in re.findall(r"[A-Za-z0-9']+", query)]
    filtered = [
        token
        for token in tokens
        if token not in GUIDE_SEARCH_STOPWORDS and (len(token) > 1 or token.isdigit())
    ]
    return filtered or tokens[:1]


def _guide_fts_query(tokens: list[str]) -> str:
    return " ".join(f'"{token}"' for token in tokens)


def _guide_matches_filters(
    chunk: GuideChunk, kind: str | None, heading: str | None
) -> bool:
    if kind and chunk.k.lower() != kind.lower():
        return False
    if heading and heading.lower() not in chunk.heading_path.lower():
        return False
    return True


def _search_guide_fts(
    chunks: list[GuideChunk],
    tokens: list[str],
    *,
    kind: str | None,
    heading: str | None,
    limit: int,
) -> list[tuple[GuideChunk, str]]:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE guide USING fts5(heading, kind, text)")
        conn.executemany(
            "INSERT INTO guide(rowid, heading, kind, text) VALUES (?, ?, ?, ?)",
            ((chunk.row, chunk.heading_path, chunk.k, chunk.t) for chunk in chunks),
        )
        sql = (
            "SELECT rowid, snippet(guide, 2, '[', ']', '...', 32) "
            "FROM guide WHERE guide MATCH ?"
        )
        params: list[object] = [_guide_fts_query(tokens)]
        if kind:
            sql += " AND lower(kind) = lower(?)"
            params.append(kind)
        if heading:
            sql += " AND lower(heading) LIKE lower(?)"
            params.append(f"%{heading}%")
        sql += " ORDER BY bm25(guide) LIMIT ?"
        params.append(limit)
        by_row = {chunk.row: chunk for chunk in chunks}
        return [
            (by_row[int(row)], " ".join(str(snippet).split()))
            for row, snippet in conn.execute(sql, params)
            if int(row) in by_row
        ]
    finally:
        conn.close()


def _python_guide_score(chunk: GuideChunk, tokens: list[str]) -> int:
    heading = chunk.heading_path.lower()
    kind = chunk.k.lower()
    text = chunk.t.lower()
    score = 0
    for token in tokens:
        score += heading.count(token) * 8
        score += kind.count(token) * 4
        score += text.count(token)
    return score


def _guide_contains_all_tokens(chunk: GuideChunk, tokens: list[str]) -> bool:
    haystack = f"{chunk.heading_path} {chunk.k} {chunk.t}".lower()
    return all(token in haystack for token in tokens)


def _search_guide_python(
    chunks: list[GuideChunk],
    tokens: list[str],
    *,
    kind: str | None,
    heading: str | None,
    limit: int,
) -> list[tuple[GuideChunk, str]]:
    ranked: list[tuple[int, int, GuideChunk]] = []
    for chunk in chunks:
        if not _guide_matches_filters(chunk, kind, heading):
            continue
        if not _guide_contains_all_tokens(chunk, tokens):
            continue
        score = _python_guide_score(chunk, tokens)
        if score > 0:
            ranked.append((-score, chunk.row, chunk))
    ranked.sort()
    return [(chunk, _guide_snippet(chunk.t, tokens)) for _, _, chunk in ranked[:limit]]


def _search_guide_chunks(
    chunks: list[GuideChunk],
    query: str,
    *,
    kind: str | None,
    heading: str | None,
    limit: int,
) -> list[tuple[GuideChunk, str]]:
    tokens = _guide_tokens(query)
    if not tokens or limit <= 0:
        return []
    try:
        return _search_guide_fts(
            chunks, tokens, kind=kind, heading=heading, limit=limit
        )
    except sqlite3.Error:
        return _search_guide_python(
            chunks, tokens, kind=kind, heading=heading, limit=limit
        )


def _is_hex_byte_string(value: str) -> bool:
    parts = value.split()
    return bool(parts) and all(
        len(part) == HEX_BYTE_WIDTH
        and all(ch in "0123456789abcdefABCDEF" for ch in part)
        for part in parts
    )


def _text_list(value: object) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    return []


def _source_registry_entries() -> dict[str, object] | None:
    try:
        data = _resource_json("source_registry.json")
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return None
    return entries


def _source_metadata(key: str) -> tuple[dict[str, object] | None, str]:
    entries = _source_registry_entries()
    if entries is None:
        return None, "source_registry.json is missing or invalid"
    entry = entries.get(key)
    if not isinstance(entry, dict):
        return None, f"unknown source key: {key}"
    return entry, ""


def _metadata_claims_save_truth(entry: dict[str, object]) -> bool:
    text = " ".join(_text_list(entry.get("allowed_use"))).lower()
    return any(marker in text for marker in SAVE_TRUTH_MARKERS)


def _audit_source_registry() -> list[str]:
    issues: list[str] = []
    entries = _source_registry_entries()
    if entries is None:
        return ["source_registry.json: expected version 1 object with entries"]
    for key in SOURCES:
        if key not in entries:
            issues.append(f"source_registry.json: missing source key {key}")
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            issues.append(f"source_registry.json {key}: expected object entry")
            continue
        for field in REQUIRED_SOURCE_METADATA_FIELDS:
            if field not in entry:
                issues.append(f"source_registry.json {key}: missing {field}")
        for field in ("name", "url", "license", "source_type", "risk"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                issues.append(f"source_registry.json {key}: invalid {field}")
        for field in ("allowed_use", "not_allowed_for"):
            values = entry.get(field)
            if (
                not isinstance(values, list)
                or not values
                or not all(isinstance(value, str) and value.strip() for value in values)
            ):
                issues.append(f"source_registry.json {key}: invalid {field}")
        for field in ("machine_readable", "copyable"):
            if not isinstance(entry.get(field), bool):
                issues.append(f"source_registry.json {key}: invalid {field}")
        license_text = str(entry.get("license", "")).lower()
        if entry.get("copyable") is True and any(
            marker in license_text for marker in NO_COPY_LICENSE_MARKERS
        ):
            issues.append(
                f"source_registry.json {key}: unlicensed source marked copyable"
            )
        source_type = str(entry.get("source_type", ""))
        if source_type != "save-tool" and _metadata_claims_save_truth(entry):
            issues.append(
                f"source_registry.json {key}: non-save source overclaims save truth"
            )
    return issues


def _print_source_explain(key: str) -> None:
    entry, error = _source_metadata(key)
    if entry is None:
        print(f"Unknown source: {key}" if not error else error)
        return
    print(f"=== Source: {key} ===")
    print(f"Name: {entry.get('name')}")
    print(f"URL: {entry.get('url')}")
    print(f"License: {entry.get('license')}")
    print(f"Type: {entry.get('source_type')}")
    print(f"Machine-readable: {entry.get('machine_readable')}")
    print(f"Copyable: {entry.get('copyable')}")
    for label, field in (
        ("Allowed use", "allowed_use"),
        ("Not allowed for", "not_allowed_for"),
    ):
        values = _text_list(entry.get(field))
        if values:
            print(f"{label}:")
            for value in values:
                print(f"  - {value}")
    risk = entry.get("risk")
    if risk:
        print(f"Risk: {risk}")
    print("Caveat: cite source URLs/keys; cache files are transport artifacts.")


# ── argparse ─────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ds3",
        description="Spoiler-safe Dark Souls 3 companion CLI",
        epilog=(
            "Quick start: ds3 fresh | ds3 softcaps | ds3 origins\n"
            "Explore: ds3 origins | ds3 weapons --all | ds3 rings\n"
            "Completion: ds3 achievements --missable | ds3 covenants darkmoon | "
            "ds3 farm proofs"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp = p.add_subparsers(dest="command")

    sp.add_parser("fresh", help="Show a fresh-start overview")
    sp.add_parser("softcaps", help="Show stat softcap breakpoints")
    op = sp.add_parser("origins", help="List starting classes")
    op.add_argument(
        "filter",
        nargs="?",
        help="Build type filter: quality, str, dex, int, fth, pyro, luck",
    )

    up = sp.add_parser(
        "upgrade", help="Show materials needed for a weapon upgrade level"
    )
    up.add_argument("level", type=int, help="Target upgrade level (1-10)")
    up.add_argument(
        "--type",
        choices=["normal", "twinkling", "scale"],
        default="normal",
        help="Weapon upgrade type",
    )

    wp = sp.add_parser("weapons", help="Show weapon info")
    wp.add_argument("name", nargs="?", help="Weapon name to look up")
    wp.add_argument("--all", action="store_true", help="Show all starter weapons")

    ca = sp.add_parser("calc", help="Calculate approximate weapon AR")
    ca.add_argument("weapon", help="Weapon name")
    ca.add_argument("str", type=int, help="Strength")
    ca.add_argument("dex", type=int, help="Dexterity")
    ca.add_argument(
        "int", type=int, nargs="?", default=10, help="Intelligence (default 10)"
    )
    ca.add_argument("fth", type=int, nargs="?", default=10, help="Faith (default 10)")

    sc = sp.add_parser("soul-cost", help="Calculate souls needed to level")
    sc.add_argument("current", type=int, help="Current soul level")
    sc.add_argument("target", type=int, help="Target soul level")

    es = sp.add_parser("estus", help="Estus Flask information")
    es.add_argument(
        "sub", nargs="?", choices=["shards", "bones", "allotment", "max"], default="max"
    )

    inf = sp.add_parser("infusions", help="Infusion guide")
    inf.add_argument(
        "weapon", nargs="?", help="Weapon name for specific recommendations"
    )
    inf.add_argument(
        "--build",
        choices=[
            "quality",
            "strength",
            "dexterity",
            "sorcerer",
            "pyromancer",
            "cleric",
            "luck",
        ],
        help="Filter by build",
    )

    el = sp.add_parser("equip-load", help="Calculate equip load")
    el.add_argument(
        "--vitality", type=int, default=15, help="Vitality stat level (default 15)"
    )
    el.add_argument("--havels", action="store_true", help="Include Havel's Ring")
    el.add_argument("--favor", action="store_true", help="Include Ring of Favor")

    cv = sp.add_parser("covenants", help="Covenant overview")
    cv.add_argument("id", nargs="?", help="Covenant ID (sunlight, darkmoon, etc.)")
    cv.add_argument(
        "--achievement",
        "--platinum",
        action="store_true",
        help="Show only platinum-relevant covenant rewards",
    )

    np = sp.add_parser("npcs", help="NPC questline guide")
    np.add_argument(
        "name", nargs="?", help="NPC name or key (e.g. greirat, siegward, anri, sirris)"
    )
    np.add_argument("--all", action="store_true", help="Show all NPC questlines")
    np.add_argument(
        "--missable", action="store_true", help="Show only missable questlines"
    )

    fm = sp.add_parser(
        "farm", help="Farming guide for souls, materials, and covenant items"
    )
    fm.add_argument(
        "item",
        nargs="?",
        help="Item to farm: souls, shards, large-shards, chunks, slabs, twinkling, scales, proofs, shackles, medals, grass, dregs, tongues",
    )

    bd = sp.add_parser("build", help="Show build archetype")
    bd.add_argument(
        "type",
        nargs="?",
        choices=[
            "quality",
            "strength",
            "dexterity",
            "sorcerer",
            "pyromancer",
            "cleric",
            "luck",
        ],
        help="Build type",
    )
    bd.add_argument(
        "--level", type=int, default=120, help="Target soul level (default 120)"
    )

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
    ro.add_argument(
        "--spoilers", action="store_true", help="Show full route with boss names"
    )

    ach = sp.add_parser("achievements", help="Achievement guide")
    ach.add_argument(
        "--missable", action="store_true", help="Show only missable achievements"
    )
    ach.add_argument(
        "--plat-route", action="store_true", help="Show optimal platinum route overview"
    )

    md = sp.add_parser("mods", help="Mod recommendations")
    md.add_argument(
        "--current",
        action="store_true",
        help="Show current mod awareness (legit vs cracked)",
    )

    sp2 = sp.add_parser("spells", help="Spell catalog")
    sp2.add_argument("name", nargs="?", help="Spell name to look up")
    sp2.add_argument(
        "--type",
        choices=["sorcery", "miracle", "pyromancy"],
        help="Filter by spell type",
    )
    sp2.add_argument(
        "--achievement",
        action="store_true",
        help="List all spells needed for platinum Master achievements",
    )

    sp.add_parser("audit", help="Run self-consistency checks")

    tr = sp.add_parser("track", help="Show tracking file summary")
    tr.add_argument(
        "section",
        nargs="?",
        choices=["summary", "stats", "gear", "next"],
        help="Section to show",
    )
    tr.add_argument("--path", required=True, help="Path to tracking JSON file")

    rc = sp.add_parser("recommend", help="Recommendations based on tracking file")
    rc.add_argument("--path", required=True, help="Path to tracking JSON file")

    src = sp.add_parser("sources", help="Source registry")
    src_sub = src.add_subparsers(dest="sources_action")
    src_sub.add_parser("list", help="List all registered sources")
    src_sub.add_parser("status", help="Show cache status")
    src_sub.add_parser("policy", help="Show live-vs-local source policy")
    src_ex = src_sub.add_parser("explain", help="Explain one source key")
    src_ex.add_argument("key", help="Source key to explain")
    src_rf = src_sub.add_parser("refresh", help="Refresh cached sources")
    src_rf.add_argument(
        "keys", nargs="*", help="Source keys to refresh (all if omitted)"
    )
    src_rf.add_argument(
        "--force", action="store_true", help="Force refresh even if not stale"
    )

    guide = sp.add_parser(
        "guide", help="Look up the spoiler-heavy generated platinum guide corpus"
    )
    guide_sub = guide.add_subparsers(dest="guide_action")
    guide_sub.add_parser("info", help="Show guide corpus metadata")
    guide_sub.add_parser("kinds", help="List chunk kinds")
    guide_sub.add_parser("headings", help="List heading paths")
    guide_get = guide_sub.add_parser("get", help="Get one guide chunk by 1-based row")
    guide_get.add_argument("row", type=int, help="1-based JSONL row number")
    guide_get.add_argument("--json", action="store_true", help="Print JSON object")
    guide_search = guide_sub.add_parser("search", help="Search the guide corpus")
    guide_search.add_argument("query", nargs="+", help="Search terms")
    guide_search.add_argument("--kind", help="Filter by exact chunk kind")
    guide_search.add_argument("--heading", help="Filter by heading path substring")
    guide_search.add_argument(
        "--limit", type=int, default=8, help="Maximum rows to print"
    )
    guide_search.add_argument("--json", action="store_true", help="Print JSON array")
    ri = sp.add_parser(
        "rings", help="Rings catalog: browse, search, or filter by build"
    )
    ri.add_argument(
        "name", nargs="?", help="Ring name to search (case-insensitive substring match)"
    )
    ri.add_argument(
        "--build",
        choices=["quality", "strength", "dex", "sorcerer", "pyro", "cleric", "luck"],
        help="Filter rings by build archetype",
    )
    ri.add_argument(
        "--spoilers",
        action="store_true",
        help="Show exact locations, including future/DLC areas",
    )

    sp_save = sp.add_parser("save", help="Read save file data")
    sp_save.add_argument(
        "save_path",
        nargs="?",
        default="auto",
        help="Path to DS30000.sl2 file (or 'auto' to auto-detect)",
    )
    sp_save.add_argument(
        "action",
        nargs="?",
        default="summary",
        choices=[
            "summary",
            "stats",
            "name",
            "level",
            "covenants",
            "bosses",
            "bonfires",
            "progress",
            "inventory",
            "gestures",
            "missed",
            "achievements",
            "checklist",
            "owned",
            "completion",
        ],
        help="Action to perform",
    )
    sp_save.add_argument(
        "--spoilers",
        action="store_true",
        help="Show locked/remaining future names in save-backed progress",
    )
    sp_save.add_argument(
        "--all",
        action="store_true",
        help="Show all resolved inventory/owned names instead of the compact sample",
    )
    sp_save.add_argument(
        "--find",
        metavar="TEXT",
        help="Filter inventory/owned output by case-insensitive text",
    )
    return p


# ── Command handlers ─────────────────────────────────────────────


def _print_guide_chunk(chunk: GuideChunk, snippet: str | None = None) -> None:
    print(f"Row {chunk.row}: {chunk.heading_path}")
    print(f"Kind: {chunk.k}")
    print(f"Text: {snippet if snippet is not None else _guide_snippet(chunk.t)}")


def _print_guide_matches(matches: list[tuple[GuideChunk, str]]) -> None:
    print(_guide_header())
    if not matches:
        print("No guide rows matched.")
        return
    for index, (chunk, snippet) in enumerate(matches, start=1):
        if index > 1:
            print()
        _print_guide_chunk(chunk, snippet)


def cmd_guide(args) -> None:
    action = args.guide_action
    if not action:
        print("Use: guide info | kinds | headings | get ROW [--json] | search QUERY...")
        return

    if action == "info":
        manifest = _load_guide_manifest()
        chunks = _load_guide_chunks()
        print(_guide_header())
        print(f"Title: {manifest.get('title', 'Unknown')}")
        print(f"Author: {manifest.get('author', 'Unknown')}")
        print(f"URL: {manifest.get('url', 'Unknown')}")
        print(f"Updated: {manifest.get('updated', 'Unknown')}")
        print(f"Chunks: {len(chunks)}")
        print(
            "Caveat: spoiler-heavy local lookup; verify against primary sources when citing."
        )
        return

    chunks = _load_guide_chunks()
    if action == "kinds":
        counts: dict[str, int] = {}
        for chunk in chunks:
            counts[chunk.k] = counts.get(chunk.k, 0) + 1
        print(_guide_header())
        for kind, count in sorted(counts.items()):
            print(f"{kind}: {count}")
        return

    if action == "headings":
        print(_guide_header())
        seen: set[str] = set()
        for chunk in chunks:
            heading = chunk.heading_path
            if heading not in seen:
                seen.add(heading)
                print(heading)
        return

    if action == "get":
        row = args.row
        if row < 1 or row > len(chunks):
            print(
                f"Guide row out of range: {row} (valid: 1-{len(chunks)})",
                file=sys.stderr,
            )
            raise SystemExit(2)
        chunk = chunks[row - 1]
        if args.json:
            print(json.dumps(chunk.as_json(), ensure_ascii=False))
        else:
            print(_guide_header())
            _print_guide_chunk(chunk, chunk.t)
        return

    if action == "search":
        query = " ".join(args.query)
        matches = _search_guide_chunks(
            chunks,
            query,
            kind=args.kind,
            heading=args.heading,
            limit=args.limit,
        )
        if args.json:
            print(
                json.dumps(
                    [
                        chunk.as_json() | {"snippet": snippet}
                        for chunk, snippet in matches
                    ],
                    ensure_ascii=False,
                )
            )
        else:
            _print_guide_matches(matches)
        return

    print("Use: guide info | kinds | headings | get ROW [--json] | search QUERY...")


def cmd_fresh(args) -> None:
    print(
        "Welcome to Dark Souls 3, Ashen One.\n"
        "\n"
        "You are at the Cemetery of Ash. Light the first bonfire.\n"
        "\n"
        "Layered early priorities:\n"
        "  - Survival first: level VGR early; 20 is comfortable.\n"
        "  - VGR 27 is the first big HP target when you want more cushion.\n"
        "  - Keep equip load under 70% for a medium roll; add VIT or lighter gear.\n"
        "  - Meet requirements for the weapon, catalyst, or tool you want to use.\n"
        "  - Upgrade one main tool before spreading upgrade materials widely.\n"
        "  - Choose stats that serve your plan: STR/DEX for physical weapons; "
        "INT/FTH/ATT for spells, FP, or utility; LCK for status setups.\n"
        "  - Focus a lane first, then branch once the core works.\n"
        "\n"
        "Key commands to get started:\n"
        "  ds3 softcaps  — stat breakpoints to plan your build\n"
        "  ds3 origins   — view starting classes and their stats\n"
        "  ds3 weapons   — weapon lookup and comparison\n"
        "  ds3 estus     — flask shard and bone shard details"
    )


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
        "str": "warrior",
        "strength": "warrior",
        "dex": "mercenary",
        "dexterity": "mercenary",
        "int": "sorcerer",
        "fth": "cleric",
        "faith": "cleric",
        "pyro": "pyromancer",
        "pyromancer": "pyromancer",
        "luck": "thief",
    }
    target_class = build_to_class.get(filt, "")
    print(
        f"{'Class':<14} {'LV':>3} {'VGR':>4} {'ATT':>4} {'END':>4} {'VIT':>4} {'STR':>4} {'DEX':>4} {'INT':>4} {'FTH':>4} {'LCK':>4}"
    )
    print("-" * 64)
    for name, o in ORIGINS.items():
        if filt == "" or name == target_class or filt in name:
            print(
                f"{name.title():<14} {o['level']:>3} {o['vig']:>4} {o['att']:>4} {o['end']:>4} {o['vit']:>4} {o['str']:>4} {o['dex']:>4} {o['int']:>4} {o['fth']:>4} {o['lck']:>4}"
            )
    if filt:
        matching = [n for n in ORIGINS if n == target_class or filt in n]
        if not matching:
            print(
                f"\nNo class matches '{args.filter}'. Available filters: quality, str, dex, int, fth, pyro, luck"
            )


def cmd_upgrade(args) -> None:
    path = {
        "normal": UPGRADE_NORMAL,
        "twinkling": UPGRADE_TWINKLING,
        "scale": UPGRADE_SCALE,
    }[args.type]
    max_lvl = len(path)
    level = min(args.level, max_lvl)
    print(f"=== Upgrade path: {args.type} ===")
    if args.level > max_lvl:
        print(
            f"  Warning: Max upgrade for {args.type} is +{max_lvl}. Showing cost to max."
        )
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
    if (
        args.current < 1
        or args.target <= args.current
        or args.current < 0
        or args.target < 0
    ):
        print(
            "Invalid: current level must be 1 or higher, target must be greater than current."
        )
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
        print(
            f"  Estus Shards: {ESTUS_SHARDS_MAX} total. Each shard adds one flask use, up to 15 total flasks."
        )
        print(
            "  Early checklist: Firelink rafters, High Wall anvil room, Undead Settlement burning tree, Road/woods ruins, Farron swamp fallen tower."
        )
        print(
            "  Use save auto summary for current flask count; exact shard pickup flags are not save-backed."
        )
        return
    if sub == "bones":
        print(
            f"  Undead Bone Shards: {BONE_SHARDS_MAX} total. Burn at Firelink bonfire to improve healing, up to Estus +10."
        )
        print(
            "  Early checklist: Undead Settlement white birch tree, Farron Keep slug tower, Cathedral graveyard route."
        )
        print(
            "  Use save auto missed for current-area checklist hints; exact bone pickup flags are not save-backed."
        )
        return
    if sub == "allotment":
        print(
            "  Allotment: talk to the blacksmith to split total flasks between HP Estus and FP/Ashen Estus."
        )
        print(
            "  Pure melee usually wants mostly/all HP Estus; casters and weapon-art-heavy builds may reserve FP flasks."
        )
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
        if args.havels:
            rings.append("Havel's Ring (+15%)")
        if args.favor:
            rings.append("Ring of Favor (+5%)")
        print(f"  Rings: {', '.join(rings)}")


def _covenant_achievement_rewards(covenant: dict) -> list[tuple[str, str]]:
    """Return covenant rank rewards that count toward base-game achievements."""
    rewards: list[tuple[str, str]] = []
    for rank, label in (("rank10", "Rank 1"), ("rank30", "Rank 2")):
        reward = covenant.get(rank)
        if not reward:
            continue
        text = str(reward).lower()
        if any(
            token in text
            for token in ("ring", "miracle", "sorcery", "pyromancy", "platinum")
        ):
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
        print(
            f"Covenant '{args.id}' not found. IDs: {', '.join(c['id'] for c in COVENANTS)}"
        )
        return
    title = (
        "Covenants — base-game platinum rewards" if achievement_only else "Covenants"
    )
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
            note = (
                "DLC covenant; not base-platinum"
                if c["id"] == "spears"
                else "not rank-reward relevant"
            )
            print(f"    {c['name']} ({c['id']}): {note}")
    print()
    print("See also: farm, achievements")


def cmd_farm(args) -> None:
    farming: dict[str, tuple[str, str]] = {
        "souls": (
            "Souls",
            "Early: Tower on the Wall Lothric Knight loop for safe souls plus titanite practice. Early-mid: giant-arrow cleanup in the settlement if unlocked; lazy but effective. Mid: Farron Keep Perimeter enemy-vs-enemy loop; rest, repeat, and let enemies damage each other. Equip Covetous Silver Serpent Ring if owned. Farm only to cover Vigor breakpoints, weapon upgrades, infusion fees, or a specific level gap; upgrades usually beat grinding raw levels.",
        ),
        "shards": (
            "Titanite Shard",
            "Early-game pickups and common early enemies. Handmaid sells after the early ash; use guaranteed pickups before farming.",
        ),
        "large-shards": (
            "Large Titanite Shard",
            "Mid-game pickups/enemies. Handmaid sells after the mid-game ash; farm only after guaranteed pickups dry up.",
        ),
        "chunks": (
            "Titanite Chunk",
            "Late-game enemies. Handmaid sells after late-game ash. Rare drop.",
        ),
        "slabs": (
            "Titanite Slab",
            "Fixed pickups only (8 per NG in base game, more in DLC). Cannot be farmed from enemies.",
        ),
        "twinkling": (
            "Twinkling Titanite",
            "Crystal lizards throughout the world. Handmaid sells after late-game ash.",
        ),
        "scales": (
            "Titanite Scale",
            "Crystal lizards near boss areas. Handmaid sells after late-game ash.",
        ),
        "proofs": (
            "Proof of Concord Kept",
            "Silver Knight stair farm. ~1% base drop. Base-game setup: Symbol of Avarice + Gold Serpent Ring + Crystal Sage Rapier + Rusted Coins + LCK. DLC +3 ring is optional, not platinum-required.",
        ),
        "shackles": (
            "Vertebra Shackle",
            "Skeletons in catacombs (mid-game area). ~1% drop. ~4-6 hours offline.",
        ),
        "medals": (
            "Sunlight Medal",
            "Lothric Knights (mid-game castle). ~3% drop. Faster via co-op.",
        ),
        "grass": (
            "Wolf's Blood Swordgrass",
            "3 Ghru enemies at bonfire (early swamp). ~3% drop. ~2-4 hours.",
        ),
        "dregs": (
            "Human Dregs",
            "Deacons on an upper balcony (mid-game castle). ~5% drop. ~1-2 hours.",
        ),
        "tongues": ("Pale Tongue", "Darkwraiths (early swamp). ~3% drop. ~2-3 hours."),
    }
    if not args.item:
        print("=== Farm Targets ===\n")
        for key, (name, guide) in farming.items():
            print(f"  {name} ({key}): {guide.split('.')[0]}.")
        print(
            f"\n  Use 'ds3 farm <item>' for details. Items: {', '.join(sorted(farming.keys()))}"
        )
        return
    item = args.item.lower()
    if item in farming:
        name, guide = farming[item]
        print(f"=== {name} Farm ===")
        print(f"  {guide}")
        if item == "proofs":
            print(
                "  Best optional boost if DLC is available: Gold Serpent Ring +3. DLC gear is not required for platinum."
            )
    else:
        print(f"Unknown item: {args.item}")
        print(f"Try: {', '.join(sorted(farming.keys()))}")


def cmd_build(args) -> None:
    if not args.type:
        print(
            "=== Build Archetype Examples ===\n\n"
            "  These are planning templates, not defaults; pick or adapt one to "
            "match your weapon, spell, status, or utility plan.\n"
        )
        for name, b in BUILDS.items():
            print(
                f"  {name.title()}: example start {b['class'].title()} -> {b['note']}"
            )
        print("\n  Use `build <type>` for that template's stat targets.")
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
    print(
        f"  Damage: STR {b.get('str', 10)} / DEX {b.get('dex', 10)} / INT {b.get('int', 10)} / FTH {b.get('fth', 10)}"
    )
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
    a = STARTER_WEAPONS[wa]
    b = STARTER_WEAPONS[wb]
    stats = {"str": args.str, "dex": args.dex, "int": args.int, "fth": args.fth}
    ar_a = weapon_ar(a, stats)
    ar_b = weapon_ar(b, stats)
    print(f"=== {wa.title()} vs {wb.title()} ===")
    print(
        f"  Stats: STR {stats['str']} / DEX {stats['dex']} / INT {stats['int']} / FTH {stats['fth']}"
    )
    print(
        f"  {wa.title()}: {a['base_damage']} base, {a['str_scale']}/{a['dex_scale']}, ~{ar_a} AR, {a['weight']} wt"
    )
    print(
        f"  {wb.title()}: {b['base_damage']} base, {b['str_scale']}/{b['dex_scale']}, ~{ar_b} AR, {b['weight']} wt"
    )
    print(
        f"  Winner: {wa.title() if ar_a >= ar_b else wb.title()} ({abs(ar_a - ar_b)} AR difference)"
    )


def cmd_mods(args) -> None:
    print(
        "=== Mod Tools & Launchers ===\n"
        "\n"
        "  Mod Engine 1 (dinput8.dll passive proxy)\n"
        "    Mechanism: game loads dinput8.dll from folder; loads mod/ overrides\n"
        "    Compatibility: works with cracked + legit copies, no injection\n"
        "    Repo: github.com/katalash/ModEngine (GPL-3.0)\n"
        "\n"
        "  Mod Engine 2 (ME2, external launcher)\n"
        "    Mechanism: launcher injects modengine2.dll via CreateRemoteThread\n"
        "    Compatibility: legit Steam copies; may fail on cracked (CODEX blocks)\n"
        "    Repo: github.com/soulsmods/ModEngine2\n"
        "\n"
        "  Mod Engine 3 (ME3, external launcher)\n"
        "    Mechanism: profile-based mod loading, DLL injection\n"
        "    Compatibility: legit Steam copies only; CODEX blocks CreateRemoteThread\n"
        "    Repo: github.com/garyttierney/me3 (MIT)\n"
        "\n"
        "=== Common Utility Mods ===\n"
        "\n"
        "  Proper PC Experience (#1545): FPS unlock, FoV, refresh rate, skip intros\n"
        "  FromStutterFix: general FromSoft frame-pacing fix (github.com/kh0nsu)\n"
        "  Blue Sentinel (#723): anti-cheat + player overlay + save backups (online-safe)\n"
        "  Camera Fix (#2028): disable auto camera rotation (requires ME2/ME3)\n"
        "  PS4 Controller Icons (#278): replace Xbox glyphs with PlayStation glyphs\n"
        "\n"
        "  All mod data from Nexus Mods + GitHub. Use live research for latest versions."
    )


def cmd_audit(args) -> None:
    print("=== Audit ===")
    issues = []
    if len(ORIGINS) != 10:
        issues.append(f"ORIGINS: expected 10 classes, got {len(ORIGINS)}")
    for name, o in ORIGINS.items():
        keys = {"level", "vig", "att", "end", "vit", "str", "dex", "int", "fth", "lck"}
        if set(o.keys()) != keys:
            issues.append(f"ORIGINS {name}: unexpected keys {set(o.keys()) ^ keys}")
    expected_stats = {
        "vigor",
        "attunement",
        "endurance",
        "vitality",
        "strength",
        "dexterity",
        "intelligence",
        "faith",
        "luck",
    }
    if set(SOFTCAPS.keys()) != expected_stats:
        issues.append(
            f"SOFTCAPS keys mismatch: {set(SOFTCAPS.keys()) ^ expected_stats}"
        )
    if len(INFUSIONS) != 15:
        issues.append(f"INFUSIONS: expected 15, got {len(INFUSIONS)}")
    if len(COVENANTS) != 9:
        issues.append(f"COVENANTS: expected 9, got {len(COVENANTS)}")
    expected_spells = {"sorceries": 34, "miracles": 35, "pyromancies": 27}
    for cat, expected in expected_spells.items():
        actual = len(SPELLS.get(cat, []))
        if actual != expected:
            issues.append(f"SPELLS {cat}: expected {expected}, got {actual}")
    for name in THIN_CATALOG_FILES:
        try:
            data = _resource_json(name)
        except (json.JSONDecodeError, OSError) as exc:
            issues.append(f"{name}: cannot read thin catalog ({exc})")
            continue
        if not isinstance(data, dict):
            issues.append(f"{name}: expected object mapping names to hex IDs")
            continue
        for item_name, item_id in data.items():
            if not isinstance(item_name, str) or not isinstance(item_id, str):
                issues.append(
                    f"{name}: thin catalog must map string names to string hex IDs"
                )
                break
            if not _is_hex_byte_string(item_id):
                issues.append(f"{name}: invalid hex ID for {item_name!r}")
                break
    issues.extend(_audit_source_registry())
    if issues:
        for i in issues:
            print(f"  FAIL: {i}")
    else:
        print("  All data integrity checks passed.")
    print(f"  Sources: {len(SOURCES)} registered")
    print(f"  Builds: {len(BUILDS)} archetypes")
    print(f"  Starter weapons: {len(STARTER_WEAPONS)}")
    print(
        f"  Spells: {sum(len(v) for v in SPELLS.values())} total "
        f"({len(SPELLS['sorceries'])} sorceries, {len(SPELLS['miracles'])} miracles, "
        f"{len(SPELLS['pyromancies'])} pyromancies)"
    )
    print(f"  Rings: {len(RINGS)} total")


def cmd_sources(args) -> None:
    action = args.sources_action
    if action == "list":
        print(f"=== Registered Sources ({len(SOURCES)}) ===\n")
        for key, s in SOURCES.items():
            print(f"  {key}: {s.url} ({s.license})")
            print(f"    Use: {s.use}")
            if s.risk:
                print(f"    Risk: {s.risk}")
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
                print(
                    f"  {f.stem}: {age_h:.1f}h old ({'stale' if age_h > CACHE_TTL_HOURS else 'fresh'})"
                )
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                print(f"  {f.stem}: invalid cache entry ({exc})")
    elif action == "policy":
        _print_source_policy()
    elif action == "explain":
        _print_source_explain(args.key)
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
        print(SOURCE_USAGE)


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
        print(
            f"  Stats: VGR {s.get('vig', '?')} / ATT {s.get('att', '?')} / END {s.get('end', '?')}"
        )
        print(
            f"         VIT {s.get('vit', '?')} / STR {s.get('str', '?')} / DEX {s.get('dex', '?')}"
        )
        print(
            f"         INT {s.get('int', '?')} / FTH {s.get('fth', '?')} / LCK {s.get('lck', '?')}"
        )
        print(
            f"  Estus: {data.get('estus_shards', 0)}/11 shards, {data.get('bone_shards', 0)}/10 bones"
        )
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
        print(
            "Route suggestions based on tracking file... (needs boss ID cross-reference)"
        )


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
        print(
            f"  Priority: Level VGR to 27 (currently {stats.get('vig', 0)}). That's the first softcap."
        )
    if stats.get("end", 0) < 20 and sl > 30:
        print(f"  Consider leveling END to 20+ (currently {stats.get('end', 0)}).")
    highest_dmg = max(
        stats.get("str", 0),
        stats.get("dex", 0),
        stats.get("int", 0),
        stats.get("fth", 0),
    )
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


def _print_owned_items(
    save_path: str, *, show_all: bool = False, find: str | None = None
) -> None:
    names = owned_item_names(save_path)
    print("=== Owned Items ===")
    if isinstance(names, dict):
        for key in ("rings", "spells", "goods", "weapons"):
            values = names.get(key, [])
            if not isinstance(values, (set, list, tuple)):
                continue
            ordered = sorted(str(value) for value in values)
            if find:
                needle = find.casefold()
                ordered = [name for name in ordered if needle in name.casefold()]
            label = key.replace("_", " ").title()
            print(f"  {label}: {len(ordered)} owned")
            if ordered:
                shown = ordered if show_all else ordered[:12]
                suffix = "" if show_all or len(ordered) <= 12 else " ..."
                print("    " + ", ".join(shown) + suffix)
        return
    if isinstance(names, (set, list, tuple)):
        ordered = sorted(str(value) for value in names)
        if find:
            needle = find.casefold()
            ordered = [name for name in ordered if needle in name.casefold()]
        print(f"  Items: {len(ordered)} owned")
        if ordered:
            shown = ordered if show_all else ordered[:20]
            suffix = "" if show_all or len(ordered) <= 20 else " ..."
            print("    " + ", ".join(shown) + suffix)
        return
    print("  Owned item helper returned no printable data.")


def _completion_checklist() -> dict[str, list[str]]:
    from ds3_save import read_completion_checklist

    return read_completion_checklist()


def _print_name_sample(
    items: list[dict], limit: int = 12, *, show_all: bool = False, find: str | None = None
) -> None:
    names = sorted(str(item.get("name", "Unknown")) for item in items)
    if find:
        needle = find.casefold()
        names = [name for name in names if needle in name.casefold()]
    if names:
        shown = names if show_all else names[:limit]
        suffix = "" if show_all or len(names) <= limit else " ..."
        print("    " + ", ".join(shown) + suffix)


def _print_inventory(
    save_path: str, *, show_all: bool = False, find: str | None = None
) -> None:
    inv = read_inventory(save_path)
    print(f"=== Inventory: {inv['total_items']} resolved items ===")
    for label, key in (
        ("Weapons", "weapons"),
        ("Armor", "armor"),
        ("Rings", "rings"),
        ("Goods", "goods"),
    ):
        items = inv.get(key, [])
        if find:
            needle = find.casefold()
            items = [
                item
                for item in items
                if needle in str(item.get("name", "Unknown")).casefold()
            ]
        print(f"  {label}: {len(items)}")
        _print_name_sample(items, show_all=show_all, find=None)


def _tracked_boss_names() -> list[str]:
    return [str(name) for name in BOSS_FLAGS]


def _tracked_bonfire_names() -> list[str]:
    return sorted(f"{item['area']} - {item['name']}" for item in BONFIRE_BIT_FLAGS)


def _print_unsupported_event_flags(
    kind: str, names: list[str], *, spoilers: bool = False
) -> None:
    print(f"  {kind}: save-backed event flag region unsupported")
    if names and spoilers:
        print("  Tracked names (status unknown):")
        for name in names:
            print(f"    - {name}")
    elif names:
        print(
            f"  {len(names)} tracked names hidden. Use --spoilers to show unknown/future names."
        )


def _print_save_flag_caveat() -> None:
    print(
        "  Note: read-only save parse; boss/bonfire status uses known event flags only."
    )
    print(
        "  Remaining/locked means not observed in tracked flags, not a miss/lockout proof."
    )


def _max_weapon_label(stats: dict) -> str:
    value = stats.get("maxWeaponReinforcement")
    if isinstance(value, int):
        return f"+{value}"
    return "unsupported"


def _print_save_overview(save_path: str, stats: dict, *, include_stats: bool) -> None:
    boss_flags_supported = _boss_flags_supported()
    bonfire_flags_supported = _bonfire_flags_supported()
    print(f"=== {read_name(save_path)} ===")
    journey = read_ng_plus(save_path)
    journey_label = "NG" if journey == 0 else f"NG+{journey}"
    print(
        f"  Class: {CLASS_NAMES.get(stats['class_'], 'Unknown')}  |  SL: {stats['soulLevel']}  |  Journey: {journey_label}  |  Souls: {stats['souls']:,}"
    )
    print(
        f"  Estus: {stats['estusAllocation']} HP / {stats['ashenEstusAllocation']} FP  |  Max weapon: {_max_weapon_label(stats)}"
    )
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
    stat_names = [
        ("VGR", "vigor"),
        ("ATT", "attunement"),
        ("END", "endurance"),
        ("VIT", "vitality"),
        ("STR", "strength"),
        ("DEX", "dexterity"),
        ("INT", "intelligence"),
        ("FTH", "faith"),
        ("LCK", "luck"),
    ]
    if include_stats:
        print(
            "  Stats: "
            + "  ".join(f"{label} {stats[key]}" for label, key in stat_names)
        )
        print(
            f"  HP: {stats['health']}/{stats['maxHealth']}  |  FP: {stats['mana']}/{stats['maxMana']}  |  Stamina: {stats['stamina']}/{stats['maxStamina']}"
        )
        print(
            f"  Hollowing: {stats['hollow']}  |  Base item discovery: {100 + stats['luck']}"
        )
    else:
        first = stat_names[:5]
        second = stat_names[5:]
        print("  " + "  ".join(f"{label}: {stats[key]:>2}" for label, key in first))
        print("  " + "  ".join(f"{label}: {stats[key]:>2}" for label, key in second))


def _print_missed_result(missed: dict[str, object]) -> None:
    area = missed.get("current_area") or "Unknown"
    print(f"=== Missed: {area} ===")
    checklist_available = missed.get("checklist_available", True)
    missing_bosses = [
        str(boss) for boss in missed.get("missing_bosses", []) if isinstance(boss, str)
    ]
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
    if (
        missed.get("estus_shards_supported") is True
        and isinstance(estus_found, int)
        and isinstance(estus_total, int)
    ):
        print(f"  Estus shards: {estus_found}/{estus_total} found (save-backed)")
    elif isinstance(estus_total, int) and estus_total > 0:
        print(
            f"  Estus shards: {estus_total} checklist entries (save-backed count unsupported)"
        )
    else:
        print("  Estus shards: save-backed count unsupported")
    bones_found = missed.get("bone_shards_found")
    bones_total = missed.get("bone_shards_total")
    if (
        missed.get("bone_shards_supported") is True
        and isinstance(bones_found, int)
        and isinstance(bones_total, int)
    ):
        print(f"  Undead bone shards: {bones_found}/{bones_total} found (save-backed)")
    elif isinstance(bones_total, int) and bones_total > 0:
        print(
            f"  Undead bone shards: {bones_total} checklist entries (save-backed count unsupported)"
        )
    else:
        print("  Undead bone shards: save-backed count unsupported")


def _print_save_achievements(save_path: str) -> None:
    from ds3_save import read_completion_checklist

    has_status = _print_completion_status(save_path)
    checklist = read_completion_checklist()
    print(
        "=== Completion Checklist ==="
        if not has_status
        else "\n=== Completion Checklist ==="
    )
    if _boss_flags_supported():
        bosses = read_bosses(save_path)
        defeated = [boss for boss in bosses if boss["defeated"]]
        print(f"  Bosses: {len(defeated)}/{len(bosses)} defeated")
        print(
            "    " + ", ".join(boss["name"] for boss in defeated[:8])
            if defeated
            else "    None recorded yet"
        )
    else:
        print("  Bosses: unsupported (event flag region not verified)")

    if _bonfire_flags_supported():
        bonfires = read_bonfires(save_path)
        unlocked = [name for name, is_unlocked in bonfires.items() if is_unlocked]
        print(f"  Tracked bonfires: {len(unlocked)}/{len(bonfires)} unlocked")
        print(
            "    " + ", ".join(sorted(unlocked)[:8])
            if unlocked
            else "    None recorded yet"
        )
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
        unit = (
            "checklist entries"
            if key in {"gestures", "infusions", "reinforcement"}
            else "tracked"
        )
        print(f"  {label}: {len(values)} {unit}")
        if values:
            print("    " + ", ".join(values[:8]) + (" ..." if len(values) > 8 else ""))


def _print_save_checklist(save_path: str, stats: dict) -> None:
    from ds3_save import read_area_checklists, read_current_area

    area_name = read_current_area(save_path)
    area_data = read_area_checklists().get(area_name, {}) if area_name else {}
    print(f"=== Current Area: {area_name or 'Unknown'} ===")
    if not area_data:
        print(
            "  Area checklist: unavailable; current area is unknown because bonfire event flags are unsupported."
        )
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
    print(
        f"  Current flask split: {stats['estusAllocation']} HP / {stats['ashenEstusAllocation']} FP"
    )


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
        if not _boss_flags_supported():
            _print_unsupported_event_flags(
                "Bosses", _tracked_boss_names(), spoilers=args.spoilers
            )
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
        if not _bonfire_flags_supported():
            _print_unsupported_event_flags(
                "Tracked bonfires", _tracked_bonfire_names(), spoilers=args.spoilers
            )
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
        cov = {k: v for k, v in stats.items() if k.endswith("Points") and v > 0}
        for name, pts in cov.items():
            print(f"  {name}: {pts}")
        if not cov:
            print("  No covenant ranks yet.")
        return

    if action == "inventory":
        _print_inventory(save_path, show_all=args.all, find=args.find)
        return

    if action == "gestures":
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
            locked = [
                g for g in result if isinstance(g, dict) and not g.get("unlocked")
            ]
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
        return

    if action == "owned":
        _print_owned_items(save_path, show_all=args.all, find=args.find)
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
        _print_missed_result(read_missed(save_path))
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
        "fresh": cmd_fresh,
        "softcaps": cmd_softcaps,
        "origins": cmd_origins,
        "upgrade": cmd_upgrade,
        "weapons": _cmd_weapons_with_hint,
        "calc": cmd_calc,
        "soul-cost": cmd_soul_cost,
        "estus": cmd_estus,
        "infusions": cmd_infusions,
        "equip-load": cmd_equip_load,
        "covenants": cmd_covenants,
        "npcs": cmd_npcs,
        "farm": cmd_farm,
        "build": cmd_build,
        "compare": cmd_compare,
        "areas": _cmd_areas_with_hint,
        "bosses": cmd_bosses,
        "route": cmd_route,
        "achievements": cmd_achievements,
        "mods": cmd_mods,
        "audit": cmd_audit,
        "sources": cmd_sources,
        "spells": cmd_spells,
        "rings": cmd_rings,
        "guide": cmd_guide,
        "track": cmd_track,
        "recommend": cmd_recommend,
        "save": cmd_save,
    }
    handler = handlers.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
