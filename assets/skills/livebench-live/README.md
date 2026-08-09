# livebench-live

`livebench-live` is an independent, source-backed LiveBench adapter. It discovers the current official application/bundle release selector, plans one exact release-scoped table/category/optional-cost asset set, preserves raw bytes and field-level provenance, and emits one compact JSON envelope.

## Use

```text
uv run --script assets/skills/livebench-live/scripts/cli.py releases
uv run --script assets/skills/livebench-live/scripts/cli.py leaderboard --release latest
uv run --script assets/skills/livebench-live/scripts/cli.py compare --models model-a,model-b --release latest
```

Use `--snapshot <path>` for deterministic historical fixtures, `--cache-dir <path>` for immutable cache placement, and `--allow-stale` only when an outage-served cache is explicitly acceptable. `schema` is offline and describes the stable wire contract.

The current application/bundle is release-discovery authority but not an origin-wide index. No guessed directory URL, older-release fallback, implicit stale fallback, browser runtime, screenshot, or cross-benchmark cost substitution is used.
