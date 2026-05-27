-- psql variables:
--   limit : maximum rows to return (required)
WITH model_tables AS (
    SELECT DISTINCT
        replace(model, '.', '_') AS table_name
    FROM ir_model
),
public_tables AS (
    SELECT
        c.oid,
        c.relname AS table_name,
        c.relkind,
        c.reltuples::bigint AS estimated_rows,
        s.n_live_tup::bigint AS live_rows,
        pg_total_relation_size(c.oid) AS total_bytes,
        pg_relation_size(c.oid) AS table_bytes,
        pg_indexes_size(c.oid) AS index_bytes
    FROM pg_class AS c
    JOIN pg_namespace AS n
        ON n.oid = c.relnamespace
    LEFT JOIN pg_stat_user_tables AS s
        ON s.relid = c.oid
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p')
),
orphan_tables AS (
    SELECT
        pt.table_name,
        pt.relkind,
        pt.estimated_rows,
        pt.live_rows,
        pt.total_bytes,
        pt.table_bytes,
        pt.index_bytes,
        pt.table_name LIKE '%\_rel' ESCAPE '\' AS looks_like_relation_table
    FROM public_tables AS pt
    LEFT JOIN model_tables AS mt
        ON mt.table_name = pt.table_name
    WHERE mt.table_name IS NULL
)
SELECT
    table_name,
    CASE relkind
        WHEN 'r' THEN 'table'
        WHEN 'p' THEN 'partitioned_table'
        ELSE relkind::text
    END AS relation_kind,
    looks_like_relation_table,
    COALESCE(estimated_rows, 0) AS estimated_rows,
    COALESCE(live_rows, 0) AS live_rows,
    total_bytes,
    table_bytes,
    index_bytes,
    pg_size_pretty(total_bytes) AS total_size,
    pg_size_pretty(table_bytes) AS table_size,
    pg_size_pretty(index_bytes) AS index_size
FROM orphan_tables
ORDER BY total_bytes DESC, live_rows DESC, table_name
LIMIT CAST(:'limit' AS integer);
