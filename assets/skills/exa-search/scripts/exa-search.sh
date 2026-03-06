#!/usr/bin/env bash
# shellcheck shell=bash
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "source this file from bash: . ${BASH_SOURCE[0]}" >&2
  exit 2
fi

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
