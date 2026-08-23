#!/usr/bin/env bun
import { BunRuntime, BunServices } from "@effect/platform-bun";
import { Console, Effect, Option } from "effect";
import { Argument, Command, Flag } from "effect/unstable/cli";
import { executeScan } from "#engine";
import { SCHEMA_VERSION, type DealHunterEnvelope, type ScanResultData } from "#models";

const emitJson = Effect.fn("emitJson")(function*(data: ScanResultData) {
  const envelope: DealHunterEnvelope = {
    ok: true,
    schema_version: SCHEMA_VERSION,
    command: "scan",
    data,
  };
  yield* Console.log(JSON.stringify(envelope, null, 2));
});

const emitHumanReport = Effect.fn("emitHumanReport")(function*(data: ScanResultData) {
  const lines: string[] = [];

  lines.push("================================================================================");
  lines.push(`🎯 MARKET HUNTER: ${data.query.toUpperCase()}`);
  lines.push(`Scanned: ${data.total_scanned} total offers across [${data.markets_queried.join(", ")}]`);
  if (data.budget !== null) {
    lines.push(`Budget Constraint: <= $${data.budget.toFixed(2)} USD`);
  }
  if (data.warning) {
    lines.push("--------------------------------------------------------------------------------");
    lines.push(`⚠️  NOTICE: ${data.warning}`);
  }
  lines.push("================================================================================");
  lines.push("");

  if (data.top_deals.length === 0) {
    lines.push("No verified deals found matching your criteria.");
    if (data.filtered_scams_count > 0) {
      lines.push(`Filtered out ${data.filtered_scams_count} low-trust or high-risk listings.`);
    }
    lines.push("");
    yield* Console.log(lines.join("\n"));
    return;
  }

  const topPick = data.top_deals[0];
  if (topPick) {
    lines.push("👑 TOP VERIFIED RECOMMENDATION");
    lines.push(`- Product: ${topPick.title}`);
    lines.push(`- Marketplace: ${topPick.marketplace.toUpperCase()}`);
    lines.push(`- Price: $${topPick.priceUsd.toFixed(2)} USD (${topPick.discountVsMsrpPercent}% discount vs retail)`);
    lines.push(`- Trust & Deal Score: ${topPick.trustScore}/100 [${topPick.trustTier}]`);
    lines.push(`- Delivery Format: ${topPick.deliveryFormat}`);
    lines.push(`- Seller: ${topPick.seller.name} (${topPick.seller.positiveFeedbackPercent}% positive${topPick.seller.totalSalesCount ? `, ${topPick.seller.totalSalesCount.toLocaleString()} sales` : ""})`);
    if (topPick.warrantyDays) {
      lines.push(`- Warranty: ${topPick.warrantyDays} days replacement guarantee`);
    }
    lines.push(`- Direct URL: ${topPick.url}`);
    if (topPick.detectedRedFlags.length > 0) {
      lines.push(`- ⚠️ Warnings: ${topPick.detectedRedFlags.join(", ")}`);
    }
    lines.push("");
    lines.push("--------------------------------------------------------------------------------");
    lines.push("📋 RANKED DEALS LIST");
    lines.push("");
  }

  const displayDeals = data.top_deals.slice(0, 10);
  for (let i = 0; i < displayDeals.length; i++) {
    const deal = displayDeals[i];
    if (!deal) continue;

    const rank = i + 1;
    lines.push(`${rank}. [Score: ${deal.trustScore}/100 - ${deal.trustTier}] $${deal.priceUsd.toFixed(2)} | ${deal.marketplace.toUpperCase()}`);
    lines.push(`   Title: ${deal.title}`);
    lines.push(`   Format: ${deal.deliveryFormat} | Seller: ${deal.seller.name} (${deal.seller.positiveFeedbackPercent}%)`);
    lines.push(`   Link: ${deal.url}`);
    if (deal.detectedRedFlags.length > 0) {
      lines.push(`   Flags: ${deal.detectedRedFlags.join(", ")}`);
    }
    lines.push("");
  }

  if (data.filtered_scams_count > 0) {
    lines.push("--------------------------------------------------------------------------------");
    lines.push(`🛡️ Filtered Out: ${data.filtered_scams_count} high-risk, shared pool, or low-trust listings.`);
    lines.push("================================================================================");
  }

  yield* Console.log(lines.join("\n"));
});

export const scanCommand = Command.make(
  "market-hunter",
  {
    query: Argument.string("query").pipe(
      Argument.withDescription("Search keywords for AI subscription, license, or account"),
      Argument.variadic({ min: 1 })
    ),
    budget: Flag.float("budget").pipe(
      Flag.withDescription("Maximum budget in USD"),
      Flag.optional
    ),
    type: Flag.choice("type", ["all", "account", "link", "code", "invite"]).pipe(
      Flag.withDescription("Delivery format filter (all, account, link, code, invite)"),
      Flag.withDefault("all")
    ),
    minScore: Flag.integer("min-score").pipe(
      Flag.withDescription("Minimum Trust Score threshold (0-100)"),
      Flag.withDefault(50)
    ),
    markets: Flag.string("markets").pipe(
      Flag.withDescription("Comma-separated list of marketplaces (g2a, kinguin, plati, z2u, funpay)"),
      Flag.optional
    ),
    json: Flag.boolean("json").pipe(
      Flag.withDescription("Emit raw JSON envelope only"),
      Flag.withDefault(false)
    ),
    full: Flag.boolean("full").pipe(
      Flag.withDescription("Include low-trust and filtered listings in output"),
      Flag.withDefault(false)
    ),
  },
  (config) =>
    Effect.gen(function* () {
      const query = config.query.join(" ");
      const budget = Option.getOrUndefined(config.budget);
      const marketsRaw = Option.getOrUndefined(config.markets);
      const markets = marketsRaw ? marketsRaw.split(",").map((m) => m.trim()) : undefined;

      const resultData = yield* executeScan({
        query,
        budget,
        typeFilter: config.type,
        minScore: config.minScore,
        markets,
        jsonOnly: config.json,
        full: config.full,
      });

      if (config.json) {
        yield* emitJson(resultData);
      } else {
        yield* emitHumanReport(resultData);
      }
    })
).pipe(Command.withDescription("Search and score digital subscriptions and software across deal marketplaces"));

export const runCli = (args: readonly string[]) =>
  Command.runWith(scanCommand, { version: "1.0.0" })(args).pipe(
    Effect.provide(BunServices.layer)
  );

if (import.meta.main) {
  BunRuntime.runMain(runCli(process.argv.slice(2)));
}
