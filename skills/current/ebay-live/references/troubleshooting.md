# Resolve access and parsing failures

Read this when live access fails or a detail fetch is incomplete.

## Direct access is blocked

If stderr reports a challenge or asks for a key, set `FIRECRAWL_API_KEY`
and rerun with `--transport auto`.
Use `--transport firecrawl` to skip a known blocked direct search.
Do not repeat requests in an automatic retry loop.

If Firecrawl also returns a challenge, report the failure.
An HTTP 200 response alone does not establish usable catalog content.
A successful empty response needs explicit no-match text.

## Firecrawl rate limits

A Firecrawl HTTP 429 rate-limit error gets exactly one retry.
The client waits the advertised "retry after" seconds, capped at 30 seconds;
when the message lacks a wait, it waits two seconds.
A second rate-limit error fails the fetch. Other proxy errors are not retried.
Detail enrichment defaults to two item fetches; reduce `--detail-limit` if needed.

## Inspect saved markup

Save the response HTML to a file, then run:

```text
uv run --script <skill-dir>/scripts/cli.py "original query" --html <capture-file> --llm-json
```

Verify that the capture contains real listing cards rather than markdown,
a challenge page, or a sign-in page.
The parser expects `li.s-card` with item links and titles.
An unrecognized empty page fails instead of yielding an empty success.

## Results contain accessories

Require distinguishing title terms with `--include`.
Reject accessory or repair terms with repeated `--exclude` flags.
Read scoring reasons and compare the full titles before selecting a deal.
A low amount for an auction or a variation is not a confirmed purchase price.

## Details fail

Read `warnings` and `enrichment` in the envelope.
The original search card remains usable as search evidence.
Reduce `--detail-limit` to the candidates you need.
Missing returns or item specifics remain null or an empty object.

## Sold comps are unavailable

Use the supported active catalog search.
Sold and completed pages can require sign-in or present a captcha wall.
This skill does not support sold comps or authenticate to retrieve them.
