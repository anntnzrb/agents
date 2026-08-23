import { Effect } from "effect";
import type { AdapterError, MarketplaceAdapter, RawMarketListing, SearchTarget } from "#models";
import { normalizeRawItems, type RawScrapedItem } from "./common.ts";

export class G2aAdapter implements MarketplaceAdapter {
  readonly id = "g2a" as const;
  readonly displayName = "G2A";
  readonly isEnabledByDefault = true;

  buildSearchTarget(query: string): SearchTarget {
    const encoded = encodeURIComponent(query.trim());
    return {
      marketplace: this.id,
      url: `https://www.g2a.com/search?query=${encoded}`,
      waitForMs: 2000,
      format: "json",
    };
  }

  parseListings(raw: unknown): Effect.Effect<readonly RawMarketListing[], AdapterError> {
    if (!raw) return Effect.succeed([]);

    if (typeof raw === "string") {
      const items: RawScrapedItem[] = [];
      const linkRegex = /\[\*\*([^*]+)\*\*([\s\S]*?)\]\((https:\/\/www\.g2a\.com\/[^)]+)\)[\s\S]*?([0-9]+(?:\.[0-9]+)?)\s*USD/g;
      let match: RegExpExecArray | null;
      while ((match = linkRegex.exec(raw)) !== null) {
        const title = (match[1] || "").replace(/\s+/g, " ").trim();
        const subText = (match[2] || "")
          .replace(/[\n\r]+/g, " ")
          .replace(/[-\\*#]+/g, " ")
          .replace(/\s+/g, " ")
          .trim();
        const url = match[3];
        const price = match[4];
        const fullTitle = subText ? `${title} - ${subText}` : title;
        if (title && price) {
          items.push({
            id: url ? url.split("-i")[1]?.replace(/[^0-9]/g, "") || `g2a-${items.length + 1}` : undefined,
            title: fullTitle,
            deliveryType: subText || undefined,
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
