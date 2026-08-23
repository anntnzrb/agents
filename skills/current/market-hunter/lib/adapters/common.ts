import { Effect } from "effect";
import {
  AdapterError,
  type DeliveryFormat,
  type MarketplaceId,
  type RawMarketListing,
} from "#models";

export interface RawScrapedItem {
  readonly id?: string | number | undefined;
  readonly title?: string | undefined;
  readonly name?: string | undefined;
  readonly priceUsd?: number | string | undefined;
  readonly price?: number | string | undefined;
  readonly rawPrice?: number | string | undefined;
  readonly price_usd?: number | string | undefined;
  readonly sellerName?: string | undefined;
  readonly seller?: string | undefined;
  readonly sellerRating?: number | string | undefined;
  readonly rating?: number | string | undefined;
  readonly sellerSalesCount?: number | string | undefined;
  readonly salesCount?: number | string | undefined;
  readonly sales_count?: number | string | undefined;
  readonly reviewsCount?: number | string | undefined;
  readonly deliveryType?: string | undefined;
  readonly isGlobal?: boolean | undefined;
  readonly url?: string | undefined;
  readonly warranty?: string | undefined;
  readonly description?: string | undefined;
}

export function parsePrice(val: unknown): number {
  if (typeof val === "number" && !isNaN(val)) return val;
  if (typeof val === "string") {
    const cleaned = val.replace(/[^0-9.]/g, "");
    const parsed = parseFloat(cleaned);
    return isNaN(parsed) ? 0 : parsed;
  }
  return 0;
}

export function parseRating(val: unknown, fallback = 95): number {
  if (typeof val === "number" && !isNaN(val)) {
    return val <= 5 ? (val / 5) * 100 : val;
  }
  if (typeof val === "string") {
    const cleaned = val.replace(/[^0-9.]/g, "");
    const parsed = parseFloat(cleaned);
    if (!isNaN(parsed)) {
      return parsed <= 5 ? (parsed / 5) * 100 : parsed;
    }
  }
  return fallback;
}

export function parseSales(val: unknown, fallback = 100): number {
  if (typeof val === "number" && !isNaN(val)) return Math.floor(val);
  if (typeof val === "string") {
    const cleaned = val.replace(/[^0-9]/g, "");
    const parsed = parseInt(cleaned, 10);
    return isNaN(parsed) ? fallback : parsed;
  }
  return fallback;
}

export function detectDeliveryFormat(title: string, rawType?: string): DeliveryFormat {
  const combined = `${title} ${rawType || ""}`.toLowerCase();

  if (
    combined.includes("cookie") ||
    combined.includes("session token") ||
    combined.includes("token connect") ||
    combined.includes("auth token")
  ) {
    return "SESSION_COOKIE";
  }
  if (combined.includes("shared") || combined.includes("family pool") || combined.includes("multi device") || combined.includes("5 devices")) {
    return "SHARED_POOL";
  }
  if (combined.includes("student") || combined.includes("edu pack") || combined.includes("github student")) {
    return "STUDENT_PACK";
  }
  if (combined.includes("invite") || combined.includes("upgrade your") || combined.includes("top up") || combined.includes("on your email")) {
    return "BUYER_EMAIL_UPGRADE";
  }
  if (combined.includes("link") || combined.includes("code") || combined.includes("redeem") || combined.includes("voucher") || combined.includes("key")) {
    return "PROMO_LINK_OR_CODE";
  }
  if (combined.includes("account") || combined.includes("acc") || combined.includes("personal") || combined.includes("dedicated") || combined.includes("private")) {
    return "DEDICATED_ACCOUNT";
  }

  return "UNKNOWN";
}

export const normalizeRawItems = Effect.fn("normalizeRawItems")(function*(
  rawItems: readonly RawScrapedItem[],
  marketplace: MarketplaceId,
  defaultWarrantyDays = 14
): Effect.fn.Return<readonly RawMarketListing[], AdapterError> {
  const result: RawMarketListing[] = [];

  for (let i = 0; i < rawItems.length; i++) {
    const item = rawItems[i];
    if (!item) continue;

    const title = (item.title || item.name || "").trim();
    if (!title) continue;

    const priceUsd = parsePrice(item.priceUsd ?? item.price ?? item.rawPrice ?? item.price_usd);
    if (priceUsd <= 0) continue;

    const ratingPercent = parseRating(item.sellerRating ?? item.rating);
    const totalSales = parseSales(item.sellerSalesCount ?? item.salesCount ?? item.sales_count ?? item.reviewsCount);
    const format = detectDeliveryFormat(title, item.deliveryType);

    const titleLower = title.toLowerCase();
    const isGlobal =
      !titleLower.includes("us only") &&
      !titleLower.includes("eu only") &&
      !titleLower.includes("restricted") &&
      !titleLower.includes("region locked");

    result.push({
      id: String(item.id || `${marketplace}-${i + 1}`),
      marketplace,
      title,
      url: item.url || `https://www.${marketplace}.com/search?query=${encodeURIComponent(title)}`,
      priceUsd,
      seller: {
        name: item.sellerName || item.seller || `${marketplace.toUpperCase()} Verified Seller`,
        positiveFeedbackPercent: ratingPercent,
        totalSalesCount: totalSales,
      },
      deliveryFormat: format,
      isStockAvailable: true,
      isAutoDelivery: true,
      isGlobal,
      warrantyDays: defaultWarrantyDays,
      description: item.description || title,
    });
  }

  return result;
});
