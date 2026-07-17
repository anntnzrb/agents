---
name: amz-live
description: Search and compare Amazon products, prices, and recommendations with read-only catalog data.
license: GPL-3.0-or-later
compatibility: Requires `uv`. Uses bundled skill-local `scripts/cli.py`. Network access required for live mode.
metadata:
  author: anntnzrb
allowed-tools: ""
---

# amz-live

Read-only Amazon catalog search through the bundled skill-local CLI. Use it for Amazon product discovery, price comparison, shortlist generation, cheap-but-decent recommendations, connector/type-specific cable hunts, structured output, delivery-location reruns, and process/RPC integration.

## Entry points

- From the skill root: `uv run --script <skill-dir>/scripts/cli.py ...`
- If `SKILLS_DIR` is set: `uv run --script "$SKILLS_DIR/amz-live/scripts/cli.py" ...`
- Otherwise resolve the skill directory, then run `uv run --script <skill-dir>/scripts/cli.py ...`
- For process integration: `uv run --script <skill-dir>/scripts/cli.py --mode rpc`

## Core rules

- Prefer `--llm-json` unless the user explicitly wants human text.
- Start cheap; avoid `--details` on a broad first pass unless the shortlist is already tiny.
- Add `--zip` early when delivery locality matters.
- Add `--details --detail-limit 2` only for finalists.
- Add `--scoring` when the user wants “best”, “good enough”, “not trash”, “value”, or ranking help.
- Answer from envelope fields, not vibes.
- Do not dump raw JSON unless asked.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Maintainer contract | `README.md` | Before changing CLI, parser, tests, or machine-readable behavior |
| Shortest correct command | `references/cheatsheet.md` | For discovery, shortlist, details, scoring, zip-aware search, fixture parsing, or trusted fields |
| Multi-step routing | `references/workflows.md` | For recommendations, accessory filtering, finalist validation, locality reruns, enrichment, or answer shape |
| Operational contract | `references/operational-contract.md` | For output modes, exact controls, locality, enrichment, scoring, accessory heuristics, failures, or evidence fields |
| Process integration | `references/rpc.md` | For `--mode rpc`, request/response schema, `zipCode`, or `query.zip_code` |
| Recovery | `references/troubleshooting.md` | For blocked fetches, sparse details, locale drift, parser drift, conflicting fields, or fixture debugging |

## Workflow

1. Identify the task shape:
   - discovery
   - shortlist/ranking
   - detail validation
   - programmatic integration
   - blocked fetch debugging
   - location-sensitive reruns
2. Run an `--llm-json` discovery pass with `--limit 10`; add `--zip` if locality matters.
3. Tighten with `--max-price`, `--min-rating`, `--include`, `--exclude`, `--title-contains`, `--badge`, `--zip`, `--page`, `--pages`, or `--amazon-sort`.
4. For finalists, rerun with `--details --detail-limit 2 --scoring --limit 5`.
5. Inspect top 3-5 results, then summarize price, rating, review count, brand, merchant trust when available, delivery-locality caveat when using `--zip`, and mismatch/risk.

## Reference routing

Use the Required follow-up reads table near the top of this file; do not preload references for routine searches.
