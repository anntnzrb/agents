# Troubleshooting

## Hard fail: agent-browser wrapper unavailable

Confirm that `agent-browser` is installed beside `flight-live`, then run:

```text
uv run --script <agent-browser-skill-dir>/scripts/cli.py --version
```

Follow any error from the wrapper, then retry the search.

## Date window invalid

Symptom:

- `error: depart-end must be >= depart-start`

Fix:

- correct date ordering

## No results after filters

Symptom:

- `warnings` says no planner offers after filters
- empty `results`

Fix order:

1. widen departure window
2. disable `--nonstop`
3. remove/raise `--max-budget`
4. relax stay window for roundtrip

## Provider execution/network failures

Symptoms:

- `error: agent-browser execution failed via sibling wrapper ...`
- `error: agent-browser command timed out ...`

Fix:

- retry (transient)
- verify the wrapper works: `uv run --script <agent-browser-skill-dir>/scripts/cli.py --version`
- reduce window size

## RPC request errors

Common issues:

- non-JSON lines
- wrong field types (e.g. string instead of integer)
- missing required `search` fields

Smoke test:

```bash
printf '%s\n' '{"id":"1","type":"ping"}' | uv run --script <skill-dir>/scripts/cli.py --mode rpc
```

## Evidence priority when conflicted

Trust order:

1. `warnings`
2. `summary.returned`
3. `results[].effective_price`
4. `results[].reasons`
5. `decision.recommendation`
