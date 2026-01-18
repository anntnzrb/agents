/**
 * Domain formatting utilities
 */

import type {
  ModelInfo,
  OutputStyle,
  CostInfo,
  TokenMetrics,
} from "../types.ts";

/**
 * Domain formatting utilities
 */
export const formatters = {
  model: (model: ModelInfo) => model.display_name ?? "Claude",
  version: (version?: string) => (version ? `[v${version}]` : ""),
  style: (style: OutputStyle) =>
    style.name === "default" ? "🗣️ [Def]" : `🗣️ [${style.name}]`,
  cost: (cost: CostInfo) =>
    cost.total_cost_usd > 0 ? `💰 $${cost.total_cost_usd.toFixed(2)}` : "",
  contextWarning: (exceeds200k: boolean) => (exceeds200k ? "⚠️ 200k+" : ""),
  messageCount: (count: number) => (count > 0 ? `💬 ${count}` : ""),
  contextLength: (tokens: TokenMetrics) =>
    tokens.contextLength > 0
      ? `💾 ${Math.round(tokens.contextLength / 1000)}k`
      : "",
} as const;
