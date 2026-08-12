# Amazon operational contract

Scope: output modes; search controls; locality; enrichment; scoring; accessory heuristics; failure recovery; trusted evidence.

## Output modes

Human: `uv run --script <skill-dir>/scripts/cli.py "wireless mouse"`
Raw JSON: `uv run --script <skill-dir>/scripts/cli.py "wireless mouse" --json`
LLM JSON: `uv run --script <skill-dir>/scripts/cli.py "wireless mouse" --llm-json`
Schema: `uv run --script <skill-dir>/scripts/cli.py --schema`
RPC: `printf '%s\n' ... | uv run --script <skill-dir>/scripts/cli.py --mode rpc`

## Fast patterns

Broad: `uv run --script <skill-dir>/scripts/cli.py "$QUERY" --llm-json --limit 10`
Zip-aware: `uv run --script <skill-dir>/scripts/cli.py "$QUERY" --zip 33101 --llm-json --limit 10`

Final shortlist:
```bash
uv run --script <skill-dir>/scripts/cli.py "$QUERY" \
  --llm-json \
  --details \
  --detail-limit 2 \
  --scoring \
  --limit 5
```

Local deterministic debug:
```bash
uv run --script <skill-dir>/scripts/cli.py "$QUERY" \
  --html tests/fixtures/search_results_fragment.html \
  --llm-json
```

## Search controls

High-signal flags: `--max-price <n>`, `--min-rating <n>`, `--badge "Best Seller"`, `--title-contains <text>`, repeatable `--include <term>`, repeatable `--exclude <term>`, `--limit <n>`, `--page <n>`, `--pages <n>`, `--amazon-sort <raw-amazon-sort>`, `--zip <zipcode>`.

## Delivery location / locale

Use `--zip` for shipping locality, delivery dates, regional stock or price, or “change delivery address” / “assume Miami”. Behavior: `--zip` → Amazon query filter `rh=p_47:<zipcode>`; LLM JSON includes `query.zip_code`; RPC accepts `zipCode` and returns `query.zip_code`; `--zip` affects live search URLs, not local `--html` parsing beyond envelope metadata.

Final price/delivery may vary by session, account, Prime state, and region. If live results still look wrong, tell the user locale/session effects may remain.

## Detail enrichment

`--details --detail-limit 2` may add `results[].details.brand`, `availability_text`, `delivery_text`, `ships_from`, `sold_by`, and `bullet_points`. Use for merchant trust, stock checks, brand confirmation, concrete bullet claims, and post-`--zip` delivery text. Detail fields are bonuses, not hard truth, when many are null.

## Scoring

`--scoring` ranks by rating, review count, relative price value, badges, brand signal, certification/trust wording, merchant trust, stock/delivery, and connector/query mismatch penalties. Ranking helps but is not truth; inspect top rows for sponsored or mismatched items.

## Cable/accessory heuristics

Connector terms > generic quality metrics. Add negative guards aggressively; set `--zip` before comparing finalists when delivery locale matters.

- `usb c to usb c` query → `--exclude "usb a"`
- not Lightning → `--exclude lightning`
- braided wanted → `--include braided`
- certification wanted → `--include certified`

## Failure handling

Possible failures: Amazon anti-bot/captcha/503, geo-specific catalog differences, shipping locale changes, markup drift.

If blocked:
1. Retry with fewer detail fetches.
2. Tighten query/filter terms.
3. Use `--html <saved-file>` for local parsing/debug.
4. Retry with or without `--zip` to isolate locality.
5. Tell the user results may vary by locale, shipping target, or session.

Conflicting outputs: trust roughly in this order: explicit filters/query terms > result title > detail merchant/brand fields > bullet points > score/reasons.

## Evidence fields to trust most

Top-level: `summary.raw_result_count`, `summary.returned_result_count`, `ranking`, `enrichment`, `query.zip_code`.

Per result: `price`, `rating`, `review_count`, `badges`, `details.brand`, `details.delivery_text`, `details.ships_from`, `details.sold_by`, `score`, `reasons`, `signal_scores`.
