import { Effect } from "effect";
import type { AdapterError, MarketplaceAdapter, RawMarketListing, SearchTarget } from "#models";
import { normalizeRawItems, type RawScrapedItem } from "./common.ts";

export class PlatiAdapter implements MarketplaceAdapter {
  readonly id = "plati" as const;
  readonly displayName = "Plati.Market";
  readonly isEnabledByDefault = true;

  buildSearchTarget(query: string): SearchTarget {
    const encoded = encodeURIComponent(query.trim());
    return {
      marketplace: this.id,
      url: `https://plati.io/api/search.ashx?query=${encoded}&pagesize=30&response=json`,
      format: "api",
    };
  }

  parseListings(raw: unknown): Effect.Effect<readonly RawMarketListing[], AdapterError> {
    if (!raw || typeof raw !== "object") return Effect.succeed([]);

    const obj = raw as Record<string, unknown>;
    const rawItems = Array.isArray(obj["items"])
      ? (obj["items"] as readonly RawScrapedItem[])
      : Array.isArray(obj["products"])
        ? (obj["products"] as readonly RawScrapedItem[])
        : [];

    const mapped: RawScrapedItem[] = [];
    for (const item of rawItems) {
      const itemRecord = item as Record<string, unknown>;
      const id = itemRecord["id"];
      const title = itemRecord["name_eng"] || itemRecord["name"] || itemRecord["title"];
      const price = itemRecord["price_usd"] || itemRecord["price"];
      const sales = itemRecord["sales_count"] || itemRecord["salesCount"];
      const rating = itemRecord["rating"] ?? 99;

      mapped.push({
        id: id !== undefined ? String(id) : undefined,
        title: title !== undefined ? String(title) : undefined,
        priceUsd: typeof price === "number" || typeof price === "string" ? price : undefined,
        sellerRating: typeof rating === "number" || typeof rating === "string" ? rating : undefined,
        salesCount: typeof sales === "number" || typeof sales === "string" ? sales : undefined,
        url: id !== undefined ? `https://plati.market/itm/${id}?lang=en-US` : undefined,
      });
    }

    return normalizeRawItems(mapped, this.id, 30);
  }
}
