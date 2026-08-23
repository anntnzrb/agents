import type { DeliveryFormat, RawMarketListing, ScoredDeal, TrustTier } from "#models";

const RED_FLAG_PATTERNS: ReadonlyArray<{ readonly regex: RegExp; readonly penalty: number; readonly label: string }> = [
  { regex: /session\s*token|cookie\s*inject|auth\s*cookie|auth\s*token/i, penalty: 100, label: "Session Cookie / Auth Token Hijack Risk" },
  { regex: /shared|family\s*pool|multi\s*device|5\s*devices|co-use|shared\s*account/i, penalty: 40, label: "Shared Multi-User Pool" },
  { regex: /\|\s*go\s*\||\bchatgpt\s*go\b|\bgo\s*subscription\b/i, penalty: 15, label: "Tier Mismatch Risk (May be lower-tier Go option in dropdown)" },
  { regex: /no\s*warranty|no\s*replacement|as-is/i, penalty: 30, label: "No Seller Replacement Warranty" },
  { regex: /change\s*pass(word)?\s*in\s*1\s*h(our)?/i, penalty: 35, label: "Short Lifetime / Churn Account" },
  { regex: /risk\s*of\s*ban|temporary\s*use/i, penalty: 25, label: "Reported Ban Risk" },
  { regex: /carded|cracked|stolen/i, penalty: 100, label: "Carded / Fraudulent Origin" },
];

export function estimateMsrp(title: string): number {
  const t = title.toLowerCase();
  if (t.includes("perplexity") && (t.includes("year") || t.includes("1 yr") || t.includes("12 month") || t.includes("1y"))) return 200;
  if (t.includes("copilot") && (t.includes("year") || t.includes("1 yr") || t.includes("12 month") || t.includes("1y"))) return 100;
  if (t.includes("adobe") && (t.includes("year") || t.includes("1 yr") || t.includes("12 month"))) return 600;
  if (t.includes("gemini") && (t.includes("6 month") || t.includes("6m"))) return 120;
  if (t.includes("gemini") && (t.includes("3 month") || t.includes("3m"))) return 60;
  if (t.includes("gemini") || t.includes("chatgpt") || t.includes("claude") || t.includes("cursor") || t.includes("midjourney")) return 20;
  if (t.includes("spotify") && (t.includes("year") || t.includes("12 month"))) return 120;
  if (t.includes("youtube") && (t.includes("year") || t.includes("12 month"))) return 140;
  if (t.includes("discord") && (t.includes("nitro") || t.includes("year"))) return 100;
  return 20;
}

export function computePriceSanity(priceUsd: number, msrp: number): number {
  if (priceUsd <= 0 || msrp <= 0) return 0;
  const ratio = priceUsd / msrp;

  // Suspicious micro-dump (e.g. $0.50 for a $20 service) -> high scam likelihood
  if (ratio < 0.05) return 20;
  if (ratio < 0.10) return 50;

  // Sweet spot for arbitrage / promo links (e.g. $2.50 to $9.00 on $20 service)
  if (ratio >= 0.10 && ratio <= 0.50) return 100;

  // Fair discount ($10.00 to $15.00 on $20 service)
  if (ratio > 0.50 && ratio <= 0.75) return 80;

  // Low arbitrage / near retail
  if (ratio > 0.75 && ratio <= 1.00) return 50;

  // Above retail
  return 30;
}

export function computeSellerScore(posPercent: number, salesCount = 100): number {
  // Bayesian smoothed feedback ratio (prior of 95% on 50 sales)
  const smoothedPercent = (posPercent * salesCount + 95 * 50) / (salesCount + 50);

  // Log-scaled sales volume score (0 - 100)
  const volumeScore = Math.min(100, Math.max(10, 20 * Math.log10(Math.max(1, salesCount))));

  return Math.round(0.6 * smoothedPercent + 0.4 * volumeScore);
}

