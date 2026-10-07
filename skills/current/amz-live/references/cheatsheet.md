# Cheatsheet

Run with `uv run --script <skill-dir>/scripts/cli.py ...`, replacing `<skill-dir>` with this skill directory.

Read this when the shortest correct Amazon query command is needed.

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
- `summary.delivery_location`, `query.deal_refinement`, and live `source.checked_at`
- `results[].price`
- `results[].rating`
- `results[].review_count`
- `results[].reference_price` and `reference_price_label`
- `results[].discount_percent` (before coupons, relative to the displayed reference)
- `results[].prime_exclusive` (true for an explicit membership-price label, otherwise null)
- `results[].coupon_text`
- `results[].sponsored`
- `results[].details.brand`
- `results[].details.ships_from`
- `results[].details.sold_by`
- `results[].score`
- `results[].reasons`

## Prime offers

```bash
uv run --script <skill-dir>/scripts/cli.py "wireless earbuds" --zip 33101 --deals --badge "Prime" --llm-json --limit 10
```

Read `operational-contract.md` before interpreting deal evidence. Empty output means no matching labels were parsed in this search, not that Amazon has no Prime deals.

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
