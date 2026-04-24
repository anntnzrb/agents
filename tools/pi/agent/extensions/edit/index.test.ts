import { describe, expect, mock, test } from "bun:test";

mock.module("@mariozechner/pi-coding-agent", () => ({
	formatSize: (bytes: number) => `${bytes}B`,
	createEditToolDefinition: () => ({
		name: "edit",
		renderShell: "self",
	}),
	createWriteToolDefinition: () => ({ name: "write" }),
}));

class MockText {
	text = "";
	constructor(value = "") {
		this.text = value;
	}
	setText(value: string) {
		this.text = value;
	}
}

mock.module("@mariozechner/pi-tui", () => ({
	Text: MockText,
}));

const { __test, default: editExtension } = await import("./index.js");

const passthroughTheme = {
	fg: (_token: string, text: string) => text,
	bold: (text: string) => text,
};

const tokenTheme = {
	fg: (token: string, text: string) => `<${token}>${text}</${token}>`,
	bold: (text: string) => `**${text}**`,
};

describe("edit compact helpers", () => {
	test("counts logical lines without trailing newline noise", () => {
		expect(__test.getLogicalLineCount("")).toBe(0);
		expect(__test.getLogicalLineCount("\n")).toBe(0);
		expect(__test.getLogicalLineCount("\r\n")).toBe(0);
		expect(__test.getLogicalLineCount("a")).toBe(1);
		expect(__test.getLogicalLineCount("a\n")).toBe(1);
		expect(__test.getLogicalLineCount("a\r\n")).toBe(1);
		expect(__test.getLogicalLineCount("a\nb")).toBe(2);
		expect(__test.getLogicalLineCount("a\nb\n")).toBe(2);
	});

	test("extracts array, json-string, and legacy edits", () => {
		expect(__test.getRenderableEdits({ edits: [{ oldText: "a", newText: "b" }] })).toEqual([{ oldText: "a", newText: "b" }]);
		expect(__test.getRenderableEdits({ edits: '[{"oldText":"a","newText":"b"}]' })).toEqual([{ oldText: "a", newText: "b" }]);
		expect(__test.getRenderableEdits({ oldText: "a", newText: "b" })).toEqual([{ oldText: "a", newText: "b" }]);
		expect(__test.getRenderableEdits({ edits: [{ oldText: "a" }] })).toBeUndefined();
	});

	test("aggregates edit line stats", () => {
		const stats = __test.getLineStats([
			{ oldText: "a\nb", newText: "a\nb\nc" },
			{ oldText: "x", newText: "" },
		]);
		expect(stats).toEqual({ additions: 3, removals: 3 });
		expect(__test.formatLineStats(stats)).toBe("+3/-3");
		expect(__test.formatColoredLineStats(stats, passthroughTheme)).toBe("+3/-3");
		expect(__test.formatColoredLineStats(stats, tokenTheme)).toBe("<toolDiffAdded>+3</toolDiffAdded>/<toolDiffRemoved>-3</toolDiffRemoved>");
	});

	test("uses edit wording for count", () => {
		expect(__test.formatEditCount(1)).toBe("1 edit");
		expect(__test.formatEditCount(2)).toBe("2 edits");
	});
});

describe("edit compact rendering", () => {
	test("uses naked self shell", () => {
		let registered: any;
		editExtension({ registerTool: (tool: unknown) => (registered = tool) } as any);
		expect(registered.renderShell).toBe("self");
	});

	test("call is single-line telemetry with glyph and hides payload", () => {
		const summary = __test.getEditSummary({
			path: "src/foo.ts",
			edits: [{ oldText: "SECRET_OLD", newText: "SECRET_NEW\nline" }],
		});
		const text = __test.buildCollapsedEditCallText(summary, passthroughTheme);
		expect(text).toBe("✎ edit src/foo.ts · 1 edit · +2/-1");
		expect(text).not.toContain("SECRET");
		expect(text.split("\n")).toHaveLength(1);
	});

	test("colors cue/title/path/delta separately", () => {
		const text = __test.buildCollapsedEditCallText(
			__test.getEditSummary({ path: "src/foo.ts", edits: [{ oldText: "a", newText: "a\nb" }] }),
			tokenTheme,
		);
		expect(text).toContain("<muted>✎</muted>");
		expect(text).toContain("<toolTitle>**edit**</toolTitle>");
		expect(text).toContain("<muted>src/foo.ts</muted>");
		expect(text).toContain("<toolDiffAdded>+2</toolDiffAdded>/<toolDiffRemoved>-1</toolDiffRemoved>");
	});

	test("summary preserves previous count and delta when args lose edit payload", () => {
		const first = __test.getEditSummary({ path: "src/foo.ts", edits: [{ oldText: "a", newText: "a\nb" }] });
		const second = __test.getEditSummary({ path: "src/foo.ts" }, first);
		expect(second).toEqual(first);
		expect(__test.buildCollapsedEditCallText(second, passthroughTheme)).toBe("✎ edit src/foo.ts · 1 edit · +2/-1");
	});

	test("success result renders empty slot", () => {
		let registered: any;
		editExtension({ registerTool: (tool: unknown) => (registered = tool) } as any);

		const result = registered.renderResult(
			{ content: [{ type: "text", text: "raw" }], details: { diff: "diff", firstChangedLine: 37 } },
			{ expanded: false, isPartial: false },
			passthroughTheme,
			{ isError: false, lastComponent: new MockText(), state: {}, args: {}, invalidate: () => undefined },
		) as MockText;

		expect(result.text).toBe("");
	});

	test("expanded mode stays compact instead of delegating native UI", () => {
		let registered: any;
		editExtension({ registerTool: (tool: unknown) => (registered = tool) } as any);

		const call = registered.renderCall(
			{ path: "src/foo.ts", edits: [{ oldText: "a", newText: "b" }] },
			passthroughTheme,
			{ expanded: true, lastComponent: new MockText(), state: {} },
		) as MockText;
		expect(call.text).toBe("✎ edit src/foo.ts · 1 edit · +1/-1");
	});
});
