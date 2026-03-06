#!/usr/bin/env bash
# shellcheck shell=bash
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "source this file from bash: . ${BASH_SOURCE[0]}" >&2
  exit 2
fi

grep-app() {
  local base_url="${GREP_APP_BASE_URL:-https://grep.app/api/search}"
  local cmd="${1:-search}"
  shift || true

  local pair
  local -a extra=()

  case "$cmd" in
    search)
      local query="${1:?usage: grep-app search <pattern> [key=value ...]}"
      shift
      for pair in "$@"; do extra+=(--data-urlencode "$pair"); done
      command curl -fsSLG "$base_url" \
        --data-urlencode "q=${query}" \
        "${extra[@]}"
      ;;
    regex)
      local pattern="${1:?usage: grep-app regex <pattern> [key=value ...]}"
      shift
      for pair in "$@"; do extra+=(--data-urlencode "$pair"); done
      command curl -fsSLG "$base_url" \
        --data-urlencode "q=${pattern}" \
        --data-urlencode "regexp=true" \
        "${extra[@]}"
      ;;
    *)
      echo "usage: grep-app <search|regex> ..." >&2
      return 2
      ;;
  esac
}
