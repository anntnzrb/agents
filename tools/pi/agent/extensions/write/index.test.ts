import { describe, expect, mock, test } from "bun:test";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

mock.module("@mariozechner/pi-coding-agent", () => ({
	formatSize: (bytes: number) => `${bytes}B`,
	keyHint: (_action: string, hint: string) => hint,
	createWriteToolDefinition: () => ({
		name: "write",
		renderCall: () => new MockText(),
	}),
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

describe("write marker snapshot", () => {
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

		const first = registered.renderCall({ path: filePath, content: "payload" }, { fg: (_: string, t: string) => t, bold: (t: string) => t }, context) as MockText;
		expect(first.text).toContain("~");

		rmSync(filePath, { force: true });
		context.executionStarted = true;
		const second = registered.renderCall({ path: filePath, content: "payload" }, { fg: (_: string, t: string) => t, bold: (t: string) => t }, context) as MockText;
		expect(second.text).toContain("~");

		rmSync(dir, { recursive: true, force: true });
	});
});
