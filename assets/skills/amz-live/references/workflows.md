# Workflows

Use for multi-pass discovery, ranking, enrichment, or location-aware recommendations.

## 1. Discovery

Goal: broad candidate set, low request cost.

```bash
uv run --script <skill-dir>/scripts/cli.py "$QUERY" --llm-json --limit 10
```

Inspect `summary.raw_result_count`; connector/type mismatches; obvious junk brands; price bands.
If noisy, tighten with `--include ...`, `--exclude ...`, `--max-price ...`, `--min-rating ...`.

## 2. Shortlist

Goal: final candidates with richer evidence.

```bash
uv run --script <skill-dir>/scripts/cli.py "$QUERY" \
  --llm-json \
  --details \
  --detail-limit 2 \
  --scoring \
  --limit 5
```

Inspect `results[].details.brand`; `results[].details.ships_from`; `results[].details.sold_by`; `results[].details.bullet_points`; `results[].score`; `results[].reasons`.

## 3. Query tightening

Sequence: broad query → inspect junk → add excludes → rerun → only then add details/scoring.

Examples:
- wrong USB-A results → `--exclude "usb a"`
- unwanted Lightning → `--exclude lightning`
- wants braided only → `--include braided`
- wants certified only → `--include certified`

## 4. User-facing answer

Prefer top 3 options; each with price, rating, review count, brand; mention merchant trust only when meaningful; mention one risk or mismatch if present.

Template:
- **Option 1** — `$X` — `Y★` — `N reviews` — why it wins
- **Option 2** — ...
- **Option 3** — ...
- caveats: shipping, locale, sponsored weirdness

## 5. Cable-specific playbook

Best default:

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

If still noisy:
- add `--title-contains "usb c to usb c"`
- add `--include certified`
- raise `--min-rating`
- lower `--limit`

## 6. Fixture/debug mode

Use when debugging parser/scoring without live requests.

```bash
uv run --script <skill-dir>/scripts/cli.py "$QUERY" \
  --html tests/fixtures/search_results_fragment.html \
  --llm-json
```

Good for schema work; output-contract checks; scoring regression checks; parser investigation.
