# Parallel Work with Separate Replicas

Read this before splitting work across agents that each need their own local database. Every agent still follows [Database recipes](db-recipes.md) and the delegation boundary in `SKILL.md`.

## One replica per delegated agent

- Give each agent its own working replica named `<prodDB>_work_<YYYYMMDD>_<slug>`, where `<slug>` is a short identifier of lowercase letters or digits for the agent's task.
- Only the orchestrator clones and drops replicas. Clone each one from the seed; never write to the seed:

```text
uv run --script <skill-dir>/scripts/cli.py db-clone <prodDB>_seed_<YYYYMMDD> <prodDB>_work_<YYYYMMDD>_<slug> --force
uv run --script <skill-dir>/scripts/cli.py db-drop <prodDB>_work_<YYYYMMDD>_<slug> --force
```

- Each agent passes `--db <prodDB>_work_<YYYYMMDD>_<slug>` explicitly to `test`, `shell`, and `db-query`. The default database may belong to another agent.
- Each agent also needs its own checkout or worktree. The CLI mounts the current checkout into every Odoo container, so agents sharing a checkout share code changes.
- Integrate the agents' branches at the end, then run the full test suite on one replica.

## Size the fan-out

- Each clone takes about as much disk as the seed. Check free disk space before cloning: `db-list` reports database sizes.
- Each concurrent `test` run starts its own Odoo container, and every run shares the single PostgreSQL container. Bound the number of agents by available RAM, CPU, and disk.

## Current limits

`test` runs lock per database (`odoo-ops-test-<db>.lock`), `db-clone`, `db-drop`, and `db-restore` wait on the locks of the databases they touch, and other database commands wait for a run on their database before they start. Pod creation keeps a global lock (`odoo-ops.lock`), and `stop` waits for every running test. The following shared resources still collide when two `test` runs on different databases overlap, so do not assume full parallelism:

- Every test run first removes test containers under the active profile's prefix, including a concurrent run's container.
- Single-run container names use a timestamp with one-second resolution, so simultaneous runs can collide.
- Every test container in the pod uses the same HTTP port (the profile's test HTTP port, or `ODOO_TEST_HTTP_PORT`), and the pod shares one network namespace.
- `logs -c test` follows the newest test container for the active profile, which may belong to another run.
- All Odoo containers mount the same `<runtime>/data/web` directory. Filestores are per database, but the directory is shared.
- `stop` and `prune` act on the whole stack, not on one agent's runs.
- `test --parallel` runs one container per module against a single database, and each container updates its assigned module with `-u <module>`. Concurrent updates to the same database can conflict. Run the workflow suite sequentially (`test <workflow>`) on a shared database.
