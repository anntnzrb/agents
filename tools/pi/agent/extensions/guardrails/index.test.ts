import { describe, expect, mock, test } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

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

const { __test } = await import("./index.js");

describe("guardrails config cache", () => {
	test("reuses cache for unchanged file and invalidates on change", async () => {
		const dir = mkdtempSync(join(tmpdir(), "guardrails-index-"));
		const configPath = join(dir, "guardrails.jsonc");
		const writeConfig = (message: string) => {
			writeFileSync(
				configPath,
				JSON.stringify({
					version: 1,
					agentBash: {
						rules: [
							{
								match: { type: "executable", names: ["rg"] },
								action: { type: "warn", message },
							},
						],
					},
					protectedPaths: { rules: [] },
				}),
			);
		};

		__test.resetConfigCache();
		writeConfig("one");
		const first = __test.getConfigOrBlockReason(configPath);
		const second = __test.getConfigOrBlockReason(configPath);
		expect(second).toBe(first);

		await new Promise((resolve) => setTimeout(resolve, 5));
		writeConfig("two");
		const third = __test.getConfigOrBlockReason(configPath);
		expect(third).not.toBe(first);
		expect(typeof third).toBe("object");
		if (typeof third !== "string") {
			expect(third.agentBash.rules[0]?.action.message).toBe("two");
		}
	});
});
