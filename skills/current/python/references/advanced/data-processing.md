# Data Processing: Polars + DuckDB



## Section index


# Phase 1: DuckDB for the join
joined = duckdb.sql("""
    SELECT o.*, c.region, p.category
    FROM 'orders.parquet' o
    JOIN 'customers.parquet' c ON o.customer_id = c.id
    JOIN 'products.parquet'  p ON o.product_id  = p.id
""").pl()

# Phase 2: Polars for filtering and transformation
processed = joined.filter(pl.col("amount") > 100).with_columns(
    [
        (pl.col("amount") * 1.1).alias("amount_with_tax"),
    ]
)

# Phase 3: DuckDB for final aggregation - register Polars frame by name
duckdb.register("processed", processed)
final = duckdb.sql("""
    SELECT region, category, SUM(amount_with_tax) AS revenue
    FROM processed
    GROUP BY region, category
    ORDER BY revenue DESC
""").pl()
```

## Type safety with Polars

Polars supports schema overrides at read time, and `.cast()` for explicit conversion. Avoid implicit coercion in hot paths.

```python
schema = {"id": pl.Int64, "amount": pl.Float64, "date": pl.Date}
df = pl.read_csv("data.csv", schema_overrides=schema)
```

basedpyright understands `polars-stubs`, which ship with polars itself. No extra type stubs to install.

## Things you might miss from pandas (and how to do them in Polars)

|pandas|polars|
|---|---|
|`df.iloc[5]`|`df.row(5)` (named tuple) or `df[5]` (single-row frame)|
|`df.loc[df["x"] > 5]`|`df.filter(pl.col("x") > 5)`|
|`df["x"].apply(fn)`|`df["x"].map_elements(fn)` (slow path) or use native expressions|
|`df.merge(...)`|`df.join(other, on="key")`|
|`df.groupby(...).agg(...)`|`df.group_by(...).agg(...)`|
|`pd.read_csv(...).dtypes`|`pl.read_csv(...).schema`|
|`df.to_dict("records")`|`df.to_dicts()`|

## Sources

- Polars docs: <https://docs.pola.rs>
- DuckDB Python API: <https://duckdb.org/docs/api/python/overview>
