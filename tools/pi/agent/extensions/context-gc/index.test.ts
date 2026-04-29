import { describe, expect, test } from "bun:test";
import { formatRecordsForQuery, ToolResultIndex } from "./indexer.js";
import {
	CUSTOM_TYPE_INDEX,
	LARGE_SINGLE_RESULT_CHARS,
	MIN_PENDING_RESULT_CHARS,
	captureBatch,
	compactMessages,
	serializeBatchesForSummary,
	shouldCollect,
	totalResultChars,
	type CapturedBatch,
} from "./logic.js";

const textPart = (text: string) => ({ type: "text", text });

const batchWithResult = (resultText: string): CapturedBatch => ({
	turnIndex: 1,
	timestamp: 10,
	assistantText: "",
	toolCalls: [
		{
			toolCallId: "call-1",
			toolName: "grep",
			arguments: { pattern: "needle" },
			resultText,
			isError: false,
		},
	],
});

describe("captureBatch", () => {
	test("captures current Pi toolCall arguments field", () => {
		const batch = captureBatch(
			{
				content: [textPart("checking"), { type: "toolCall", id: "abc", name: "read", arguments: { path: "package.json" } }],
			},
			[{ role: "toolResult", toolCallId: "abc", content: [textPart("file body")], isError: false }],
			7,
			100,
		);

		expect(batch.assistantText).toBe("checking");
		expect(batch.toolCalls).toHaveLength(1);
		expect(batch.toolCalls[0]?.arguments).toEqual({ path: "package.json" });
		expect(batch.toolCalls[0]?.resultText).toBe("file body");
	});

	test("keeps legacy input/args fallback only as compatibility at capture boundary", () => {
		const batch = captureBatch(
			{
				content: [
					{ type: "toolCall", id: "input-id", name: "bash", input: { command: "pwd" } },
					{ type: "toolCall", id: "args-id", name: "find", args: { pattern: "*.ts" } },
				],
			},
			[
				{ role: "toolResult", toolCallId: "input-id", content: [textPart("/tmp")], isError: false },
				{ role: "toolResult", toolCallId: "args-id", content: [textPart("index.ts")], isError: false },
			],
			1,
			2,
		);

		expect(batch.toolCalls.map((call) => call.arguments)).toEqual([{ command: "pwd" }, { pattern: "*.ts" }]);
	});

	test("does not capture context_tree_query recovery output for recursive collection", () => {
		const batch = captureBatch(
			{ content: [{ type: "toolCall", id: "recovery", name: "context_tree_query", arguments: { toolCallIds: ["old"] } }] },
			[{ role: "toolResult", toolCallId: "recovery", content: [textPart("huge recovered exact output")], isError: false }],
			1,
			2,
		);

		expect(batch.toolCalls).toEqual([]);
	});
});

describe("collect threshold", () => {
	test("does not collect small harmless batches", () => {
		expect(shouldCollect([batchWithResult("small output")])).toBe(false);
	});

	test("collects one large result or large accumulated output", () => {
		expect(shouldCollect([batchWithResult("x".repeat(LARGE_SINGLE_RESULT_CHARS))])).toBe(true);
		expect(shouldCollect([batchWithResult("x".repeat(MIN_PENDING_RESULT_CHARS / 2)), batchWithResult("y".repeat(MIN_PENDING_RESULT_CHARS / 2))])).toBe(true);
	});

	test("counts result characters across batches", () => {
		expect(totalResultChars([batchWithResult("abc"), batchWithResult("defg")])).toBe(7);
	});
});

describe("context compaction", () => {
	test("removes only collected toolResult messages", () => {
		const messages = [
			{ role: "assistant", content: [{ type: "toolCall", id: "call-1", name: "grep", arguments: {} }] },
			{ role: "toolResult", toolCallId: "call-1", content: [textPart("raw")], isError: false },
			{ role: "toolResult", toolCallId: "call-2", content: [textPart("keep")], isError: false },
			{ role: "user", content: [textPart("hello")] },
		];

		const compacted = compactMessages(messages, new Set(["call-1"]));
		expect(compacted).toEqual([messages[0], messages[2], messages[3]]);
	});
});

describe("index persistence", () => {
	test("stores exact original outputs and reconstructs from custom entries", () => {
		const piEntries: unknown[] = [];
		const index = new ToolResultIndex();
		index.addBatches([batchWithResult("original exact output")], {
			appendEntry(customType, data) {
				piEntries.push({ type: "custom", customType, data });
			},
		});

		expect(piEntries).toHaveLength(1);
		expect((piEntries[0] as { customType: string }).customType).toBe(CUSTOM_TYPE_INDEX);

		const restored = new ToolResultIndex();
		restored.reconstructFromSession({ sessionManager: { getEntries: () => piEntries as never[] } });
		expect(restored.lookup(["call-1"])[0]?.resultText).toBe("original exact output");
		expect(formatRecordsForQuery(restored.lookup(["call-1"]))).toContain("original exact output");
	});
});

describe("summary serialization", () => {
	test("includes ids and keeps serialized fallback compact while originals remain separate", () => {
		const serialized = serializeBatchesForSummary([batchWithResult("z".repeat(5_000))]);
		expect(serialized).toContain("ToolCallId: call-1");
		expect(serialized).toContain("z".repeat(180));
		expect(serialized.length).toBeLessThan(1_000);
	});
});
