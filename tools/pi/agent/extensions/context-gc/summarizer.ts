import { collectSummaryDetails, type CapturedBatch } from "./logic.js";

const PREVIEW_LINES = 18;
const MAX_LINE_CHARS = 180;

export interface SummaryResult {
	text: string;
}

const compactResult = (text: string): string => {
	const lines = text.split(/\r?\n/).filter((line) => line.length > 0);
	const preview = lines.slice(0, PREVIEW_LINES).map((line) => (line.length > MAX_LINE_CHARS ? `${line.slice(0, MAX_LINE_CHARS)}…` : line));
	const omitted = Math.max(0, lines.length - preview.length);
	if (omitted > 0) preview.push(`…[${omitted} lines omitted; exact original recoverable by toolCallId]`);
	if (preview.length === 0 && text.length > 0) return text.length > MAX_LINE_CHARS ? `${text.slice(0, MAX_LINE_CHARS)}…` : text;
	return preview.join("\n");
};

const argsText = (value: unknown): string => {
	try {
		return JSON.stringify(value, null, 2);
	} catch {
		return "(unserializable arguments)";
	}
};

export function summarizeBatches(batches: readonly CapturedBatch[]): SummaryResult | null {
	if (batches.length === 0) return null;
	const details = collectSummaryDetails(batches);
	const sections = batches.map((batch) => {
		const calls = batch.toolCalls.map((call) => {
			const status = call.isError ? "ERROR" : "OK";
			return [
				`### ${call.toolName} — ${status}`,
				`- toolCallId: \`${call.toolCallId}\``,
				`- result chars: ${call.resultText.length}`,
				"- arguments:",
				"```json",
				argsText(call.arguments),
				"```",
				"- compacted result:",
				"```text",
				compactResult(call.resultText),
				"```",
			].join("\n");
		});
		return [`## Turn ${batch.turnIndex}`, batch.assistantText ? `Assistant text: ${batch.assistantText}` : undefined, ...calls].filter((part): part is string => typeof part === "string").join("\n\n");
	});

	const ids = details.toolCallIds.map((id) => `\`${id}\``).join(", ");
	return {
		text: [`# Context GC summary`, `Compacted ${details.toolCallIds.length} tool output(s), ${details.totalResultChars} raw chars.`, ...sections, `Exact originals: ${ids}`, `Use \`context_tree_query\` with those IDs if exact output is needed.`].join("\n\n"),
	};
}
