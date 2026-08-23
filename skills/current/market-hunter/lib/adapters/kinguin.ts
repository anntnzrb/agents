import { Effect } from "effect";
import type { AdapterError, MarketplaceAdapter, RawMarketListing, SearchTarget } from "#models";
import { normalizeRawItems, type RawScrapedItem } from "./common.ts";

export class KinguinAdapter implements MarketplaceAdapter {
  readonly id = "kinguin" as const;
  readonly displayName = "Kinguin";
  readonly isEnabledByDefault = true;

  buildSearchTarget(query: string): SearchTarget {
    const encoded = encodeURIComponent(query.trim());
    return {
      marketplace: this.id,
      url: `https://www.kinguin.net/listing?phrase=${encoded}&active=1&hide_out_of_stock=1`,
      waitForMs: 2000,
      format: "json",
    };
  }

  parseListings(raw: unknown): Effect.Effect<readonly RawMarketListing[], AdapterError> {
    if (!raw) return Effect.succeed([]);

    if (typeof raw === "string") {
      const items: RawScrapedItem[] = [];
      const linkRegex = /\[([^\]]+)\]\((https:\/\/www\.kinguin\.net\/category\/[^)]+)\)[\s\S]*?([0-9]+(?:\.[0-9]+)?)\s*(?:USD|\$|EUR|€)/g;
      let match: RegExpExecArray | null;

      while ((match = linkRegex.exec(raw)) !== null) {
        const title = match[1]?.trim();
        const url = match[2];
        const price = match[3];
        if (title && price && !title.includes("logo") && !title.includes("Sign in")) {
          items.push({
            id: url ? url.split("/category/")[1]?.split("/")[0] || `kinguin-${items.length + 1}` : undefined,
            title,
            url,
            priceUsd: price,
            sellerRating: 97,
          });
        }
      }

      return normalizeRawItems(items, this.id, 30);
    }

    if (typeof raw === "object") {
      const obj = raw as Record<string, unknown>;
      const rawItems = Array.isArray(obj["items"])
        ? (obj["items"] as readonly RawScrapedItem[])
        : Array.isArray(obj["products"])
          ? (obj["products"] as readonly RawScrapedItem[])
          : [];

      return normalizeRawItems(rawItems, this.id, 30);
    }

    return Effect.succeed([]);
  }
}
