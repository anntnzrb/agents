# Use Odoo Ops with OMP Eval

Read only when using this skill through Oh My Pi (OMP). This companion does not change the skill's CLI, permissions, or behavior. Read [Safety model](safety-model.md) first.

## Local Analysis Workspace

OMP Eval is a persistent Python workspace for local data analysis, joins, and aggregations. It is not an alternative transport to Odoo.

Agents MUST NOT write custom HTTP, XML-RPC, or JSON-RPC clients, import the skill's Python modules or transports into notebook or eval kernels, or make network calls to Odoo from within Eval. All data acquisition and all mutations MUST go through the CLI via shell (`odoo-ops rpc ...`). If the CLI lacks a required operation, stop and report the capability gap.

Production reads through the CLI need no per-read approval. Production writes strictly require the dry-run plan, user review, and `apply <plan-id>` workflow executed through the CLI.

Follow this boundary:
1. Acquire data using the CLI in shell, saving structured output to a file:
   ```text
   uv run --script <skill-dir>/scripts/cli.py rpc --allow-rpc search_read crm.lead '[["user_id", "=", 2]]' --fields 'name team_id expected_revenue' --limit 100 --json > <temp-dir>/leads.json
   ```
2. Load and analyze the saved JSON file inside Eval.
3. If mutations are needed, generate a dry-run plan via the CLI, present the diff to the user, and run `apply <plan-id>` via the CLI upon approval.

## Preserve Useful State

Work incrementally: load the saved JSON file, normalize shapes, validate on a small sample, then process the full input. Keep normalized tables and pure helpers in memory across cells. Print totals, schemas, mismatches, and bounded summaries instead of raw dumps.

Keep analysis deterministic. After an analysis error, rerun only the failed transformation cell. After a kernel restart, reload inputs from the saved file.

## Select Libraries by Workload

Process data locally with standard Python tools or installed data libraries:

| Workload | Useful combination | Boundary |
| --- | --- | --- |
| Small audits | `json`, `collections.Counter`, sets, `decimal.Decimal` | No dependencies needed for counts, exact ID comparisons, or small joins. |
| Tabular joins and distributions | Polars with explicit schemas | Normalize Odoo relation values before constructing a table. |
| SQL over local snapshots | DuckDB over saved Parquet, CSV, or JSON | Filter early; bound displayed results. |
| Reusing a columnar snapshot in SQL | Polars to Arrow to DuckDB | Reuse Arrow tables in memory without re-parsing files. |
| Excel reconciliation | `fastexcel` with Polars | Preserve identifiers, blanks, and leading zeros. |
| Duplicate-name candidates | `rapidfuzz` after exact blocking | Similarity proposes candidates; it never authorizes a merge or deletion. |
| Dependency analysis | `networkx` over extracted edges | Detect cycles and ordering without guessing model constraints. |

Normalize many-to-one fields: convert `False` to `None` and `[id, display_name]` to `id`. Keep Boolean fields Boolean. Use explicit timezones and decimal types for financial figures. Reject unexpected schemas instead of coercing them to empty values.

## Analyze a Saved Snapshot

The following cells load and analyze a local dataset in memory. They make zero network calls:

First cell:

```python
import json
from decimal import Decimal
from pathlib import Path
import polars as pl

# Load data saved from CLI output
raw_data = json.loads(Path("<temp-dir>/leads.json").read_text(encoding="utf-8"))

normalized = [
    {
        "id": row["id"],
        "team_id": None if row["team_id"] is False else row["team_id"][0],
        "amount": Decimal(str(row.get("expected_revenue") or "0.00")),
    }
    for row in raw_data
]

leads = pl.DataFrame(
    normalized,
    schema={
        "id": pl.Int64,
        "team_id": pl.Int64,
        "amount": pl.Decimal(precision=18, scale=2),
    },
)
```

Second cell:

```python
summary = (
    leads.group_by("team_id")
    .agg(
        pl.len().alias("records"),
        pl.col("amount").sum(),
    )
    .sort("team_id", nulls_last=True)
)
print(summary)
print({"rows": leads.height, "unique_ids": leads["id"].n_unique()})
```

SQL analysis via DuckDB:

```python
import duckdb

with duckdb.connect(":memory:") as analysis_db:
    analysis_db.register("lead_snapshot", leads.to_arrow())
    result = analysis_db.sql("""
        SELECT team_id, count(*) AS records, sum(amount) AS amount
        FROM lead_snapshot GROUP BY team_id ORDER BY team_id NULLS LAST
    """).fetchall()
print(result)
```

## Orchestration for Independent Analysis

Use harness orchestration only when supported in the active session. Orchestration steers concurrency; it does not bypass the CLI or make parallel writes safe.

For independent analytical questions:
- Give workers disjoint analytical questions over the same saved snapshot.
- Never dispatch duplicate acquisition jobs or make concurrent network requests to Odoo.
- If exposing tools to workers, provide pure functions operating over loaded in-memory data:

```python
@tool
def snapshot_team_count(team_id: int) -> int:
    """Count rows for one team in the loaded snapshot without I/O."""
    return leads.filter(pl.col("team_id") == team_id).height
```

## Recovery

- For `NameError`, check whether the definition cell succeeded or the kernel restarted. Reload only the missing local analysis state.
- Distinguish the Eval kernel from the Odoo runtime container. Eval lacks Odoo application packages (`odoo`, `psycopg2`). Do not attempt to install Odoo dependencies into Eval.
- For `ImportError`, inspect `sys.executable` and package availability. Do not install packages unless explicitly authorized.
- For cell timeouts, inspect kernel state. Never assume a timeout rolled back server changes; check the server via CLI if a mutation was underway.

