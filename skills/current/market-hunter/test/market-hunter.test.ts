import { describe, expect, it } from "bun:test";
import { Effect } from "effect";
import {
  FunPayAdapter,
  G2aAdapter,
  KinguinAdapter,
  PlatiAdapter,
  Z2uAdapter,
  registerBuiltinAdapters,
} from "#adapters";
import {
  clearRegistry,
  getAvailableAdapters,
  registerAdapter,
  resolveAdapters,
  unregisterAdapter,
} from "#registry";
import {
  computeFormatScore,
  computePriceSanity,
  computeSellerScore,
  computeWarrantyScore,
  estimateMsrp,
  scoreListing,
} from "#scoring";
import type { RawMarketListing } from "#models";

describe("Market Hunter - Dynamic Registry", () => {
  it("registers and resolves builtin adapters", () => {
    clearRegistry();
    expect(getAvailableAdapters().length).toBe(0);

    registerBuiltinAdapters();
    const adapters = getAvailableAdapters();
    expect(adapters.length).toBeGreaterThanOrEqual(5);

    const ids = adapters.map((a) => a.id);
    expect(ids).toContain("g2a");
    expect(ids).toContain("kinguin");
    expect(ids).toContain("plati");
    expect(ids).toContain("z2u");
    expect(ids).toContain("funpay");
  });

  it("filters adapters by marketplace name", () => {
    registerBuiltinAdapters();
    const filtered = resolveAdapters(["g2a", "plati"]);
    expect(filtered.length).toBe(2);
    expect(filtered.map((a) => a.id)).toEqual(["g2a", "plati"]);
  });

  it("allows dynamic registration and unregistration", () => {
    const customAdapter = new G2aAdapter();
    registerAdapter(customAdapter);
    expect(getAvailableAdapters().some((a) => a.id === "g2a")).toBe(true);

    unregisterAdapter("g2a");
    expect(getAvailableAdapters().some((a) => a.id === "g2a")).toBe(false);
  });
});

