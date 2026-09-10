# Use Odoo Ops with OMP Eval

Read only when using this skill through Oh My Pi (OMP). This optional companion does not change the skill's CLI, dependencies, permissions, or behavior in other harnesses. Follow [Safety model](safety-model.md) first.

## Choose the execution environment

OMP Eval is a persistent Python workspace for analysis and orchestration. It is not Odoo's Server Action `safe_eval`. Imports, asynchronous code, and third-party libraries that work in Eval may be forbidden in a Server Action. Render deployment snippets separately and check them against the target Odoo and Python versions.

Follow the live Eval schema and active harness rules, not an older session's syntax. These examples use `language="py"`. Do not substitute JavaScript or an embedded shell when the active schema rejects it.

Use specialized tools for file reads, discovery, edits, commands, and supported database inspection. Use Eval to distill already acquired data, perform joins and aggregations, or expose narrow analysis tools. Eval is not an alternate transport around RPC permission checks.

## Preserve useful state, not stale permission

Work incrementally: import, define, validate on a small sample, then process the full approved input. Keep normalized tables and pure helpers in memory across cells. Print totals, schema, mismatches, and bounded examples instead of entire records.

Reuse a snapshot only while its database, acquisition time, domain, fields, context, and completeness remain suitable. Refresh preconditions before an approved write. A cached client, token, variable named `approved`, or result from another worker does not renew consent.

Keep acquisition, analysis, and mutation in separate cells. After an analysis error, rerun only the failed transformation, not the cell that acquired data or wrote records. After a kernel restart, rebuild analysis from saved inputs. Never reconstruct progress by replaying writes.

Use the bundled guarded RPC client or CLI for authorized acquisition. A read client uses `allow_rpc=True, allow_write=False` only after scoped permission. Do not leave a write-enabled client exposed to general worker callbacks. End its use when the approved operation ends.

## Select libraries by workload

Reduce acquisition work before adding concurrency. For approved counts or distributions, prefer `search_count` or `read_group` over downloading every record. For record analysis, request explicit fields and bounded pages, then reuse the acquired snapshot for multiple questions.

Use stable ID ordering and record page boundaries. For a changing dataset, offset pagination can skip or duplicate records; an ID cursor with an initial upper bound avoids shifting offsets but is still not a transactionally consistent snapshot. Reconcile completeness and refresh write preconditions separately.

No third-party package is guaranteed by this skill. Prefer one suitable engine over converting the same data through every installed library.

| Workload | Useful combination | Boundary |
| --- | --- | --- |
| Small audits | `json`, `collections.Counter`, sets, `decimal.Decimal` | No dependency needed for counts, exact ID comparisons, or small joins |
| Tabular joins and distributions | Polars with explicit schemas | Normalize Odoo relation values before constructing a table |
| SQL over large local snapshots | DuckDB over existing Parquet, CSV, or JSONL | Project and filter early; bound displayed results, not silently the analyzed dataset |
| Reusing a columnar snapshot in SQL | Polars to Arrow to DuckDB | Reuse an Arrow table; conversion is not guaranteed zero-copy for every type |
| Excel reconciliation | `fastexcel` with Polars | Preserve identifiers, blanks, date interpretation, and leading zeros |
| Duplicate-name candidates | `rapidfuzz` after exact blocking | Similarity proposes candidates; it never authorizes a merge or deletion |
| Dependency analysis | `networkx` over extracted edges | Useful for cycles and ordering, not a substitute for reading model constraints |
| Independent local analysis | Pure functions or bounded asynchronous tasks | Avoid adding an outer worker pool around an already parallel dataframe engine without measurement |

`httpx` can pool authorized HTTP connections, but it does not implement this skill's RPC guardrails. Do not replace the guarded Odoo client with a raw HTTP or XML-RPC loop for throughput.

Normalize many-to-one `false` to a null relation ID and `[id, display_name]` to the ID. Keep Boolean fields Boolean. Preserve many-to-many lists deliberately, use explicit timezones, and avoid binary floats for financial reconciliation. Reject unexpected shapes instead of coercing them to empty values.

