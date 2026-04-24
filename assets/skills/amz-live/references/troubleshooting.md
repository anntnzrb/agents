# Troubleshooting

## Amazon blocked request

Symptoms:
- 503
- captcha
- robot check text
- empty/useless live output

Actions:
1. retry later
2. reduce detail fetches
3. narrow query
4. use fixture/debug mode if parser work only

## Results look wrong

Common causes:
- query too broad
- locale/shipping target affecting marketplace view
- sponsored items
- connector mismatch not fully filtered

Fixes:
- add `--include` for must-have terms
- add `--exclude` for explicit wrong types
- add `--title-contains` for exact phrase pressure
- add `--scoring`
- inspect `results[].reasons` and `signal_scores`

## Cable ranking weirdness

Typical cause: query lacks negative guards.

Examples:
- wanted USB-C↔USB-C but got USB-A noise
  - add `--exclude "usb a"`
- wanted non-Lightning
  - add `--exclude lightning`
- wanted braided only
  - add `--include braided`

## Detail enrichment missing

`results[].details` may be `null` because:
- detail fetch failed
- Amazon blocked detail page
- markup drift
- detail limit too low

Fixes:
- lower `--detail-limit`
- retry later
- use detail fields only as bonuses, not hard truth, when many nulls appear

## RPC errors

Check:
- request field should be `type`
- one JSON object per line
- booleans should be actual JSON booleans
- `type: search` requires `query`

Good smoke test:
```bash
printf '%s\n' '{"id":"1","type":"ping"}' | uv run --script <skill-dir>/scripts/cli.py --mode rpc
```

## Local deterministic debug

Use fixture mode when debugging output contract or ranking logic:

```bash
uv run --script <skill-dir>/scripts/cli.py "$QUERY" \
  --html tests/fixtures/search_results_fragment.html \
  --llm-json
```

## Evidence priority

When outputs conflict, trust roughly in this order:
1. explicit filters/query terms
2. result title
3. detail merchant/brand fields
4. bullet points
5. score/reasons

Score helps ranking. It does not override obvious query mismatch.
