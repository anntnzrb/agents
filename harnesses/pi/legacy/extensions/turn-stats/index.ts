import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type AssistantUsage = {
  input?: number;
  output?: number;
  inputTokens?: number;
  outputTokens?: number;
};

type AssistantLikeMessage = {
  role?: unknown;
  usage?: AssistantUsage;
};

type TurnUsage = {
  input: number;
  output: number;
};

type GcStats = {
  events: number;
  estimatedTokens: number;
};

type ContextGcRecord = {
  toolCallId?: unknown;
  resultText?: unknown;
};

type ContextGcEntry = {
  type?: unknown;
  customType?: unknown;
  data?: {
    records?: ContextGcRecord[];
  };
};

// Optional telemetry emitted by the legacy context-gc extension.
// Session-entry based by design: no runtime dependency; absent entries render nothing.
const CONTEXT_GC_INDEX_TYPE = "context-gc-index";
const APPROX_CHARS_PER_TOKEN = 4;
const emptyTurnUsage: TurnUsage = { input: 0, output: 0 };

const isAssistantMessage = (
  message: unknown,
): message is AssistantLikeMessage =>
  !!message &&
  typeof message === "object" &&
  (message as { role?: unknown }).role === "assistant";

const getNumber = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) ? value : 0;

const getInputTokens = (usage?: AssistantUsage): number =>
  getNumber(usage?.input) || getNumber(usage?.inputTokens);

const getOutputTokens = (usage?: AssistantUsage): number =>
  getNumber(usage?.output) || getNumber(usage?.outputTokens);

const summarizeTurnUsage = (messages: readonly unknown[]): TurnUsage =>
  messages.reduce<TurnUsage>(
    (total, message) =>
      isAssistantMessage(message)
        ? {
            input: total.input + getInputTokens(message.usage),
            output: total.output + getOutputTokens(message.usage),
          }
        : total,
    emptyTurnUsage,
  );

const formatCompactNumber = (value: number): string => {
  if (value >= 1_000_000) return `${Math.round(value / 100_000) / 10}m`;
  if (value >= 1_000) return `${Math.round(value / 100) / 10}k`;
  return String(value);
};

const summarizeGcStats = (entries: readonly unknown[]): GcStats => {
  let events = 0;
  let rawChars = 0;
  for (const entry of entries as ContextGcEntry[]) {
    if (entry.type !== "custom" || entry.customType !== CONTEXT_GC_INDEX_TYPE)
      continue;
    const records = Array.isArray(entry.data?.records)
      ? entry.data.records
      : [];
    if (records.length === 0) continue;
    events += 1;
    for (const record of records) {
      if (typeof record.resultText === "string")
        rawChars += record.resultText.length;
    }
  }
  return {
    events,
    estimatedTokens: Math.ceil(rawChars / APPROX_CHARS_PER_TOKEN),
  };
};

const formatGcStats = (stats: GcStats): string =>
  stats.events > 0
    ? ` · 🧹 ${stats.events} ~${formatCompactNumber(stats.estimatedTokens)}t`
    : "";

const formatTurnStats = (
  usage: TurnUsage,
  elapsedMs: number,
  gcStats: GcStats,
): string => {
  const elapsedSeconds = elapsedMs / 1000;
  const tokensPerSecond = usage.output / elapsedSeconds;
  return `⚡ ${tokensPerSecond.toFixed(1)} tok/s · ↑ ${usage.input.toLocaleString()}t · ↓ ${usage.output.toLocaleString()}t${formatGcStats(gcStats)} · ⏱ ${elapsedSeconds.toFixed(1)}s`;
};

export const __test = {
  formatCompactNumber,
  formatGcStats,
  formatTurnStats,
  summarizeGcStats,
  summarizeTurnUsage,
};

export default function turnStatsExtension(pi: ExtensionAPI) {
  let agentStartMs: number | null = null;

  pi.on("agent_start", () => {
    agentStartMs = Date.now();
  });

  pi.on("agent_end", (event, ctx) => {
    if (agentStartMs === null) return;

    const elapsedMs = Date.now() - agentStartMs;
    agentStartMs = null;
    if (!ctx.hasUI) return;
    if (elapsedMs <= 0) return;

    const usage = summarizeTurnUsage(event.messages);
    if (usage.output <= 0) return;

    const gcStats = summarizeGcStats(ctx.sessionManager.getEntries());
    ctx.ui.notify(formatTurnStats(usage, elapsedMs, gcStats), "info");
  });
}
