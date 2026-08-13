-- psql variables:
--   module : addon technical name (required)
WITH module_model_links AS (
    SELECT
        md.res_id AS model_id,
        ARRAY_AGG(md.name ORDER BY md.name) AS xmlid_names
    FROM ir_model_data AS md
    WHERE md.model = 'ir.model'
      AND md.module = :'module'
    GROUP BY md.res_id
)
SELECT
    m.id,
    :'module' AS module_name,
    m.model,
    m.name AS model_name,
    m.state,
    m.transient,
    l.xmlid_names,
    replace(m.model, '.', '_') AS guessed_table,
    to_regclass(format('public.%I', replace(m.model, '.', '_')))::text AS guessed_table_regclass,
    to_regclass(format('public.%I', replace(m.model, '.', '_'))) IS NOT NULL AS guessed_table_exists
FROM module_model_links AS l
JOIN ir_model AS m
    ON m.id = l.model_id
ORDER BY m.model;
