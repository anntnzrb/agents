# Reddit future refactor notes

Read this when planning a larger Reddit skill refactor. Do not load it for normal subreddit browsing or glossary lookup.

## Expectations

- Default output stays compact and agent-shaped. Raw Reddit JSON is available only via explicit `raw=1`
- Block pages and HTML failures stay summarized. The skill must never dump Reddit’s network-security HTML shell into agent context
- Public JSON endpoints remain read-only and anonymous by default. OAuth is a separate feature, not something to bolt onto the current low-friction helper casually
- Validation should fail before network calls when the bad input is local: malformed URL, invalid `time_range`, malformed `subreddits=`, bad numeric args, invalid browse sort
- `explain` remains local and deterministic
- User-facing docs should distinguish local validation failures from Reddit/provider failures

## Non-expectations

- This skill should not scrape authenticated/private Reddit surfaces
- It should not auto-retry network-security blocks. Those usually require egress/User-Agent changes, not more requests
- It should not pass through all Reddit fields by default. Reddit payloads are huge and UI-heavy
- It should not silently drop malformed filters. Bad input should produce rc=2 and a named error
- It should not turn `user-analysis` into a vague reputation score. Keep computed fields explicit and inspectable

## Ideal shape

- Listing/search envelopes:
  - `type`
  - `query` or `subreddit`
  - `sort`
  - `time`
  - `count`
  - `results`
- Post envelope:
  - `type: "post"`
  - `post`
  - `comments`
- User envelope:
  - `type: "user"`
  - `user`
  - `profile`
- Error envelope:
  - `error.provider`
  - `error.status`
  - `error.kind`
  - `error.message`
  - `error.body_bytes`
  - `error.body_preview`
  - `error.body_truncated`

## Future refactor candidates

1. Move shared env loading and HTTP error shaping into a small shared helper used by Reddit, Brave, Exa, and Grep.app
2. Add fixture-based tests for successful Reddit listings, post/comment payloads, profile payloads, and blocked-page failures
3. Add live smoke tests gated behind an env flag and documented as optional because Reddit often blocks automated egress
4. Consider an OAuth-backed sibling mode only if the user explicitly needs authenticated/private/high-throughput access
5. Split network fetching from projection functions more cleanly so projections can be tested with raw fixtures without monkeypatching `urlopen`
6. Consider adding `after=` pagination support to envelopes if real workflows need multi-page browsing
7. Expand the glossary only when the new terms are stable enough to avoid slang churn

## Regression traps

- `network_security_block` is not a credential problem. Do not tell users to set credentials when Reddit is blocking egress
- `time_range=invalid` must not silently mean `all`
- `subreddits=` must be a JSON list of non-empty strings. Non-list JSON is still invalid
- `post-url` must require `http://` or `https://`; otherwise urllib raises tracebacks on malformed values
- `browse` sort is positional and fragile. Keep the closed sort set and reject stray positional tokens after `key=value` args
- `explain` should output the canonical glossary term after normalization, not the raw user spelling
