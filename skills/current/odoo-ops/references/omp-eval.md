# Use Odoo Ops with OMP Eval



## Section index


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
