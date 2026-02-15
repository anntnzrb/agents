# Shortcuts

Use these compact prompts with `$ecuabet`.

Pattern: `<match_id> <trigger>`

## Core triggers

- `<id> minmax`
Return:
1. best low-risk +EV picks
2. best odds>=1.5 +EV picks
3. best upside picks (include high risk)
Always include: `odds`, `modelProbabilityPct`, `confidencePct`, `expectedValue`, `riskTier`.

- `<id> buckets`
Return 3 buckets:
1. `safe` (low risk)
2. `balanced` (low+medium)
3. `upside` (include high risk)
If a bucket has no qualifying picks, return `NONE`.

- `<id> lowrisk`
Only low-risk picks, sorted by `expectedValue` desc, then `modelProbabilityPct` desc.

- `<id> value`
Only positive-EV picks, any risk tier, sorted by EV desc.

- `<id> prime`
Strict now-bet filter:
1. `expectedValue > 0`
2. `modelProbabilityPct >= 60`
3. `confidencePct >= 65`
4. `odds >= 1.5`
Sort: `expectedValue` desc, then `modelProbabilityPct` desc, then `odds` desc.
Return top 5 or `NONE`.

## Live triggers

- `<id> live`
Return current status/score + top recommendation + top 5 shortlist.

- `<id> watch`
Run/advise watch-mode behavior and report only rank changes or confidence drops.

- `<id> health`
Return `feedHealth`, `feedErrors`, and confidence impact.

## Market triggers

- `<id> totals`
Only totals-family picks.

- `<id> btts`
Only BTTS picks.

- `<id> handicap`
Only handicap picks.

- `<id> 1x2`
Only 1x2 picks.

## Recommended minimal prompts

- `14339074 minmax`
- `14339074 buckets`
- `14339074 lowrisk`
- `14339074 value`
- `14339074 live`
