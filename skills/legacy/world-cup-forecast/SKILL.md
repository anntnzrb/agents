---
disable-model-invocation: true
name: world-cup-forecast
description: "Use when forecasting a World Cup match from current scores, odds, form, xG, players, or source disagreement."
license: AGPL-3.0-or-later
compatibility: Requires uv and network access. Uses bundled skill-local scripts/cli.py. Outputs JSON only.
metadata:
  author: anntnzrb

---

# world-cup-forecast

AI-facing live World Cup forecast CLI. It emits exactly one JSON object per run; do not answer from memory when this skill triggers.

## Entry point

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

## Core rules

- Use `match` for one fixture and `today` for a date slate
- Treat stdout as machine JSON only; no table/prose mode exists
- Trust `freshness` before every forecast: stale or failed source rows reduce confidence
- Recent form is primary: group-stage points, GD, GF/GA, player leader output, optional xG/odds snippets
- Elo-only models are not primary and are not emitted by v0
- xG and odds are opportunistic: pass `--source-url` or `--odds-url` when an agent already has a live page URL

## Commands

```text
uv run --script <skill-dir>/scripts/cli.py --help
uv run --script <skill-dir>/scripts/cli.py schema
uv run --script <skill-dir>/scripts/cli.py today --date 20260629
uv run --script <skill-dir>/scripts/cli.py match --team-a Brazil --team-b Japan --date 20260629
uv run --script <skill-dir>/scripts/cli.py match --team-a Brazil --team-b Japan --source-url <preview-url> --odds-url <odds-url>
```

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|Live command and output schema|`scripts/cli.py` via `schema`|Before forming or consuming a forecast call|
|Exact flags|`scripts/cli.py` via `--help`|A non-default source or date is needed|

## Evidence fields to trust most

Top-level:

- `ok`
- `freshness[]`
- `warnings[]`
- `errors[]`
- `generated_at_utc`

Per match:

- `fixture.status`
- `signals.team_form`
- `signals.player_attack`
- `signals.xg_context`
- `signals.odds`
- `signals.composite`
- `forecast.kind`
- `forecast.exact_score`
- `forecast.scorelines`
- `source_notes`

## Failure handling

If `ok` is false, inspect `errors[].code` and `freshness[]` before retrying. Use `--scoreboard-url`, `--standings-url`, or `--stats-url` only when ESPN endpoints have moved or a fixture endpoint must be injected for validation. Missing xG or odds does not invalidate a forecast; the corresponding signal reports `available: false`.
