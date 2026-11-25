# Source registry: adding, vetting, and repairing sources

## Contents

- The registry
- Add a source
- Vet a discovered source
- Manual fallback when firecrawl fails
- Fingerprint-drift repair workflow

## The registry

`sources.json` beside this file's skill root declares every source, keyed by
source key:

```json
{
  "sources": {
    "agents": {
      "name": "valking.gg agent tier list",
      "url": "https://valking.gg/en/agents",
      "parser": "parse_agents_table",
      "description": "..."
    }
  }
}
```

The key does double duty: it names the registry entry and, under fixture
injection (`VALORANT_META_FIXTURE_DIR`), it names the fixture file
`<fixture_dir>/<key>.md`. The patch detail page is deliberately not a
registry entry: its URL is dynamic, extracted from the latest patch card by
the patches parser, so it is a second fetch step inside the `patch` command.

## Add a source

1. Capture a real fixture: scrape the URL through the sibling firecrawl CLI
   and save the markdown as `tests/fixtures/<key>.md`. Never hand-write a
   fixture; the parser must be built against real bytes.
2. Write the parser function in `scripts/cli.py`. Strict rules: parse every
   row or fail the whole parse, validate structural minimums (row counts,
   required columns), and raise `_ParseError` on any deviation. Compute the
   shape fingerprint from the structural keys the parser depends on plus the
   row-count bucket.
3. Register the parser name in the `PARSERS` map and add the registry entry
   to `sources.json`.
4. Add tests driving the CLI with the fixture: parse correctness, the error
   envelope when the fixture is missing, the parse error when it is corrupt.
5. Run the gates, then `doctor` live once to establish the fingerprint
   baseline in the state file.

## Vet a discovered source

`discover` lists candidate domains. Before adding one to the registry:

1. Determine rendering: fetch the page with plain curl. If the data table is
   in the HTML, the source is server-rendered and cheap to scrape. If the
   HTML is an empty shell, the source is JS-rendered and needs firecrawl or
   a browser.
2. Scrape it through the sibling firecrawl CLI and inspect the markdown. The
   table or sections must survive extraction as parseable text. If firecrawl
   output is garbled or empty, the source is not machine-readable through
   this pipeline; either use the manual fallback below or drop the candidate.
3. Check cadence and coverage: does the data update per patch, and does it
   cover what the registry lacks? A source that duplicates valking.gg adds
   value only as cross-validation.
4. Check stability: pages backed by a table or stable section structure are
   parseable; free-prose pages are not. Reject sources whose data only
   appears inside images or canvases.

## Manual fallback when firecrawl fails

When firecrawl cannot render a page (anti-bot walls, interactive selectors
the scrape never triggers), use the agent-browser skill: drive a real
browser, wait for the data to render, and export the page text or HTML.
Then either parse that capture by hand for the immediate question, or save
it as a development fixture to build a parser for a new pipeline. Do not
silently substitute stale captured data for a live answer; label anything
manual with its capture date when reporting.

## Fingerprint-drift repair workflow

The fingerprint is a sha256 of sorted structural keys plus a row-count
bucket, truncated to 12 hex chars, stored per source in the state file.
A mismatch means the source shape changed since the baseline. Row-count
bucket crossings are benign (a new agent release moves the count); key
changes are not.

1. Run `doctor`. Read `fingerprint_status` per source: `mismatch` means the
   fresh parse shape differs from the stored baseline, `no-baseline` means
   the source was never recorded, `match` is healthy.
2. Run the failing or drifting command and inspect the output or error.
   `PARSE_FAILED` means the strict parser rejected the page: the breakage is
   real and total. A drift warning inside `ok:true` output means the parse
   still works but the shape moved: verify the data before trusting it.
3. Capture the current page through the sibling firecrawl CLI and diff it
   against `tests/fixtures/<key>.md`. The diff shows exactly what drifted.
4. If the drift is benign (row-count bucket, cosmetic reordering), update
   the fixture copy with the fresh capture so tests track reality, and let
   the next successful command write the new baseline. No parser change.
5. If the drift is structural (renamed columns, new sections, moved tables),
   update the parser and the fixture together, then update the tests.
6. Rerun the gates and `doctor`. `fingerprint_status` returns to `match`
   once a successful parse writes the new baseline. `consecutive_failures`
   resets to zero on the first success.
