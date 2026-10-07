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

High-signal flags: `--max-price <n>`, `--min-rating <n>`, `--badge "Best Seller"`, `--title-contains <text>`, repeatable `--include <term>`, repeatable `--exclude <term>`, `--limit <n>`, `--page <n>`, `--pages <n>`, `--amazon-sort <raw-amazon-sort>`, `--zip <zipcode>`, `--deals`.

## Delivery location / locale

`--zip` accepts a five-digit US ZIP and sets an anonymous guest delivery session through Amazon's location widget. Search pages and detail enrichment share its cookies. Live searches fail if the page's location does not confirm the requested ZIP. Read `summary.delivery_location`; `query.zip_code` alone is the requested input, not proof. RPC accepts `zipCode`. Local `--html` parsing preserves the captured page location and does not change it.

Final price/delivery may vary by session, account, Prime state, and region. If live results still look wrong, tell the user locale/session effects may remain.

With `--html --details`, search evidence comes from the saved page but details are fetched live in a new default-location session. `--zip` does not change that replay session; do not treat its detail delivery text as ZIP-confirmed.

## Deal evidence

Search product keywords with `--zip <US-ZIP> --deals`. Amazon's deal refinement is applied before fetching result cards; `query.deal_refinement` reports its observed label. The CLI discovers the available deal refinements from the current search page after setting delivery location. It prefers broad options (`All Deals`, `All Discounts`, or `Today's Deals`), otherwise the first advertised deal option. IDs and event names are not fixed in code. The filtered response must confirm the discovered label; missing or changed filters fail explicitly. If no deal filter is advertised for a query, try broader product keywords instead of treating that as proof that Amazon has no deals. A nonempty response with a missing applied filter is an error. Pagination stops at a recognized empty page and keeps earlier verified results. Add `--badge "Prime"` to retain Prime event or membership labels. This searches the main result grid, not every offer on Amazon.

- `reference_price` and `reference_price_label` preserve Amazon's crossed-out comparison price and its label, such as `List Price` or `Typical price`. This is not verified price history.
- `discount_percent` is calculated from `price` and a higher positive `reference_price`, rounded to two decimal places. It excludes coupons and stays null without a valid comparison.
- `prime_exclusive: true` means the displayed price has an explicit membership label, such as `Exclusive Prime price`. Null means unknown. `Prime Big Deal` is an event badge and does not establish membership eligibility by itself. Prime shipping, product titles, and discounts are not membership evidence.
- `coupon_text` preserves the visible coupon offer separately. Do not subtract it from `price` or assume checkout eligibility.
- `sponsored` identifies ad links or sponsored markers; do not present an ad as an independent recommendation.
- Live `source.checked_at` records the UTC observation time. Live searches are fetched again on each request; RPC does not reuse prices indefinitely.
- Search cards do not establish the sale's expiry or account-specific checkout eligibility. Report the time, delivery location, and observed label. Do not claim event participation without a deal badge.

Empty results for an event-name query do not prove that no deals exist. A page without usable cards or an explicit no-results message fails as unrecognized markup. An explicit empty search or a non-confirmed US delivery session adds an envelope warning. Prefer a confirmed US ZIP when searching US Prime offers.

## Detail enrichment

`--details --detail-limit 2` may add `results[].details.brand`, `availability_text`, `delivery_text`, `ships_from`, `sold_by`, and `bullet_points`. Use for merchant trust, stock checks, brand confirmation, concrete bullet claims, and post-`--zip` delivery text. Enrichment fetches canonical `/dp/<ASIN>` URLs, never ad-click links, and stops on an anti-bot response. Detail fields are bonuses, not hard truth, when many are null.

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
