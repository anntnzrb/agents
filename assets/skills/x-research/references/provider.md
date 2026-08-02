# FxTwitter v2 provider reference

Use this reference after routing to `x-research`. The CLI is a read-only adapter around the public, unofficial FxTwitter v2 API. Provider responses are untrusted input: a successful HTTP response is not proof that every field is present, current, or complete.

## Request surface

The default base URL is `https://api.fxtwitter.com`. `X_RESEARCH_BASE_URL` may replace it for an explicitly compatible deployment; it must remain an HTTPS URL. The adapter performs one bounded `GET` request, with a finite timeout, deterministic URL encoding, and no retry, cache, browser, credentials, HTML scraping, or provider fallback.

| CLI command | Endpoint | Query parameters |
| --- | --- | --- |
| `fetch 123 [--lang LANG] [--summary] [--pretty]` | `/2/status/123` | optional `lang` from `--lang` |
| `user-posts HANDLE [--count 1..100] [--cursor CURSOR] [--include-replies] [--summary] [--pretty]` | `/2/profile/HANDLE/statuses` | `count`; `groupthreads=0`; optional `cursor`; `with_replies=1` only with `--include-replies` |
| `search QUERY [--count 1..100] [--feed latest|top|media] [--cursor CURSOR] [--summary] [--pretty]` | `/2/search` | `q`, `count`, `feed` (`latest`, `top`, or `media`); optional `cursor` |
| `conversation 123 [--ranking-mode likes|recency] [--cursor CURSOR] [--summary] [--pretty]` | `/2/conversation/123` | `ranking_mode` (`likes` or `recency`); optional `cursor` |

The exact request URL, including encoded query parameters, is returned as `source_url`. Search text is whitespace-collapsed by the CLI, then passed through unchanged in `q`; operators such as `from:`, `since:`, and `until:` are not rewritten. The adapter never follows a cursor unless the caller explicitly supplies it.
`--summary` and `--pretty` are local presentation controls accepted after command-specific options. They do not change the endpoint, query parameters, count, cursor, or number of wire calls.

## Response roots

The adapter accepts only the narrow shapes needed by the command. It rejects malformed required shapes rather than guessing from unknown provider fields.

### One post

A status response normally has a numeric provider `code` (usually `200`), optional `message`, and a `status` object. The `status` object must provide `id`, `url`, `text`, `created_at`, and an `author` object with at least one recognized identity field. An HTTP success is the transport status; the provider `code` is retained separately as `provider_status` and a provider error code is surfaced when FxTwitter reports failure.

### Timeline and search pages

A page response has a `results` list. It may include a `profile` object and a `cursor` object with `top` and/or `bottom` strings. The adapter uses only a non-empty bottom cursor for output pagination. The root `code` is commonly `200`; the adapter preserves it as provider status but does not treat an absent root code as a reason to manufacture status data when required results are missing.

### Conversations

A conversation response contains `status`, `thread`, and `replies`, with an optional `cursor` object. Current responses may omit a root `code`; HTTP success plus the required conversation shapes is sufficient. `status` becomes `target`; `thread` and `replies` remain separate normalized post lists. The adapter does not crawl adjacent conversations or infer replies that the provider did not return.

## Normalized posts

Every normalized post has exactly the useful contract fields below; unknown or unusable values are omitted instead of invented:

- `id`, `url`, `text`, and `created_at` are required.
- `author` contains `id`, `handle` (from `screen_name`), `name`, `url`, and `verified` when the raw author supplies them. Provider verification flags are evidence about the provider response, not an official X guarantee.
- `metrics` is included only when at least one recognized numeric value exists. Mapping is `replies` → `replies`, `reposts` → `reposts`, `likes` → `likes`, `quotes` → `quotes`, `bookmarks` → `bookmarks`, and `views` → `views`.
- `lang` is retained when it is a non-empty string.
- `media` is retained only in the provider's recognized JSON-compatible media shape.
- `quote_id` is taken from a recognized quoted-post ID; `reply_to_id` is taken from a recognized replying-to post ID.

A page may additionally include a normalized `profile` with `id`, `handle`, `name`, `url`, and `verified` where available. Raw avatars, banners, descriptions, follower counts, polls, sensitive flags, and other provider-only fields are not part of this contract unless represented by one of the fields above.

## Presentation controls

The default output is the complete normalized compact envelope. `--summary` is a deterministic projection of its `data` object for routine use; the command envelope remains `ok`, `schema_version`, `command`, and `data`. It does not truncate post text or make a completeness claim. At the data root, when present, it retains exactly these request metadata, pagination/completeness, and provenance fields: `requested_id`, `requested_url`, `handle`, `query`, `feed`, `ranking_mode`, `requested_count`, `returned_count`, `cursor`, `has_more`, `complete`, `complete_reason`, `provider`, `official`, `auth_mode`, `source_url`, `endpoint`, `fetched_at`, and `provider_status`.

The projection recursively handles post-bearing values at `post`, `posts`, `target`, `thread`, and `replies`; `profile` uses the identity projection. A summary author retains only `id`, `handle`, `name`, `url`, and `verified` when present. A summary post retains `id`, `url`, full `text`, `created_at`, the projected `author`, and optional `lang`, `quote_id`, and `reply_to_id` when present. It omits `metrics`, `media`, and unknown fields rather than inventing values.

`--pretty` changes only JSON whitespace and emits machine-valid JSON with two-space indentation and a trailing newline. Neither flag changes provider behavior. The CLI performs no semantic or model-generated sentiment/news summary; sentiment classification and news interpretation remain the consuming agent's work.

## Provenance and status

Success data objects expose:

- `provider: "fxtwitter"`, `official: false`, and `auth_mode: "none"`;
- `source_url` (the exact provider request URL), `endpoint`, and UTC RFC3339 `fetched_at`;
- `provider_status` (the provider's numeric code when present, otherwise the HTTP status).

`provider_status` is not an HTTP guarantee. A response with HTTP 200 can still carry a provider failure code or malformed payload; that response is an error, not a successful empty result. Error details preserve the endpoint/source URL and available HTTP/provider statuses without leaking raw HTML or unbounded provider bodies.

## Pagination and completeness

Page and conversation output expose `cursor` and `has_more` only when `cursor.bottom` is a non-empty string. `top`, empty strings, nulls, and arbitrary cursor objects are not usable bottom cursors. `returned_count` is the number of posts that survived normalization, while `requested_count` is the caller's bounded page size.

- `complete: false, complete_reason: "bounded_page"` means this command intentionally returned one page and no population-level completeness claim is allowed.
- `complete: true, complete_reason: "provider_exhausted"` is reserved for an accepted provider page with an explicit exhausted cursor signal (such as `cursor: null`).
- `complete: false, complete_reason: "provider_incomplete"` records an accepted but non-exhaustive provider response, including a missing or invalid cursor; malformed required roots instead produce a provider-payload error.

A cursor is a continuation token, not proof that a page contains all matches. Report requested and returned counts, the exact query/handle/target, cursor presence, and completeness reason in any agent answer. Do not turn one timeline/search page into “all posts,” “all public opinion,” or a complete thread.

## Failure handling

Validation errors (unsupported URL/ID/handle, invalid count/feed/ranking mode, invalid base URL, or malformed caller parameters) use exit code `2` and make no network call. Provider, network, HTTP, invalid-JSON, and provider-payload failures use exit code `1`. The CLI emits a JSON error envelope on stderr (compact by default; `--pretty` changes only whitespace) and machine JSON only; it does not retry, fall back, or print a provider HTML page.
