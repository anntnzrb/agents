# Route Safety

Route inspection in this skill is static analysis over local addon/controller source. It is read-only and should stay clearly separate from database inspection.

## Purpose

Use route commands to answer questions like:

- Which controller routes exist in this local Odoo workspace?
- Which routes are likely to mutate state?
- Which controller handlers deserve manual review before invoking any endpoint?

This is about **risk visibility**, not route execution.

## Commands

List all discovered routes:

```text
uv run --script <skill-dir>/scripts/cli.py route list --json
```

List only routes with heuristic write signals:

```text
uv run --script <skill-dir>/scripts/cli.py route scan-writes --json
```

Use `--json` by default.

## Discovery source

Route scanning should work from the resolved addon paths for the current runtime backend.

For a Compose runtime, that usually means:

- `<odoo-runtime>/source/<odoo-version>/odoo/addons`
- `<custom-addons>/addons`

For host runtimes, it means addon paths derived from `odoo.conf`.

The scanner should inspect Python files under addon directories and collect controller methods decorated with `@route`.

## Heuristic write signals

Mark a route as likely mutating when the controller handler name or AST body suggests state changes. Useful signals include:

### Function names

- `create`
- `write`
- `unlink`
- `copy`
- `action_*`
- `button_*`
- `save`
- `submit`
- `confirm`
- `approve`
- `assign`
- `sync`

### Body-level signals

- ORM writes like `.create(...)`, `.write(...)`, `.unlink(...)`, `.copy(...)`
- direct SQL like `cr.execute(...)`
- explicit transaction control like `commit` / `rollback`
- helper calls with obviously mutating names

These are **signals**, not proof. A route can look suspicious and still be harmless, or look harmless and still trigger writes indirectly.

## Output contract

Each discovered route should include enough context for review:

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

`route list` returns all routes.

`route scan-writes` returns only those with non-empty `write_signals`.

`parse_errors` should surface files that could not be parsed. That is a warning, not proof that no routes exist there.

## Review flow

Use this order:

1. `uv run --script <skill-dir>/scripts/cli.py env inspect --json`
2. `uv run --script <skill-dir>/scripts/cli.py route list --json`
3. `uv run --script <skill-dir>/scripts/cli.py route scan-writes --json`
4. read the flagged handler source before considering any invocation

Do not jump from route discovery straight to conclusions about production safety.

## Boundary with DB inspection

Separate these clearly:

- DB inspection
- route inspection
- route invocation

DB inspection answers questions about current data.
Route inspection answers questions about likely code paths.
Route invocation is out of scope for this skill unless a future version explicitly adds it.

A route with write signals is not a reason to mutate the database during investigation.

## Failure behavior

Good failures:

- parser could not read `controllers/foo.py` because of syntax error
- no routes found under resolved addon paths
- addon paths resolved but contained no controller modules

Bad failures:

- silently ignoring parse errors
- claiming no risky routes exist when files were skipped
- presenting heuristics as certainty
