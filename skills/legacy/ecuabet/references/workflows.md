# Workflows

Use these patterns when the user asks for deeper or repeated analysis.

## 1) Pre-match workflow

Goal: baseline probabilities and safe shortlist before kickoff.

```bash
uv run --script <skill-dir>/scripts/cli.py run <match_id_or_url> \
  --ecuabet <match_id_or_url> \
  --require-ecuabet \
  --recommend-top 10 \
  --recommend-min-confidence 0.6 \
  --no-raw \
  --compact
```

Report:

- `oneShot.globalConfidence`
- Top 3 from `oneShot.shortlist`
- `decisionSummary.understatForm`
- `decisionSummary.weather`

## 2) In-play workflow

Goal: adapt picks to live momentum and market state.

```bash
uv run --script <skill-dir>/scripts/cli.py run <match_id_or_url> \
  --ecuabet <match_id_or_url> \
  --require-ecuabet \
  --watch 20 \
  --max-iterations 0 \
  --line-history-limit 240 \
  --stale-threshold-seconds 120 \
  --no-raw \
  --compact
```

Monitor:

- `decisionSummary.liveMetrics`
- `decisionSummary.timeline`
- `recommendations.shortlist[*].movement`
- `recommendations.feedHealth`

## 3) Feed conflict workflow

Goal: resolve disagreements before recommending any line.

Steps:

1. Check `decisionSummary.scoreConsensus.consistent`
2. If inconsistent, inspect:

- `feeds.sofascore.match`
- `feeds.espn.match`
- `feeds.ecuabet.match`

3. Re-run one-shot and compare
4. If still inconsistent, downweight recommendation confidence in narrative and state risk

## 4) Market-focused workflow

Goal: user asks specifically for totals, BTTS, handicap, etc.

Steps:

1. Filter `decisionSummary.ecuabetMarkets.keyLines` to requested family
2. Compare with shortlist entries from same family
3. Keep picks with:

- positive `expectedValue`
- acceptable `riskTier` per user tolerance
- no severe `feedHealth` penalties
