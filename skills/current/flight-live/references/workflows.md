# Workflows

## 1. Search pass

Goal: map fare surface and shortlist best dates.

```bash
uv run --script <skill-dir>/scripts/cli.py \
  --origin NYC \
  --destination MAD \
  --depart-start 2026-06-01 \
  --depart-end 2026-06-30 \
  --llm-json
```

Inspect:

- `summary.planner_received`
- `summary.after_filters`
- `insights.weekend_premium_pct`
- top `results[].effective_price`

If thin/noisy:

- widen `--depart-start/--depart-end`
- relax `--nonstop`
- remove/raise `--max-budget`
- adjust `--stay-min/--stay-max` for roundtrip

## 2. Decision pass

Use payload fields, not prose instincts:

- anchor recommendation on `results[0]`
- include `decision.actions`
- include at least one `decision.avoid`
- cite weekend premium when present

## 3. User-facing answer pattern

- **Option 1**: dates; effective price; nonstop/stops; why score wins
- **Option 2**: same fields
- **Option 3**: same fields
- caveats from `warnings`
- next action from `decision.actions[0]`

## 4. RPC integration loop

1. `ping`
2. `get_schema`
3. `search`
4. persist raw envelopes for auditability
