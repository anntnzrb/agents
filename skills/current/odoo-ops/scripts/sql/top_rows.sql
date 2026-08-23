-- psql variables:
--   limit : maximum rows to return (required)
WITH public_tables AS (
    SELECT
        c.oid,
        c.relname AS table_name,
        c.relkind,
        CASE
            WHEN s.n_live_tup IS NOT NULL THEN GREATEST(s.n_live_tup::bigint, 0)
            ELSE GREATEST(c.reltuples::bigint, 0)
        END AS estimated_rows,
        COALESCE(s.n_dead_tup, 0)::bigint AS dead_rows,
        pg_total_relation_size(c.oid) AS total_bytes,
        s.last_analyze,
        s.last_autoanalyze
    FROM pg_class AS c
    JOIN pg_namespace AS n
        ON n.oid = c.relnamespace
    LEFT JOIN pg_stat_user_tables AS s
        ON s.relid = c.oid
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p')
)
SELECT
    table_name,
    CASE relkind
        WHEN 'r' THEN 'table'
        WHEN 'p' THEN 'partitioned_table'
        ELSE relkind::text
    END AS relation_kind,
    estimated_rows,
    dead_rows,
    total_bytes,
    pg_size_pretty(total_bytes) AS total_size,
    CASE
        WHEN estimated_rows > 0 THEN ROUND(total_bytes::numeric / estimated_rows, 2)
        ELSE NULL
    END AS avg_bytes_per_row,
    last_analyze,
    last_autoanalyze
FROM public_tables
ORDER BY estimated_rows DESC, total_bytes DESC, table_name
LIMIT CAST(:'limit' AS integer);
