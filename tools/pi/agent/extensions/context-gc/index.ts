import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { formatRecordsForQuery, ToolResultIndex } from "./indexer.js";
import {
	collectSummaryDetails,
	CONTEXT_TREE_QUERY_TOOL,
	CUSTOM_TYPE_SUMMARY,
	captureBatch,
	compactMessages,
	shouldCollect,
	type CapturedBatch,
} from "./logic.js";
import { summarizeBatches } from "./summarizer.js";

interface SendMessageCapable {
	sendMessage: (message: { customType: string; content: string; display?: boolean; details?: unknown }, options?: { deliverAs?: "steer" | "followUp" | "nextTurn"; triggerTurn?: boolean }) => void;
}

const toolResultCount = (event: { toolResults?: unknown[] }): number => (Array.isArray(event.toolResults) ? event.toolResults.length : 0);
const formatCompactNumber = (value: number): string => {
	if (value >= 1_000_000) return `${Math.round(value / 100_000) / 10}m`;
	if (value >= 1_000) return `${Math.round(value / 100) / 10}k`;
	return String(value);
};

const notifyLoaded = (ctx: unknown, count: number, chars: number): void => {
	const candidate = ctx as { ui?: { notify?: unknown } };
	if (typeof candidate.ui?.notify !== "function") return;
	candidate.ui.notify(`context-gc loaded · ${count} indexed · ${formatCompactNumber(chars)} compacted`, "info");
};

export default function contextGc(pi: ExtensionAPI) {
	const index = new ToolResultIndex();
	const pendingBatches: CapturedBatch[] = [];
	let isFlushing = false;
	let compactedChars = 0;

	const flushPending = async () => {
		if (isFlushing || pendingBatches.length === 0) return;
		if (!shouldCollect(pendingBatches)) {
			pendingBatches.length = 0;
			return;
		}

		const batches = [...pendingBatches];
		const details = collectSummaryDetails(batches);
		isFlushing = true;
		try {
			const summary = summarizeBatches(batches);
			if (!summary) return;

			index.addBatches(batches, pi);
			compactedChars += details.totalResultChars;
			pendingBatches.length = 0;

			(pi as SendMessageCapable).sendMessage(
				{
					customType: CUSTOM_TYPE_SUMMARY,
					content: summary.text,
					display: false,
					details,
				},
				{ deliverAs: "nextTurn" },
			);
		} finally {
			isFlushing = false;
		}
	};

	pi.on("session_start", async (event, ctx) => {
		index.reconstructFromSession(ctx);
		compactedChars = index.totalResultChars();
		pendingBatches.length = 0;
		if (event.reason === "startup" || event.reason === "reload") notifyLoaded(ctx, index.records.size, compactedChars);
	});

	pi.on("session_tree", async (_event, ctx) => {
		index.reconstructFromSession(ctx);
		compactedChars = index.totalResultChars();
		pendingBatches.length = 0;
	});

	pi.on("turn_end", async (event) => {
		if (toolResultCount(event) === 0) {
			await flushPending();
			return;
		}

		const batch = captureBatch(event.message, event.toolResults, event.turnIndex ?? 0, Date.now());
		if (batch.toolCalls.length === 0) return;
		pendingBatches.push(batch);
	});

	pi.on("agent_end", async () => {
		await flushPending();
	});

	pi.on("context", async (event) => {
		if (index.records.size === 0 || !Array.isArray(event.messages)) return undefined;
		const compacted = compactMessages(event.messages, index.ids());
		if (compacted.length === event.messages.length) return undefined;
		return { messages: compacted };
	});

	pi.registerTool({
		name: CONTEXT_TREE_QUERY_TOOL,
		label: "Context Tree Query",
		description: "Retrieve exact original outputs for toolCallIds collected by context-gc.",
		promptSnippet: "Retrieve exact original outputs for collected toolCallIds",
		promptGuidelines: ["Use context_tree_query when a context-gc summary says exact original tool output is needed for specific toolCallIds."],
		parameters: Type.Object({
			toolCallIds: Type.Array(Type.String({ description: "Collected toolCallIds to retrieve" }), { description: "Tool call IDs listed in a context-gc summary" }),
		}),
		execute(_toolCallId: string, input: { toolCallIds?: unknown }) {
			const ids = Array.isArray(input.toolCallIds) ? input.toolCallIds.filter((id): id is string => typeof id === "string") : [];
			return {
				content: [{ type: "text", text: formatRecordsForQuery(index.lookup(ids)) }],
				details: { requested: ids, found: index.lookup(ids).map((record) => record.toolCallId) },
			};
		},
	});
}
