# /// script
# requires-python = ">=3.12"
# ///
# ruff: noqa: S607
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
  uv run --script skills/current/artificial-analysis-live/scripts/filter_agent_models.py

Fresh data first:
  uv run --script skills/current/artificial-analysis-live/scripts/filter_agent_models.py
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
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

type JsonValue = (
    bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
)
type Json = dict[str, JsonValue]
type OpenWeight = Literal["all", "true", "false"]
type SortKey = Literal["tbench", "omni", "ifbench", "name"]
type OutputFormat = Literal["markdown", "tsv", "json"]


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


def _bool_or_none(value: object) -> bool | None:
    """Return the value if it is a boolean, else None."""
    return value if isinstance(value, bool) else None


def _str_or_none(value: object) -> str | None:
    """Return the value if it is a string, else None."""
    return value if isinstance(value, str) else None


def model_row(model: Json) -> Row:
    """Convert a canonical model payload to the filter row shape."""
    row: Row = {
        "slug": str(model.get("slug") or ""),
        "name": str(model.get("name") or ""),
        "open_weights": _bool_or_none(model.get("is_open_weights")),
        "omni": model_omni(model),
        "tbench": number(model.get("terminalbench_hard")),
        "ifbench": number(model.get("ifbench")),
        "license": _str_or_none(model.get("license_name")),
    }
    if "raw_fields" in model:
        row["raw_fields"] = model["raw_fields"]
    if "raw_metadata" in model:
        row["raw_metadata"] = model["raw_metadata"]
    if "evidence" in model:
        row["evidence"] = model["evidence"]
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


def _build_canonical(models: JsonValue) -> dict[str, Json]:
    """Index canonical models by slug."""
    canonical: dict[str, Json] = {}
    if not isinstance(models, list):
        return canonical
    for model in models:
        if not isinstance(model, dict):
            continue
        slug = model.get("slug")
        if not isinstance(slug, str):
            continue
        canonical[slug] = model
    return canonical


def load_rows(  # noqa: C901
    snapshot: Path,
    *,
    diagnostics: list[Json] | None = None,
) -> list[Row]:
    """Load canonical model rows joined from v1 or schema-v2 endpoints."""
    raw_value = cast("object", json.loads(snapshot.read_text()))
    if not isinstance(raw_value, dict):
        message = f"snapshot must be an object: {snapshot}"
        raise TypeError(message)
    raw = cast("Json", raw_value)
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
    canonical = _build_canonical(raw.get("models"))
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
            nested_slug = (
                nested_model.get("slug") if isinstance(nested_model, dict) else None
            )
            if not isinstance(nested_slug, str):
                continue
            model_slug = nested_slug
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
    _ = sys.stdout.write(
        "| Rank | Model | Open | Omni | TBench | IFBench | License |\n"
    )
    _ = sys.stdout.write("|---:|---|---|---:|---:|---:|---|\n")
    for idx, row in enumerate(rows, start=1):
        line = (
            f"| {idx} | {row['name']} | {fmt(row['open_weights'])} | "
            f"{fmt(row['omni'])} | {fmt(row['tbench'])} | "
            f"{fmt(row['ifbench'])} | {row['license'] or '-'} |\n"
        )
        _ = sys.stdout.write(line)
    _ = sys.stderr.write(
        "Note: text output is a fixed view; use --format json for "
        + "raw/evidence fields.\n",
    )


def emit_tsv(rows: list[Row]) -> None:
    """Write rows as tab-separated fixed-view values."""
    _ = sys.stdout.write("Rank\tModel\tOpen\tOmni\tTBench\tIFBench\tLicense\n")
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
        _ = sys.stdout.write(f"{line}\n")
    _ = sys.stderr.write(
        "Note: text output is a fixed view; use --format json for "
        + "raw/evidence fields.\n",
    )


