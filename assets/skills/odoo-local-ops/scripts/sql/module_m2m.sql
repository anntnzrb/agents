-- psql variables:
--   module : addon technical name (required)
WITH module_fields AS (
    SELECT
        md.module,
        f.id AS field_id,
        f.model,
        f.name AS field_name,
        f.relation AS relation_model,
        f.relation_table,
        COALESCE(
            NULLIF(f.relation_table, ''),
            concat(replace(f.model, '.', '_'), '_', replace(f.relation, '.', '_'), '_rel')
        ) AS relation_table_name,
        f.column1,
        f.column2
    FROM ir_model_data AS md
    JOIN ir_model_fields AS f
        ON f.id = md.res_id
    WHERE md.model = 'ir.model.fields'
      AND md.module = :'module'
      AND f.ttype = 'many2many'
),
relation_tables AS (
    SELECT
        mf.module,
        mf.field_id,
        mf.model,
        mf.field_name,
        mf.relation_model,
        mf.relation_table,
        mf.relation_table_name,
        mf.column1,
        mf.column2,
        c.oid AS relation_oid,
        c.reltuples::bigint AS estimated_rows,
        s.n_live_tup::bigint AS live_rows,
        pg_total_relation_size(c.oid) AS total_bytes,
        pg_relation_size(c.oid) AS table_bytes,
        pg_indexes_size(c.oid) AS index_bytes
    FROM module_fields AS mf
    LEFT JOIN pg_class AS c
        ON c.relname = mf.relation_table_name
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
    field_name,
    relation_model,
    relation_table_name AS relation_table,
    column1,
    column2,
    relation_oid IS NOT NULL AS relation_table_exists,
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
FROM relation_tables
ORDER BY live_rows DESC NULLS LAST, total_bytes DESC NULLS LAST, model, field_name;