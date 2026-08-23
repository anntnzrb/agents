import { Effect } from "effect";
import type { AdapterError, MarketplaceAdapter, RawMarketListing, SearchTarget } from "#models";
import { normalizeRawItems, type RawScrapedItem } from "./common.ts";

export class Z2uAdapter implements MarketplaceAdapter {
  readonly id = "z2u" as const;
  readonly displayName = "Z2U";
  readonly isEnabledByDefault = true;

  buildSearchTarget(query: string): SearchTarget {
    const encoded = encodeURIComponent(query.trim());
    return {
      marketplace: this.id,
      url: `https://www.z2u.com/search?q=${encoded}`,
      waitForMs: 2000,
      format: "json",
    };
  }

  parseListings(raw: unknown): Effect.Effect<readonly RawMarketListing[], AdapterError> {
    if (!raw) return Effect.succeed([]);

    if (typeof raw === "string") {
      const items: RawScrapedItem[] = [];
      const linkRegex = /\[([^\]]+)\]\((https:\/\/www\.z2u\.com\/product-[^)]+)\)/g;
      let match: RegExpExecArray | null;

      while ((match = linkRegex.exec(raw)) !== null) {
        const fullBlock = match[1] || "";
        const url = match[2];
        const priceMatch = /from\$([0-9]+(?:\.[0-9]+)?)/.exec(fullBlock) || /\$([0-9]+(?:\.[0-9]+)?)/.exec(fullBlock);
        const titleMatch = /^([^\\\[]+)/.exec(fullBlock);

        const title = titleMatch ? titleMatch[1]?.trim() : "";
        const price = priceMatch ? priceMatch[1] : "";

        if (title && price) {
          items.push({
            id: url ? url.split("/product-")[1]?.split("/")[0] || `z2u-${items.length + 1}` : undefined,
            title,
            url,
            priceUsd: price,
            sellerRating: 98,
          });
        }
      }

      return normalizeRawItems(items, this.id, 14);
    }

    if (typeof raw === "object") {
      const obj = raw as Record<string, unknown>;
      const rawItems = Array.isArray(obj["items"])
        ? (obj["items"] as readonly RawScrapedItem[])
        : Array.isArray(obj["products"])
          ? (obj["products"] as readonly RawScrapedItem[])
          : [];

      return normalizeRawItems(rawItems, this.id, 14);
    }

    return Effect.succeed([]);
  }
}
