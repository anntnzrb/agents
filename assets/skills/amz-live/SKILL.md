---
name: amz-live
description: Read-only Amazon catalog search through the bundled `amz-live` CLI in this skill. Use whenever the user wants Amazon product discovery, price comparison, shortlist generation, cheap-but-decent recommendations, connector/type-specific cable hunting, structured Amazon search output, or agent-usable machine-readable results. Prefer this skill over manual browsing for Amazon shopping/search/filter/rank tasks, especially when you need repeatable filters, detail enrichment, scoring, delivery-location control, or Pi-style RPC integration.
license: GPL-3.0-or-later
compatibility: Requires `uv`. Uses bundled skill-local `scripts/cli.py`. Network access required for live mode.
metadata:
  author: anntnzrb
allowed-tools: ""
disable-model-invocation: true
---

# amz-live

Read-only Amazon catalog search through the bundled skill-local CLI. Use it for Amazon product discovery, price comparison, shortlist generation, cheap-but-decent recommendations, connector/type-specific cable hunts, structured output, delivery-location reruns, and process/RPC integration.

## Entry points

- From the skill root: `uv run --script <skill-dir>/scripts/cli.py ...`
- If `SKILLS_DIR` is set: `uv run --script "$SKILLS_DIR/amz-live/scripts/cli.py" ...`
- Otherwise resolve the skill directory, then run `uv run --script <skill-dir>/scripts/cli.py ...`
- For process integration: `uv run --script <skill-dir>/scripts/cli.py --mode rpc`

## Core rules

- Prefer `--llm-json` unless the user explicitly wants human text.
- Start cheap; avoid `--details` on a broad first pass unless the shortlist is already tiny.
- Add `--zip` early when delivery locality matters.
- Add `--details --detail-limit 2` only for finalists.
- Add `--scoring` when the user wants “best”, “good enough”, “not trash”, “value”, or ranking help.
- Answer from envelope fields, not vibes.
- Do not dump raw JSON unless asked.

## Required follow-up reads

| Reference                       | Read when                                                                                                                                                                                  |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `references/cheatsheet.md`      | You need the shortest correct command for discovery, shortlist, details, scoring, zip-aware search, fixture parsing, or trusted fields.                                                    |
| `references/workflows.md`       | You need multi-step task routing for discovery, recommendation, cable/accessory filtering, finalist validation, location-sensitive reruns, detail enrichment, or user-facing answer shape. |
| `references/rpc.md`             | You are integrating with the CLI as a process, need `--mode rpc`, request/response schema, or field names such as `zipCode` / `query.zip_code`.                                            |
| `references/troubleshooting.md` | Live fetching is blocked, detail enrichment is sparse, results look locale/session-dependent, parser output changed, output fields conflict, or fixture-mode debugging is needed.          |

## Workflow

1. Identify the task shape:
   - discovery
   - shortlist/ranking
   - detail validation
   - programmatic integration
   - blocked fetch debugging
   - location-sensitive reruns
2. Run an `--llm-json` discovery pass with `--limit 10`; add `--zip` if locality matters.
3. Tighten with `--max-price`, `--min-rating`, `--include`, `--exclude`, `--title-contains`, `--badge`, `--zip`, `--page`, `--pages`, or `--amazon-sort`.
4. For finalists, rerun with `--details --detail-limit 2 --scoring --limit 5`.
5. Inspect top 3-5 results, then summarize price, rating, review count, brand, merchant trust when available, delivery-locality caveat when using `--zip`, and mismatch/risk.

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

## Reference routing

Use the Required follow-up reads table near the top of this file; do not preload references for routine searches.
