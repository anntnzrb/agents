WITH public_table_summary AS (
    SELECT
        COUNT(*) AS public_table_count,
        COALESCE(SUM(c.reltuples::bigint), 0) AS estimated_public_rows,
        COALESCE(SUM(COALESCE(s.n_live_tup, 0)::bigint), 0) AS live_public_rows,
        COALESCE(SUM(pg_total_relation_size(c.oid)), 0) AS public_table_bytes
    FROM pg_class AS c
    JOIN pg_namespace AS n
        ON n.oid = c.relnamespace
    LEFT JOIN pg_stat_user_tables AS s
        ON s.relid = c.oid
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p')
),
module_counts AS (
    SELECT
        COUNT(*) FILTER (WHERE state = 'installed') AS installed_modules,
        COUNT(*) FILTER (WHERE state = 'uninstalled') AS uninstalled_modules,
        COUNT(*) FILTER (WHERE state = 'uninstallable') AS uninstallable_modules,
        COUNT(*) FILTER (WHERE state = 'to install') AS to_install_modules,
        COUNT(*) FILTER (WHERE state = 'to upgrade') AS to_upgrade_modules,
        COUNT(*) FILTER (WHERE state = 'to remove') AS to_remove_modules
    FROM ir_module_module
),
model_counts AS (
    SELECT
        COUNT(*) AS model_count,
        COUNT(*) FILTER (WHERE transient) AS transient_model_count,
        COUNT(*) FILTER (WHERE state = 'manual') AS manual_model_count
    FROM ir_model
)
SELECT
    current_database() AS database_name,
    pg_database_size(current_database()) AS database_bytes,
    pg_size_pretty(pg_database_size(current_database())) AS database_size,
    pts.public_table_count,
    pts.estimated_public_rows,
    pts.live_public_rows,
    pts.public_table_bytes,
    pg_size_pretty(pts.public_table_bytes) AS public_table_size,
    mc.model_count,
    mc.transient_model_count,
    mc.manual_model_count,
    modc.installed_modules,
    modc.uninstalled_modules,
    modc.uninstallable_modules,
    modc.to_install_modules,
    modc.to_upgrade_modules,
    modc.to_remove_modules
FROM public_table_summary AS pts
CROSS JOIN model_counts AS mc
CROSS JOIN module_counts AS modc;
