# /// script
# requires-python = ">=3.12"
# ///
# ruff: noqa: CPY001, FBT001, S607
"""Filter Artificial Analysis model snapshot for agent/dev model selection.

The v2 snapshot stores canonical model metrics in ``models`` and endpoint
observations in ``hosts_models``.  Filtering joins observations to canonical
models by ``model_slug``; it never expects an embedded endpoint ``model`` object.
JSON preserves additive unknown fields/evidence/diagnostics.  Markdown and TSV
remain fixed named-column views.

Default filter saved from chat:
  open_weight = all
  Omni >= -20
  Terminal-Bench Hard >= 0.30
  IFBench >= 0.55

Run:
  uv run --script assets/skills/artificial-analysis-live/scripts/filter_agent_models.py

Fresh data first:
  uv run --script assets/skills/artificial-analysis-live/scripts/filter_agent_models.py
  --fetch
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

Json = dict[str, Any]
OpenWeight = Literal["all", "true", "false"]
SortKey = Literal["tbench", "omni", "ifbench", "name"]
OutputFormat = Literal["markdown", "tsv", "json"]


class Row(TypedDict):
    """Normalized model fields used by filtering and output."""

    slug: str
    name: str
    open_weights: bool | None
    omni: float
    tbench: float | None
    ifbench: float | None
    license: str | None
    raw_fields: NotRequired[object]
    raw_metadata: NotRequired[object]
    evidence: NotRequired[object]
    diagnostics: NotRequired[list[Json]]


DEFAULT_SNAPSHOT = (
    Path(tempfile.gettempdir()) / "artifacts" / "artificial-analysis" / "full-data.json"
)
DEFAULT_SKILL_CLI = Path(__file__).resolve().parent / "cli.py"
DEFAULT_SNAPSHOT_MAX_AGE = timedelta(hours=24)
SNAPSHOT_SCHEMA_V2 = 2


def number(value: object) -> float | None:
    """Convert finite numeric JSON values to float, excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None


