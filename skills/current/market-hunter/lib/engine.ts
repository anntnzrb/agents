import { Effect } from "effect";
import { Firecrawl } from "firecrawl";
import type {
  MarketplaceAdapter,
  MarketplaceId,
  RawMarketListing,
  ScanOptions,
  ScanResultData,
  ScoredDeal,
} from "./models.ts";
import { registerBuiltinAdapters } from "./adapters/index.ts";
import { resolveAdapters } from "./registry.ts";
import { scoreListing } from "./scoring.ts";

// Ensure built-in marketplace adapters are initialized
registerBuiltinAdapters();

export const fetchAdapterListings = Effect.fn("fetchAdapterListings")(function*(
  adapter: MarketplaceAdapter,
  query: string,
  firecrawlApiKey?: string
) {
  const target = adapter.buildSearchTarget(query);

  if (target.format === "api") {
    const rawData = yield* Effect.tryPromise({
      try: async (signal) => {
        const res = await fetch(target.url, {
          signal,
          headers: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            Accept: "application/json, text/html;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
          },
        });
        if (!res.ok) return null;
        const contentType = res.headers.get("content-type") || "";
        if (contentType.includes("json")) {
          return await res.json();
        }
        return await res.text();
      },
      catch: () => null,
    }).pipe(Effect.orElseSucceed(() => null));

    if (rawData) {
      return yield* adapter.parseListings(rawData).pipe(
        Effect.orElseSucceed(() => [] as readonly RawMarketListing[])
      );
    }
    return [] as readonly RawMarketListing[];
  }

  // Web scraping via Firecrawl SDK with keyless fallback
  const scrapedData = yield* Effect.tryPromise({
    try: async () => {
      const apiKey = firecrawlApiKey || process.env["FIRECRAWL_API_KEY"];
      if (apiKey) {
        try {
          const apiUrl = process.env["FIRECRAWL_API_URL"] || "https://api.firecrawl.dev";
          const app = new Firecrawl({ apiKey, apiUrl });
          const res = await app.scrape(target.url, {
            formats: ["json"],
            waitFor: target.waitForMs ?? 2000,
            onlyMainContent: true,
          });
          if (res && res.json) return res.json;
        } catch {
          // fall through to keyless CLI fallback
        }
      }

      // Fallback to keyless Firecrawl CLI scraper
      try {
        const proc = Bun.spawn(["bun", "x", "firecrawl-cli@latest", "scrape", target.url, "--only-main-content"], {
          stdin: "ignore",
          stdout: "pipe",
          stderr: "ignore",
        });
        const text = await new Response(proc.stdout).text();
        await proc.exited;
        if (text && text.trim().length > 0) {
          return text;
        }
      } catch {
        return null;
      }

      return null;
    },
    catch: () => null,
  }).pipe(Effect.orElseSucceed(() => null));

  if (scrapedData) {
    return yield* adapter.parseListings(scrapedData).pipe(
      Effect.orElseSucceed(() => [] as readonly RawMarketListing[])
    );
  }

  return [] as readonly RawMarketListing[];
});

export const executeScan = Effect.fn("executeScan")(function*(options: ScanOptions): Effect.fn.Return<ScanResultData, never> {
  registerBuiltinAdapters();
  const hasFirecrawlKey = Boolean(process.env["FIRECRAWL_API_KEY"] || process.env["FIRECRAWL_API_URL"]);
  const warningMessage = !hasFirecrawlKey
    ? "FIRECRAWL_API_KEY is not configured. Web scraping adapters (G2A, Kinguin, Z2U, FunPay) are degraded; only direct API adapters (Plati) returned live results. Configure FIRECRAWL_API_KEY for complete multi-marketplace coverage."
    : undefined;

  const adapters = resolveAdapters(options.markets);
  const marketsQueried: MarketplaceId[] = adapters.map((a) => a.id);
  const degradedMarkets: MarketplaceId[] = [];

  // Query enabled adapters with concurrency of 2 to prevent CLI process locks
  const adapterResults = yield* Effect.all(
    adapters.map((adapter) =>
      fetchAdapterListings(adapter, options.query).pipe(
        Effect.map((listings) => ({
          id: adapter.id,
          listings,
          failed: listings.length === 0,
        }))
      )
    ),
    { concurrency: 2 }
  );

  const rawListings: RawMarketListing[] = [];
  for (const r of adapterResults) {
    if (r.failed) {
      degradedMarkets.push(r.id);
    }
    rawListings.push(...r.listings);
  }

  // Score and evaluate all listings through the decision engine
  const scoredDeals: ScoredDeal[] = rawListings.map(scoreListing);

  // Filter deals based on budget, minScore, and type
  const minScore = options.minScore ?? 50;
  let filteredScamsCount = 0;
  const validDeals: ScoredDeal[] = [];

  for (const deal of scoredDeals) {
    if (deal.isCircuitBreakerTripped || deal.trustScore < minScore) {
      filteredScamsCount++;
      if (!options.full) continue;
    }

    if (options.budget !== undefined && deal.priceUsd > options.budget) {
      continue;
    }

    if (options.typeFilter && options.typeFilter !== "all") {
      const tf = options.typeFilter.toLowerCase();
      const df = deal.deliveryFormat.toLowerCase();
      if (!df.includes(tf)) continue;
    }

    validDeals.push(deal);
  }

  // Sort by trust score descending, then price ascending
  validDeals.sort((a, b) => {
    if (b.trustScore !== a.trustScore) {
      return b.trustScore - a.trustScore;
    }
    return a.priceUsd - b.priceUsd;
  });

  return {
    query: options.query,
    budget: options.budget ?? null,
    total_scanned: rawListings.length,
    valid_deals_count: validDeals.length,
    filtered_scams_count: filteredScamsCount,
    top_deals: validDeals,
    markets_queried: marketsQueried,
    degraded_markets: degradedMarkets,
    is_degraded_mode: !hasFirecrawlKey,
    warning: warningMessage,
  };
});
