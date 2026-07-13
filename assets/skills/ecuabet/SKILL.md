---
name: ecuabet
description: Analyze an Ecuabet match URL or ID for live odds, EV, incidents, and feed health.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
---

# Ecuabet

## Overview

This skill uses `scripts/cli.py` as the public cross-platform entrypoint and local docs in `references/` for advanced execution patterns.

## Activation Triggers

- User mentions `$ecuabet`.
- User gives an Ecuabet match id/url and asks for predictions.
- User asks for live refresh with cards/fouls/offsides/corners/weather/form context.
- User asks for lower-risk vs higher-return tradeoff using current market state.

## Entry point

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. Do not rely on shell sourcing, executable bits, or shebang dispatch.

## Layout

- `scripts/cli.py`: public dispatcher (`run` and `feed`).
- `scripts/main.py`: integrated internal entrypoint (all feeds + recommendations).
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
uv run --script <skill-dir>/scripts/cli.py run <match_id_or_url> \
  --ecuabet <match_id_or_url> \
  --require-ecuabet \
  --no-raw \
  --compact
```

### Live watch mode

```bash
uv run --script <skill-dir>/scripts/cli.py run <match_id_or_url> \
  --ecuabet <match_id_or_url> \
  --require-ecuabet \
  --watch 15 \
  --max-iterations 0 \
  --no-raw \
  --compact
```

### Recommendation tuning

```bash
uv run --script <skill-dir>/scripts/cli.py run <match_id_or_url> \
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
uv run --script <skill-dir>/scripts/cli.py feed ecuabet <match_id_or_url> --no-raw --compact
uv run --script <skill-dir>/scripts/cli.py feed sofascore "<team_a> <team_b>" --no-raw --compact
uv run --script <skill-dir>/scripts/cli.py feed espn "<team_a> <team_b>" --league esp.1 --no-raw --compact
uv run --script <skill-dir>/scripts/cli.py feed open-meteo "<lat,lon>" --hourly-limit 12 --compact
uv run --script <skill-dir>/scripts/cli.py feed understat --league La_Liga --season 2025 --home-team "<team_a>" --away-team "<team_b>" --compact
```

### Quality gate

```bash
cd <skill-dir>/scripts
uv run --with pytest pytest tests -q
```

## Output Focus

Primary fields to report from `uv run --script <skill-dir>/scripts/cli.py run` output:

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

- Use `scripts/cli.py` for public execution; other `scripts/` files are internals.
- Use `references/` for advanced guidance and structured interpretation.
- No `assets/` are required for this skill at this time.