def model_omni(model: Json) -> float:
    """Return a model's omniscience score or the missing-value sentinel."""
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
    """Convert a canonical model payload to the filter row shape."""
    row: Row = {
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
    for key in ("raw_fields", "raw_metadata", "evidence"):
        if key in model:
            row[key] = model[key]
    return row


def ensure_default_snapshot_fresh(snapshot: Path, raw: Json) -> None:
    """Reject stale or malformed default snapshots."""
    if snapshot != DEFAULT_SNAPSHOT:
        return

    meta = raw.get("meta")
    fetched_at = meta.get("fetched_at") if isinstance(meta, dict) else None
    if not isinstance(fetched_at, str) or not fetched_at:
        message = (
            f"default snapshot missing meta.fetched_at: {snapshot}. "
            "Run with --fetch first or pass --snapshot."
        )
        raise ValueError(message)
    try:
        fetched_at_dt = datetime.fromisoformat(fetched_at)
    except ValueError as exc:
        message = (
            f"default snapshot has invalid meta.fetched_at: {snapshot}. "
            "Run with --fetch first or pass --snapshot."
        )
        raise ValueError(message) from exc
    if fetched_at_dt.tzinfo is None:
        fetched_at_dt = fetched_at_dt.replace(tzinfo=UTC)
    age = datetime.now(UTC) - fetched_at_dt.astimezone(UTC)
    if age > DEFAULT_SNAPSHOT_MAX_AGE:
        message = (
            f"default snapshot is stale ({fetched_at}, older than 24h): "
            f"{snapshot}. Run with --fetch first or pass --snapshot."
        )
        raise ValueError(message)


LAST_LOAD_DIAGNOSTICS: list[Json] = []


def load_rows(  # noqa: C901, PLR0912
    snapshot: Path,
    *,
    diagnostics: list[Json] | None = None,
) -> list[Row]:
    """Load canonical model rows joined from v1 or schema-v2 endpoints."""
    raw_value = json.loads(snapshot.read_text())
    if not isinstance(raw_value, dict):
        message = f"snapshot must be an object: {snapshot}"
        raise TypeError(message)
    raw: Json = raw_value
    ensure_default_snapshot_fresh(snapshot, raw)
    hosts_models = raw.get("hosts_models")
    if not isinstance(hosts_models, list):
        message = f"snapshot missing hosts_models list: {snapshot}"
        raise ValueError(message)  # noqa: TRY004
    meta = raw.get("meta")
    schema_version = meta.get("schema_version") if isinstance(meta, dict) else None
    require_canonical_join = (
        isinstance(schema_version, int)
        and not isinstance(schema_version, bool)
        and schema_version >= SNAPSHOT_SCHEMA_V2
    )

    local_diagnostics: list[Json] = []
    canonical: dict[str, Json] = {}
    models = raw.get("models")
    if isinstance(models, list):
        for model in models:
            if isinstance(model, dict) and isinstance(model.get("slug"), str):
                canonical[model["slug"]] = model

    by_slug: dict[str, Row] = {}
    for index, endpoint in enumerate(hosts_models):
        if not isinstance(endpoint, dict):
            continue
        model_slug = endpoint.get("model_slug")
        nested_model = endpoint.get("model")
        if not isinstance(model_slug, str) or not model_slug:
            if require_canonical_join:
                local_diagnostics.append(
                    {
                        "code": "MISSING_MODEL_JOIN",
                        "severity": "error",
                        "stage": "filter.load_rows",
                        "message": "Endpoint has no canonical model join.",
                        "details": {
                            "endpoint_index": index,
                            "model_slug": model_slug
                            if isinstance(model_slug, str)
                            else None,
                        },
                    },
                )
                continue
            if isinstance(nested_model, dict) and isinstance(
                nested_model.get("slug"), str
            ):
                model_slug = nested_model["slug"]
            else:
                continue
        model = canonical.get(model_slug)
        if model is None and not require_canonical_join:
            model = nested_model if isinstance(nested_model, dict) else None
        if model is None:
            local_diagnostics.append(
                {
                    "code": "MISSING_MODEL_JOIN",
                    "severity": "error",
                    "stage": "filter.load_rows",
                    "message": (
                        f"Endpoint has no canonical model join for {model_slug!r}."
                    ),
                    "details": {"endpoint_index": index, "model_slug": model_slug},
                },
            )
            continue
        row = model_row(model)
        slug = row["slug"]
        if not slug:
            continue
        if slug not in by_slug:
            by_slug[slug] = row

    LAST_LOAD_DIAGNOSTICS.clear()
    LAST_LOAD_DIAGNOSTICS.extend(local_diagnostics)
    if diagnostics is not None:
        diagnostics.extend(local_diagnostics)
    return list(by_slug.values())


def load_rows_with_diagnostics(snapshot: Path) -> tuple[list[Row], list[Json]]:
    """Load rows and return stable non-fatal join diagnostics."""
    collected: list[Json] = []
    rows = load_rows(snapshot, diagnostics=collected)
    return rows, collected


def max_nullable(a: float | None, b: float | None) -> float | None:
    """Return the greater finite non-null value."""
    left = a if a is not None and math.isfinite(a) else None
    right = b if b is not None and math.isfinite(b) else None
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def passes_open(row: Row, open_weight: OpenWeight) -> bool:
    """Check an open-weights filter against a row."""
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
    """Apply all configured threshold filters."""
    return [
        row
        for row in rows
        if passes_open(row, open_weight)
        and row["omni"] >= min_omni
        and (row["tbench"] if row["tbench"] is not None else -999.0) >= min_tbench
        and (row["ifbench"] if row["ifbench"] is not None else -999.0) >= min_ifbench
    ]


def sort_rows(
    rows: list[Row],
    sort_by: SortKey,
    descending: bool,
) -> list[Row]:
    """Sort rows by the requested metric."""
    if sort_by == "name":
        return sorted(rows, key=lambda row: row["name"].lower(), reverse=descending)

    def metric(row: Row) -> float:
        if sort_by == "omni":
            return row["omni"]
        if sort_by == "ifbench":
            return row["ifbench"] if row["ifbench"] is not None else -999.0
        return row["tbench"] if row["tbench"] is not None else -999.0

    return sorted(rows, key=metric, reverse=descending)


def fmt(value: object) -> str:
    """Format a value for tabular output without emitting non-finite numbers."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int | float):
        converted = float(value)
        if not math.isfinite(converted):
            return "-"
        return f"{converted:.3f}".rstrip("0").rstrip(".")
    return str(value)


def emit_markdown(rows: list[Row]) -> None:
    """Write rows as a Markdown fixed-view table."""
    sys.stdout.write("| Rank | Model | Open | Omni | TBench | IFBench | License |\n")
    sys.stdout.write("|---:|---|---|---:|---:|---:|---|\n")
    for idx, row in enumerate(rows, start=1):
        line = (
            f"| {idx} | {row['name']} | {fmt(row['open_weights'])} | "
            f"{fmt(row['omni'])} | {fmt(row['tbench'])} | "
            f"{fmt(row['ifbench'])} | {row['license'] or '-'} |\n"
        )
        sys.stdout.write(line)
    sys.stderr.write(
        "Note: text output is a fixed view; use --format json for "
        "raw/evidence fields.\n",
    )


def emit_tsv(rows: list[Row]) -> None:
    """Write rows as tab-separated fixed-view values."""
    sys.stdout.write("Rank\tModel\tOpen\tOmni\tTBench\tIFBench\tLicense\n")
    for idx, row in enumerate(rows, start=1):
        line = "\t".join(
            [
                str(idx),
                row["name"],
                fmt(row["open_weights"]),
                fmt(row["omni"]),
                fmt(row["tbench"]),
                fmt(row["ifbench"]),
                row["license"] or "-",
            ],
        )
        sys.stdout.write(f"{line}\n")
    sys.stderr.write(
        "Note: text output is a fixed view; use --format json for "
        "raw/evidence fields.\n",
    )


def _finite_json(value: object) -> object:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _finite_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_finite_json(item) for item in value]
    if isinstance(value, tuple):
        return [_finite_json(item) for item in value]
    return value


def emit_json(rows: list[Row]) -> None:
    """Write rows as formatted finite JSON."""
    sys.stdout.write(
        json.dumps(_finite_json(rows), indent=2, sort_keys=True, allow_nan=False)
        + "\n",
    )


def fetch_snapshot(skill_cli: Path) -> None:
    """Fetch a fresh snapshot through the skill CLI."""
    subprocess.run(  # noqa: S603 (trusted local skill CLI)
        ["uv", "run", "--script", str(skill_cli), "fetch"],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description="Filter Artificial Analysis models for coding-agent use.",
    )
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="refresh AA snapshot before filtering",
    )
    parser.add_argument("--skill-cli", type=Path, default=DEFAULT_SKILL_CLI)
    parser.add_argument(
        "--open-weight",
        choices=["all", "true", "false"],
        default="all",
    )
    parser.add_argument("--min-omni", type=float, default=-20.0)
    parser.add_argument("--min-tbench", type=float, default=0.30)
    parser.add_argument("--min-ifbench", type=float, default=0.55)
    parser.add_argument(
        "--sort-by",
        choices=["tbench", "omni", "ifbench", "name"],
        default="tbench",
    )
    parser.add_argument("--asc", action="store_true", help="sort ascending")
    parser.add_argument("--limit", type=int, default=0, help="0 means no limit")
    parser.add_argument(
        "--format",
        choices=["markdown", "tsv", "json"],
        default="markdown",
    )
    return parser.parse_args()


def main() -> int:
    """Run filtering and return the process exit status."""
    args = parse_args()
    if args.fetch:
        fetch_snapshot(args.skill_cli)
    if not args.snapshot.exists():
        sys.stderr.write(
            f"snapshot not found: {args.snapshot}. Run with --fetch first.\n",
        )
        return 2

    diagnostics: list[Json] = []
    rows = load_rows(args.snapshot, diagnostics=diagnostics)
    for diagnostic in diagnostics:
        sys.stderr.write(json.dumps(diagnostic, sort_keys=True) + "\n")
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
