# Output Contract

Canonical output comes from `scripts/main.py`.

## Decision-first extraction order

1. `oneShot.topRecommendation`
2. `oneShot.shortlist`
3. `oneShot.globalConfidence`
4. `oneShot.feedHealth`
5. `decisionSummary.scoreConsensus`
6. `decisionSummary.liveMetrics`
7. `decisionSummary.ecuabetMarkets`
8. `feedErrors`

## Key objects

### `oneShot.topRecommendation`

Core fields:

- `marketFamily`
- `marketName`
- `selectionName`
- `odds`
- `modelProbability`
- `fairProbability`
- `expectedValue`
- `confidence`
- `riskTier`

### `oneShot.shortlist`

Ordered list of candidate picks. Keep ordering as ranking.

### `oneShot.globalConfidence`

Global scalar in `[0, 1]` for recommendation reliability at current fetch time.

### `oneShot.feedHealth`

Per-feed health and staleness impact.

### `decisionSummary.liveMetrics`

Includes shots, xG, corners, fouls, cards, offsides, possession, saves.

### `decisionSummary.timeline`

Merged event stream from SofaScore and ESPN.

### `decisionSummary.ecuabetMarkets`

Market coverage and key lines:

- `keyLines.1x2`
- `keyLines.doubleChance`
- `keyLines.btts`
- `keyLines.handicap`
- `keyLines.totals`
- `keyLines.totals_1st_half`
- `keyLines.totals_2nd_half`

## Conflict handling

- If `feedErrors` non-empty, report exactly which feeds failed
- If `scoreConsensus.consistent` is `false`, mark recommendations as higher risk in narrative
- If `oneShot.globalConfidence < 0.55`, avoid claiming high certainty
