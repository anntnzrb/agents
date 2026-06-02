# amz-live

Tiny read-only Amazon search CLI.

Fetch live search result cards or parse saved Amazon search HTML, then filter locally.

## Entry point

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

## Quickstart

```bash
uv run --script <skill-dir>/scripts/cli.py --help
uv run --with pytest --with hypothesis --with httpx --with selectolax pytest
uv run --with pyright --with httpx --with selectolax pyright
```

## CLI

```bash
uv run --script <skill-dir>/scripts/cli.py "wireless mouse"
```

## Machine-readable outputs

`--json` stays unchanged: raw array of normalized results.

### `--llm-json`

Rich single-object envelope for agents and LLM flows.

```bash
uv run --script <skill-dir>/scripts/cli.py "usb c to usb c braided cable" \
  --html tests/fixtures/search_results_fragment.html \
  --llm-json \
  --min-rating 4.5 \
  --max-price 9 \
  --limit 2
```

Add detail-page enrichment for shortlisted candidates:

```bash
uv run --script <skill-dir>/scripts/cli.py "usb c to usb c braided cable" \
  --llm-json \
  --max-price 10 \
  --min-rating 4.5 \
  --limit 5 \
  --details \
  --detail-limit 2
```

Top-level shape:

```json
{
  "type": "amz-live.search_results",
  "version": "1",
  "ok": true,
  "source": {
    "mode": "html",
    "html_path": "tests/fixtures/search_results_fragment.html"
  },
  "query": {
    "keywords": "usb c to usb c braided cable",
    "page": 1,
    "pages": 1,
    "amazon_sort": null
  },
  "filters": {
    "min_rating": 4.5,
    "max_price": 9.0,
    "badge": null,
    "title_contains": null,
    "include": [],
    "exclude": [],
    "limit": 2
  },
  "summary": { "raw_result_count": 3, "returned_result_count": 2 },
  "results": []
}
```

### `--schema`

Machine-readable schema/capabilities document for agents.

```bash
uv run --script <skill-dir>/scripts/cli.py --schema
```

### `--mode rpc`

Minimal **pi-inspired** JSONL RPC. Not full pi RPC.

- one JSON object per stdin line
- one JSON response per stdout line
- request field: `type` (`command` still accepted for compatibility)
- commands: `ping`, `get_schema`, `search`
- `search` also accepts `details` + `detailLimit`
- response envelope: `{id?, type:"response", command, success, data?, error?}`

Example:

```bash
printf '%s\n' \
  '{"id":"1","type":"ping"}' \
  '{"id":"2","type":"get_schema"}' \
  '{"id":"3","type":"search","query":"usb c to usb c braided cable","htmlPath":"tests/fixtures/search_results_fragment.html","minRating":4.5,"maxPrice":9,"limit":2}' \
  | uv run --script <skill-dir>/scripts/cli.py --mode rpc
```

## Useful filters

- `--min-rating 4.5`
- `--max-price 10`
- `--badge "Best Seller"`
- `--title-contains "amazon basics"`
- repeat `--include ...`
- repeat `--exclude ...`
- `--limit 5`
- `--page 2 --pages 3`
