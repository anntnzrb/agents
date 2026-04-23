import { describe, expect, mock, test } from "bun:test";

mock.module("@mariozechner/pi-coding-agent", () => ({
	DEFAULT_MAX_BYTES: 50 * 1024,
	DEFAULT_MAX_LINES: 2000,
	formatSize: (bytes: number) => `${bytes}B`,
	keyHint: (_action: string, hint: string) => hint,
	truncateHead: (content: string) => ({ content, truncated: false }),
	isToolCallEventType: () => false,
	createReadToolDefinition: () => ({ name: "read" }),
	createWriteToolDefinition: () => ({ name: "write" }),
}));

class MockText {
	text = "";
	setText(value: string) {
		this.text = value;
	}
}

mock.module("@mariozechner/pi-tui", () => ({
	Text: MockText,
	truncateToWidth: (value: string, width: number) => value.slice(0, width),
	visibleWidth: (value: string) => value.length,
}));

const { __test, default: readExtension } = await import("./index.js");

const passthroughTheme = {
	fg: (_token: string, text: string) => text,
};

describe("read collapsed summary", () => {
	test("always includes expand hint", () => {
		const text = __test.buildCollapsedReadText({}, passthroughTheme);
		expect(text).toContain("to expand");
	});

	test("shows line-window hint when truncated by lines", () => {
		const text = __test.buildCollapsedReadText(
			{
				truncation: {
					truncated: true,
					truncatedBy: "lines",
					maxLines: 120,
				},
			},
			passthroughTheme,
		);
		expect(text).toContain("120 line window");
	});

	test("shows byte limit hint when first line exceeds limit", () => {
		const text = __test.buildCollapsedReadText(
			{
				truncation: {
					truncated: true,
					firstLineExceedsLimit: true,
					maxBytes: 64,
				},
			},
			passthroughTheme,
		);
		expect(text).toContain("64B limit");
	});
});

describe("read renderResult", () => {
	test("shows raw output in expanded mode", () => {
		let registered: any;
		readExtension({ registerTool: (tool: unknown) => (registered = tool) } as any);
		const text = new MockText();
		registered.renderResult(
			{ content: [{ type: "text", text: "RAW" }], details: {} },
			{ expanded: true, isPartial: false },
			passthroughTheme,
			{ lastComponent: text, isError: false },
		);
		expect(text.text).toBe("RAW");
	});

	test("shows raw output in error mode", () => {
		let registered: any;
		readExtension({ registerTool: (tool: unknown) => (registered = tool) } as any);
		const text = new MockText();
		registered.renderResult(
			{ content: [{ type: "text", text: "ERR" }], details: {} },
			{ expanded: false, isPartial: false },
			passthroughTheme,
			{ lastComponent: text, isError: true },
		);
		expect(text.text).toBe("ERR");
	});
});