## Analyze one snapshot

The following cells use synthetic data only. They make no RPC calls.

First cell:

```python
import polars as pl
from decimal import Decimal

rows = [
    {"id": 101, "team_id": [7, "Example"], "amount": "10.20"},
    {"id": 102, "team_id": False, "amount": "0.00"},
    {"id": 103, "team_id": [7, "Example"], "amount": "2.30"},
]
normalized = [
    {
        "id": row["id"],
        "team_id": None if row["team_id"] is False else row["team_id"][0],
        "amount": Decimal(row["amount"]),
    }
    for row in rows
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

Second cell, without re-importing or reacquiring rows:

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

Expected: team 7 has two records totaling `12.50`; the unset team has one totaling `0.00`. Three rows have three unique IDs.

If SQL is clearer for the next analysis, reuse the same table:

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

This path also needs Arrow support. `fetchall()` here returns two aggregate rows, not the source dataset. Avoid `.df()` merely to display results when pandas is not otherwise needed.

## Use workflow orchestration for independent work

Use the harness workflow keyword only when it is available in the active session. The keyword steers orchestration. It does not grant RPC permission, create a transaction, enforce a deterministic result, or make parallel writes safe. A single query or small edit should remain direct.

For multiple independent items, scope ownership and result contracts first. Prefer one named worker pool per phase when the harness provides one. Push known items together, continue useful local work, and consume every result. Use a new pool name for a later phase once the earlier job has fully drained. If blocked, wait outside Eval rather than polling continuously.

Use individual agent handles for a small dependency graph or schema-returning results. Do not assume filesystem isolation implies kernel isolation. Avoid resetting a shared kernel or mutating shared globals while workers use it.

Give workers disjoint analysis questions over the same approved snapshot, not duplicate acquisition jobs. Keep production writes with one owner and execute approved batches serially. Pass compact findings and artifact references instead of credentials or complete customer records.

If the active session supports defining callable tools, expose narrow analysis-only functions over retained data:

```python
@tool
def snapshot_team_count(team_id: int) -> int:
    """Count rows for one team in the loaded snapshot without I/O."""
    return leads.filter(pl.col("team_id") == team_id).height
```

Pass only that tool's name when creating workers. Do not expose a generic SQL executor, arbitrary RPC method, or write-enabled client. Shared callbacks may execute in the parent kernel; keep shared data immutable or synchronize actual mutations.

## Recover without expanding scope

- For `NameError`, inspect whether the definition cell succeeded or the kernel restarted. Restore only missing analysis state.
- Distinguish the Eval kernel from an Odoo runtime or a child process. A subprocess does not inherit Python variables from the kernel. Missing `odoo` or `psycopg2` while importing the application into Eval does not establish a broken kernel. Run application validation through the configured local runtime rather than installing Odoo's dependency tree into Eval.
- After a wrapper-signature `TypeError`, inspect its actual signature and correct that call. Do not rebuild the transport or repeat successful earlier RPC calls. A later non-error tool result proves neither complete retrieval nor a valid audit.
- For `ImportError`, identify the failing interpreter and API first. Inspect `sys.executable` and package versions without printing environment secrets. A missing name can mean an incompatible API, not a missing package.
- A dependency reminder is not an error and does not authorize installation. If a required package is genuinely absent and installation is authorized, install only that package for the failing interpreter. Do not upgrade unrelated packages or reset healthy state.
- Use top-level `await` rather than `asyncio.run()` inside Eval. Bound independent I/O and own task cleanup. Cancellation of an awaiting coroutine does not prove a blocking worker thread or remote request stopped.
- A cell timeout can leave earlier assignments intact or lead to kernel replacement. Inspect the actual outcome. Never assume cancellation rolled back Odoo or replay an ambiguous mutation.
- Recover spilled output through the returned artifact reference. For `output()`, verify the actual returned structure before indexing it; `format="json"` is an output envelope, not a promise that its content is already decoded business JSON.

