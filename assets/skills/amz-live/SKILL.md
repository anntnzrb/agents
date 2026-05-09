---
name: amz-live
description: Read-only Amazon catalog search through the bundled `amz-live` CLI in this skill. Use whenever the user wants Amazon product discovery, price comparison, shortlist generation, cheap-but-decent recommendations, connector/type-specific cable hunting, structured Amazon search output, or agent-usable machine-readable results. Prefer this skill over manual browsing for Amazon shopping/search/filter/rank tasks, especially when you need repeatable filters, detail enrichment, scoring, delivery-location control, or Pi-style RPC integration.
compatibility: Requires `uv`. Uses bundled skill-local `scripts/cli.py`. Network access required for live mode.
disable-model-invocation: true
---

# amz-live

Treat this skill as the operator manual for the bundled Amazon read-only CLI.

## Entry points
- From the skill root: `uv run --script <skill-dir>/scripts/cli.py ...`
- If `SKILLS_DIR` is set: `uv run --script "$SKILLS_DIR/amz-live/scripts/cli.py" ...`
- Otherwise resolve the skill directory, then run `uv run --script <skill-dir>/scripts/cli.py ...`
- For process integration: `uv run --script <skill-dir>/scripts/cli.py --mode rpc`

## Core rule
Prefer `--llm-json` unless the user explicitly wants human text. It gives the cleanest envelope for filters, enrichment, ranking, and location context.

Why:
- stable envelope
- structured shortlist data
- easier agent reasoning
- carries filters, enrichment, and scoring metadata
- includes delivery zip context when used

## Workflow
1. Identify the task shape:
   - discovery
   - shortlist/ranking
   - detail validation
   - programmatic integration
   - blocked fetch debugging
   - location-sensitive reruns

2. Start cheap:
   - usually `--llm-json`
   - avoid `--details` on a broad first pass unless the shortlist is already tiny
   - add `--zip` early when delivery locale matters

3. Tighten with:
   - `--max-price`
   - `--min-rating`
   - `--include`
   - `--exclude`
   - `--title-contains`
   - `--badge`
   - `--zip`

4. Add `--details --detail-limit 2` only for finalists.

5. Add `--scoring` when the user wants “best”, “good enough”, “not trash”, “value”, or ranking help.

6. Answer from envelope fields, not vibes.

## Output modes
- Human: `uv run --script <skill-dir>/scripts/cli.py "wireless mouse"`
- Raw JSON: `uv run --script <skill-dir>/scripts/cli.py "wireless mouse" --json`
- LLM JSON: `uv run --script <skill-dir>/scripts/cli.py "wireless mouse" --llm-json`
- Schema: `uv run --script <skill-dir>/scripts/cli.py --schema`
- RPC: `printf '%s\n' ... | uv run --script <skill-dir>/scripts/cli.py --mode rpc`

## Fast patterns
### Broad discovery
`uv run --script <skill-dir>/scripts/cli.py "$QUERY" --llm-json --limit 10`

### Broad discovery with US/Miami delivery context
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

### Location-sensitive shortlist
```bash
uv run --script <skill-dir>/scripts/cli.py "$QUERY" \
  --zip 33101 \
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

Use fixture mode when you need parser or ranking work without live requests.

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

Example:
```bash
uv run --script <skill-dir>/scripts/cli.py "usb c pd charger 65w" --zip 33101 --llm-json
```

Behavior:
- `--zip` becomes Amazon query filter `rh=p_47:<zipcode>`
- LLM JSON includes `query.zip_code`
- RPC accepts `zipCode` and returns `query.zip_code`
- `--zip` affects live search URLs, not local `--html` parsing beyond envelope metadata

Caution:
- final pricing and delivery can still vary by session, account, Prime state, and region
- if live results still look wrong, tell the user locale/session effects may remain

## Detail enrichment
Enable only when needed:

```bash
--details --detail-limit 2
```

Adds `results[].details` when fetch succeeds:
- `brand`
- `availability_text`
- `delivery_text`
- `ships_from`
- `sold_by`
- `bullet_points`

Use detail enrichment for:
- merchant trust
- stock checks
- brand confirmation
- extracting concrete claims from bullets
- comparing delivery text after setting `--zip`

Avoid large `detail-limit` unless the user explicitly wants exhaustive inspection. Detail fields are bonuses, not hard truth, when many are null.

## Scoring
Enable when the user wants ranked recommendations.

```bash
--scoring
```

Current scoring mixes:
- rating
- review count
- relative price value
- badges
- brand signal
- certification/trust wording
- merchant trust
- stock/delivery
- connector/query mismatch penalties

Scoring helps ranking. It is not truth. Inspect top rows for sponsored or mismatched items.

## Agent answering policy
Do not dump raw JSON unless asked.

Prefer:
1. run query
2. inspect top 3-5 results
3. summarize with:
   - price
   - rating
   - review count
   - brand
   - merchant trust if available
   - delivery-locality caveat if using `--zip`
   - notable mismatch/risk
4. rerun tighter if junk remains

## Cable/accessory heuristics
When the user asks about cables/adapters:
- explicit connector terms matter more than generic quality metrics
- add negative guards aggressively
- if delivery locale matters, set `--zip` before comparing finalists

Examples:
- query says `usb c to usb c` → add `--exclude "usb a"`
- not Lightning → add `--exclude lightning`
- wants braided → add `--include braided`
- wants certification → add `--include certified`

Good cable hunt template:
```bash
uv run --script <skill-dir>/scripts/cli.py "usb c to usb c braided cable" \
  --zip 33101 \
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

## Failure handling
Possible failures:
- Amazon anti-bot / captcha / 503
- geo-specific catalog differences
- shipping locale changes results
- markup drift

If blocked:
1. retry with fewer detail fetches
2. tighten query/filter terms
3. use `--html <saved-file>` for local parsing/debug
4. try again with or without `--zip` to isolate locality
5. tell the user results may vary by locale, shipping target, or session

When outputs conflict, trust roughly in this order:
1. explicit filters/query terms
2. result title
3. detail merchant/brand fields
4. bullet points
5. score/reasons

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

## Reference files
Read only what the task needs:
- `references/cheatsheet.md` — fastest command patterns
- `references/rpc.md` — RPC request/response contract and usage
