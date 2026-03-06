---
name: reddit
description: "Read Reddit directly via Reddit's public JSON endpoints. Use for subreddit browsing, search, post/comment retrieval, user activity analysis, and common Reddit glossary lookups."
---

# Reddit

Use Reddit directly over HTTP via `reddit.com/*.json`; no mcporter needed.

## Required shell helper

Define `reddit` once per shell:

```bash
reddit() {
  local base_url="${REDDIT_BASE_URL:-https://www.reddit.com}"
  local user_agent="${REDDIT_USER_AGENT:-agents-reddit/1.0}"
  local cmd="${1:-}"
  shift || true

  _reddit_get() {
    command curl -fsSLG -A "$user_agent" "$@"
  }

  _reddit_alias_param() {
    case "$1" in
      time=*) printf 't=%s' "${1#time=}" ;;
      comment_limit=*) printf 'limit=%s' "${1#comment_limit=}" ;;
      comment_sort=*) printf 'sort=%s' "${1#comment_sort=}" ;;
      comment_depth=*) printf 'depth=%s' "${1#comment_depth=}" ;;
      *) printf '%s' "$1" ;;
    esac
  }

  _reddit_explain() {
    local term="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
    case "$term" in
      karma) command jq -nc --arg term "$term" '{term:$term, definition:"Score derived from upvotes on posts and comments. Usually split into post karma and comment karma."}' ;;
      "cake day") command jq -nc --arg term "$term" '{term:$term, definition:"The anniversary of a Reddit account creation date, shown with a cake icon."}' ;;
      ama) command jq -nc --arg term "$term" '{term:$term, definition:"Ask Me Anything. A Q&A thread where a person invites questions from the community."}' ;;
      op) command jq -nc --arg term "$term" '{term:$term, definition:"Original Poster: the author of the post or sometimes the parent comment under discussion."}' ;;
      tldr) command jq -nc --arg term "$term" '{term:$term, definition:"Too Long; Did Not Read. A short summary of a longer post or comment."}' ;;
      eli5) command jq -nc --arg term "$term" '{term:$term, definition:"Explain Like I Am Five. A request or community norm for simple, plain-language explanations."}' ;;
      throwaway) command jq -nc --arg term "$term" '{term:$term, definition:"A temporary account, often created for privacy-sensitive posting."}' ;;
      flair) command jq -nc --arg term "$term" '{term:$term, definition:"A label or badge attached to a post or username inside a subreddit."}' ;;
      nsfw) command jq -nc --arg term "$term" '{term:$term, definition:"Not Safe For Work. Content that may be explicit or inappropriate in some settings."}' ;;
      crosspost) command jq -nc --arg term "$term" '{term:$term, definition:"A repost of the same submission into another subreddit using the native crosspost flow."}' ;;
      shadowban) command jq -nc --arg term "$term" '{term:$term, definition:"A state where activity is hidden or heavily limited without an obvious visible ban message."}' ;;
      modmail) command jq -nc --arg term "$term" '{term:$term, definition:"Shared moderator inbox for communication between subreddit mods and users."}' ;;
      *) command jq -nc --arg term "$term" '{term:$term, definition:"Unknown term in the built-in glossary. Search Reddit or the web for current community usage."}' ;;
    esac
  }

  case "$cmd" in
    browse)
      local subreddit="${1:?usage: reddit browse <subreddit> [sort] [key=value ...]}"
      local sort="${2:-hot}"
      shift 2 || true
      local limit="10"
      local pair aliased
      local -a extra=()
      for pair in "$@"; do
        aliased="$(_reddit_alias_param "$pair")"
        case "$aliased" in
          limit=*) limit="${aliased#limit=}" ;;
          *) extra+=(--data-urlencode "$aliased") ;;
        esac
      done
      _reddit_get "${base_url}/r/${subreddit}/${sort}.json" --data-urlencode "limit=${limit}" "${extra[@]}"
      ;;
    search)
      local query="${1:?usage: reddit search <query> [key=value ...]}"
      shift || true
      local sort="relevance"
      local t="all"
      local limit="10"
      local author=""
      local flair=""
      local value pair full_query
      local -a subreddits=() extra=()
      for pair in "$@"; do
        case "$pair" in
          sort=*) sort="${pair#sort=}" ;;
          t=*) t="${pair#t=}" ;;
          time=*) t="${pair#time=}" ;;
          limit=*) limit="${pair#limit=}" ;;
          author=*) author="${pair#author=}" ;;
          flair=*) flair="${pair#flair=}" ;;
          subreddits=*)
            while IFS= read -r value; do
              [ -n "$value" ] && subreddits+=("$value")
            done <<EOF
$(printf '%s' "${pair#subreddits=}" | command jq -r '.[]' 2>/dev/null || true)
EOF
            ;;
          *) extra+=(--data-urlencode "$pair") ;;
        esac
      done
      full_query="$query"
      for value in "${subreddits[@]}"; do full_query="${full_query} subreddit:${value}"; done
      [ -n "$author" ] && full_query="${full_query} author:${author}"
      [ -n "$flair" ] && full_query="${full_query} flair:\"${flair}\""
      _reddit_get "${base_url}/search.json" \
        --data-urlencode "q=${full_query}" \
        --data-urlencode "sort=${sort}" \
        --data-urlencode "t=${t}" \
        --data-urlencode "limit=${limit}" \
        "${extra[@]}"
      ;;
    post)
      local subreddit="${1:?usage: reddit post <subreddit> <post_id> [key=value ...]}"
      local post_id="${2:?usage: reddit post <subreddit> <post_id> [key=value ...]}"
      shift 2 || true
      local limit="20"
      local pair aliased
      local -a extra=()
      for pair in "$@"; do
        aliased="$(_reddit_alias_param "$pair")"
        case "$aliased" in
          limit=*) limit="${aliased#limit=}" ;;
          *) extra+=(--data-urlencode "$aliased") ;;
        esac
      done
      _reddit_get "${base_url}/r/${subreddit}/comments/${post_id}/.json" --data-urlencode "limit=${limit}" "${extra[@]}"
      ;;
    post-url)
      local url="${1:?usage: reddit post-url <url> [key=value ...]}"
      shift || true
      local clean_url="${url%%\?*}"
      clean_url="${clean_url%.json}.json"
      local limit="20"
      local pair aliased
      local -a extra=()
      for pair in "$@"; do
        aliased="$(_reddit_alias_param "$pair")"
        case "$aliased" in
          limit=*) limit="${aliased#limit=}" ;;
          *) extra+=(--data-urlencode "$aliased") ;;
        esac
      done
      _reddit_get "$clean_url" --data-urlencode "limit=${limit}" "${extra[@]}"
      ;;
    user)
      local username="${1:?usage: reddit user <username>}"
      command curl -fsSL -A "$user_agent" "${base_url}/user/${username}/about.json"
      ;;
    user-posts)
      local username="${1:?usage: reddit user-posts <username> [key=value ...]}"
      shift || true
      local limit="10"
      local pair aliased
      local -a extra=()
      for pair in "$@"; do
        aliased="$(_reddit_alias_param "$pair")"
        case "$aliased" in
          limit=*) limit="${aliased#limit=}" ;;
          *) extra+=(--data-urlencode "$aliased") ;;
        esac
      done
      _reddit_get "${base_url}/user/${username}/submitted.json" --data-urlencode "limit=${limit}" "${extra[@]}"
      ;;
    user-comments)
      local username="${1:?usage: reddit user-comments <username> [key=value ...]}"
      shift || true
      local limit="10"
      local pair aliased
      local -a extra=()
      for pair in "$@"; do
        aliased="$(_reddit_alias_param "$pair")"
        case "$aliased" in
          limit=*) limit="${aliased#limit=}" ;;
          *) extra+=(--data-urlencode "$aliased") ;;
        esac
      done
      _reddit_get "${base_url}/user/${username}/comments.json" --data-urlencode "limit=${limit}" "${extra[@]}"
      ;;
    user-analysis)
      local username="${1:?usage: reddit user-analysis <username> [posts_limit=<n>] [comments_limit=<n>] [time_range=<day|week|month|year|all>] [top_subreddits_limit=<n>]}"
      shift || true
      local posts_limit=10
      local comments_limit=10
      local time_range="month"
      local top_subreddits_limit=10
      local fetch_limit=100
      local pair now about_file posts_file comments_file status
      for pair in "$@"; do
        case "$pair" in
          posts_limit=*) posts_limit="${pair#posts_limit=}" ;;
          comments_limit=*) comments_limit="${pair#comments_limit=}" ;;
          time_range=*) time_range="${pair#time_range=}" ;;
          top_subreddits_limit=*) top_subreddits_limit="${pair#top_subreddits_limit=}" ;;
        esac
      done
      now="$(date +%s)"
      about_file="$(mktemp)"
      posts_file="$(mktemp)"
      comments_file="$(mktemp)"
      command curl -fsSL -A "$user_agent" "${base_url}/user/${username}/about.json" > "$about_file" || { rm -f "$about_file" "$posts_file" "$comments_file"; return 1; }
      _reddit_get "${base_url}/user/${username}/submitted.json" --data-urlencode "limit=${fetch_limit}" > "$posts_file" || { rm -f "$about_file" "$posts_file" "$comments_file"; return 1; }
      _reddit_get "${base_url}/user/${username}/comments.json" --data-urlencode "limit=${fetch_limit}" > "$comments_file" || { rm -f "$about_file" "$posts_file" "$comments_file"; return 1; }
      command jq -n \
        --slurpfile about "$about_file" \
        --slurpfile posts "$posts_file" \
        --slurpfile comments "$comments_file" \
        --arg timeRange "$time_range" \
        --argjson now "$now" \
        --argjson postsLimit "$posts_limit" \
        --argjson commentsLimit "$comments_limit" \
        --argjson topLimit "$top_subreddits_limit" '
          ($about[0]) as $about
          | ($posts[0]) as $posts
          | ($comments[0]) as $comments
          | def cutoff($range):
              if $range == "day" then $now - 86400
              elif $range == "week" then $now - 604800
              elif $range == "month" then $now - 2592000
              elif $range == "year" then $now - 31536000
              else 0 end;
            def recent($listing; $limit):
              $listing.data.children
              | map(.data)
              | map(select((.created_utc // 0) >= cutoff($timeRange)))
              | .[:$limit];
            {
              user: {
                name: $about.data.name,
                created_utc: $about.data.created_utc,
                link_karma: $about.data.link_karma,
                comment_karma: $about.data.comment_karma,
                total_karma: (($about.data.link_karma // 0) + ($about.data.comment_karma // 0)),
                is_gold: $about.data.is_gold,
                is_mod: $about.data.is_mod,
                verified: $about.data.verified
              },
              posts: recent($posts; $postsLimit),
              comments: recent($comments; $commentsLimit),
              top_subreddits: (
                (recent($posts; 100) + recent($comments; 100))
                | map(select(.subreddit != null))
                | group_by(.subreddit)
                | map({subreddit: .[0].subreddit, count: length})
                | sort_by(-.count, .subreddit)
                | .[:$topLimit]
              )
            }
        '
      status=$?
      rm -f "$about_file" "$posts_file" "$comments_file"
      return "$status"
      ;;
    explain)
      _reddit_explain "${1:?usage: reddit explain <term>}"
      ;;
    *)
      echo "usage: reddit <browse|search|post|post-url|user|user-posts|user-comments|user-analysis|explain> ..." >&2
      return 2
      ;;
  esac
}
```

Then use `reddit <subcommand>` everywhere below.

## Quick start

```bash
reddit browse all hot limit=10
reddit browse technology top time=week limit=10
reddit search "h1b" subreddits='["cscareerquestions","immigration"]' sort=new time=month limit=10
reddit post programming 1abcde comment_limit=20 comment_sort=top
reddit post-url "https://reddit.com/r/programming/comments/1abcde/example/" comment_limit=20
reddit user-analysis spez posts_limit=5 comments_limit=5 time_range=month
reddit explain "cake day"
```

## Notes

- Public JSON endpoints work anonymously for basic read-only use.
- Set a custom `REDDIT_USER_AGENT` for better hygiene and fewer blocks.
- Anonymous access is rate-limited; phase 2 can add richer auth/env handling.
- `search` accepts legacy convenience args:
  - `subreddits='["a","b"]'`
  - `author=<username>`
  - `flair=<text>`
- `post` / `post-url` accept legacy aliases:
  - `comment_limit=` -> `limit=`
  - `comment_sort=` -> `sort=`
  - `comment_depth=` -> `depth=`

## Query templates

See `assets/query-templates.json`.

## Validation

```bash
sh scripts/test-reddit-http.sh
```

## Reference

See `reference.md`.