describe("Market Hunter - Scoring Engine", () => {
  it("estimates MSRP correctly based on title keywords", () => {
    expect(estimateMsrp("ChatGPT Plus 1 Month Account")).toBe(20);
    expect(estimateMsrp("Claude Pro Dedicated Account")).toBe(20);
    expect(estimateMsrp("Google Gemini Pro 6 Months Activation Link")).toBe(120);
    expect(estimateMsrp("Perplexity Pro 1 Year Key")).toBe(200);
    expect(estimateMsrp("GitHub Copilot 1 Year Student Pack")).toBe(100);
  });

  it("evaluates price sanity curves", () => {
    // $6 on a $20 service is in the sweet spot (30% ratio)
    expect(computePriceSanity(6, 20)).toBe(100);

    // $0.50 on a $20 service is a suspicious dump (2.5% ratio)
    expect(computePriceSanity(0.5, 20)).toBe(20);

    // $18 on a $20 service is low arbitrage (90% ratio)
    expect(computePriceSanity(18, 20)).toBe(50);
  });

  it("computes Bayesian smoothed seller reliability", () => {
    // Top seller with 10,000 sales and 99.8% rating
    const topScore = computeSellerScore(99.8, 10000);
    expect(topScore).toBeGreaterThanOrEqual(90);

    // Brand new seller with 1 review at 100%
    const newScore = computeSellerScore(100, 1);
    expect(newScore).toBeLessThan(70);
  });

  it("scores delivery formats appropriately", () => {
    expect(computeFormatScore("DEDICATED_ACCOUNT")).toBe(95);
    expect(computeFormatScore("PROMO_LINK_OR_CODE")).toBe(85);
    expect(computeFormatScore("SHARED_POOL")).toBe(30);
    expect(computeFormatScore("SESSION_COOKIE")).toBe(0);
  });

  it("scores warranties appropriately", () => {
    expect(computeWarrantyScore(30)).toBe(100);
    expect(computeWarrantyScore(14)).toBe(85);
    expect(computeWarrantyScore(0)).toBe(30);
  });

  it("identifies high-value legitimate deals as STRONG_BUY", () => {
    const listing: RawMarketListing = {
      id: "plati-12345",
      marketplace: "plati",
      title: "ChatGPT Plus Dedicated Personal Account",
      url: "https://plati.market/itm/12345",
      priceUsd: 8.5,
      seller: {
        name: "EliteSeller",
        positiveFeedbackPercent: 99.5,
        totalSalesCount: 15000,
      },
      deliveryFormat: "DEDICATED_ACCOUNT",
      isStockAvailable: true,
      isAutoDelivery: true,
      isGlobal: true,
      warrantyDays: 30,
    };

    const scored = scoreListing(listing);
    expect(scored.trustScore).toBeGreaterThanOrEqual(85);
    expect(scored.trustTier).toBe("STRONG_BUY");
    expect(scored.isCircuitBreakerTripped).toBe(false);
    expect(scored.discountVsMsrpPercent).toBeGreaterThanOrEqual(57);
  });

  it("trips circuit breakers on session cookie injection", () => {
    const listing: RawMarketListing = {
      id: "scam-1",
      marketplace: "plati",
      title: "ChatGPT Plus Cookie Session Token Injector",
      url: "https://plati.market/itm/scam-1",
      priceUsd: 1.0,
      seller: {
        name: "ShadyVendor",
        positiveFeedbackPercent: 88.0,
        totalSalesCount: 5,
      },
      deliveryFormat: "SESSION_COOKIE",
      isStockAvailable: true,
      isAutoDelivery: true,
      isGlobal: true,
    };

    const scored = scoreListing(listing);
    expect(scored.isCircuitBreakerTripped).toBe(true);
    expect(scored.trustTier).toBe("CONFIRMED_SCAM");
    expect(scored.trustScore).toBeLessThanOrEqual(5);
  });

  it("penalizes shared multi-user pool accounts", () => {
    const listing: RawMarketListing = {
      id: "shared-1",
      marketplace: "z2u",
      title: "ChatGPT Plus Shared Account 5 Devices Pool",
      url: "https://z2u.com/shared-1",
      priceUsd: 3.5,
      seller: {
        name: "PoolSeller",
        positiveFeedbackPercent: 92.0,
        totalSalesCount: 200,
      },
      deliveryFormat: "SHARED_POOL",
      isStockAvailable: true,
      isAutoDelivery: true,
      isGlobal: true,
    };

    const scored = scoreListing(listing);
    expect(scored.detectedRedFlags).toContain("Shared Multi-User Pool");
    expect(scored.trustScore).toBeLessThan(70);
  });
});

describe("Market Hunter - Platform Adapters", () => {
  it("builds correct search targets for each marketplace", () => {
    const g2a = new G2aAdapter();
    expect(g2a.buildSearchTarget("ChatGPT Plus").url).toContain("g2a.com/search?query=ChatGPT%20Plus");

    const kinguin = new KinguinAdapter();
    expect(kinguin.buildSearchTarget("Gemini Pro").url).toContain("kinguin.net/listing?phrase=Gemini%20Pro");

    const plati = new PlatiAdapter();
    expect(plati.buildSearchTarget("GitHub Copilot").url).toContain("plati.io/api/search.ashx?query=GitHub%20Copilot");

    const z2u = new Z2uAdapter();
    expect(z2u.buildSearchTarget("Claude Pro").url).toContain("z2u.com/search?q=Claude%20Pro");

    const funpay = new FunPayAdapter();
    expect(funpay.buildSearchTarget("ChatGPT Plus").url).toContain("funpay.com/en/lots/1355/");
  });

  it("parses listings effectfully with Effect.runPromise", async () => {
    const plati = new PlatiAdapter();
    const mockApiResponse = {
      items: [
        {
          id: 123456,
          name_eng: "ChatGPT Plus Dedicated Personal Account",
          price_usd: 8.99,
          rating: 99.5,
          sales_count: 5000,
        },
      ],
    };

    const parsed = await Effect.runPromise(plati.parseListings(mockApiResponse));
    expect(parsed.length).toBe(1);
    const item = parsed[0];
    expect(item?.id).toBe("123456");
    expect(item?.priceUsd).toBe(8.99);
    expect(item?.marketplace).toBe("plati");
    expect(item?.deliveryFormat).toBe("DEDICATED_ACCOUNT");
  });
});
