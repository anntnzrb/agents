# Route Safety

Scope: route inspection = read-only static analysis of local addon/controller source; keep it separate from DB inspection. Purpose: risk visibility, not route execution.

## Commands

List all discovered routes:

```text
uv run --script <skill-dir>/scripts/cli.py route list --json
```

List routes with heuristic write signals:

```text
uv run --script <skill-dir>/scripts/cli.py route scan-writes --json
```

Use `--json` by default.

## Discovery

Scan resolved addon paths for the current runtime backend. Compose paths usually include:

- `<odoo-runtime>/source/<odoo-version>/odoo/addons`
- `<custom-addons>/addons`

For host runtimes, derive addon paths from `odoo.conf`. Inspect Python files under addon directories and collect controller methods decorated with `@route`.

## Heuristic write signals

Mark a route likely mutating when its handler name or AST body suggests state changes.

Function names:

- `create`, `write`, `unlink`, `copy`, `action_*`, `button_*`
- `save`, `submit`, `confirm`, `approve`, `assign`, `sync`

Body signals:

- ORM writes: `.create(...)`, `.write(...)`, `.unlink(...)`, `.copy(...)`
- direct SQL: `cr.execute(...)`
- transaction control: `commit` / `rollback`
- helper calls with obviously mutating names

Signals are not proof: suspicious routes may be harmless, and apparently harmless routes may trigger indirect writes.

## Output contract

Each discovered route includes enough review context:

- `module`
- `controller`
- `function`
- `paths`
- `methods`
- `auth`
- `route_type`
- `source`
- `line`
- `write_signals`

`route list` returns all routes. `route scan-writes` returns only routes with non-empty `write_signals`.

Surface `parse_errors` for files that could not be parsed; this warns about skipped analysis, not proof that no routes exist there.

## Review flow

1. `uv run --script <skill-dir>/scripts/cli.py env inspect --json`
2. `uv run --script <skill-dir>/scripts/cli.py route list --json`
3. `uv run --script <skill-dir>/scripts/cli.py route scan-writes --json`
4. Read flagged handler source before considering any invocation.

Do not infer production safety directly from route discovery.

## DB boundary

Keep these distinct:

- DB inspection — current data
- route inspection — likely code paths
- route invocation — out of scope unless a future version explicitly adds it

Write signals do not justify database mutation during investigation.

## Failure behavior

Report:

- parser could not read `controllers/foo.py` because of syntax error
- no routes found under resolved addon paths
- addon paths resolved but contained no controller modules

Never:

- silently ignore parse errors
- claim no risky routes exist when files were skipped
- present heuristics as certainty
