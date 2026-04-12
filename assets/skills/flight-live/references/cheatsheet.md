# Cheatsheet

Run from skill root with `uv run flight-live ...`; elsewhere use `scripts/flight-live.sh ...`.

## Baseline search

```bash
uv run flight-live \
  --origin NYC \
  --destination MAD \
  --depart-start 2026-06-01 \
  --depart-end 2026-06-30 \
  --llm-json
```

## Budget + nonstop

```bash
uv run flight-live \
  --origin SFO \
  --destination HND \
  --depart-start 2026-09-01 \
  --depart-end 2026-09-21 \
  --trip-type roundtrip \
  --stay-min 7 \
  --stay-max 12 \
  --nonstop \
  --max-budget 1200 \
  --llm-json
```

Roundtrip note: pricing is parsed from Kiwi date-pair buttons (departure-return combos).

## Evidence fields

- `warnings`
- `summary.planner_received`
- `summary.after_filters`
- `summary.returned`
- `insights.weekend_premium_pct`
- `results[].effective_price`
- `results[].score`
- `results[].reasons`
- `results[].hints`

## RPC search request

```json
{
  "id": "1",
  "type": "search",
  "origin": "NYC",
  "destination": "MAD",
  "departStart": "2026-06-01",
  "departEnd": "2026-06-30",
  "tripType": "oneway",
  "nonstop": false,
  "maxBudget": 900,
  "plannerLimit": 20
}
```
