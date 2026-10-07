---
name: metacritic
description: "Use when looking up Metacritic Metascores, user scores, or critic reviews for films, TV shows, or video games."
license: AGPL-3.0-or-later
compatibility: Requires the metacritic MCP server via MCPorter, launched with bun.
---

# Metacritic

Read Metacritic entries through MCPorter (`mcporter call metacritic.<tool>`). The server needs no API key and is unofficial.

## Public entrypoint

```sh
mcporter call metacritic.<tool> key=value --output json
mcporter call metacritic.<tool> --args '<JSON-matching-live-schema>' --output json
```

Use `--args` for array arguments such as `sections`. Inspect live schemas before guessing a parameter:

```sh
mcporter list metacritic --brief
mcporter list metacritic.<tool> --schema --all-parameters
```

## Tools

| Tool | Use |
|---|---|
| `search_titles` | Find films, shows, or games by title; returns `slug`, `kind`, and Metascore |
| `get_title` | Read one entry with critic and user score breakdowns |
| `get_reviews` | Read critic or user reviews, filtered by sentiment |
| `browse_titles` | List a catalogue by `score`, `recent`, or `popular`, optionally by genre |

## Workflow

1. Search, then pass the row's `slug` and `kind` together. The same slug can name a film and a game.
   ```sh
   mcporter call metacritic.search_titles query="elden ring" kind=game limit=5 --output json
   mcporter call metacritic.get_title slug=elden-ring kind=game --output json
   ```
2. Read reviews from the same pair. `get_reviews` serves a sample, so also read the counts from `get_title`: its `critic_score` and `user_score` carry `positive_count`, `neutral_count`, and `negative_count`.
   ```sh
   mcporter call metacritic.get_reviews slug=batman-v-superman-dawn-of-justice kind=movie source=critic sentiment=negative limit=50 --output json
   mcporter call metacritic.get_title --args '{"slug":"batman-v-superman-dawn-of-justice","kind":"movie","sections":["scores"]}' --output json
   ```
   Report served versus counted, such as "7 of 10 negative reviews", and link `source_url` for the rest.
3. Browse when the user asks for best, recent, or popular titles:
   ```sh
   mcporter call metacritic.browse_titles kind=movie sort=score genre=Comedy limit=10 --output json
   ```
4. Request extra entry sections only when asked; each costs a request:
   ```sh
   mcporter call metacritic.get_title --args '{"slug":"the-matrix","kind":"movie","sections":["basic","scores","where_to_watch"]}' --output json
   ```

## Read results correctly

- Search rows always have `user_score: null`. Use `get_title` or `browse_titles` for the user score.
- `null` means Metacritic computed no score. Report it as missing, never as zero.
- The Metascore is out of 100 from critics; the user score is out of 10 from members. Report both with their scales; never compare the raw numbers.
- `get_reviews` serves a sample, not every review. `total_available` counts every review of that source, whatever the sentiment filter. Only the `get_title` sentiment counts say how many reviews of one sentiment exist.
- An empty `reviews` list with a sentiment filter means the sample has none of that sentiment. Check the `get_title` count before saying none exist.
- Name the `publication` when quoting a critic review.
- Paginate with `offset=<next_offset>` while `next_offset` is not `null`.

## Errors

Failures return `isError: true` with a code in brackets and a `Hint:` line. Follow the hint.

- `not_found`: rerun `search_titles` and pass its exact `slug` and `kind`.
- `rate_limited`: wait the seconds the hint names, then repeat the same call.
- `parse_failure`: Metacritic changed its response format. Report the error to the user instead of retrying.
