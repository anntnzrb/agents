import { describe, expect, mock, test } from "bun:test";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

mock.module("@mariozechner/pi-coding-agent", () => ({
	formatSize: (bytes: number) => `${bytes}B`,
	createReadToolDefinition: () => ({ name: "read" }),
	createWriteToolDefinition: () => ({ name: "write" }),
	createEditToolDefinition: () => ({ name: "edit", renderShell: "self" }),
}));

class MockText {
	text = "";
	setText(value: string) {
		this.text = value;
	}
}

mock.module("@mariozechner/pi-tui", () => ({
	Text: MockText,
}));

const { __test, default: writeExtension } = await import("./index.js");

const passthroughTheme = {
	fg: (_token: string, text: string) => text,
	bold: (text: string) => text,
};

const tokenTheme = {
	fg: (token: string, text: string) => `<${token}>${text}</${token}>`,
	bold: (text: string) => `**${text}**`,
};

describe("write content stats", () => {
	test("handles empty and newline-only payloads", () => {
		expect(__test.getContentStats("")).toEqual({ bytes: 0, lines: 0 });
		expect(__test.getContentStats("\n")).toEqual({ bytes: 1, lines: 0 });
		expect(__test.getContentStats("\r\n")).toEqual({ bytes: 2, lines: 0 });
	});

	test("counts lines without allocating splits", () => {
		expect(__test.getContentStats("a").lines).toBe(1);
		expect(__test.getContentStats("a\n").lines).toBe(1);
		expect(__test.getContentStats("a\r\n").lines).toBe(1);
		expect(__test.getContentStats("a\nb\n").lines).toBe(2);
		expect(__test.getContentStats("a\nb").lines).toBe(2);
	});

	test("reports utf8 byte length", () => {
		const payload = "α\nβ";
		expect(__test.getContentStats(payload).bytes).toBe(Buffer.byteLength(payload, "utf8"));
	});
});

describe("write compact rendering", () => {
	test("call is naked single-line telemetry", () => {
		const text = __test.buildCollapsedWriteCallText({ path: "src/foo.ts", content: "a\nb" }, "+", passthroughTheme);
		expect(text).toBe("▣ write + src/foo.ts · 3B · 2 lines");
		expect(text.split("\n")).toHaveLength(1);
	});

	test("colors cue/title/path/marker separately", () => {
		const text = __test.buildCollapsedWriteCallText({ path: "src/foo.ts", content: "a" }, "+", tokenTheme);
		expect(text).toContain("<muted>▣</muted>");
		expect(text).toContain("<toolTitle>**write**</toolTitle>");
		expect(text).toContain("<muted>src/foo.ts</muted>");
		expect(text).toContain("<toolDiffAdded>+</toolDiffAdded>");
		expect(text).toContain("1B");
		expect(text).toContain("1 line");
		expect(text).not.toContain("<text>1B</text>");
	});

	test("colors update marker as warning", () => {
		expect(__test.formatWriteMarker("~", tokenTheme)).toBe("<warning>~</warning>");
	});

	test("uses naked self shell", () => {
		let registered: any;
		writeExtension({ registerTool: (tool: unknown) => (registered = tool) } as any);
		expect(registered.renderShell).toBe("self");
	});

	test("preserves marker after execution starts", () => {
		let registered: any;
		writeExtension({ registerTool: (tool: unknown) => (registered = tool) } as any);

		const dir = join(tmpdir(), `write-marker-${Date.now()}-${Math.random().toString(16).slice(2)}`);
		mkdirSync(dir, { recursive: true });
		const filePath = join(dir, "file.txt");
		writeFileSync(filePath, "existing");

		const context = {
			expanded: false,
			executionStarted: false,
			state: {},
			cwd: dir,
			lastComponent: new MockText(),
		};

		const first = registered.renderCall({ path: filePath, content: "payload" }, passthroughTheme, context) as MockText;
		expect(first.text).toContain("~");

		rmSync(filePath, { force: true });
		context.executionStarted = true;
		const second = registered.renderCall({ path: filePath, content: "payload" }, passthroughTheme, context) as MockText;
		expect(second.text).toContain("~");

		rmSync(dir, { recursive: true, force: true });
	});
});
