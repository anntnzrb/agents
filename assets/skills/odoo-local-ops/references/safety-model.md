# Safety model

This skill is for local operational visibility first. Destructive behavior is opt-in, explicit, and never the default.

## Default posture

Default every database interaction and workspace inspection flow to read-only.

That means:

- inspect before acting
- prefer metadata commands over SQL when a built-in subcommand exists
- prefer JSON output
- avoid side effects unless the user explicitly asks for them and the CLI exposes a write gate

## Runtime backends and safety

Host runtime DB access uses `psql.exe`/`psql` discovered from the local install tree or PATH.

Compose runtime DB access uses `docker compose exec -T db psql ...` through the CLI. Agents should still invoke `odooctl.py`, not raw Compose commands, so redaction and read-only guards remain centralized.

## Read-only SQL rules

For ad-hoc SQL, use one of:

- `db query --read-only --sql-file PATH`
- `db query --read-only --sql-stdin`

Do not encourage inline SQL shell blobs.

Read-only execution has two layers:

1. obvious mutating SQL is rejected before execution
2. the DB session is requested as read-only (`PGOPTIONS=-c default_transaction_read_only=on`) where supported

Reject obvious mutating SQL when `--read-only` is in effect. Heuristics should catch at least:

- `INSERT`
- `UPDATE`
- `DELETE`
- `MERGE`
- `UPSERT`
- `ALTER`
- `DROP`
- `TRUNCATE`
- `CREATE`
- `GRANT`
- `REVOKE`
- `COMMENT ON`
- `COPY ... FROM`
- `VACUUM`
- `ANALYZE`
- `REINDEX`
- `CALL`
- `SELECT ... INTO`
- `DO $$`
- explicit `COMMIT`, `ROLLBACK`, savepoint control, or session setting changes meant to escape the wrapper

This is a safety net, not a full SQL parser. If SQL is ambiguous, reject it under read-only mode and say why.

## Confirmation and write gates

Write-oriented actions are allowed only when all of the following are true:

1. the user clearly asked for a write
2. the command exposes an explicit gate such as `--allow-write`
3. the CLI surfaces the target database and intended effect before execution

The skill should not normalize writes into routine maintenance. Avoid examples that make destructive flows look standard.

## Secret handling and redaction

Never print secrets in normal output, logs, or examples.

Redact or omit at least:

- database passwords
- Compose `.env` password variables
- connection URIs containing credentials
- tokens or API keys found in config or environment
- full DSNs that embed credentials

Safe output patterns:

- show host, port, database, username, runtime backend, and runtime root separately
- replace passwords with redacted markers
- if a connection string must be referenced, emit a redacted form

Docs should never include live secrets or machine-specific credentials unless they are explicit safe local defaults.

## JSON-first output

Default to structured JSON for command output. Text output is fallback for quick human inspection.

JSON should be safe to share internally:

- include runtime backend/provenance and warnings
- omit or redact secrets
- include unresolved or ambiguous values instead of inventing them

## Route safety inspection

Route inspection is read-only analysis.

Expose at least two flows:

- `route list` for detected controller routes
- `route scan-writes` for heuristic write-risk inspection

Flag handlers as likely mutating when names or bodies suggest side effects, such as:

- `create`
- `write`
- `unlink`
- `copy`
- `action_`
- `button_`
- `commit`
- `rollback`
- direct cursor writes like `cr.execute(...)`
- ORM calls that usually mutate records

Treat these as risk signals, not certainty. The command should say why a route was flagged.

## Workspace safety

The skill is scoped to local inspection. It must not:

- edit the Odoo repository as part of normal operational commands
- leak path assumptions that only work on one machine
- bypass the CLI by issuing raw Docker/psql commands for normal operations

## Query examples and local truths

Examples should encode local truths that matter for safe, accurate investigation:

- cast `jsonb` to `::text` before `ILIKE`
- derive table names from `ir_model.model` with `replace(model,'.','_')` when `_table` is unavailable
- check Compose env before assuming `db_name = False` means no active DB

## Failure behavior

On safety-sensitive ambiguity, prefer a clear refusal over a plausible lie.

Good failures:

- unable to resolve active database unambiguously
- SQL rejected because read-only mode detected mutating statements
- DB execution backend could not be found through supported resolution chain

Bad failures:

- silently running against a guessed database
- printing credentials to help debug faster
- downgrading a requested read-only query into a normal session without saying so
