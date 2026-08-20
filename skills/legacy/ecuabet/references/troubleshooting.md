# Troubleshooting

Use this when execution fails or output quality drops.

## 1) Ecuabet id parsing failure

Symptoms:

- `error: could not resolve ecuabet event id`
- empty `feeds.ecuabet`

Checks:

- Ensure input is numeric id or URL with `/deportes/partido/<id>`
- Run direct:

```bash
uv run --script <skill-dir>/scripts/cli.py feed ecuabet <match_id_or_url> --no-raw --compact
```

## 2) Feed network/API failure

Symptoms:

- `feedErrors` has `sofascore`, `espn`, `openMeteo`, `understat`, or `ecuabet`

Checks:

- Re-run one-shot once
- Run failing feed script directly
- If still failing, proceed with available feeds and explicitly report degraded confidence

## 3) Understat team mismatch

Symptoms:

- Understat resolution errors in `feedErrors.understat`

Checks:

- Override league with `--understat-league`
- Verify team naming from `match.home` and `match.away`
- Retry `feed understat` through `scripts/cli.py` with explicit teams

## 4) Low confidence output

Symptoms:

- `oneShot.globalConfidence` unexpectedly low

Checks:

- Inspect `oneShot.feedHealth`
- Increase freshness sensitivity with smaller `--stale-threshold-seconds`
- If watch mode, keep `--line-history-limit` >= 120

## 5) Recommendation set too empty

Symptoms:

- shortlist has too few entries

Checks:

- Relax `--recommend-min-confidence`
- Increase `--recommend-max-odds`
- Add `--recommend-include-high-risk` if user accepts more variance