def _finite_json(value: object) -> object:
    """Replace non-finite floats so json.dumps(allow_nan=False) succeeds."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        mapping = cast("Mapping[str, object]", value)
        return {str(key): _finite_json(item) for key, item in mapping.items()}
    if isinstance(value, list):
        items = cast("list[object]", cast("object", value))
        return [_finite_json(item) for item in items]
    if isinstance(value, tuple):
        entries = cast("tuple[object, ...]", cast("object", value))
        return [_finite_json(item) for item in entries]
    return value


def emit_json(rows: list[Row]) -> None:
    """Write rows as formatted finite JSON."""
    _ = sys.stdout.write(
        json.dumps(_finite_json(rows), indent=2, sort_keys=True, allow_nan=False)
        + "\n",
    )


def fetch_snapshot(skill_cli: Path) -> None:
    """Fetch a fresh snapshot through the skill CLI."""
    _ = subprocess.run(  # noqa: S603 (trusted local skill CLI)
        ["uv", "run", "--script", str(skill_cli), "fetch"],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description="Filter Artificial Analysis models for coding-agent use.",
    )
    _ = parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    _ = parser.add_argument(
        "--fetch",
        action="store_true",
        help="refresh AA snapshot before filtering",
    )
    _ = parser.add_argument("--skill-cli", type=Path, default=DEFAULT_SKILL_CLI)
    _ = parser.add_argument(
        "--open-weight",
        choices=["all", "true", "false"],
        default="all",
    )
    _ = parser.add_argument("--min-omni", type=float, default=-20.0)
    _ = parser.add_argument("--min-tbench", type=float, default=0.30)
    _ = parser.add_argument("--min-ifbench", type=float, default=0.55)
    _ = parser.add_argument(
        "--sort-by",
        choices=["tbench", "omni", "ifbench", "name"],
        default="tbench",
    )
    _ = parser.add_argument("--asc", action="store_true", help="sort ascending")
    _ = parser.add_argument("--limit", type=int, default=0, help="0 means no limit")
    _ = parser.add_argument(
        "--format",
        choices=["markdown", "tsv", "json"],
        default="markdown",
    )
    return parser.parse_args()


def main() -> int:
    """Run filtering and return the process exit status."""
    args = parse_args()
    if _flag(args, "fetch"):
        fetch_snapshot(_req_path(args, "skill_cli"))
    snapshot = _req_path(args, "snapshot")
    if not snapshot.exists():
        _ = sys.stderr.write(
            f"snapshot not found: {snapshot}. Run with --fetch first.\n",
        )
        return 2

    diagnostics: list[Json] = []
    rows = load_rows(snapshot, diagnostics=diagnostics)
    for diagnostic in diagnostics:
        _ = sys.stderr.write(json.dumps(diagnostic, sort_keys=True) + "\n")
    filtered = apply_filter(
        rows,
        open_weight=cast("OpenWeight", _req_str(args, "open_weight")),
        min_omni=_req_float(args, "min_omni"),
        min_tbench=_req_float(args, "min_tbench"),
        min_ifbench=_req_float(args, "min_ifbench"),
    )
    sorted_rows = sort_rows(
        filtered, cast("SortKey", _req_str(args, "sort_by")), not _flag(args, "asc")
    )
    limit = _req_int(args, "limit")
    if limit > 0:
        sorted_rows = sorted_rows[:limit]

    output_format = cast("OutputFormat", _req_str(args, "format"))
    if output_format == "json":
        emit_json(sorted_rows)
    elif output_format == "tsv":
        emit_tsv(sorted_rows)
    else:
        emit_markdown(sorted_rows)
    return 0


def _req_str(args: argparse.Namespace, field: str) -> str:
    """Narrow a required string argument to a typed value."""
    value = cast("object", getattr(args, field))
    if not isinstance(value, str):
        message = f"Missing required argument: {field}."
        raise TypeError(message)
    return value


def _req_path(args: argparse.Namespace, field: str) -> Path:
    """Narrow a required path argument to a typed value."""
    value = cast("object", getattr(args, field))
    if not isinstance(value, Path):
        message = f"Missing required argument: {field}."
        raise TypeError(message)
    return value


def _req_float(args: argparse.Namespace, field: str) -> float:
    """Narrow a required float argument to a typed value."""
    value = cast("object", getattr(args, field))
    if not isinstance(value, float):
        message = f"Invalid float argument: {field}."
        raise TypeError(message)
    return value


def _req_int(args: argparse.Namespace, field: str) -> int:
    """Narrow a required integer argument to a typed value."""
    value = cast("object", getattr(args, field))
    if not isinstance(value, int) or isinstance(value, bool):
        message = f"Invalid integer argument: {field}."
        raise TypeError(message)
    return value


def _flag(args: argparse.Namespace, field: str) -> bool:
    """Narrow a boolean flag to a typed value."""
    value = cast("object", getattr(args, field))
    return value if isinstance(value, bool) else False


if __name__ == "__main__":
    raise SystemExit(main())
