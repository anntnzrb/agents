#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Filter Artificial Analysis model snapshot for agent/dev model selection.

Default filter saved from chat:
  open_weight = all
  Omni >= -20
  Terminal-Bench Hard >= 0.30
  IFBench >= 0.55

Run:
  uv run --script assets/skills/artificial-analysis-live/scripts/filter_agent_models.py

Fresh data first:
  uv run --script assets/skills/artificial-analysis-live/scripts/filter_agent_models.py --fetch
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal, TypedDict

Json = dict[str, Any]
OpenWeight = Literal["all", "true", "false"]
SortKey = Literal["tbench", "omni", "ifbench", "name"]
OutputFormat = Literal["markdown", "tsv", "json"]


class Row(TypedDict):
    slug: str
    name: str
    open_weights: bool | None
    omni: float
    tbench: float | None
    ifbench: float | None
    license: str | None


DEFAULT_SNAPSHOT = Path("artifacts/artificial-analysis/full-data.json")
DEFAULT_SKILL_CLI = Path(__file__).resolve().parent / "cli.py"


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def model_omni(model: Json) -> float:
    direct = number(model.get("omniscience"))
    if direct is not None:
        return direct
    breakdown = model.get("omniscience_breakdown")
    if isinstance(breakdown, dict):
        total = breakdown.get("total")
        if isinstance(total, dict):
            nested = number(total.get("omniscience"))
            if nested is not None:
                return nested
    return -999.0


def model_row(model: Json) -> Row:
    return {
        "slug": str(model.get("slug") or ""),
        "name": str(model.get("name") or ""),
        "open_weights": model.get("is_open_weights")
        if isinstance(model.get("is_open_weights"), bool)
        else None,
        "omni": model_omni(model),
        "tbench": number(model.get("terminalbench_hard")),
        "ifbench": number(model.get("ifbench")),
        "license": model.get("license_name")
        if isinstance(model.get("license_name"), str)
        else None,
    }


def load_rows(snapshot: Path) -> list[Row]:
    raw = json.loads(snapshot.read_text())
    hosts_models = raw.get("hosts_models")
    if not isinstance(hosts_models, list):
        raise ValueError(f"snapshot missing hosts_models list: {snapshot}")

    by_slug: dict[str, Row] = {}
    for endpoint in hosts_models:
        if not isinstance(endpoint, dict):
            continue
        model = endpoint.get("model")
        if not isinstance(model, dict):
            continue
        row = model_row(model)
        slug = row["slug"]
        if not slug:
            continue
        old = by_slug.get(slug)
        if old is None:
            by_slug[slug] = row
            continue
        # Same model repeats per provider endpoint. Keep max benchmark values and stable metadata.
        old["omni"] = max(old["omni"], row["omni"])
        old["tbench"] = max_nullable(old["tbench"], row["tbench"])
        old["ifbench"] = max_nullable(old["ifbench"], row["ifbench"])
        old["open_weights"] = (
            old["open_weights"]
            if old["open_weights"] is not None
            else row["open_weights"]
        )
        old["license"] = old["license"] or row["license"]
    return list(by_slug.values())


def max_nullable(a: float | None, b: float | None) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def passes_open(row: Row, open_weight: OpenWeight) -> bool:
    if open_weight == "all":
        return True
    expected = open_weight == "true"
    return row["open_weights"] is expected


def apply_filter(
    rows: list[Row],
    *,
    open_weight: OpenWeight,
    min_omni: float,
    min_tbench: float,
    min_ifbench: float,
) -> list[Row]:
    return [
        row
        for row in rows
        if passes_open(row, open_weight)
        and row["omni"] >= min_omni
        and (row["tbench"] if row["tbench"] is not None else -999.0) >= min_tbench
        and (row["ifbench"] if row["ifbench"] is not None else -999.0) >= min_ifbench
    ]


def sort_rows(rows: list[Row], sort_by: SortKey, descending: bool) -> list[Row]:
    if sort_by == "name":
        return sorted(rows, key=lambda row: row["name"].lower(), reverse=descending)

    def metric(row: Row) -> float:
        if sort_by == "omni":
            return row["omni"]
        if sort_by == "ifbench":
            return row["ifbench"] if row["ifbench"] is not None else -999.0
        return row["tbench"] if row["tbench"] is not None else -999.0

    return sorted(rows, key=metric, reverse=descending)


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int | float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def emit_markdown(rows: list[Row]) -> None:
    print("| Rank | Model | Open | Omni | TBench | IFBench | License |")
    print("|---:|---|---|---:|---:|---:|---|")
    for idx, row in enumerate(rows, start=1):
        print(
            f"| {idx} | {row['name']} | {fmt(row['open_weights'])} | "
            f"{fmt(row['omni'])} | {fmt(row['tbench'])} | {fmt(row['ifbench'])} | {row['license'] or '-'} |"
        )


def emit_tsv(rows: list[Row]) -> None:
    print("Rank\tModel\tOpen\tOmni\tTBench\tIFBench\tLicense")
    for idx, row in enumerate(rows, start=1):
        print(
            "\t".join(
                [
                    str(idx),
                    row["name"],
                    fmt(row["open_weights"]),
                    fmt(row["omni"]),
                    fmt(row["tbench"]),
                    fmt(row["ifbench"]),
                    row["license"] or "-",
                ]
            )
        )


def emit_json(rows: list[Row]) -> None:
    print(json.dumps(rows, indent=2, sort_keys=True))


def fetch_snapshot(skill_cli: Path) -> None:
    subprocess.run(
        ["uv", "run", "--script", str(skill_cli), "fetch"],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filter Artificial Analysis models for coding-agent use."
    )
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument(
        "--fetch", action="store_true", help="refresh AA snapshot before filtering"
    )
    parser.add_argument("--skill-cli", type=Path, default=DEFAULT_SKILL_CLI)
    parser.add_argument(
        "--open-weight", choices=["all", "true", "false"], default="all"
    )
    parser.add_argument("--min-omni", type=float, default=-20.0)
    parser.add_argument("--min-tbench", type=float, default=0.30)
    parser.add_argument("--min-ifbench", type=float, default=0.55)
    parser.add_argument(
        "--sort-by", choices=["tbench", "omni", "ifbench", "name"], default="tbench"
    )
    parser.add_argument("--asc", action="store_true", help="sort ascending")
    parser.add_argument("--limit", type=int, default=0, help="0 means no limit")
    parser.add_argument(
        "--format", choices=["markdown", "tsv", "json"], default="markdown"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.fetch:
        fetch_snapshot(args.skill_cli)
    if not args.snapshot.exists():
        print(
            f"snapshot not found: {args.snapshot}. Run with --fetch first.",
            file=sys.stderr,
        )
        return 2

    rows = load_rows(args.snapshot)
    filtered = apply_filter(
        rows,
        open_weight=args.open_weight,
        min_omni=args.min_omni,
        min_tbench=args.min_tbench,
        min_ifbench=args.min_ifbench,
    )
    sorted_rows = sort_rows(filtered, args.sort_by, not args.asc)
    if args.limit > 0:
        sorted_rows = sorted_rows[: args.limit]

    if args.format == "json":
        emit_json(sorted_rows)
    elif args.format == "tsv":
        emit_tsv(sorted_rows)
    else:
        emit_markdown(sorted_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
