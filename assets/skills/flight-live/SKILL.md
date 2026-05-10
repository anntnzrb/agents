---
name: flight-live
description: Read-only flight search via Kiwi web scraping through agent-browser (nix wrapper) plus public skypicker location resolution. Use for date-window fare discovery, shortlist ranking, and weekday/weekend tradeoff checks with machine-readable output.
license: GPL-3.0-or-later
compatibility: Requires `uv` and `nix`. Uses bundled skill-local `scripts/cli.py`. Network access required.
metadata:
  author: anntnzrb
allowed-tools: ""
disable-model-invocation: true
---

# flight-live

Operator manual for the bundled read-only flight CLI.

## Credentials
No credentials. No API keys. No commercial APIs.

## Entry points
- From skill root: `uv run --script <skill-dir>/scripts/cli.py ...`
- From anywhere: `uv run --script "$SKILLS_DIR/flight-live/scripts/cli.py" ...`
- If `SKILLS_DIR` is not set: `uv run --script <skill-dir>/scripts/cli.py ...`
- For process integration: `uv run --script <skill-dir>/scripts/cli.py --mode rpc`

## Core rule
Prefer `--llm-json` unless user asks for human text.

## Fast pattern
```bash
uv run --script <skill-dir>/scripts/cli.py \
  --origin GYE \
  --destination MIA \
  --depart-start 2026-08-01 \
  --depart-end 2026-10-31 \
  --trip-type roundtrip \
  --stay-min 4 \
  --stay-max 10 \
  --llm-json
```

## Failure handling
Common failures:
- missing `nix` in PATH (hard fail)
- `agent-browser` unavailable via nix wrapper (hard fail)
- provider execution/network failures (hard fail)
- over-constrained filters (empty shortlist with guidance in `decision.actions`)

Recovery order:
1. verify `nix` works
2. run `nix run github:numtide/llm-agents.nix#agent-browser -- --version`
3. widen date window
4. disable `--nonstop`
5. raise/remove `--max-budget`
6. relax `--stay-min/--stay-max`

## Evidence fields to trust most
Top-level:
- `warnings`
- `summary.planner_received`
- `summary.after_filters`
- `summary.returned`
- `resolved.origin.iata` / `resolved.destination.iata`
- `insights.weekend_premium_pct`
- `decision.recommendation`

Per result:
- `effective_price`
- `nonstop`
- `depart_date` / `return_date`
- `score`
- `reasons`
- `hints`

## RPC usage
Use RPC for strict JSONL envelopes (`ping`, `get_schema`, `search`).

Reference docs:
- `references/cheatsheet.md`
- `references/workflows.md`
- `references/rpc.md`
- `references/troubleshooting.md`
