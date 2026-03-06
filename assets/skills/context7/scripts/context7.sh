#!/usr/bin/env bash
# shellcheck shell=bash
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "source this file from bash: . ${BASH_SOURCE[0]}" >&2
  exit 2
fi

context7() {
  _context7_source_env() {
    local env_path="${1:-}" had_allexport=0
    [ -n "$env_path" ] || return 1
    [ -f "$env_path" ] || return 1
    case "$-" in *a*) had_allexport=1 ;; esac
    set -a
    . "$env_path"
    [ "$had_allexport" -eq 1 ] || set +a
  }

  _context7_load_env() {
    [ -n "${CONTEXT7_API_KEY:-}" ] && return 0

    _context7_source_env "${CONTEXT7_ENV_FILE:-}" && return 0
    [ -n "${SKILLS_DIR:-}" ] && _context7_source_env "$SKILLS_DIR/context7/.env" && return 0

    local dir="$PWD"
    while [ "$dir" != "/" ]; do
      _context7_source_env "$dir/skills/context7/.env" && return 0
      dir="$(dirname "$dir")"
    done
  }

  _context7_load_env

  local base_url="${CONTEXT7_BASE_URL:-https://context7.com/api/v2}"
  local api_key="${CONTEXT7_API_KEY:-}"
  local cmd="${1:-}"
  shift || true

  local -a headers=()
  [ -n "$api_key" ] && headers+=( -H "CONTEXT7_API_KEY: ${api_key}" )

  case "$cmd" in
    search)
      local library_name="${1:?usage: context7 search <library-name> <query>}"
      shift
      local query="${*:?usage: context7 search <library-name> <query>}"
      command curl -fsSLG "${headers[@]}" "${base_url}/libs/search" \
        --data-urlencode "libraryName=${library_name}" \
        --data-urlencode "query=${query}"
      ;;
    id)
      local library_name="${1:?usage: context7 id <library-name> <query>}"
      shift
      local query="${*:?usage: context7 id <library-name> <query>}"
      context7 search "$library_name" "$query" | command jq -r '.results[0].id'
      ;;
    docs|json)
      local library_id="${1:?usage: context7 ${cmd} <library-id> <query>}"
      shift
      local query="${*:?usage: context7 ${cmd} <library-id> <query>}"
      local type="txt"
      [ "$cmd" = "json" ] && type="json"
      command curl -fsSLG "${headers[@]}" "${base_url}/context" \
        --data-urlencode "libraryId=${library_id}" \
        --data-urlencode "query=${query}" \
        --data-urlencode "type=${type}"
      ;;
    *)
      echo "usage: context7 <search|id|docs|json> ..." >&2
      return 2
      ;;
  esac
}
