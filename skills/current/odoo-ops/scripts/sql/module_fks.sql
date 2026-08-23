-- psql variables:
--   module : addon technical name (required)
WITH module_tables AS (
    SELECT DISTINCT
        md.module,
        im.model,
        replace(im.model, '.', '_') AS table_name
    FROM ir_model_data AS md
    JOIN ir_model AS im
        ON im.id = md.res_id
    WHERE md.model = 'ir.model'
      AND md.module = :'module'
),
outgoing_fks AS (
    SELECT
        mt.module,
        mt.model,
        mt.table_name AS source_table,
        c.conname AS constraint_name,
        c.condeferrable,
        c.condeferred,
        c.confupdtype,
        c.confdeltype,
        s.i AS key_ordinal,
        a.attname AS source_column,
        ft.relname AS target_table,
        fa.attname AS target_column
    FROM module_tables AS mt
    JOIN pg_class AS t
        ON t.relname = mt.table_name
       AND t.relkind IN ('r', 'p')
    JOIN pg_namespace AS n
        ON n.oid = t.relnamespace
       AND n.nspname = 'public'
    JOIN pg_constraint AS c
        ON c.conrelid = t.oid
       AND c.contype = 'f'
    JOIN generate_subscripts(c.conkey, 1) AS s(i)
        ON TRUE
    JOIN pg_attribute AS a
        ON a.attrelid = t.oid
       AND a.attnum = c.conkey[s.i]
    JOIN pg_class AS ft
        ON ft.oid = c.confrelid
    JOIN pg_namespace AS fn
        ON fn.oid = ft.relnamespace
       AND fn.nspname = 'public'
    JOIN pg_attribute AS fa
        ON fa.attrelid = ft.oid
       AND fa.attnum = c.confkey[s.i]
)
SELECT
    module,
    model,
    source_table,
    constraint_name,
    key_ordinal,
    source_column,
    target_table,
    target_column,
    CASE confupdtype
        WHEN 'a' THEN 'no_action'
        WHEN 'r' THEN 'restrict'
        WHEN 'c' THEN 'cascade'
        WHEN 'n' THEN 'set_null'
        WHEN 'd' THEN 'set_default'
        ELSE confupdtype::text
    END AS on_update,
    CASE confdeltype
        WHEN 'a' THEN 'no_action'
        WHEN 'r' THEN 'restrict'
        WHEN 'c' THEN 'cascade'
        WHEN 'n' THEN 'set_null'
        WHEN 'd' THEN 'set_default'
        ELSE confdeltype::text
    END AS on_delete,
    condeferrable,
    condeferred
FROM outgoing_fks
ORDER BY source_table, constraint_name, key_ordinal;