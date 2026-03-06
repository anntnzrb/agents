---
name: brave-search
description: "Fallback search via the Brave Search HTTP API. Use for quick lookups, recency checks, images/videos/local results, and lightweight web research when Exa isn't ideal."
---

# Brave Search

Use Brave Search directly over HTTP with `curl`; no mcporter needed.

## Required shell helper

Define `brave-search` once per shell:

```bash
brave-search() {
  _brave_search_source_env() {
    local env_path="${1:-}" had_allexport=0
    [ -n "$env_path" ] || return 1
    [ -f "$env_path" ] || return 1
    case "$-" in *a*) had_allexport=1 ;; esac
    set -a
    . "$env_path"
    [ "$had_allexport" -eq 1 ] || set +a
  }

  _brave_search_load_env() {
    [ -n "${BRAVE_API_KEY:-${BRAVE_SEARCH_API_KEY:-}}" ] && return 0

    _brave_search_source_env "${BRAVE_SEARCH_ENV_FILE:-}" && return 0
    [ -n "${SKILLS_DIR:-}" ] && _brave_search_source_env "$SKILLS_DIR/brave-search/.env" && return 0

    local dir="$PWD"
    while [ "$dir" != "/" ]; do
      _brave_search_source_env "$dir/skills/brave-search/.env" && return 0
      dir="$(dirname "$dir")"
    done
  }

  _brave_search_load_env

  local base_url="${BRAVE_SEARCH_BASE_URL:-https://api.search.brave.com/res/v1}"
  local api_key="${BRAVE_API_KEY:-${BRAVE_SEARCH_API_KEY:-}}"
  local cmd="${1:-}"
  shift || true

  [ -n "$api_key" ] || {
    echo "BRAVE_API_KEY required (export it, source this skill's .env, or set BRAVE_SEARCH_ENV_FILE)" >&2
    return 2
  }

  local pair
  local -a extra=()
  for pair in "$@"; do
    extra+=(--data-urlencode "$pair")
  done

  case "$cmd" in
    web)
      local query="${1:?usage: brave-search web <query> [key=value ...]}"
      shift
      extra=()
      for pair in "$@"; do extra+=(--data-urlencode "$pair"); done
      command curl -fsSLG -H "X-Subscription-Token: ${api_key}" \
        "${base_url}/web/search" \
        --data-urlencode "q=${query}" \
        "${extra[@]}"
      ;;
    news)
      local query="${1:?usage: brave-search news <query> [key=value ...]}"
      shift
      extra=()
      for pair in "$@"; do extra+=(--data-urlencode "$pair"); done
      command curl -fsSLG -H "X-Subscription-Token: ${api_key}" \
        "${base_url}/news/search" \
        --data-urlencode "q=${query}" \
        "${extra[@]}"
      ;;
    local)
      local query="${1:?usage: brave-search local <query> [key=value ...]}"
      shift
      extra=()
      for pair in "$@"; do extra+=(--data-urlencode "$pair"); done
      command curl -fsSLG -H "X-Subscription-Token: ${api_key}" \
        "${base_url}/local/search" \
        --data-urlencode "q=${query}" \
        "${extra[@]}"
      ;;
    image)
      local query="${1:?usage: brave-search image <query> [key=value ...]}"
      shift
      extra=()
      for pair in "$@"; do extra+=(--data-urlencode "$pair"); done
      command curl -fsSLG -H "X-Subscription-Token: ${api_key}" \
        "${base_url}/images/search" \
        --data-urlencode "q=${query}" \
        "${extra[@]}"
      ;;
    video)
      local query="${1:?usage: brave-search video <query> [key=value ...]}"
      shift
      extra=()
      for pair in "$@"; do extra+=(--data-urlencode "$pair"); done
      command curl -fsSLG -H "X-Subscription-Token: ${api_key}" \
        "${base_url}/videos/search" \
        --data-urlencode "q=${query}" \
        "${extra[@]}"
      ;;
    summarizer-key)
      local query="${1:?usage: brave-search summarizer-key <query> [key=value ...]}"
      shift
      extra=()
      for pair in "$@"; do extra+=(--data-urlencode "$pair"); done
      command curl -fsSLG -H "X-Subscription-Token: ${api_key}" \
        "${base_url}/web/search" \
        --data-urlencode "q=${query}" \
        --data-urlencode "summary=1" \
        "${extra[@]}" | command jq -r '.summarizer.key'
      ;;
    summarize)
      local key="${1:?usage: brave-search summarize <summary-key> [key=value ...]}"
      shift
      extra=()
      for pair in "$@"; do extra+=(--data-urlencode "$pair"); done
      command curl -fsSLG -H "X-Subscription-Token: ${api_key}" \
        "${base_url}/summarizer/search" \
        --data-urlencode "key=${key}" \
        "${extra[@]}"
      ;;
    raw)
      local path="${1:?usage: brave-search raw </path> [key=value ...]}"
      shift
      extra=()
      for pair in "$@"; do extra+=(--data-urlencode "$pair"); done
      command curl -fsSLG -H "X-Subscription-Token: ${api_key}" \
        "${base_url}${path}" \
        "${extra[@]}"
      ;;
    *)
      echo "usage: brave-search <web|news|local|image|video|summarizer-key|summarize|raw> ..." >&2
      return 2
      ;;
  esac
}
```

Then use `brave-search <subcommand>` everywhere below.

## When to use

- Fast scoping / quick lookups
- Recency-sensitive news checks
- Image / video / local search
- Lightweight web research before escalating to Exa

## Quick start

```bash
brave-search web "rust async tutorial" count=5 summary=1
brave-search news "typescript 5.9" count=5 freshness=pd
brave-search local "coffee near times square" count=5
brave-search image "saturn v launch" count=10
brave-search video "bun runtime benchmark" count=10
```

## Summaries

Brave's older summarizer flow is still reachable directly:

```bash
key="$(brave-search summarizer-key "what is the second highest mountain" count=5)"
brave-search summarize "$key" inline_references=true entity_info=1
```

Use `brave-search raw /summarizer/title key="$key"` or other `/summarizer/*` paths for specialized endpoints.

## Credentials

- Keep `.env` beside this skill.
- Helper lookup order:
  - `BRAVE_SEARCH_ENV_FILE`
  - `$SKILLS_DIR/brave-search/.env`
  - nearest ancestor `skills/brave-search/.env`
- Tracked template: `.env.example`

## Notes

- Auth header: `X-Subscription-Token: $BRAVE_API_KEY`
- Pass optional query params as `key=value` pairs after the main argument.
- Useful params: `count=`, `freshness=`, `country=`, `search_lang=`, `ui_lang=`, `safesearch=`, `summary=1`
- `summary=1` on web search returns a summarizer key in the search response; fetch the full summary separately.
- Prefer Exa for deeper multi-source synthesis.

## Validation

```bash
bash scripts/test-brave-http.sh
```

## Query templates

See `assets/query-templates.json`.

## Reference

See `reference.md`.