export function computeFormatScore(format: DeliveryFormat): number {
  switch (format) {
    case "DEDICATED_ACCOUNT":
      return 95;
    case "BUYER_EMAIL_UPGRADE":
      return 90;
    case "PROMO_LINK_OR_CODE":
      return 85;
    case "STUDENT_PACK":
      return 65;
    case "SHARED_POOL":
      return 30;
    case "SESSION_COOKIE":
      return 0;
    case "UNKNOWN":
    default:
      return 50;
  }
}

export function computeWarrantyScore(warrantyDays = 0): number {
  if (warrantyDays >= 30) return 100;
  if (warrantyDays >= 14) return 85;
  if (warrantyDays >= 7) return 70;
  if (warrantyDays >= 1) return 50;
  return 30;
}

export function scoreListing(listing: RawMarketListing): ScoredDeal {
  const msrp = estimateMsrp(listing.title);
  const priceScore = computePriceSanity(listing.priceUsd, msrp);
  const sellerScore = computeSellerScore(listing.seller.positiveFeedbackPercent, listing.seller.totalSalesCount);
  const formatScore = computeFormatScore(listing.deliveryFormat);
  const warrantyScore = computeWarrantyScore(listing.warrantyDays);

  const detectedRedFlags: string[] = [];
  let penaltyDeductions = 0;
  const searchableText = `${listing.title} ${listing.description || ""}`.toLowerCase();

  for (const flag of RED_FLAG_PATTERNS) {
    if (flag.regex.test(searchableText)) {
      detectedRedFlags.push(flag.label);
      penaltyDeductions += flag.penalty;
    }
  }

  // Check hard circuit breakers
  let isCircuitBreakerTripped = false;
  let circuitBreakerReason: string | undefined;

  if (listing.deliveryFormat === "SESSION_COOKIE" || searchableText.includes("cookie")) {
    isCircuitBreakerTripped = true;
    circuitBreakerReason = "High-risk session cookie injection detected";
  } else if (listing.seller.positiveFeedbackPercent < 75) {
    isCircuitBreakerTripped = true;
    circuitBreakerReason = `Low seller feedback rating (${listing.seller.positiveFeedbackPercent}%)`;
  } else if (listing.priceUsd < 0.80 && msrp >= 20 && listing.deliveryFormat === "DEDICATED_ACCOUNT") {
    isCircuitBreakerTripped = true;
    circuitBreakerReason = "Unrealistically low price for dedicated account (high fraud probability)";
  }

  let finalTrustScore = isCircuitBreakerTripped
    ? 5
    : Math.round(
        0.30 * priceScore +
        0.30 * sellerScore +
        0.25 * formatScore +
        0.15 * warrantyScore -
        penaltyDeductions
      );

  finalTrustScore = Math.max(0, Math.min(100, finalTrustScore));

  let trustTier: TrustTier = "CONFIRMED_SCAM";
  if (finalTrustScore >= 85) trustTier = "STRONG_BUY";
  else if (finalTrustScore >= 70) trustTier = "ACCEPTABLE";
  else if (finalTrustScore >= 50) trustTier = "RISKY_BUDGET";
  else if (finalTrustScore >= 25) trustTier = "AVOID_DANGER";

  const discountPercent = Math.max(0, Math.round((((msrp - listing.priceUsd) / msrp) * 100) + Number.EPSILON));
  let recommendationSummary = `${trustTier}: $${listing.priceUsd.toFixed(2)} (${discountPercent}% off est. $${msrp} retail)`;
  if (detectedRedFlags.length > 0) {
    recommendationSummary += ` | Warnings: ${detectedRedFlags.join(", ")}`;
  }

  return {
    ...listing,
    trustScore: finalTrustScore,
    trustTier,
    priceSanityScore: priceScore,
    sellerScore,
    formatScore,
    warrantyScore,
    penaltyDeductions,
    detectedRedFlags,
    isCircuitBreakerTripped,
    circuitBreakerReason,
    discountVsMsrpPercent: discountPercent,
    recommendationSummary,
  };
}
