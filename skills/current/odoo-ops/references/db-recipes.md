# Database Recipes

Safe PostgreSQL database operations and schema probes.

## Execution

Database queries run against the active container database (`podman exec -i odoo-db psql ...`).

## Golden Master Clones

Clone from master in ~15 seconds:

```sql
CREATE DATABASE "<target>" TEMPLATE "erptech_0817" OWNER odoo;
```
