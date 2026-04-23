import { describe, expect, mock, test } from "bun:test";

mock.module("@mariozechner/pi-tui", () => ({
	truncateToWidth: (value: string, width: number) => value.slice(0, width),
	visibleWidth: (value: string) => value.length,
}));

const { __test, default: footerExtension } = await import("./index.js");

describe("footer helpers", () => {
	test("detects stale extension errors", () => {
		expect(
			__test.isStaleExtensionError(
				new Error("This extension instance is stale after session replacement or reload."),
			),
		).toBe(true);
		expect(__test.isStaleExtensionError(new Error("boom"))).toBe(false);
		expect(__test.isStaleExtensionError("boom")).toBe(false);
	});

	test("computes pollution percent for compaction summary blocks", () => {
		expect(__test.calculatePollutionPercent("")).toBeNull();
		expect(__test.calculatePollutionPercent("hello world")).toBe(0);

		const summary = "abc<read-files>one\ntwo</read-files>def";
		const block = "<read-files>one\ntwo</read-files>";
		const expected = Math.round((100 * block.length) / summary.length);
		expect(__test.calculatePollutionPercent(summary)).toBe(expected);
	});
});

describe("footer stale fallback", () => {
	const createHarness = (initiallyStale = false) => {
		let sessionStartHandler: ((event: unknown, ctx: any) => void) | undefined;
		const pi = {
			on: (event: string, handler: (event: unknown, ctx: any) => void) => {
				if (event === "session_start") sessionStartHandler = handler;
			},
			getThinkingLevel: () => "off",
		};
		footerExtension(pi as any);

		let footerFactory: ((...args: any[]) => any) | undefined;
		let stale = initiallyStale;
		const ctx = {
			hasUI: true,
			cwd: "/tmp",
			sessionManager: {
				getEntries: () => [],
				getLeafId: () => null,
			},
			ui: {
				setFooter: (factory: (...args: any[]) => any) => {
					footerFactory = factory;
				},
			},
			getContextUsage: () => {
				if (stale) {
					throw new Error("This extension instance is stale after session replacement or reload.");
				}
				return { tokens: 10, contextWindow: 100, percent: 10 };
			},
			model: { id: "m", reasoning: false, contextWindow: 100 },
		};

		sessionStartHandler?.({}, ctx);
		expect(footerFactory).toBeDefined();
		const footer = footerFactory?.(
			{ requestRender: () => {} },
			{ fg: (_token: string, text: string) => text },
			{ onBranchChange: () => () => {}, getGitBranch: () => null },
		);
		expect(footer).toBeDefined();
		return {
			footer,
			setStale: (value: boolean) => {
				stale = value;
			},
		};
	};

	test("reuses last good line on stale-extension error", () => {
		const { footer, setStale } = createHarness(false);
		const first = footer.render(80)[0];
		setStale(true);
		const second = footer.render(80)[0];
		expect(second).toBe(first);
		footer.dispose();
	});

	test("renders cwd-only line when stale before first successful render", () => {
		const { footer } = createHarness(true);
		const line = footer.render(80)[0] ?? "";
		expect(line).toContain("/tmp");
		expect(line.toLowerCase()).not.toContain("reloading");
		footer.dispose();
	});
});
