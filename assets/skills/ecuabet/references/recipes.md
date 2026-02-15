# Recipes

Assumption: run commands from the skill directory (where `SKILL.md` lives).

Shortcut prompts are documented in `references/shortcuts.md`.

## Integrated one-shot
```bash
uv run scripts/main.py 13821298 --ecuabet 13821298 --require-ecuabet --no-raw --compact
```

## Integrated watch
```bash
uv run scripts/main.py 13821298 --ecuabet 13821298 --require-ecuabet --watch 20 --max-iterations 0 --no-raw --compact
```

## Write snapshot file
```bash
uv run scripts/main.py 13821298 --ecuabet 13821298 --require-ecuabet --no-raw --output snapshots/latest.json
```

## Strict low-variance shortlist
```bash
uv run scripts/main.py 13821298 \
  --ecuabet 13821298 \
  --require-ecuabet \
  --recommend-top 8 \
  --recommend-min-odds 1.01 \
  --recommend-max-odds 2.1 \
  --recommend-min-confidence 0.7 \
  --no-raw \
  --compact
```

## Wider upside shortlist
```bash
uv run scripts/main.py 13821298 \
  --ecuabet 13821298 \
  --require-ecuabet \
  --recommend-top 12 \
  --recommend-min-odds 1.2 \
  --recommend-max-odds 5.0 \
  --recommend-min-confidence 0.45 \
  --recommend-include-high-risk \
  --no-raw \
  --compact
```

## Tune recommendation bounds
```bash
uv run scripts/main.py 13821298 \
  --ecuabet 13821298 \
  --require-ecuabet \
  --recommend-top 12 \
  --recommend-min-odds 1.05 \
  --recommend-max-odds 4.5 \
  --recommend-min-confidence 0.6 \
  --stale-threshold-seconds 120 \
  --line-history-limit 240 \
  --no-raw \
  --compact
```

## Per-feed debugging
```bash
uv run scripts/ecuabet.py 13821298 --no-raw --compact
uv run scripts/sofascore.py "RB Leipzig Wolfsburg" --no-raw --compact
uv run scripts/espn.py "RB Leipzig Wolfsburg" --league ger.1 --no-raw --compact
uv run scripts/open_meteo.py "51.3397,12.3731" --hourly-limit 12 --compact
uv run scripts/understat.py --league Bundesliga --season 2025 --home-team "RB Leipzig" --away-team "Wolfsburg" --compact
```

## Run tests
```bash
cd scripts
uv run pytest tests -q
```
