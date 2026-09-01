---
disable-model-invocation: true
name: odoo-ops
description: "Use when running Odoo 17 dev server, test runner, linter/formatter, and inspecting workspaces or databases."
license: AGPL-3.0-or-later
---

# Odoo Ops

Single-control skill for Odoo 17 dev stack, test runner, linter/formatter, and PostgreSQL inspection.

Use the bundled CLI as the single entrypoint:

```bash
uv run --script <skill-dir>/scripts/cli.py ...
```

## The 4 Core Commands

### 1. Dev Runner (`dev`)
Starts the local development stack directly in foreground with instant hot-reloading (`--dev=all`). (Press `Ctrl-C` to stop).

```bash
uv run --script <skill-dir>/scripts/cli.py dev <workflow> [--pretty]
```

### 2. Test Runner (`test`)
Runs a fast preliminary linter/formatter check, then executes an isolated headless test gauntlet.

```bash
uv run --script <skill-dir>/scripts/cli.py test <workflow|module> [--pretty] [--skip-lint]
```

### 3. Linter Gate (`lint`)
Runs Ruff linter across workflow modules or single module with `<skill>/config/ruff.toml`.

```bash
uv run --script <skill-dir>/scripts/cli.py lint <workflow|module> [--fix] [--pretty]
```

### 4. Formatter Gate (`fmt`)
Runs Ruff formatter across workflow modules or single module.

```bash
uv run --script <skill-dir>/scripts/cli.py fmt <workflow|module> [--check] [--pretty]
```

## Stack Control & Logs

```bash
uv run --script <skill-dir>/scripts/cli.py stop     # Stop development stack and free resources
uv run --script <skill-dir>/scripts/cli.py logs     # Follow live server logs
```

## Workflows & Profiles

Workflows are defined in `<skill>/profiles/<profile>.json`:

- **`crm`**: `erptech_0817-crm` (CRM, WhatsApp, B2B, Budget, Templates)

Linter and formatter configurations are centralized in `<skill>/config/ruff.toml`.
