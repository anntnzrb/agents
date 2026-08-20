# Shortcuts

Use compact prompts with `$ecuabet`.
Pattern: `<match_id> <trigger>`.

## Core

`<id> minmax` → return:
1. best low-risk +EV picks
2. best `odds>=1.5` +EV picks
3. best upside picks, including high risk
Always include: `odds`, `modelProbabilityPct`, `confidencePct`, `expectedValue`, `riskTier`.

`<id> buckets` → return 3 buckets:
- `safe`: low risk
- `balanced`: low+medium
- `upside`: include high risk
Empty bucket → `NONE`.

`<id> lowrisk` → only low-risk picks; sort `expectedValue` desc, then `modelProbabilityPct` desc.

`<id> value` → only positive-EV picks, any risk tier; sort EV desc.

`<id> prime` → strict now-bet filter:
- `expectedValue > 0`
- `modelProbabilityPct >= 60`
- `confidencePct >= 65`
- `odds >= 1.5`
Sort `expectedValue` desc, then `modelProbabilityPct` desc, then `odds` desc. Return top 5 or `NONE`.

## Live

`<id> live` → current status/score + top recommendation + top 5 shortlist.
`<id> watch` → run/advise watch-mode behavior; report only rank changes or confidence drops.
`<id> health` → `feedHealth`, `feedErrors`, and confidence impact.

## Markets

`<id> totals` → only totals-family picks.
`<id> btts` → only BTTS picks.
`<id> handicap` → only handicap picks.
`<id> 1x2` → only 1x2 picks.

## Recommended minimal prompts

- `14339074 minmax`
- `14339074 buckets`
- `14339074 lowrisk`
- `14339074 value`
- `14339074 live`
