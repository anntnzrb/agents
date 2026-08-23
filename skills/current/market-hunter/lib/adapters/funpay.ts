import { Effect } from "effect";
import type { AdapterError, MarketplaceAdapter, RawMarketListing, SearchTarget } from "#models";
import { normalizeRawItems, type RawScrapedItem } from "./common.ts";

const CATEGORY_MAP: Record<string, string> = {
  chatgpt: "https://funpay.com/en/lots/1355/",
  claude: "https://funpay.com/en/lots/4187/",
  copilot: "https://funpay.com/en/lots/4150/",
  cursor: "https://funpay.com/en/lots/3736/",
  gemini: "https://funpay.com/en/lots/4093/",
  discord: "https://funpay.com/en/lots/596/",
  telegram: "https://funpay.com/en/lots/1266/",
  spotify: "https://funpay.com/en/lots/372/",
};

export class FunPayAdapter implements MarketplaceAdapter {
  readonly id = "funpay" as const;
  readonly displayName = "FunPay";
  readonly isEnabledByDefault = true;

  buildSearchTarget(query: string): SearchTarget {
    const qLower = query.toLowerCase();
    let targetUrl = "https://funpay.com/en/lots/1355/"; // default to AI/chatgpt

    for (const [key, url] of Object.entries(CATEGORY_MAP)) {
      if (qLower.includes(key)) {
        targetUrl = url;
        break;
      }
    }

    return {
      marketplace: this.id,
      url: targetUrl,
      waitForMs: 1500,
      format: "api", // Allows direct fast HTML fetch & parse
    };
  }

  parseListings(raw: unknown): Effect.Effect<readonly RawMarketListing[], AdapterError> {
    if (!raw) return Effect.succeed([]);

    // 1. If raw is HTML string from direct SSR fetch
    if (typeof raw === "string" && raw.includes("funpay.com")) {
      const items: RawScrapedItem[] = [];
      const offerRegex = /<a[^>]*class="[^"]*tc-item[^"]*"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g;
      let match: RegExpExecArray | null;

      while ((match = offerRegex.exec(raw)) !== null) {
        const href = match[1];
        const block = match[2];
        if (!href || !block) continue;

        const descMatch = /<div[^>]*class="[^"]*tc-desc-text[^"]*"[^>]*>([\s\S]*?)<\/div>/.exec(block);
        const userMatch = /<div[^>]*class="[^"]*media-user-name[^"]*"[^>]*>([\s\S]*?)<\/div>/.exec(block);
        const priceMatch = /<div[^>]*class="[^"]*tc-price[^"]*"[^>]*>([\s\S]*?)<\/div>/.exec(block);

        const title = descMatch ? descMatch[1]?.replace(/<[^>]+>/g, "").trim() : "";
        const sellerName = userMatch ? userMatch[1]?.replace(/<[^>]+>/g, "").trim() : "FunPay Verified Seller";
        const priceRaw = priceMatch ? priceMatch[1]?.replace(/<[^>]+>/g, "").trim() : "";

        if (title && priceRaw) {
          items.push({
            id: href.split("id=")[1] || `funpay-${items.length + 1}`,
            title,
            sellerName,
            priceUsd: priceRaw,
            sellerRating: 99,
            url: href.startsWith("http") ? href : `https://funpay.com${href}`,
          });
        }
      }

      return normalizeRawItems(items, this.id, 7);
    }

    // 2. If raw is JSON from Firecrawl schema
    if (typeof raw === "object") {
      const obj = raw as Record<string, unknown>;
      const rawItems = Array.isArray(obj["items"])
        ? (obj["items"] as readonly RawScrapedItem[])
        : Array.isArray(obj["products"])
          ? (obj["products"] as readonly RawScrapedItem[])
          : [];

      return normalizeRawItems(rawItems, this.id, 7);
    }

    return Effect.succeed([]);
  }
}
