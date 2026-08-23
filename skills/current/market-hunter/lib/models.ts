import { Schema } from "effect";
import type { Effect } from "effect";

export const SCHEMA_VERSION = 1 as const;

export const DeliveryFormat = Schema.Literals([
  "DEDICATED_ACCOUNT",
  "BUYER_EMAIL_UPGRADE",
  "PROMO_LINK_OR_CODE",
  "STUDENT_PACK",
  "SHARED_POOL",
  "SESSION_COOKIE",
  "UNKNOWN",
]);
export type DeliveryFormat = typeof DeliveryFormat.Type;

export const TrustTier = Schema.Literals([
  "STRONG_BUY",
  "ACCEPTABLE",
  "RISKY_BUDGET",
  "AVOID_DANGER",
  "CONFIRMED_SCAM",
]);
export type TrustTier = typeof TrustTier.Type;

export const MarketplaceId = Schema.String;
export type MarketplaceId = "g2a" | "kinguin" | "plati" | "z2u" | "funpay" | (string & {});

export const SellerMetadata = Schema.Struct({
  name: Schema.String,
  positiveFeedbackPercent: Schema.Number,
  totalSalesCount: Schema.optional(Schema.Number),
  totalReviewsCount: Schema.optional(Schema.Number),
  tenureDescription: Schema.optional(Schema.String),
  isOnline: Schema.optional(Schema.Boolean),
});
export type SellerMetadata = typeof SellerMetadata.Type;

export const RawMarketListing = Schema.Struct({
  id: Schema.String,
  marketplace: Schema.String,
  title: Schema.String,
  url: Schema.String,
  priceUsd: Schema.Number,
  originalCurrency: Schema.optional(Schema.String),
  originalPrice: Schema.optional(Schema.Number),
  seller: SellerMetadata,
  deliveryFormat: DeliveryFormat,
  isStockAvailable: Schema.Boolean,
  isAutoDelivery: Schema.Boolean,
  isGlobal: Schema.Boolean,
  warrantyDays: Schema.optional(Schema.Number),
  description: Schema.optional(Schema.String),
});
export type RawMarketListing = typeof RawMarketListing.Type;

export const ScoredDeal = Schema.Struct({
  id: Schema.String,
  marketplace: Schema.String,
  title: Schema.String,
  url: Schema.String,
  priceUsd: Schema.Number,
  originalCurrency: Schema.optional(Schema.String),
  originalPrice: Schema.optional(Schema.Number),
  seller: SellerMetadata,
  deliveryFormat: DeliveryFormat,
  isStockAvailable: Schema.Boolean,
  isAutoDelivery: Schema.Boolean,
  isGlobal: Schema.Boolean,
  warrantyDays: Schema.optional(Schema.Number),
  description: Schema.optional(Schema.String),
  trustScore: Schema.Number,
  trustTier: TrustTier,
  priceSanityScore: Schema.Number,
  sellerScore: Schema.Number,
  formatScore: Schema.Number,
  warrantyScore: Schema.Number,
  penaltyDeductions: Schema.Number,
  detectedRedFlags: Schema.Array(Schema.String),
  isCircuitBreakerTripped: Schema.Boolean,
  circuitBreakerReason: Schema.optional(Schema.String),
  discountVsMsrpPercent: Schema.Number,
  recommendationSummary: Schema.String,
});
export type ScoredDeal = typeof ScoredDeal.Type;

export interface SearchTarget {
  readonly marketplace: MarketplaceId;
  readonly url: string;
  readonly queryParams?: Record<string, string> | undefined;
  readonly waitForMs?: number | undefined;
  readonly format: "json" | "api" | "html";
}

export interface MarketplaceAdapter {
  readonly id: MarketplaceId;
  readonly displayName: string;
  readonly isEnabledByDefault: boolean;
  buildSearchTarget(query: string, options?: { budget?: number | undefined } | undefined): SearchTarget;
  parseListings(raw: unknown): Effect.Effect<readonly RawMarketListing[], AdapterError>;
}

export interface ScanOptions {
  readonly query: string;
  readonly budget?: number | undefined;
  readonly typeFilter?: string | undefined;
  readonly minScore?: number | undefined;
  readonly markets?: readonly string[] | undefined;
  readonly timeoutSeconds?: number | undefined;
  readonly jsonOnly?: boolean | undefined;
  readonly full?: boolean | undefined;
}

export const ScanResultData = Schema.Struct({
  query: Schema.String,
  budget: Schema.NullOr(Schema.Number),
  total_scanned: Schema.Number,
  valid_deals_count: Schema.Number,
  filtered_scams_count: Schema.Number,
  top_deals: Schema.Array(ScoredDeal),
  markets_queried: Schema.Array(Schema.String),
  degraded_markets: Schema.Array(Schema.String),
  is_degraded_mode: Schema.optional(Schema.Boolean),
  warning: Schema.optional(Schema.String),
});
export type ScanResultData = typeof ScanResultData.Type;

export const DealHunterEnvelope = Schema.Struct({
  ok: Schema.Boolean,
  schema_version: Schema.Number,
  command: Schema.Literal("scan"),
  data: Schema.optional(ScanResultData),
  error: Schema.optional(
    Schema.Struct({
      code: Schema.String,
      message: Schema.String,
      details: Schema.optional(Schema.Record(Schema.String, Schema.Unknown)),
    })
  ),
});
export type DealHunterEnvelope = typeof DealHunterEnvelope.Type;

export class AdapterError extends Schema.TaggedError<AdapterError>()("AdapterError", {
  marketplace: Schema.String,
  message: Schema.String,
  cause: Schema.optional(Schema.Unknown),
}) {}

export class EngineError extends Schema.TaggedError<EngineError>()("EngineError", {
  code: Schema.String,
  message: Schema.String,
  details: Schema.optional(Schema.Record(Schema.String, Schema.Unknown)),
}) {}
