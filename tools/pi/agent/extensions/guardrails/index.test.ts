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

	test("emits agent-visible guardrail warnings once per tool and message", () => {
		__test.resetConfigCache();
		const notifications: string[] = [];
		const messages: Array<{ customType: string; content: string; display?: boolean }> = [];
		const pi = {
			getAllTools: () => [],
			sendMessage: (message: { customType: string; content: string; display?: boolean }) => messages.push(message),
		} as any;
		const ctx = {
			ui: {
				notify: (message: string) => notifications.push(message),
			},
		} as any;

		__test.emitGuardrailWarning(pi, ctx, "pwsh", "use native grep");
		__test.emitGuardrailWarning(pi, ctx, "pwsh", "use native grep");
		__test.emitGuardrailWarning(pi, ctx, "bash", "use native grep");

		expect(notifications).toEqual(["use native grep", "use native grep", "use native grep"]);
		expect(messages).toEqual([
			{ customType: "guardrails-warning", content: "use native grep", display: false },
			{ customType: "guardrails-warning", content: "use native grep", display: false },
		]);
	});

	test("keeps UI warnings terse while sending fuller agent hints", () => {
		expect(__test.agentHintForWarning("Use native `grep` tool for repo search.")).toContain("grep({ pattern, paths");
		expect(__test.agentHintForWarning("Use native `find` tool for file lookup.")).toContain("find({ pattern, paths");
	});
});
