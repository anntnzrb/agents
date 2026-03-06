---
name: exa-search
description: "Primary search via Exa's HTTP API. Use for deeper web research, full-page content retrieval, answer generation, and richer synthesis when lightweight search is not enough."
---

# Exa Search

Use Exa directly over HTTP with `curl`; no mcporter needed.

## Required shell helper

Define `exa-search` once per shell:

```bash
exa-search() {
  _exa_search_source_env() {
    local env_path="${1:-}" had_allexport=0
    [ -n "$env_path" ] || return 1
    [ -f "$env_path" ] || return 1
    case "$-" in *a*) had_allexport=1 ;; esac
    set -a
    . "$env_path"
    [ "$had_allexport" -eq 1 ] || set +a
  }

  _exa_search_load_env() {
    [ -n "${EXA_API_KEY:-${EXA_APIKEY:-}}" ] && return 0

    _exa_search_source_env "${EXA_SEARCH_ENV_FILE:-}" && return 0
    [ -n "${SKILLS_DIR:-}" ] && _exa_search_source_env "$SKILLS_DIR/exa-search/.env" && return 0

    local dir="$PWD"
    while [ "$dir" != "/" ]; do
      _exa_search_source_env "$dir/skills/exa-search/.env" && return 0
      dir="$(dirname "$dir")"
    done
  }

  _exa_search_load_env

  local base_url="${EXA_BASE_URL:-https://api.exa.ai}"
  local api_key="${EXA_API_KEY:-${EXA_APIKEY:-}}"
  local cmd="${1:-}"
  shift || true

  [ -n "$api_key" ] || {
    echo "EXA_API_KEY required (export it, source this skill's .env, or set EXA_SEARCH_ENV_FILE)" >&2
    return 2
  }

  case "$cmd" in
    post)
      local path="${1:?usage: exa-search post </path> '<json-body>'}"
      local body="${2:?usage: exa-search post </path> '<json-body>'}"
      command curl -fsSL "${base_url}${path}" \
        -H "Content-Type: application/json" \
        -H "x-api-key: ${api_key}" \
        -d "$body"
      ;;
    search)
      local query="${1:?usage: exa-search search <query> [numResults] [type]}"
      local num_results="${2:-5}"
      local search_type="${3:-}"
      command jq -nc \
        --arg query "$query" \
        --argjson numResults "$num_results" \
        --arg type "$search_type" '
          {query: $query, numResults: $numResults}
          + (if $type != "" then {type: $type} else {} end)
        ' | command curl -fsSL "${base_url}/search" \
          -H "Content-Type: application/json" \
          -H "x-api-key: ${api_key}" \
          -d @-
      ;;
    contents)
      local first_url="${1:?usage: exa-search contents <url> [url ...]}"
      shift
      local urls_json
      urls_json="$(printf '%s\n' "$first_url" "$@" | command jq -Rsc 'split("\n")[:-1]')"
      command jq -nc --argjson urls "$urls_json" '{urls: $urls}' | \
        command curl -fsSL "${base_url}/contents" \
          -H "Content-Type: application/json" \
          -H "x-api-key: ${api_key}" \
          -d @-
      ;;
    find-similar)
      local url="${1:?usage: exa-search find-similar <url>}"
      command jq -nc --arg url "$url" '{url: $url}' | \
        command curl -fsSL "${base_url}/findSimilar" \
          -H "Content-Type: application/json" \
          -H "x-api-key: ${api_key}" \
          -d @-
      ;;
    answer)
      local question="${1:?usage: exa-search answer <question>}"
      command jq -nc --arg query "$question" '{query: $query}' | \
        command curl -fsSL "${base_url}/answer" \
          -H "Content-Type: application/json" \
          -H "x-api-key: ${api_key}" \
          -d @-
      ;;
    research)
      local instructions="${1:?usage: exa-search research <instructions> [model]}"
      local model="${2:-exa-research}"
      command jq -nc \
        --arg instructions "$instructions" \
        --arg model "$model" \
        '{instructions: $instructions, model: $model}' | \
        command curl -fsSL "${base_url}/research/v1" \
          -H "Content-Type: application/json" \
          -H "x-api-key: ${api_key}" \
          -d @-
      ;;
    *)
      echo "usage: exa-search <post|search|contents|find-similar|answer|research> ..." >&2
      return 2
      ;;
  esac
}
```

Then use `exa-search <subcommand>` everywhere below.

## When to use

- Deeper web research with richer retrieval than lightweight search
- Fetching full-page contents from known URLs
- Grounded answer generation from web results
- Exa research mode for bigger synthesis tasks

## Quick start

```bash
exa-search search "best sqlite backup strategy" 5
exa-search contents https://sqlite.org/backup.html
exa-search answer "What is the capital of France?"
exa-search research "Summarize the current state of OpenTelemetry in the Java ecosystem" exa-research
```

## Credentials

- Keep `.env` beside this skill.
- Helper lookup order:
  - `EXA_SEARCH_ENV_FILE`
  - `$SKILLS_DIR/exa-search/.env`
  - nearest ancestor `skills/exa-search/.env`
- Tracked template: `.env.example`

## Notes

- Auth header: `x-api-key: $EXA_API_KEY`
- `search` is the best default entrypoint.
- Use `contents` when you already know the target URL(s).
- Use `post` for advanced payloads not covered by convenience wrappers.
- For code-specific public usage patterns, prefer `grep-app`, `gh`, and `context7` before forcing Exa.

## Raw examples

```bash
exa-search post /search '{"query":"rust async channels","numResults":5}'
exa-search post /contents '{"urls":["https://example.com/article"]}'
exa-search post /answer '{"query":"What is Bun?"}'
```

## Validation

```bash
bash scripts/test-exa-http.sh
```

## Query templates

See `assets/query-templates.json`.

## Reference

See `reference.md`.
