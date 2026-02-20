#!/bin/sh
set -eu

SLEEP_SECONDS="${SLEEP_SECONDS:-7}"
RETRY_WAIT_SECONDS="${RETRY_WAIT_SECONDS:-70}"
MAX_LIST_REPEATS="${MAX_LIST_REPEATS:-5}"

WORKDIR="/tmp/reddit-skill-test-$(date +%s)"
LOG="$WORKDIR/report.log"
mkdir -p "$WORKDIR"

PASS_COUNT=0
FAIL_COUNT=0

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[FAIL] missing binary: $1"
    exit 1
  fi
}

section() {
  echo
  echo "==== $1 ====" | tee -a "$LOG"
}

safe_name() {
  echo "$1" | tr ' /' '__'
}

record_pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "[PASS] $1" | tee -a "$LOG"
}

record_fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "[FAIL] $1" | tee -a "$LOG"
  echo "  detail: $2" | tee -a "$LOG"
}

save_output() {
  name="$(safe_name "$1")"
  printf "%s\n" "$2" > "$WORKDIR/$name.out"
}

extract_json_block() {
  awk '
    BEGIN { printing = 0 }
    /^[[:space:]]*\{/ { printing = 1 }
    printing { print }
  '
}

run_check() {
  name="$1"
  cmd="$2"
  expect="${3:-}"

  out="$(sh -c "$cmd" 2>&1)" || {
    save_output "$name" "$out"
    record_fail "$name" "command exited non-zero"
    return
  }

  save_output "$name" "$out"

  if [ -n "$expect" ]; then
    if printf "%s\n" "$out" | rg -q "$expect"; then
      record_pass "$name"
    else
      record_fail "$name" "expected pattern not found: $expect"
    fi
  else
    record_pass "$name"
  fi
}

run_positive_call() {
  name="$1"
  cmd="$2"
  expect="${3:-}"

  out="$(sh -c "$cmd" 2>&1)" || {
    save_output "$name" "$out"
    record_fail "$name" "command exited non-zero"
    return
  }

  if printf "%s\n" "$out" | rg -qi "rate limit|too many requests|Error: 429|Request timeout|may be slow or unreachable"; then
    sleep "$RETRY_WAIT_SECONDS"
    out="$(sh -c "$cmd" 2>&1)" || {
      save_output "$name" "$out"
      record_fail "$name" "command exited non-zero after retry"
      return
    }
  fi

  save_output "$name" "$out"

  if printf "%s\n" "$out" | rg -q "isError: true"; then
    record_fail "$name" "MCP returned isError=true"
    return
  fi

  if [ -n "$expect" ] && ! printf "%s\n" "$out" | rg -q "$expect"; then
    record_fail "$name" "expected pattern not found: $expect"
    return
  fi

  record_pass "$name"
  sleep "$SLEEP_SECONDS"
}

run_negative_call() {
  name="$1"
  cmd="$2"
  expect="${3:-isError: true}"

  out="$(sh -c "$cmd" 2>&1)" || {
    save_output "$name" "$out"
    record_fail "$name" "command exited non-zero"
    return
  }

  save_output "$name" "$out"

  if printf "%s\n" "$out" | rg -q "$expect"; then
    record_pass "$name"
  else
    record_fail "$name" "expected failure marker not found: $expect"
  fi
}

require_bin bun
require_bin jq
require_bin rg
require_bin uv

section "meta-and-sync"
run_check \
  "quick-validate-skill" \
  "uv run --with pyyaml /home/annt/.codex/skills/.system/skill-creator/scripts/quick_validate.py assets/skills/reddit" \
  "Skill is valid!"
run_check \
  "sync-skill-content-ssot-codex-SKILL" \
  "diff -u assets/skills/reddit/SKILL.md ~/.codex/skills/reddit/SKILL.md"
run_check \
  "sync-skill-content-ssot-codex-reference" \
  "diff -u assets/skills/reddit/reference.md ~/.codex/skills/reddit/reference.md"
run_check \
  "sync-skill-content-ssot-codex-templates" \
  "diff -u assets/skills/reddit/assets/query-templates.json ~/.codex/skills/reddit/assets/query-templates.json"
run_check \
  "mcporter-config-has-reddit" \
  "cat ~/.mcporter/mcporter.json" \
  "\"reddit\""
run_check \
  "mcporter-config-entry" \
  "bun x mcporter config get reddit" \
  "Transport: stdio \\(bun x reddit-mcp-buddy\\)"
run_check \
  "mcporter-list-reddit" \
  "bun x mcporter list reddit" \
  "5 tools"
run_check \
  "mcporter-schema-reddit" \
  "bun x mcporter list reddit --schema" \
  "browse_subreddit"

section "positive-functional"
run_positive_call \
  "reddit_explain_known" \
  "bun x mcporter call reddit.reddit_explain term=karma --output json" \
  "\"definition\""
run_positive_call \
  "reddit_explain_unknown" \
  "bun x mcporter call reddit.reddit_explain term=zzzz_nonexistent_term --output json" \
  "Term not found"

seed_out="$(bun x mcporter call reddit.browse_subreddit subreddit=all sort=hot limit=3 --output json 2>&1)" || seed_out=""
if [ -n "$seed_out" ] && printf "%s\n" "$seed_out" | rg -qi "rate limit|too many requests|Error: 429"; then
  sleep "$RETRY_WAIT_SECONDS"
  seed_out="$(bun x mcporter call reddit.browse_subreddit subreddit=all sort=hot limit=3 --output json 2>&1)" || seed_out=""
fi

save_output "seed_browse_all_hot" "$seed_out"
HAS_SEED=0
SEED_POST_ID=""
SEED_SUBREDDIT=""
SEED_PERMALINK=""

if [ -z "$seed_out" ]; then
  record_fail "seed_browse_all_hot" "empty output"
elif printf "%s\n" "$seed_out" | rg -q "isError: true"; then
  record_fail "seed_browse_all_hot" "MCP returned isError=true"
else
  seed_json="$(printf "%s\n" "$seed_out" | extract_json_block)"
  SEED_POST_ID="$(printf "%s\n" "$seed_json" | jq -r '.posts[0].id // empty' 2>/dev/null || true)"
  SEED_SUBREDDIT="$(printf "%s\n" "$seed_json" | jq -r '.posts[0].subreddit // empty' 2>/dev/null || true)"
  SEED_PERMALINK="$(printf "%s\n" "$seed_json" | jq -r '.posts[0].permalink // empty' 2>/dev/null || true)"
  if [ -n "$SEED_POST_ID" ] && [ -n "$SEED_SUBREDDIT" ] && [ -n "$SEED_PERMALINK" ]; then
    HAS_SEED=1
    record_pass "seed_browse_all_hot"
    {
      echo "post_id=$SEED_POST_ID"
      echo "subreddit=$SEED_SUBREDDIT"
      echo "permalink=$SEED_PERMALINK"
    } > "$WORKDIR/seed_vars.txt"
  else
    record_fail "seed_browse_all_hot" "failed extracting post id/subreddit/permalink"
  fi
fi
sleep "$SLEEP_SECONDS"

run_positive_call \
  "browse_popular_rising" \
  "bun x mcporter call reddit.browse_subreddit subreddit=popular sort=rising limit=3 include_nsfw=false --output json" \
  "\"posts\""
run_positive_call \
  "browse_technology_top_week_with_info" \
  "bun x mcporter call reddit.browse_subreddit subreddit=technology sort=top time=week limit=3 include_subreddit_info=true --output json" \
  "\"subreddit_info\""
run_positive_call \
  "browse_technology_controversial_day" \
  "bun x mcporter call reddit.browse_subreddit subreddit=technology sort=controversial time=day limit=3 --output json" \
  "\"posts\""
run_positive_call \
  "browse_technology_new" \
  "bun x mcporter call reddit.browse_subreddit subreddit=technology sort=new limit=3 --output json" \
  "\"posts\""

run_positive_call \
  "search_global_relevance" \
  "bun x mcporter call reddit.search_reddit query=openai sort=relevance time=all limit=3 --output json" \
  "\"total_results\""
run_positive_call \
  "search_single_subreddit_new_week" \
  "bun x mcporter call reddit.search_reddit query=llm subreddits='[\"programming\"]' sort=new time=week limit=3 --output json" \
  "\"results\""
run_positive_call \
  "search_multi_subreddit_comments_month" \
  "bun x mcporter call reddit.search_reddit query=h1b subreddits='[\"cscareerquestions\",\"immigration\"]' sort=comments time=month limit=4 --output json" \
  "\"results\""
run_positive_call \
  "search_hot" \
  "bun x mcporter call reddit.search_reddit query=gpu sort=hot time=day limit=3 --output json" \
  "\"results\""
run_positive_call \
  "search_top_with_author" \
  "bun x mcporter call reddit.search_reddit query=ama sort=top time=year author=spez limit=5 --output json" \
  "\"results\""
run_positive_call \
  "search_with_flair_filter" \
  "bun x mcporter call reddit.search_reddit query=hiring flair=Hiring sort=new time=year limit=5 --output json" \
  "\"results\""

if [ "$HAS_SEED" -eq 1 ]; then
  run_positive_call \
    "get_post_details_by_url_best" \
    "bun x mcporter call reddit.get_post_details url=\"$SEED_PERMALINK\" comment_limit=20 comment_sort=best comment_depth=2 --output json" \
    "\"post\""
  run_positive_call \
    "get_post_details_by_url_top" \
    "bun x mcporter call reddit.get_post_details url=\"$SEED_PERMALINK\" comment_limit=20 comment_sort=top comment_depth=2 --output json" \
    "\"post\""
  run_positive_call \
    "get_post_details_by_url_new" \
    "bun x mcporter call reddit.get_post_details url=\"$SEED_PERMALINK\" comment_limit=20 comment_sort=new comment_depth=2 --output json" \
    "\"post\""
  run_positive_call \
    "get_post_details_by_url_controversial" \
    "bun x mcporter call reddit.get_post_details url=\"$SEED_PERMALINK\" comment_limit=20 comment_sort=controversial comment_depth=2 --output json" \
    "\"post\""
  run_positive_call \
    "get_post_details_by_url_qa_extract_links" \
    "bun x mcporter call reddit.get_post_details url=\"$SEED_PERMALINK\" comment_limit=20 comment_sort=qa comment_depth=2 extract_links=true max_top_comments=3 --output json" \
    "\"post\""
  run_positive_call \
    "get_post_details_by_postid_and_subreddit" \
    "bun x mcporter call reddit.get_post_details post_id=\"$SEED_POST_ID\" subreddit=\"$SEED_SUBREDDIT\" comment_limit=10 comment_sort=top comment_depth=2 --output json" \
    "\"post\""
  run_positive_call \
    "get_post_details_by_postid_only" \
    "bun x mcporter call reddit.get_post_details post_id=\"$SEED_POST_ID\" comment_limit=10 comment_sort=best comment_depth=2 --output json" \
    "\"post\""
else
  record_fail "get_post_details_seeded_suite" "seed step failed; skipped dynamic get_post_details positives"
fi

run_positive_call \
  "user_analysis_defaults" \
  "bun x mcporter call reddit.user_analysis username=spez --output json" \
  "\"username\""
run_positive_call \
  "user_analysis_posts0_comments5_week" \
  "bun x mcporter call reddit.user_analysis username=spez posts_limit=0 comments_limit=5 time_range=week top_subreddits_limit=5 --output json" \
  "\"username\""
run_positive_call \
  "user_analysis_posts5_comments0_all" \
  "bun x mcporter call reddit.user_analysis username=spez posts_limit=5 comments_limit=0 time_range=all top_subreddits_limit=5 --output json" \
  "\"username\""
run_positive_call \
  "user_analysis_time_day" \
  "bun x mcporter call reddit.user_analysis username=spez posts_limit=3 comments_limit=3 time_range=day --output json" \
  "\"username\""
run_positive_call \
  "user_analysis_time_month" \
  "bun x mcporter call reddit.user_analysis username=spez posts_limit=3 comments_limit=3 time_range=month --output json" \
  "\"username\""
run_positive_call \
  "user_analysis_time_year" \
  "bun x mcporter call reddit.user_analysis username=spez posts_limit=3 comments_limit=3 time_range=year --output json" \
  "\"username\""

section "negative-validation"
run_negative_call \
  "browse_missing_subreddit" \
  "bun x mcporter call reddit.browse_subreddit sort=hot --output json"
run_negative_call \
  "browse_invalid_sort" \
  "bun x mcporter call reddit.browse_subreddit subreddit=all sort=invalid --output json"
run_negative_call \
  "browse_limit_zero" \
  "bun x mcporter call reddit.browse_subreddit subreddit=all limit=0 --output json"
run_negative_call \
  "search_missing_query" \
  "bun x mcporter call reddit.search_reddit sort=relevance --output json"
run_negative_call \
  "search_invalid_time" \
  "bun x mcporter call reddit.search_reddit query=ai time=never --output json"
run_negative_call \
  "get_post_details_missing_id_and_url" \
  "bun x mcporter call reddit.get_post_details comment_limit=10 --output json"
run_negative_call \
  "get_post_details_invalid_depth" \
  "bun x mcporter call reddit.get_post_details url=https://reddit.com/r/all/comments/ comment_depth=99 --output json"
run_negative_call \
  "get_post_details_bad_url" \
  "bun x mcporter call reddit.get_post_details url=https://example.com/not-reddit --output json"
run_negative_call \
  "user_analysis_missing_username" \
  "bun x mcporter call reddit.user_analysis posts_limit=5 --output json"
run_negative_call \
  "user_analysis_invalid_time_range" \
  "bun x mcporter call reddit.user_analysis username=spez time_range=never --output json"
run_negative_call \
  "reddit_explain_missing_term" \
  "bun x mcporter call reddit.reddit_explain --output json"

section "query-template-coverage"
run_positive_call \
  "template_browseAllHot" \
  "bun x mcporter call reddit.browse_subreddit subreddit=all sort=hot limit=25 include_nsfw=false --output json" \
  "\"posts\""
run_positive_call \
  "template_browseSubredditTopWeek" \
  "bun x mcporter call reddit.browse_subreddit subreddit=technology sort=top time=week limit=25 include_subreddit_info=true --output json" \
  "\"posts\""
run_positive_call \
  "template_searchGlobal" \
  "bun x mcporter call reddit.search_reddit query='ai agents' sort=relevance time=all limit=25 --output json" \
  "\"results\""
run_positive_call \
  "template_searchInSubreddits" \
  "bun x mcporter call reddit.search_reddit query='open source' subreddits='[\"cscareerquestions\",\"programming\"]' sort=new time=month limit=25 --output json" \
  "\"results\""
run_positive_call \
  "template_searchByAuthor" \
  "bun x mcporter call reddit.search_reddit query=ama author=spez sort=top time=year limit=25 --output json" \
  "\"results\""
run_positive_call \
  "template_searchByFlair" \
  "bun x mcporter call reddit.search_reddit query=hiring flair=Hiring sort=new time=year limit=25 --output json" \
  "\"results\""
run_positive_call \
  "template_userAnalysisDefault" \
  "bun x mcporter call reddit.user_analysis username=spez posts_limit=10 comments_limit=10 time_range=month top_subreddits_limit=10 --output json" \
  "\"username\""
run_positive_call \
  "template_redditExplainTerm" \
  "bun x mcporter call reddit.reddit_explain term=karma --output json" \
  "\"definition\""
if [ "$HAS_SEED" -eq 1 ]; then
  run_positive_call \
    "template_getPostDetailsByUrl" \
    "bun x mcporter call reddit.get_post_details url=\"$SEED_PERMALINK\" comment_limit=20 comment_sort=best comment_depth=3 --output json" \
    "\"post\""
  run_positive_call \
    "template_getPostDetailsByIdAndSubreddit" \
    "bun x mcporter call reddit.get_post_details post_id=\"$SEED_POST_ID\" subreddit=\"$SEED_SUBREDDIT\" comment_limit=20 comment_sort=best comment_depth=3 --output json" \
    "\"post\""
  run_positive_call \
    "template_getPostDetailsWithLinks" \
    "bun x mcporter call reddit.get_post_details url=\"$SEED_PERMALINK\" comment_limit=20 comment_sort=qa comment_depth=3 extract_links=true max_top_comments=5 --output json" \
    "\"post\""
else
  record_fail "template_getPostDetails_suite" "seed step failed; skipped template get_post_details checks"
fi

section "reliability"
i=1
while [ "$i" -le "$MAX_LIST_REPEATS" ]; do
  run_check "reliability_list_reddit_$i" "bun x mcporter list reddit" "5 tools"
  i=$((i + 1))
done

section "summary"
echo "workdir=$WORKDIR" | tee -a "$LOG"
echo "pass=$PASS_COUNT" | tee -a "$LOG"
echo "fail=$FAIL_COUNT" | tee -a "$LOG"

if [ "$FAIL_COUNT" -eq 0 ]; then
  exit 0
fi

exit 1
