#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""
Search the local Shortcuts expert chunk index.

Usage:
  uv run --script <skill-dir>/scripts/cli.py search --query "ask for input action"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import TypeGuard

type ChunkRecord = dict[str, object]


def _is_chunk_record(value: object) -> TypeGuard[ChunkRecord]:
    return type(value) is dict


def _load_record(line: str) -> ChunkRecord | None:
    value: object = json.loads(line)
    return value if _is_chunk_record(value) else None


def _record_sort_key(record: ChunkRecord) -> tuple[int, int]:
    score = record.get("score", 0)
    char_len = record.get("char_len", 0)
    return (score if isinstance(score, int) else 0, char_len if isinstance(char_len, int) else 0)


def _resolve_corpus_root(explicit: str | None) -> Path:
    candidates: list[Path] = []

    if explicit:
        candidates.append(Path(explicit))

    env_root = os.environ.get("APPLE_SHORTCUTS_CORPUS")
    if env_root:
        candidates.append(Path(env_root))

    cwd = Path.cwd()
    if cwd.name == "shortcuts-docs-corpus":
        candidates.append(cwd)

    for base in (cwd, *cwd.parents):
        candidates.append(base / "shortcuts-docs-corpus")

    seen: set[str] = set()
    for cand in candidates:
        key = str(cand.resolve()) if cand.exists() else str(cand)
        if key in seen:
            continue
        seen.add(key)
        chunks = cand / "expert-pack" / "chunks" / "shortcuts_expert_chunks.jsonl"
        if chunks.is_file():
            return cand

    raise FileNotFoundError("Could not locate shortcuts-docs-corpus. Use --corpus-root or set APPLE_SHORTCUTS_CORPUS.")


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_+-]{2,}", text.lower())


def _score(query: str, query_terms: Iterable[str], group: str | None, rec: ChunkRecord) -> int:
    rec_group = str(rec.get("source_group", ""))
    if group and rec_group != group:
        return 0

    path = str(rec.get("path", "")).lower()
    text = str(rec.get("text", "")).lower()
    score = 0

    q = query.lower().strip()
    if q and q in text:
        score += 18

    for term in query_terms:
        cnt = text.count(term)
        if cnt:
            score += min(cnt, 10) * 2
        if term in path:
            score += 1

    return score


def _excerpt(text: str, query_terms: list[str], max_len: int = 320) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""

    lower = cleaned.lower()
    start = 0
    for term in query_terms:
        idx = lower.find(term)
        if idx >= 0:
            start = max(0, idx - 80)
            break

    frag = cleaned[start : start + max_len]
    if start > 0:
        frag = "..." + frag
    if len(cleaned) > start + max_len:
        frag = frag + "..."
    return frag


def main() -> int:
    parser = argparse.ArgumentParser(description="Search Shortcuts expert chunks.")
    parser.add_argument("--query", required=True, help="Search query text.")
    parser.add_argument(
        "--group",
        choices=["support", "developer", "wwdc", "community", "cli", "other"],
        help="Optional source-group filter.",
    )
    parser.add_argument("--top", type=int, default=8, help="Maximum results to return.")
    parser.add_argument("--min-score", type=int, default=1, help="Minimum score threshold.")
    parser.add_argument("--corpus-root", help="Path to shortcuts-docs-corpus root.")
    parser.add_argument("--json", action="store_true", help="Output JSON.")
    parser.add_argument(
        "--show-corpus-root",
        action="store_true",
        help="Print resolved corpus root to stderr.",
    )
    args = parser.parse_args()

    try:
        corpus_root = _resolve_corpus_root(args.corpus_root)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.show_corpus_root:
        print(f"corpus_root={corpus_root}", file=sys.stderr)

    chunk_file = corpus_root / "expert-pack" / "chunks" / "shortcuts_expert_chunks.jsonl"
    terms = _tokenize(args.query)

    hits: list[ChunkRecord] = []
    with chunk_file.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = _load_record(line)
            if rec is None:
                continue
            score = _score(args.query, terms, args.group, rec)
            if score < args.min_score:
                continue
            rec["score"] = score
            rec["excerpt"] = _excerpt(str(rec.get("text", "")), terms)
            hits.append(rec)

    hits.sort(key=_record_sort_key, reverse=True)
    hits = hits[: max(1, args.top)]

    if args.json:
        payload = {
            "corpus_root": str(corpus_root),
            "query": args.query,
            "group": args.group,
            "results": hits,
        }
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return 0

    if not hits:
        print("No matches.")
        return 0

    print(f"Corpus: {corpus_root}")
    print(f"Query: {args.query}")
    print()
    for idx, rec in enumerate(hits, start=1):
        print(f"[{idx}] score={rec['score']} group={rec.get('source_group')} path={rec.get('path')} id={rec.get('id')}")
        print(f"    {rec.get('excerpt', '')}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
