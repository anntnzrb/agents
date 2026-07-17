# Amazon operational contract

Read this for output modes, exact search controls, locality behavior, enrichment, scoring, accessory heuristics, failure recovery, or trusted evidence fields.

## Output modes

- Human: `uv run --script <skill-dir>/scripts/cli.py "wireless mouse"`
- Raw JSON: `uv run --script <skill-dir>/scripts/cli.py "wireless mouse" --json`
- LLM JSON: `uv run --script <skill-dir>/scripts/cli.py "wireless mouse" --llm-json`
- Schema: `uv run --script <skill-dir>/scripts/cli.py --schema`
- RPC: `printf '%s\n' ... | uv run --script <skill-dir>/scripts/cli.py --mode rpc`

## Fast patterns

### Broad discovery

`uv run --script <skill-dir>/scripts/cli.py "$QUERY" --llm-json --limit 10`

### Zip-aware discovery

`uv run --script <skill-dir>/scripts/cli.py "$QUERY" --zip 33101 --llm-json --limit 10`

### Final shortlist

```bash
uv run --script <skill-dir>/scripts/cli.py "$QUERY" \
  --llm-json \
  --details \
  --detail-limit 2 \
  --scoring \
  --limit 5
```

### Local deterministic debug

```bash
uv run --script <skill-dir>/scripts/cli.py "$QUERY" \
  --html tests/fixtures/search_results_fragment.html \
  --llm-json
```

## Search controls

High-signal flags:

- `--max-price <n>`
- `--min-rating <n>`
- `--badge "Best Seller"`
- `--title-contains <text>`
- `--include <term>` repeatable
- `--exclude <term>` repeatable
- `--limit <n>`
- `--page <n>`
- `--pages <n>`
- `--amazon-sort <raw-amazon-sort>`
- `--zip <zipcode>`

## Delivery location / locale

Use `--zip` when the user cares about shipping locality, delivery dates, stock differences by region, price differences by region, or “change delivery address” / “assume Miami” requests.

Behavior:

- `--zip` becomes Amazon query filter `rh=p_47:<zipcode>`
- LLM JSON includes `query.zip_code`
- RPC accepts `zipCode` and returns `query.zip_code`
- `--zip` affects live search URLs, not local `--html` parsing beyond envelope metadata

Final pricing and delivery can still vary by session, account, Prime state, and region. If live results still look wrong, tell the user locale/session effects may remain.

## Detail enrichment

`--details --detail-limit 2` may add `results[].details.brand`, `availability_text`, `delivery_text`, `ships_from`, `sold_by`, and `bullet_points`. Use it for merchant trust, stock checks, brand confirmation, concrete bullet claims, and delivery text after `--zip`. Detail fields are bonuses, not hard truth, when many are null.

## Scoring

`--scoring` ranks with rating, review count, relative price value, badges, brand signal, certification/trust wording, merchant trust, stock/delivery, and connector/query mismatch penalties. It helps ranking but is not truth; inspect top rows for sponsored or mismatched items.

## Cable/accessory heuristics

Connector terms matter more than generic quality metrics. Add negative guards aggressively, and set `--zip` before comparing finalists when delivery locale matters.

Examples:

- query says `usb c to usb c` → add `--exclude "usb a"`
- not Lightning → add `--exclude lightning`
- wants braided → add `--include braided`
- wants certification → add `--include certified`

## Failure handling

Possible failures include Amazon anti-bot/captcha/503, geo-specific catalog differences, shipping locale changes, and markup drift.

If blocked:

1. retry with fewer detail fetches
2. tighten query/filter terms
3. use `--html <saved-file>` for local parsing/debug
4. try again with or without `--zip` to isolate locality
5. tell the user results may vary by locale, shipping target, or session

When outputs conflict, trust roughly in this order: explicit filters/query terms, result title, detail merchant/brand fields, bullet points, score/reasons.

## Evidence fields to trust most

Top-level:

- `summary.raw_result_count`
- `summary.returned_result_count`
- `ranking`
- `enrichment`
- `query.zip_code`

Per result:

- `price`
- `rating`
- `review_count`
- `badges`
- `details.brand`
- `details.delivery_text`
- `details.ships_from`
- `details.sold_by`
- `score`
- `reasons`
- `signal_scores`
