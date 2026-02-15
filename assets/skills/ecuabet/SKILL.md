---
name: ecuabet
description: "Advanced multi-feed Ecuabet match intelligence using skill-local scripts and references. Use when given an Ecuabet match id/url and you need one-shot or live decision output with confidence, EV, market context, incidents, and feed-health diagnostics."
---

# Ecuabet

## Overview

This skill uses the local scripts in `scripts/` as the operational core and local docs in `references/` for advanced execution patterns.

## Activation Triggers
- User mentions `$ecuabet`.
- User gives an Ecuabet match id/url and asks for predictions.
- User asks for live refresh with cards/fouls/offsides/corners/weather/form context.
- User asks for lower-risk vs higher-return tradeoff using current market state.

## Layout
- `scripts/main.py`: integrated entrypoint (all feeds + recommendations).
- `scripts/ecuabet.py`: Ecuabet markets/tracker.
- `scripts/sofascore.py`: live match incidents/stats.
- `scripts/espn.py`: ESPN summary/team stats/key events.
- `scripts/open_meteo.py`: weather context.
- `scripts/understat.py`: form/xG/season modeling.
- `scripts/recommendations.py`: scoring/ranking engine.
- `scripts/tests/`: regression tests.
- `references/recipes.md`: command cookbook.
- `references/shortcuts.md`: trigger-word prompt shortcuts.
- `references/workflows.md`: advanced scenario workflows.
- `references/output-contract.md`: JSON field map and extraction priorities.
- `references/troubleshooting.md`: feed failure diagnosis + recovery.

## Runbook

Assumption: current directory is this skill folder (the one containing `SKILL.md`).

### One-shot integrated output
```bash
uv run scripts/main.py <match_id_or_url> \
  --ecuabet <match_id_or_url> \
  --require-ecuabet \
  --no-raw \
  --compact
```

### Live watch mode
```bash
uv run scripts/main.py <match_id_or_url> \
  --ecuabet <match_id_or_url> \
  --require-ecuabet \
  --watch 15 \
  --max-iterations 0 \
  --no-raw \
  --compact
```

### Recommendation tuning
```bash
uv run scripts/main.py <match_id_or_url> \
  --ecuabet <match_id_or_url> \
  --require-ecuabet \
  --recommend-top 10 \
  --recommend-min-odds 1.01 \
  --recommend-max-odds 4.0 \
  --recommend-min-confidence 0.55 \
  --stale-threshold-seconds 120 \
  --line-history-limit 240 \
  --no-raw \
  --compact
```

### Per-feed debug
```bash
uv run scripts/ecuabet.py <match_id_or_url> --no-raw --compact
uv run scripts/sofascore.py "<team_a> <team_b>" --no-raw --compact
uv run scripts/espn.py "<team_a> <team_b>" --league esp.1 --no-raw --compact
uv run scripts/open_meteo.py "<lat,lon>" --hourly-limit 12 --compact
uv run scripts/understat.py --league La_Liga --season 2025 --home-team "<team_a>" --away-team "<team_b>" --compact
```

### Quality gate
```bash
cd scripts
uv run pytest tests -q
```

## Output Focus

Primary fields to report from `scripts/main.py` output:
- `oneShot.topRecommendation`
- `oneShot.shortlist`
- `oneShot.globalConfidence`
- `oneShot.feedHealth`
- `decisionSummary.liveMetrics`
- `decisionSummary.timeline`
- `decisionSummary.ecuabetMarkets`
- `feedErrors`

## Reference Loading Rules

- Start with `references/recipes.md` for exact runnable commands.
- Load `references/shortcuts.md` when user uses compact prompts like `<id> minmax`.
- Load `references/workflows.md` when the user asks for pre-match, in-play, or watch-loop strategy.
- Load `references/output-contract.md` when you need strict output-field interpretation.
- Load `references/troubleshooting.md` when any feed fails or data conflicts.

## Resource Policy

- Use `scripts/` for execution.
- Use `references/` for advanced guidance and structured interpretation.
- No `assets/` are required for this skill at this time.
