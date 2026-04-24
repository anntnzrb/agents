# Cheatsheet

Run with `uv run --script <skill-dir>/scripts/cli.py ...`, replacing `<skill-dir>` with this skill directory.

## Best default

```bash
uv run --script <skill-dir>/scripts/cli.py "$QUERY" \
  --llm-json \
  --details \
  --detail-limit 2 \
  --scoring \
  --limit 5
```

## Cheap decent cables

```bash
uv run --script <skill-dir>/scripts/cli.py "usb c to usb c braided cable" \
  --llm-json \
  --max-price 10 \
  --min-rating 4.5 \
  --include braided \
  --exclude "usb a" \
  --exclude lightning \
  --details \
  --detail-limit 2 \
  --scoring \
  --limit 5
```

## Connector guardrails

- query says `usb c to usb c` → add `--exclude "usb a"`
- not Lightning → add `--exclude lightning`
- wants braided → add `--include braided`
- wants certified → add `--include certified`

## Envelope fields

- `summary.raw_result_count`
- `summary.returned_result_count`
- `results[].price`
- `results[].rating`
- `results[].review_count`
- `results[].details.brand`
- `results[].details.ships_from`
- `results[].details.sold_by`
- `results[].score`
- `results[].reasons`

## RPC search request

```json
{
  "id": "1",
  "type": "search",
  "query": "usb c to usb c braided cable",
  "maxPrice": 10,
  "minRating": 4.5,
  "include": ["braided"],
  "exclude": ["usb a", "lightning"],
  "details": true,
  "detailLimit": 2,
  "scoring": true,
  "limit": 5
}
```
