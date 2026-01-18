#!/bin/sh
set -e

MODEL="${CHUTES_MODEL:-moonshotai/Kimi-K2-Thinking}"

PROMPT="${*:-$(cat)}"
[ -z "${PROMPT}" ] && {
    log "No prompt" >&2
    exit 1
}
[ -z "${CHUTES_API_KEY:-}" ] && {
    log "CHUTES_API_KEY not set" >&2
    exit 1
}

log() { printf '%s\n' "${1}"; }

case "${1:-}" in
    -m | --model)
        MODEL="${2}"
        shift 2
        ;;
    -h | --help)
        cat <<EOF
Usage: chutes [-m MODEL] PROMPT
       echo "<prompt>" | chutes
Env: CHUTES_API_KEY (required), CHUTES_MODEL (optional)
EOF
        exit 0
        ;;
esac

curl -s https://llm.chutes.ai/v1/chat/completions \
    -H "Authorization: Bearer ${CHUTES_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg m "${MODEL}" --arg p "${PROMPT}" \
        '{model:$m,messages:[{role:"user",content:$p}]}')" \
    | jq -r '.choices[0].message.content // .error.message'
