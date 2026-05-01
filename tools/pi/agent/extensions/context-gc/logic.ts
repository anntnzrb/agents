export const CUSTOM_TYPE_INDEX = "context-gc-index";
export const CUSTOM_TYPE_SUMMARY = "context-gc-summary";
export const CONTEXT_TREE_QUERY_TOOL = "context_tree_query";

const NON_COLLECTIBLE_TOOL_NAMES = new Set([CONTEXT_TREE_QUERY_TOOL]);

export const MIN_PENDING_RESULT_CHARS = 12_000;
export const LARGE_SINGLE_RESULT_CHARS = 8_000;
export const MAX_RESULT_CHARS_FOR_SUMMARY = 600;

export interface CapturedToolCall {
	toolCallId: string;
	toolName: string;
	arguments: unknown;
	resultText: string;
	isError: boolean;
}

export interface CapturedBatch {
	turnIndex: number;
	timestamp: number;
	assistantText: string;
	toolCalls: CapturedToolCall[];
}

export interface StoredToolCallRecord extends CapturedToolCall {
	turnIndex: number;
	timestamp: number;
}

export interface IndexEntryData {
	records: StoredToolCallRecord[];
}

export interface SummaryDetails {
	toolCallIds: string[];
	toolNames: string[];
	turnStart: number;
	turnEnd: number;
	totalResultChars: number;
}

interface ContentBlock {
	type?: string;
	text?: string;
	id?: string;
	name?: string;
	arguments?: unknown;
	input?: unknown;
	args?: unknown;
}

interface MessageLike {
	role?: string;
	customType?: string;
	content?: unknown;
	details?: unknown;
	toolCallId?: string;
	isError?: boolean;
}

interface SummaryMessageDetails extends SummaryDetails {
	summaryText?: unknown;
}

const asContentBlocks = (content: unknown): ContentBlock[] =>
	Array.isArray(content) ? (content as ContentBlock[]) : [];

const textFromContent = (content: unknown): string =>
	asContentBlocks(content)
		.filter((block) => block.type === "text" && typeof block.text === "string")
		.map((block) => block.text ?? "")
		.join("\n")
		.trim();

const toolResultText = (message: MessageLike | undefined): string => {
	if (!message) return "(no result)";
	const text = textFromContent(message.content);
	return text.length > 0 ? text : "(no text result)";
};

const toolArguments = (block: ContentBlock): unknown => {
	if ("arguments" in block) return block.arguments;
	if ("input" in block) return block.input;
	if ("args" in block) return block.args;
	return {};
};

export function captureBatch(
	message: unknown,
	toolResults: unknown[],
	turnIndex: number,
	timestamp: number,
): CapturedBatch {
	const content = asContentBlocks(
		(message as MessageLike | undefined)?.content,
	);
	const results = toolResults as MessageLike[];

	const assistantText = textFromContent(
		(message as MessageLike | undefined)?.content,
	);
	const toolCalls = content
		.filter(
			(block) =>
				block.type === "toolCall" &&
				typeof block.id === "string" &&
				typeof block.name === "string" &&
				!NON_COLLECTIBLE_TOOL_NAMES.has(block.name),
		)
		.map((block): CapturedToolCall => {
			const match = results.find((result) => result.toolCallId === block.id);
			return {
				toolCallId: block.id ?? "",
				toolName: block.name ?? "unknown",
				arguments: toolArguments(block),
				resultText: toolResultText(match),
				isError: match?.isError === true,
			};
		});

	return { turnIndex, timestamp, assistantText, toolCalls };
}

export function totalResultChars(batches: readonly CapturedBatch[]): number {
	return batches.reduce(
		(total, batch) =>
			total +
			batch.toolCalls.reduce(
				(inner, call) => inner + call.resultText.length,
				0,
			),
		0,
	);
}

export function shouldCollect(batches: readonly CapturedBatch[]): boolean {
	if (batches.length === 0) return false;
	if (totalResultChars(batches) >= MIN_PENDING_RESULT_CHARS) return true;
	return batches.some((batch) =>
		batch.toolCalls.some(
			(call) => call.resultText.length >= LARGE_SINGLE_RESULT_CHARS,
		),
	);
}

export function collectSummaryDetails(
	batches: readonly CapturedBatch[],
): SummaryDetails {
	const toolCallIds = batches.flatMap((batch) =>
		batch.toolCalls.map((call) => call.toolCallId),
	);
	const toolNames = batches.flatMap((batch) =>
		batch.toolCalls.map((call) => call.toolName),
	);
	const turns = batches.map((batch) => batch.turnIndex);
	return {
		toolCallIds,
		toolNames,
		turnStart: Math.min(...turns),
		turnEnd: Math.max(...turns),
		totalResultChars: totalResultChars(batches),
	};
}

const truncateForSummary = (text: string): string => {
	if (text.length <= MAX_RESULT_CHARS_FOR_SUMMARY) return text;
	return `${text.slice(0, MAX_RESULT_CHARS_FOR_SUMMARY)}…`;
};

export function serializeBatchesForSummary(
	batches: readonly CapturedBatch[],
): string {
	return batches
		.map((batch) => {
			const assistant =
				batch.assistantText.length > 0
					? `Assistant text:\n${batch.assistantText}\n\n`
					: "";
			const calls = batch.toolCalls
				.map((call) => {
					const status = call.isError ? "ERROR" : "OK";
					const args = JSON.stringify(call.arguments, null, 2);
					return [
						`ToolCallId: ${call.toolCallId}`,
						`Tool: ${call.toolName}`,
						`Arguments: ${args}`,
						`Result (${status}):`,
						truncateForSummary(call.resultText),
					].join("\n");
				})
				.join("\n---\n");
			return `=== Turn ${batch.turnIndex} ===\n${assistant}${calls}`;
		})
		.join("\n\n");
}

export function compactMessages(
	messages: unknown[],
	collectedToolCallIds: ReadonlySet<string>,
): unknown[] {
	return messages.filter((message) => {
		const msg = message as MessageLike;
		return !(
			msg.role === "toolResult" &&
			typeof msg.toolCallId === "string" &&
			collectedToolCallIds.has(msg.toolCallId)
		);
	});
}

export function restoreSummaryContentForContext(
	messages: unknown[],
): unknown[] {
	return messages.map((message) => {
		const msg = message as MessageLike;
		if (msg.role !== "custom" || msg.customType !== CUSTOM_TYPE_SUMMARY)
			return message;
		const summaryText = (msg.details as SummaryMessageDetails | undefined)
			?.summaryText;
		if (
			typeof summaryText !== "string" ||
			summaryText.length === 0 ||
			msg.content === summaryText
		)
			return message;
		return { ...msg, content: summaryText };
	});
}
