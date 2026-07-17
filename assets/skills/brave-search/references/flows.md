# Example Flows

Read this when a lookup needs a multi-step web, news, image, video, or local flow.

All flows run through `scripts/cli.py`:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

## Quick lookup

1. `web "<topic>"` for a small default result set with `result_filter=web`.
2. If a result looks promising, fetch the page with `raw <result-url>` (browser skill) or by hand.

## Quick news scan

1. `news "<topic>"` with `freshness=pd` for the past day.
2. Skim the compact `results` array; only the fields you actually use are present.

## Image / video shortlist

1. `image "<topic>"` (default `count=10`) to gather thumbnails and source pages.
2. `video "<topic>"` to get video titles, durations, and publishers.
3. For the upstream shape (e.g. raw `meta_url` or mixed-result fields), re-run with `raw=1` on the same command.

## Provider failure triage

1. Look at the compact error JSON on stderr — it carries the status, body byte count, and a summarized preview.
2. If `error.status` is `null`, this is a network/parse failure (rc=1), not a provider rejection.
3. If `error.status` is set, the provider responded with that code (rc=22) — chase key/quota/rate limits.
4. Usage errors (bad count, missing args) come back as rc=2 with plain text, not the JSON envelope.
