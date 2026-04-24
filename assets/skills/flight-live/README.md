# flight-live

Read-only agent-first flight search CLI.

Provider: Kiwi web search scrape via `agent-browser` (nix wrapper) + public `api.skypicker.com/locations` resolver.

## Entry point

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

## Quickstart

```bash
uv run --script <skill-dir>/scripts/cli.py --help
uv run --with pytest pytest
```

## Credentials

No API keys. No env vars required.

`.env` is optional and can stay empty.

## Wrapper

Run from the skill root:

```bash
uv run --script scripts/cli.py --schema
```

Wrapper behavior:
- resolves skill root
- auto-loads `./.env` from skill directory when present
- executes: `uv run --script "$SKILL_DIR/scripts/cli.py" "$@"`

## CLI

Minimal search:

```bash
uv run --script <skill-dir>/scripts/cli.py \
  --origin NYC \
  --destination LON \
  --depart-start 2026-07-01 \
  --depart-end 2026-07-20 \
  --llm-json
```

Useful flags:
- `--trip-type oneway|roundtrip`
- `--stay-min` / `--stay-max`
- `--nonstop`
- `--max-budget`
- `--planner-limit`
- `--json` / `--llm-json`
- `--schema`
- `--mode rpc`

## Output modes

- Human text (default)
- `--json` → raw `results[]`
- `--llm-json` → full envelope (`warnings`, `summary`, `insights`, `decision`, ranked results)

Prefer `--llm-json` for agents.

## Notes

- Oneway window search is first-class.
- Roundtrip uses scraped date-pair buttons from Kiwi web results.
- Provider hard-fails with actionable errors when `nix` / `agent-browser` is unavailable.

## RPC

JSONL, one request/response per line.
Commands:
- `ping`
- `get_schema`
- `search`

Example:

```bash
printf '%s\n' \
  '{"id":"1","type":"ping"}' \
  '{"id":"2","type":"search","origin":"NYC","destination":"MAD","departStart":"2026-06-01","departEnd":"2026-06-30"}' \
  | uv run --script <skill-dir>/scripts/cli.py --mode rpc
```

## References

- `references/cheatsheet.md`
- `references/workflows.md`
- `references/rpc.md`
- `references/troubleshooting.md`
