-- psql variables:
--   module : addon technical name (required)
WITH module_models AS (
    SELECT
        md.module,
        im.id AS ir_model_id,
        im.model,
        im.name AS model_name,
        im.state AS model_state,
        im.transient,
        replace(im.model, '.', '_') AS table_name
    FROM ir_model_data AS md
    JOIN ir_model AS im
        ON im.id = md.res_id
    WHERE md.model = 'ir.model'
      AND md.module = :'module'
),
module_tables AS (
    SELECT
        mm.module,
        mm.ir_model_id,
        mm.model,
        mm.model_name,
        mm.model_state,
        mm.transient,
        mm.table_name,
        c.oid AS table_oid,
        c.relkind,
        c.reltuples::bigint AS estimated_rows,
        s.n_live_tup::bigint AS live_rows,
        pg_total_relation_size(c.oid) AS total_bytes,
        pg_relation_size(c.oid) AS table_bytes,
        pg_indexes_size(c.oid) AS index_bytes
    FROM module_models AS mm
    LEFT JOIN pg_class AS c
        ON c.relname = mm.table_name
       AND c.relkind IN ('r', 'p')
    LEFT JOIN pg_namespace AS n
        ON n.oid = c.relnamespace
       AND n.nspname = 'public'
    LEFT JOIN pg_stat_user_tables AS s
        ON s.relid = c.oid
    WHERE c.oid IS NULL OR n.oid IS NOT NULL
)
SELECT
    module,
    model,
    model_name,
    model_state,
    transient,
    table_name,
    table_oid IS NOT NULL AS table_exists,
    CASE relkind
        WHEN 'r' THEN 'table'
        WHEN 'p' THEN 'partitioned_table'
        ELSE NULL
    END AS relation_kind,
    COALESCE(estimated_rows, 0) AS estimated_rows,
    COALESCE(live_rows, 0) AS live_rows,
    total_bytes,
    table_bytes,
    index_bytes,
    CASE
        WHEN total_bytes IS NULL THEN NULL
        ELSE pg_size_pretty(total_bytes)
    END AS total_size,
    CASE
        WHEN table_bytes IS NULL THEN NULL
        ELSE pg_size_pretty(table_bytes)
    END AS table_size,
    CASE
        WHEN index_bytes IS NULL THEN NULL
        ELSE pg_size_pretty(index_bytes)
    END AS index_size
FROM module_tables
ORDER BY table_exists DESC, total_bytes DESC NULLS LAST, model;