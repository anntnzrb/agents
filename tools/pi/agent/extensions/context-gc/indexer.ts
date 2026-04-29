import { CUSTOM_TYPE_INDEX, type CapturedBatch, type IndexEntryData, type StoredToolCallRecord } from "./logic.js";

interface SessionEntryLike {
	type?: string;
	customType?: string;
	data?: unknown;
}

interface SessionContextLike {
	sessionManager: {
		getBranch?: () => SessionEntryLike[];
		getEntries?: () => SessionEntryLike[];
	};
}

interface AppendEntryLike {
	appendEntry: <T>(customType: string, data: T) => void;
}

export class ToolResultIndex {
	readonly records = new Map<string, StoredToolCallRecord>();

	reconstructFromSession(ctx: SessionContextLike): void {
		this.records.clear();
		const entries = ctx.sessionManager.getBranch?.() ?? ctx.sessionManager.getEntries?.() ?? [];
		for (const entry of entries) {
			if (entry.type !== "custom" || entry.customType !== CUSTOM_TYPE_INDEX) continue;
			const data = entry.data as Partial<IndexEntryData> | undefined;
			if (!data || !Array.isArray(data.records)) continue;
			for (const record of data.records) {
				if (record && typeof record.toolCallId === "string") this.records.set(record.toolCallId, record);
			}
		}
	}

	addBatches(batches: readonly CapturedBatch[], pi: AppendEntryLike): void {
		const records = batches.flatMap((batch) =>
			batch.toolCalls.map(
				(call): StoredToolCallRecord => ({
					...call,
					turnIndex: batch.turnIndex,
					timestamp: batch.timestamp,
				}),
			),
		);
		if (records.length === 0) return;
		for (const record of records) this.records.set(record.toolCallId, record);
		pi.appendEntry(CUSTOM_TYPE_INDEX, { records } satisfies IndexEntryData);
	}

	isCollected(toolCallId: string): boolean {
		return this.records.has(toolCallId);
	}

	ids(): ReadonlySet<string> {
		return new Set(this.records.keys());
	}

	totalResultChars(): number {
		let total = 0;
		for (const record of this.records.values()) total += record.resultText.length;
		return total;
	}

	lookup(toolCallIds: readonly string[]): StoredToolCallRecord[] {
		return toolCallIds.flatMap((id) => {
			const record = this.records.get(id);
			return record ? [record] : [];
		});
	}
}

export function formatRecordsForQuery(records: readonly StoredToolCallRecord[]): string {
	if (records.length === 0) return "No matching compacted tool outputs found.";
	return records
		.map((record) => {
			const status = record.isError ? "ERROR" : "OK";
			const args = JSON.stringify(record.arguments, null, 2);
			return [`ToolCallId: ${record.toolCallId}`, `Turn: ${record.turnIndex}`, `Tool: ${record.toolName}`, `Arguments: ${args}`, `Result (${status}):`, record.resultText].join("\n");
		})
		.join("\n\n---\n\n");
}
