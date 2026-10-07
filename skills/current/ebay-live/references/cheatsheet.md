# Search examples

Read this when choosing a search command or local filters.
Resolve `<skill-dir>` to the skill directory.

## Compare delivered prices

```text
uv run --script <skill-dir>/scripts/cli.py "nikon z6 ii" --condition used --buy-it-now --sort price-lowest --include body --exclude battery --exclude strap --llm-json --scoring --limit 5
```

## Require seller and shipping evidence

```text
uv run --script <skill-dir>/scripts/cli.py "steam deck oled" --buy-it-now --min-seller-feedback 99 --free-shipping --max-price 500 --llm-json --limit 5
```

## Inspect an auction shortlist

```text
uv run --script <skill-dir>/scripts/cli.py "seiko 6139" --auction --sort ending-soonest --pages 2 --per-page 60 --llm-json --limit 5 --details --detail-limit 1
```

## Inspect contracts

```text
uv run --script <skill-dir>/scripts/cli.py --help
uv run --script <skill-dir>/scripts/cli.py --schema
```
