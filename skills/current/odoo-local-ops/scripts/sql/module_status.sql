-- psql variables:
--   module : addon technical name (required)
WITH selected_module AS (
    SELECT
        m.id,
        m.name,
        m.shortdesc,
        m.summary,
        m.state,
        m.application,
        m.demo,
        m.author,
        m.website,
        m.license,
        m.latest_version,
        m.published_version,
        m.auto_install,
        m.to_buy,
        m.category_id
    FROM ir_module_module AS m
    WHERE m.name = :'module'
),
module_dependencies AS (
    SELECT
        d.module_id,
        ARRAY_AGG(d.name ORDER BY d.name) AS dependency_names
    FROM ir_module_module_dependency AS d
    GROUP BY d.module_id
)
SELECT
    m.id,
    m.name,
    m.shortdesc,
    m.summary,
    m.state,
    m.application,
    m.demo,
    m.author,
    m.website,
    m.license,
    m.latest_version,
    m.published_version,
    m.auto_install,
    m.to_buy,
    c.name AS category_name,
    COALESCE(d.dependency_names, ARRAY[]::text[]) AS dependency_names,
    COALESCE(array_length(d.dependency_names, 1), 0) AS dependency_count
FROM selected_module AS m
LEFT JOIN ir_module_category AS c ON c.id = m.category_id
LEFT JOIN module_dependencies AS d ON d.module_id = m.id;
