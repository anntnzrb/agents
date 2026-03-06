---
name: context7
description: "Retrieve up-to-date library/API docs and code examples via the Context7 HTTP API. Use for library-specific questions, setup/config steps, code generation, and verifying current APIs."
---

# Context7

Use Context7 for version-specific docs and code examples. Prefer direct HTTP via `curl`

## Required shell helper

Define `context7` once per shell:

```bash
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
```

Then use `context7 <subcommand>` everywhere below.

## Workflow

1. If you do not know the library ID, search first.
2. Inspect the top matches by `title`, `description`, and `totalSnippets`.
3. Fetch docs with `context7 docs <library-id> <query>`.
4. Use `context7 json ...` only when structured parsing is needed.

## Quick start

```bash
# Find likely matches
context7 search react "hooks useState" \
  | jq '.results[:5] | map({id, title, description, totalSnippets})'

# Grab the top library ID directly
context7 id react "hooks useState"

# Fetch readable docs
context7 docs /vercel/next.js "app router server actions"

# Fetch structured JSON when you need metadata/snippets
context7 json /fastapi/fastapi "dependency injection"
```

## Credentials

- API key is optional but recommended for higher rate limits.
- Keep `.env` beside this skill.
- Helper lookup order:
  - `CONTEXT7_ENV_FILE`
  - `$SKILLS_DIR/context7/.env`
  - nearest ancestor `skills/context7/.env`
- Tracked template: `.env.example`
- Header used when present: `CONTEXT7_API_KEY: <key>`

## Notes

- If you already know the library ID (`/org/project`, `/org/project/version`, or `/websites/...`), skip search.
- Prefer exact title/source matches; use higher `totalSnippets` as a tiebreaker, not the only signal.
- `docs` uses `type=txt` because it is easier to read in agent output.
- Public endpoint works without an API key for basic usage; expect lower rate limits.
- Override `CONTEXT7_BASE_URL` if you need to point at a different host.
- The shell helper uses `--data-urlencode` to avoid broken queries from spaces or special characters.
- `id` uses `jq`; if `jq` is unavailable, inspect `search` output manually.

## Common examples

```bash
# React hooks
context7 id react "hooks useState"
context7 docs /websites/react_dev "useState"

# Next.js routing
context7 id nextjs "routing app router"
context7 docs /vercel/next.js "app router"

# FastAPI dependencies
context7 id fastapi "dependencies dependency injection"
context7 docs /fastapi/fastapi "dependency injection"
```

## Validation

```bash
bash scripts/test-context7-http.sh
```

## Query templates

See `assets/query-templates.json`.
