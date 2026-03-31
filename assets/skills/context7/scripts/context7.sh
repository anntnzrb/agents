#!/usr/bin/env bash
# shellcheck shell=bash
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "source this file from bash: . ${BASH_SOURCE[0]}" >&2
  exit 2
fi

context7() {
  _context7_skill_dir() {
    local script_path="${BASH_SOURCE[0]:-}"
    [ -n "$script_path" ] || return 1
    cd -- "$(dirname -- "$script_path")/.." 2>/dev/null && pwd
  }

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
    local skill_dir=""
    skill_dir="$(_context7_skill_dir)" || skill_dir=""
    [ -n "$skill_dir" ] && _context7_source_env "$skill_dir/.env" && return 0
    [ -n "${SKILLS_DIR:-}" ] && _context7_source_env "$SKILLS_DIR/context7/.env" && return 0

    local dir="$PWD"
    while [ "$dir" != "/" ]; do
      _context7_source_env "$dir/skills/context7/.env" && return 0
      dir="$(dirname "$dir")"
    done
  }

  _context7_error_message() {
    local http_status="${1:-}" body="${2:-}" message=""

    if command -v jq >/dev/null 2>&1; then
      message="$(printf '%s' "$body" | command jq -r 'if type == "object" then (.message // .error // empty) else empty end' 2>/dev/null || true)"
    fi

    [ -n "$message" ] || message="$body"

    case "$http_status" in
      401) [ -n "$message" ] || message="Invalid API key. Keys should start with ctx7sk." ;;
      404) [ -n "$message" ] || message="Library not found. Verify the library ID." ;;
      422) [ -n "$message" ] || message="Library unavailable for context generation. Try a different library." ;;
      429) [ -n "$message" ] || message="Rate limited. Retry later or add CONTEXT7_API_KEY for higher limits." ;;
      503) [ -n "$message" ] || message="Context7 service unavailable. Retry later." ;;
    esac

    [ -n "$message" ] || message="Context7 request failed with HTTP ${http_status}"
    printf '%s\n' "$message"
  }

  _context7_request() {
    local max_time="${1:?missing max_time}" url="${2:?missing url}"
    shift 2

    local body_file http_status curl_status=0 body=""
    body_file="$(mktemp "${TMPDIR:-/tmp}/context7.XXXXXX")" || return 1

    http_status="$(
      command curl -sSLG "${headers[@]}" \
        --connect-timeout 10 \
        --max-time "$max_time" \
        -o "$body_file" \
        -w '%{http_code}' \
        "$url" \
        "$@"
    )" || curl_status=$?

    if [ "$curl_status" -ne 0 ]; then
      body="$(command cat "$body_file")"
      rm -f "$body_file"
      case "$curl_status" in
        28) echo "Context7 request timed out after ${max_time}s" >&2 ;;
        *) echo "Context7 network error (curl ${curl_status})" >&2 ;;
      esac
      [ -n "$body" ] && printf '%s\n' "$body" >&2
      return "$curl_status"
    fi

    if [ "$http_status" -ge 200 ] && [ "$http_status" -lt 300 ]; then
      command cat "$body_file"
      rm -f "$body_file"
      return 0
    fi

    body="$(command cat "$body_file")"
    rm -f "$body_file"
    _context7_error_message "$http_status" "$body" >&2
    return 22
  }

  _context7_load_env

  local base_url="${CONTEXT7_BASE_URL:-https://context7.com/api/v2}"
  local api_key="${CONTEXT7_API_KEY:-}"
  local cmd="${1:-}"
  shift || true

  local -a headers=()
  [ -n "$api_key" ] && headers+=( -H "Authorization: Bearer ${api_key}" )

  case "$cmd" in
    search)
      local library_name="${1:?usage: context7 search <library-name> <query>}"
      shift
      local query="${*:?usage: context7 search <library-name> <query>}"
      _context7_request 30 "${base_url}/libs/search" \
        --data-urlencode "libraryName=${library_name}" \
        --data-urlencode "query=${query}"
      ;;
    id)
      command -v jq >/dev/null 2>&1 || {
        echo "context7 id requires jq" >&2
        return 127
      }
      local library_name="${1:?usage: context7 id <library-name> <query>}"
      shift
      local query="${*:?usage: context7 id <library-name> <query>}"
      local search_json
      local library_id
      search_json="$(
        _context7_request 30 "${base_url}/libs/search" \
          --data-urlencode "libraryName=${library_name}" \
          --data-urlencode "query=${query}"
      )" || return $?
      library_id="$(printf '%s' "$search_json" | command jq -er '.results[0].id')" || {
        echo "No matching library ID found" >&2
        return 1
      }
      printf '%s\n' "$library_id"
      ;;
    docs|json)
      local library_id="${1:?usage: context7 ${cmd} <library-id> <query>}"
      shift
      local query="${*:?usage: context7 ${cmd} <library-id> <query>}"
      local type="txt"
      [ "$cmd" = "json" ] && type="json"
      case "$library_id" in
        /*) ;;
        *) library_id="/${library_id}" ;;
      esac
      _context7_request 60 "${base_url}/context" \
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
