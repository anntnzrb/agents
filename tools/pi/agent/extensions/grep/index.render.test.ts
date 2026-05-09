import { describe, expect, mock, test } from "bun:test";

mock.module("@earendil-works/pi-coding-agent", () => ({
	VERSION: "0.0.0",
	DEFAULT_MAX_BYTES: 50 * 1024,
	DEFAULT_MAX_LINES: 2000,
	formatSize: (bytes: number) => `${Math.round(bytes / 1024)}KB`,
	keyHint: (_action: string, hint: string) => hint,
	getAgentDir: () => "/tmp/pi-agent",
	truncateHead: (content: string) => ({ content, truncated: false }),
	isToolCallEventType: () => false,
	createReadToolDefinition: () => ({ name: "read", renderShell: "self" }),
	createWriteToolDefinition: () => ({ name: "write", renderShell: "self" }),
	createEditToolDefinition: () => ({ name: "edit", renderShell: "self" }),
	createFindToolDefinition: () => ({ name: "find", renderShell: "self" }),
	createGrepToolDefinition: () => ({ name: "grep", renderShell: "self" }),
}));

mock.module("@earendil-works/pi-tui", () => ({
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
	bold: (text: string) => text,
};

const tokenTheme = {
	fg: (token: string, text: string) => `<${token}>${text}</${token}>`,
	bold: (text: string) => `**${text}**`,
};

describe("grep compact rendering", () => {
	test("call is naked single-line telemetry", () => {
		const text = __test.formatGrepCall({ pattern: "TODO", paths: ["src"], type: "ts", literal: true }, passthroughTheme);
		expect(text).toBe("⌕ grep paths:src · /TODO/ · ts · literal");
		expect(text.split("\n")).toHaveLength(1);
	});

	test("call includes non-default output mode and timeout", () => {
		const text = __test.formatGrepCall({ pattern: "TODO", paths: ["src"], outputMode: "files_with_matches", timeoutMs: 2500 }, passthroughTheme);
		expect(text).toBe("⌕ grep paths:src · /TODO/ · files · 2500ms");
	});

	test("call spells out offset and limit", () => {
		const text = __test.formatGrepCall({ pattern: "TODO", paths: ["src"], offset: 3, limit: 3 }, passthroughTheme);
		expect(text).toContain("offset:3");
		expect(text).toContain("limit:3");
	});

	test("call compacts long paths", () => {
		const text = __test.formatGrepCall({ pattern: "TODO", paths: ["/tmp/llm-agents-scan/opencode/packages/opencode/src/tool"] }, passthroughTheme);
		expect(text).toContain("…/packages/opencode/src/tool");
	});

	test("colors cue/title/pattern separately", () => {
		const text = __test.formatGrepCall({ pattern: "TODO", paths: ["src"] }, tokenTheme);
		expect(text).toContain("<muted>⌕</muted>");
		expect(text).toContain("<toolTitle>**grep**</toolTitle>");
		expect(text).toContain("<muted>paths:src</muted>");
		expect(text).toContain("/TODO/");
	});
	test("prefers structured details counters", () => {
		const text = __test.buildCollapsedResultText("a.ts:1: todo", { matchCount: 3, fileCount: 2 }, passthroughTheme);
		expect(text).toContain("↳ 3 matches in 2 files");
	});

	test("summarizes files output mode as files", () => {
		const text = __test.buildCollapsedResultText("a.ts\nb.ts", { outputMode: "files_with_matches", fileCount: 2 }, passthroughTheme);
		expect(text).toContain("2 files");
		expect(text).not.toContain("matches");
	});

	test("falls back to parsed output summary when counters missing", () => {
		const text = __test.buildCollapsedResultText("a.ts:1: x\nb.ts:2: y", undefined, passthroughTheme);
		expect(text).toContain("↳ 2 matches in 2 files");
	});

	test("shows warning badges from details", () => {
		const text = __test.buildCollapsedResultText(
			"a.ts:1: x",
			{
				matchCount: 1,
				fileCount: 1,
				matchLimitReached: 1,
				truncation: { truncated: true },
				linesTruncated: true,
			},
			passthroughTheme,
		);
		expect(text).not.toContain("more");
		expect(text).toContain("50KB output limit");
		expect(text).toContain("line max 500");
	});
});
