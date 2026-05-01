import { describe, expect, mock, test } from "bun:test";

mock.module("@mariozechner/pi-coding-agent", () => ({
	DEFAULT_MAX_BYTES: 50 * 1024,
	formatSize: (bytes: number) => `${bytes}B`,
	getAgentDir: () => "/tmp/pi-agent",
	truncateHead: (content: string) => ({ content, truncated: false }),
	isToolCallEventType: () => false,
	createReadToolDefinition: () => ({ name: "read" }),
	createWriteToolDefinition: () => ({ name: "write" }),
	createEditToolDefinition: () => ({ name: "edit", renderShell: "self" }),
	createFindToolDefinition: () => ({ name: "find" }),
	createGrepToolDefinition: () => ({ name: "grep" }),
}));

class MockText {
	text = "";
	setText(value: string) {
		this.text = value;
	}
}

mock.module("@mariozechner/pi-tui", () => ({
	Text: MockText,
	truncateToWidth: (value: string, _width: number) => value,
	visibleWidth: (value: string) => value.length,
}));

const { __test, default: readExtension } = await import("./index.js");

const passthroughTheme = {
	fg: (_token: string, text: string) => text,
	bold: (text: string) => text,
};

const tokenTheme = {
	fg: (token: string, text: string) => `<${token}>${text}</${token}>`,
	bold: (text: string) => `**${text}**`,
};

describe("read compact rendering", () => {
	test("call is naked single-line telemetry", () => {
		const text = __test.buildReadCallText({ path: "src/foo.ts" }, passthroughTheme);
		expect(text).toBe("◎ read src/foo.ts");
		expect(text.split("\n")).toHaveLength(1);
	});

	test("call shows requested line windows", () => {
		expect(__test.getReadRange({ offset: 4, limit: 3 })).toBe("L4:L6");
		expect(__test.getReadRange({ limit: 5 })).toBe("L1:L5");
		expect(__test.getReadRange({ offset: 8 })).toBe("L8:-");
		expect(__test.buildReadCallText({ path: "src/foo.ts", offset: 4, limit: 3 }, passthroughTheme)).toBe("◎ read src/foo.ts · L4:L6");
	});

	test("colors cue/title/path separately", () => {
		const text = __test.buildReadCallText({ path: "src/foo.ts" }, tokenTheme);
		expect(text).toContain("<muted>◎</muted>");
		expect(text).toContain("<toolTitle>**read**</toolTitle>");
		expect(text).toContain("<muted>src/foo.ts</muted>");
	});

	test("leaves line window unstyled", () => {
		const text = __test.buildReadCallText({ path: "src/foo.ts", offset: 4, limit: 3 }, tokenTheme);
		expect(text).toContain("L4:L6");
		expect(text).not.toContain("<text>L4:L6</text>");
	});

	test("result is empty unless truncated", () => {
		expect(__test.buildReadResultText({}, passthroughTheme)).toBe("");
	});

	test("shows compact truncation hints", () => {
		expect(
			__test.buildReadResultText(
				{ truncation: { truncated: true, truncatedBy: "lines", maxLines: 120 } },
				passthroughTheme,
			),
		).toBe("  120 lines");
		expect(
			__test.buildReadResultText(
				{ truncation: { truncated: true, firstLineExceedsLimit: true, maxBytes: 64 } },
				passthroughTheme,
			),
		).toBe("  64B limit");
	});

	test("registered tool uses naked self shell", () => {
		let registered: any;
		readExtension({ registerTool: (tool: unknown) => (registered = tool) } as any);
		expect(registered.renderShell).toBe("self");
	});

	test("error mode shows raw output", () => {
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
