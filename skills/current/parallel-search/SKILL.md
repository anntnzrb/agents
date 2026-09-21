---
name: parallel-search
description: "Use when web search, page extraction, deep research, or entity discovery is needed via the Parallel API."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb
---

# Parallel Search

Access web search, content extraction, multi-tier deep research, and entity discovery via Parallel.

## Entry point

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

`<skill-dir>` = this skill directory. Do not use shell sourcing, executable bits, or shebang dispatch.

Credential check: The CLI auto-loads `.env` from:
1. `PARALLEL_ENV_FILE`
2. skill-local `.env`
3. `$SKILLS_DIR/parallel-search/.env`
4. nearest ancestor `.env` or `skills/parallel-search/.env`

Ensure `PARALLEL_API_KEY` is set in the environment or an ancestor `.env` file.

## Quick start

Commands return compact, agent-shaped JSON by default. Pass `raw=1` to stream raw upstream JSON.

```text
# Web search with fast/turbo latency or deep retrieval
uv run --script <skill-dir>/scripts/cli.py search "FastAPI response models" mode=turbo max_results=5

# Web search with domain filters and publication date bounds
uv run --script <skill-dir>/scripts/cli.py search "SEC 10-K filing Apple" include_domains=sec.gov after_date=2026-01-01

# Extract clean markdown from URLs
uv run --script <skill-dir>/scripts/cli.py extract "https://docs.parallel.ai" full_content=1

# Run deep research (asynchronous task run)
uv run --script <skill-dir>/scripts/cli.py task-create "Analyze competitive landscape for AI code editors" processor=lite-fast

# Check task status and fetch completed result
uv run --script <skill-dir>/scripts/cli.py task-status trun_xxx
uv run --script <skill-dir>/scripts/cli.py task-result trun_xxx

# Fast entity search (synchronous)
uv run --script <skill-dir>/scripts/cli.py findall-search "AI developer tools Series A" entity_type=companies limit=10

# Recall saved research from Memory
uv run --script <skill-dir>/scripts/cli.py memory-retrieve "AI code editors"
```

## Available commands

| Command | Arguments | Description |
| --- | --- | --- |
| `search` | `<query> [mode=turbo\|fast\|basic\|advanced] [max_results=N] [include_domains=d1,d2] [after_date=YYYY-MM-DD] [objective=text]` | Web search with compact projection |
| `extract` | `<url1,url2...> [objective=text] [full_content=1]` | Extract markdown and excerpts from URLs |
| `task-create` | `<input> [processor=lite-fast\|core-fast\|pro\|ultra] [previous_interaction_id=id]` | Start asynchronous deep research task |
| `task-status` | `<run_id>` | Check task execution status |
| `task-result` | `<run_id>` | Retrieve final markdown/JSON output for a completed task |
| `findall-search` | `<query> [entity_type=companies\|people] [limit=N]` | Fast ranked entity search |
| `memory-retrieve` | `[query] [kind=task\|monitor\|findall] [limit=N]` | Retrieve past research from Parallel Memory |
| `raw` | `[GET\|POST] </path> [key=value ...]` | Raw API passthrough |

## Failure handling

- `PARALLEL_API_KEY required`: local env discovery failed (rc=2).
- HTTP errors emit one-line compact JSON on stderr with `error.provider`, `error.status`, `error.message`, `error.body_bytes`, and `error.body_preview`. HTTP errors: rc=22. Network/parse errors: rc=1. Usage errors: rc=2.
