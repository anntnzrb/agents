# Runtime Discovery

Dynamic resolution rules for Odoo workspaces.

## Discovery Precedence

1. **Addons Directory**:
   - Explicit flag `--root <path>`
   - Environment variable `$ODOO_ADDONS_DIR`
   - Current working directory (if containing Odoo modules or Git root)
   - Default: `~/repos/etech/odoo`

2. **Runtime Directory**:
   - Explicit flag `--runtime-dir <path>`
   - Environment variable `$ODOO_RUNTIME_DIR`
   - Discovered: `/opt/odoo17` or `~/.local/share/odoo17`

3. **Database**:
   - Explicit flag `--db <name>`
   - Active workflow profile database
   - Config file `db_name`
   - Fallback: `$ODOO17_DEFAULT_DB` or `erptech_0817-crm`
