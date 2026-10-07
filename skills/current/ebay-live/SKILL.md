---
name: ebay-live
description: "Use when searching live eBay listings, auctions, Buy It Now prices, or deals."
license: AGPL-3.0-or-later
---

# eBay live

Find current eBay listings, compare delivered prices, and shortlist deals.
Use this skill for eBay catalog searches and item-page evidence.
Use `amz-live` for Amazon and `market-hunter` for software subscription marketplaces.

## Public entrypoint

Resolve `<skill-dir>` to the directory containing this file.
Run the bundled CLI with `uv`:

```text
uv run --script <skill-dir>/scripts/cli.py "sony wh-1000xm5" --llm-json --limit 5 --scoring
```

The CLI only reads public catalog and item pages.
It does not sign in, bid, buy, contact sellers, or change an account.
Sold and completed listings are outside the supported search contract.

## Find a deal

1. Translate the request into a product query, condition, format, and price range.
2. Use `--llm-json` to preserve transport, filters, missing fields, and warnings.
3. Prefer Buy It Now when the user needs a purchase price today.
4. Exclude accessories and broken items that the user did not request.
5. Compare `total_cost`, condition, and seller feedback before recommending a listing.
6. Fetch details for the strongest candidates with `--details --detail-limit 1`.
7. Report the title, URL, condition, price, shipping, and seller evidence.

For a used pair of headphones available to buy now:

```text
uv run --script <skill-dir>/scripts/cli.py "sony wh-1000xm5" --condition used --buy-it-now --max-price 200 --exclude case --exclude hinge --exclude replacement --exclude parts --llm-json --limit 5 --scoring --details --detail-limit 1
```

For auctions ending soon:

```text
uv run --script <skill-dir>/scripts/cli.py "seiko vintage watch" --auction --sort ending-soonest --llm-json --limit 5
```

An auction's price is the current bid.
An auction's delivered total is not a final purchase price.
A price range reports the lowest amount and `price_max`.
Check the selected variation before calling a range a deal.

## Choose the search controls

Use `--help` for the complete flag set and allowed values.
The URL builder sends these controls to eBay:

- `--sort` selects best match, ending soonest, newly listed, price, or distance order.
- `--min-price` and `--max-price` constrain the advertised item price.
- `--condition` selects new, open box, refurbished, used, or for parts.
- `--buy-it-now` and `--auction` select mutually exclusive buying formats.
- `--page`, `--pages`, and `--per-page` control page retrieval.
- `--zip` supplies a US ZIP code as a best-effort location hint.

Only main-river listings before eBay's "Results matching fewer words" boundary
enter results. The summary reports exact listings and excluded rewrite cards.
Zero exact matches produce a warning. eBay exact matches can still include
accessories or titles missing query words; inspect `query_match`.

Local filters inspect the returned cards:

- Repeat `--include` to require every term in the title.
- Repeat `--exclude` to reject any term in the title.
- `--title-contains` requires a case-insensitive title substring.
- `--min-seller-feedback` requires a positive-feedback percentage.
- `--free-shipping` requires explicit free shipping or delivery evidence.
- `--limit` caps results after filtering and ranking.

Use explicit include and exclude terms when exact product identity matters.
Scoring flags possible accessories and damaged items.
Title heuristics do not verify condition or compatibility.
Missing seller feedback fails a minimum-feedback filter.
Missing shipping fails a free-shipping filter.

## Interpret the evidence

`--json` emits a result array.
`--llm-json` emits the versioned `ebay-live.search_results` envelope.
`--schema` publishes the result schema and RPC request fields.

A listing includes identity, price, shipping, condition, buying formats,
auction state, seller feedback, location, and a sponsored marker.
`query_match` is the fraction of normalized query tokens present in the title.
Unknown observations remain null.
`total_cost` is present only when price and shipping are both known.
Totals omit taxes, import fees, and checkout adjustments.

`--scoring` adds `score`, `reasons`, and `rank` to each result.
The envelope also describes the ranking population and method.
Ranking compares observed totals within each currency among full title-token matches.
Totals below 40% of that median are penalized as likely accessories or parts.
The score is a shortlist heuristic, not a seller guarantee or market valuation.
Read the reasons before presenting the first result as the best deal.

`--details` adds item-page evidence under each enriched result's `details` key.
The search snapshot stays intact, including the search price.
An item fetch failure retains the result and adds a warning.
The `enrichment` object reports attempts and successful detail parses.

## Handle live access

The default `--transport auto` uses a shared-cookie Safari session.
Chrome is a compatibility fallback when the Safari request fails.
A blocked direct page falls back once to Firecrawl if `FIRECRAWL_API_KEY` exists.
Firecrawl requests raw HTML with its cache and SDK retries disabled.

Use `--transport direct` to prohibit proxy fallback.
Use `--transport firecrawl` to fetch through Firecrawl immediately.
The envelope lists the serving transports and records individual fetches.
Read warnings when a direct page needed proxy fallback.
Never turn an access failure into a claim that eBay has no matching listings.

For saved HTML:

```text
uv run --script <skill-dir>/scripts/cli.py "headphones" --html <capture-file> --llm-json
```

`--html` accepts one search page.
Adding `--details` still fetches live item pages.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Search examples | [references/cheatsheet.md](references/cheatsheet.md) | Choosing filters or output flags |
| Evidence and transport contract | [references/operational-contract.md](references/operational-contract.md) | Recommending a deal or interpreting missing evidence |
| JSONL requests | [references/rpc.md](references/rpc.md) | Driving repeated searches through RPC |
| Access and parsing failures | [references/troubleshooting.md](references/troubleshooting.md) | A search fails or detail enrichment is incomplete |
