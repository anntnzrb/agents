import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

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

const emptyTurnUsage: TurnUsage = { input: 0, output: 0 };

const isAssistantMessage = (message: unknown): message is AssistantLikeMessage =>
	!!message && typeof message === "object" && (message as { role?: unknown }).role === "assistant";

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

const formatTurnStats = (usage: TurnUsage, elapsedMs: number): string => {
	const elapsedSeconds = elapsedMs / 1000;
	const tokensPerSecond = usage.output / elapsedSeconds;
	return `⚡ ${tokensPerSecond.toFixed(1)} tok/s · ↑ ${usage.input.toLocaleString()}t · ↓ ${usage.output.toLocaleString()}t · ⏱ ${elapsedSeconds.toFixed(1)}s`;
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

		ctx.ui.notify(formatTurnStats(usage, elapsedMs), "info");
	});
}
