-- psql variables:
--   limit : maximum rows to return (required)
WITH public_tables AS (
    SELECT
        c.oid,
        c.relname AS table_name,
        c.relkind,
        c.reltuples::bigint AS estimated_rows,
        COALESCE(s.n_live_tup, 0)::bigint AS live_rows,
        COALESCE(s.n_dead_tup, 0)::bigint AS dead_rows,
        COALESCE(s.seq_scan, 0)::bigint AS seq_scan,
        COALESCE(s.idx_scan, 0)::bigint AS idx_scan,
        pg_total_relation_size(c.oid) AS total_bytes,
        pg_relation_size(c.oid) AS table_bytes,
        pg_indexes_size(c.oid) AS index_bytes,
        s.last_vacuum,
        s.last_autovacuum,
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
    live_rows,
    dead_rows,
    seq_scan,
    idx_scan,
    total_bytes,
    table_bytes,
    index_bytes,
    pg_size_pretty(total_bytes) AS total_size,
    pg_size_pretty(table_bytes) AS table_size,
    pg_size_pretty(index_bytes) AS index_size,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze
FROM public_tables
ORDER BY total_bytes DESC, live_rows DESC, table_name
LIMIT CAST(:'limit' AS integer);
