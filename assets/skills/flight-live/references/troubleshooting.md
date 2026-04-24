# Troubleshooting

## Hard fail: missing nix

Symptom:
- `error: Kiwi web scraper requires 'nix' in PATH ...`

Fix:
1. install Nix
2. verify with `nix --version`
3. rerun

## Hard fail: agent-browser wrapper unavailable

Symptom:
- `error: agent-browser is unavailable through nix wrapper ...`

Fix:
1. run `nix run github:numtide/llm-agents.nix#agent-browser -- --version`
2. confirm flakes/nix-command enabled
3. retry search

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
- `error: agent-browser execution failed via nix wrapper ...`
- `error: agent-browser command timed out ...`

Fix:
- retry (transient)
- verify wrapper works: `nix run github:numtide/llm-agents.nix#agent-browser -- --version`
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
