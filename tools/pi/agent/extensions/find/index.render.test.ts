import { describe, expect, mock, test } from "bun:test";

mock.module("@mariozechner/pi-coding-agent", () => ({
	DEFAULT_MAX_BYTES: 50 * 1024,
	formatSize: (bytes: number) => `${Math.round(bytes / 1024)}KB`,
	getAgentDir: () => "/tmp/pi-agent",
	truncateHead: (content: string) => ({ content, truncated: false }),
	createFindToolDefinition: () => ({ name: "find" }),
	createGrepToolDefinition: () => ({ name: "grep" }),
}));

mock.module("@mariozechner/pi-tui", () => ({
	Text: class {
		setText() {}
	},
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

describe("find compact rendering", () => {
	test("call is naked single-line telemetry", () => {
		const text = __test.formatFindCall({ pattern: "**/*.ts", path: "src", hidden: false, limit: 20 }, passthroughTheme);
		expect(text).toBe("◇ find src · **/*.ts · hidden:false · limit:20");
		expect(text.split("\n")).toHaveLength(1);
	});

	test("colors cue/title/pattern separately", () => {
		const text = __test.formatFindCall({ pattern: "**/*.ts", path: "src" }, tokenTheme);
		expect(text).toContain("<muted>◇</muted>");
		expect(text).toContain("<toolTitle>**find**</toolTitle>");
		expect(text).toContain("<muted>src</muted>");
		expect(text).toContain("**/*.ts");
	});

	test("summarizes file count", () => {
		const text = __test.getCollapsedSummary("a.ts\nb.ts", {}, passthroughTheme);
		expect(text).toBe("  2 files");
	});

	test("summarizes no matches", () => {
		const text = __test.getCollapsedSummary("No files found matching pattern", {}, passthroughTheme);
		expect(text).toBe("  No files found matching pattern");
	});

	test("summarizes limit and truncation notices", () => {
		const text = __test.getCollapsedSummary(
			"a.ts",
			{ resultLimitReached: 1, truncation: { truncated: true } },
			passthroughTheme,
		);
		expect(text).toContain("1 file");
		expect(text).toContain("limit");
		expect(text).toContain("50KB output limit");
	});
});
