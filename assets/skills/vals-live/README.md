# vals-live

`vals-live` is an independent, static-runtime Vals source adapter. It discovers official Vals benchmark/model/version pages at runtime, keeps immutable raw artifacts, and emits a fixed compact JSON envelope.

## Run

```text
uv run --script assets/skills/vals-live/scripts/cli.py schema
uv run --script assets/skills/vals-live/scripts/cli.py catalog
uv run --script assets/skills/vals-live/scripts/cli.py compare --models model-a,model-b --benchmarks benchmark-a
```

Offline replay uses an explicit `--snapshot <path>`. Use `--allow-stale` only when a refresh outage should deliberately serve a matching cache entry. `--cache-dir <path>` overrides the platform/XDG cache root. The raw body is retained by immutable manifest reference and is never emitted inline.

The source is deliberately data-driven: a new benchmark, model variant, task, metric, field, archive entry, or version is catalog-visible without a production allow-list. Unknown metrics remain published-but-unrankable and retain their raw spelling/evidence.

See `SKILL.md` for routing and the files under `references/` for extraction, normalization, provenance, drift, overlap, and eval details.
