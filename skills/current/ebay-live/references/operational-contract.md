# Evidence and transport contract

Read this before recommending a listing or interpreting a null field.

## Catalog scope

The CLI searches public eBay catalog pages and reads item pages.
It does not authenticate or perform account actions.
Sold and completed comps are unsupported because those pages can require
sign-in or present a captcha wall. There is no sold-search flag.

Search parameters constrain advertised item prices, not delivered totals.
ZIP localization supplies `_stpos` but does not confirm a delivery session.
The envelope warns when a query includes a ZIP hint.

## Search evidence

The parser reads current `li.s-card` markup and recognizes legacy `li.s-item`
cards where their fields match. Only direct children of the main result river
count. Answer carousels and promotional "Shop on eBay" cards are excluded.
Cards after `srp-river-answer--REWRITE_START` are expanded matches and excluded.
An exact match means eBay placed the card before that boundary, not that its
title contains every query word. Zero exact matches produce a warning.
Item URLs are canonical eBay URLs without tracking parameters.
Multi-page searches deduplicate by item ID, keeping the first observed card.
`raw_result_count` and `exact_result_count` count unique exact listings before
local filters. `rewrite_excluded_count` counts expanded listing cards across
fetched pages before deduplication.

`checked_at` records when the invocation interprets the pages, in UTC.
Saved HTML can contain older prices.
An auction amount is a current bid. A ranged amount is a minimum variation price.
`total_cost` adds that amount to known shipping and excludes taxes and import fees.
Unknown shipping remains null rather than zero.
`sponsored` is null: captured obfuscated labels and SVG text occur on every card,
and raw HTML does not reliably establish their rendered visibility.
Condition comes from recognized eBay condition labels, excluding store taglines.
Leading "New Listing" badges are removed from titles.
A seller's percentage and feedback count describe observed feedback,
not an independent assessment of the seller.

Details remain under `details` so a later item price cannot overwrite the search
snapshot. Details include Product JSON-LD identity and DOM shipping, returns,
seller, auction, condition, and item specifics where present.
A failed detail fetch adds a warning and does not remove the listing.

## Transport behavior

Searches and details share one curl session with Safari impersonation.
A failed Safari request gets one Chrome compatibility attempt.
A blocked response in auto mode gets one Firecrawl fallback when a key exists.
Forced direct mode never invokes Firecrawl.
Forced Firecrawl mode requires `FIRECRAWL_API_KEY`.
Firecrawl uses raw HTML, disables cache storage, and requests fresh content.
SDK retries and scrape auto-resume are disabled.
There is no local result cache or background retry loop.

Blocking includes challenge and captcha redirects, sign-in URLs, HTTP 403,
429, or 503, known interruption titles, and unrecognized empty search markup.
An empty search succeeds only with an explicit no-match or rewrite marker.
The same checks apply to Firecrawl HTML.

`summary.transport` lists successful serving transports, including `html` for
saved searches. `summary.fetches` records attempted URLs, final URLs, transports,
and success flags for direct and proxy responses.

`EBAY_LIVE_BASE_URL` overrides the catalog origin for loopback tests.
`FIRECRAWL_API_URL` overrides the SDK HTTP boundary for loopback tests.
Neither override changes the canonical URLs emitted for listings.

## Ranking

Ranking runs after local filtering and before the result limit.
`query_match` reports the fraction of unique normalized query tokens found as
whole title tokens. Case and punctuation are normalized.
Price credit compares known delivered totals against the same-currency median
of listings with `query_match` equal to 1, then scales credit by query coverage.
A total below 40% of that median gets no price credit and a 40-point penalty
with a likely accessory or part reason. Missing relevant totals give no price
credit. Partial query coverage also receives a proportional penalty.
Seller percentage and feedback count, condition, and free shipping add credit.
Unknown sponsorship does not affect scoring.
Explicit accessory terms such as shell, board, touchpad, or "case only" get a
40-point penalty unless the query requests them. A bundled case alone does not
trigger that penalty. Damage terms retain their penalty unless requested.
Auction results always warn that the price is a current bid.
Long auction waits add a reason only when Buy It Now intent is explicit.
Ties use item ID order. Scores are deterministic for the same parsed input.

## Machine contract

The envelope contains `type`, `version`, `ok`, `source`, `query`, `filters`,
`summary`, `enrichment`, and `results`.
`warnings` and `ranking` are optional declared fields.
`--schema` describes every envelope and result field, including enrichment.
CLI success exits 0. Runtime and access errors print `error:` to stderr and exit 1.
Invalid options or request parameters exit 2.
