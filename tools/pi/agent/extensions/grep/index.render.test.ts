import { describe, expect, mock, test } from "bun:test";

mock.module("@mariozechner/pi-coding-agent", () => ({
	DEFAULT_MAX_BYTES: 50 * 1024,
	DEFAULT_MAX_LINES: 2000,
	formatSize: (bytes: number) => `${Math.round(bytes / 1024)}KB`,
	keyHint: (_action: string, hint: string) => hint,
	truncateHead: (content: string) => ({ content, truncated: false }),
	isToolCallEventType: () => false,
	createReadToolDefinition: () => ({ name: "read" }),
	createWriteToolDefinition: () => ({ name: "write" }),
}));

mock.module("@mariozechner/pi-tui", () => ({
	Text: class {
		setText() {}
	},
	truncateToWidth: (value: string, width: number) => value.slice(0, width),
	visibleWidth: (value: string) => value.length,
}));

mock.module("@sinclair/typebox", () => ({
	Type: {
		String: () => ({}),
		Optional: (value: unknown) => value,
		Number: () => ({}),
		Boolean: () => ({}),
		Array: () => ({}),
		Object: () => ({}),
	},
}));

const { __test } = await import("./index.js");

const passthroughTheme = {
	fg: (_token: string, text: string) => text,
};

describe("grep collapsed summary", () => {
	test("prefers structured details counters", () => {
		const text = __test.buildCollapsedResultText("a.ts:1: todo", { matchCount: 3, fileCount: 2 }, passthroughTheme);
		expect(text).toContain("3 matches · 2 files");
	});

	test("falls back to parsed output summary when counters missing", () => {
		const text = __test.buildCollapsedResultText("a.ts:1: x\nb.ts:2: y", undefined, passthroughTheme);
		expect(text).toContain("2 matches · 2 files");
	});

	test("shows warning badges from details", () => {
		const text = __test.buildCollapsedResultText(
			"a.ts:1: x",
			{
				matchCount: 1,
				fileCount: 1,
				truncation: { truncated: true },
				linesTruncated: true,
			},
			passthroughTheme,
		);
		expect(text).toContain("50KB output limit");
		expect(text).toContain("line max 500");
	});
});
