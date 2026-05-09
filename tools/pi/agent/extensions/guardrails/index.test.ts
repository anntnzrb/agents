import { describe, expect, mock, test } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const skillDir = mkdtempSync(join(tmpdir(), "guardrails-skill-"));
const skillPath = join(skillDir, "SKILL.md");
writeFileSync(skillPath, "---\nname: python\ndescription: Python test skill\n---\n# Python Skill\n");

mock.module("@earendil-works/pi-coding-agent", () => ({
	VERSION: "0.0.0",
	DEFAULT_MAX_BYTES: 50 * 1024,
	DEFAULT_MAX_LINES: 2000,
	formatSize: (bytes: number) => `${bytes}B`,
	keyHint: (_action: string, hint: string) => hint,
	getAgentDir: () => "/tmp/pi-agent",
	loadSkills: () => ({
		skills: [{ name: "python", description: "Python test skill", filePath: skillPath, baseDir: skillDir, sourceInfo: {}, disableModelInvocation: true }],
		diagnostics: [],
	}),
	truncateHead: (content: string) => ({ content, truncated: false }),
	isToolCallEventType: () => false,
	createReadToolDefinition: () => ({ name: "read", renderShell: "self" }),
	createWriteToolDefinition: () => ({ name: "write", renderShell: "self" }),
	createEditToolDefinition: () => ({ name: "edit", renderShell: "self" }),
	createFindToolDefinition: () => ({ name: "find", renderShell: "self" }),
	createGrepToolDefinition: () => ({ name: "grep", renderShell: "self" }),
}));

const { __test, createGuardrails } = await import("./index.js");

const setupGuardrailsHandler = (config: unknown) => {
	const dir = mkdtempSync(join(tmpdir(), "guardrails-index-"));
	const configPath = join(dir, "guardrails.jsonc");
	writeFileSync(configPath, JSON.stringify(config));

	let handler: ((event: unknown, ctx: unknown) => unknown) | undefined;
	const notifications: string[] = [];
	const messages: Array<{ customType: string; content: string; display?: boolean }> = [];
	const pi = {
		on: (_event: string, registered: (event: unknown, ctx: unknown) => unknown) => {
			handler = registered;
		},
		getAllTools: () => [],
		sendMessage: (message: { customType: string; content: string; display?: boolean }) => messages.push(message),
	} as any;
	const ctx = { ui: { notify: (message: string) => notifications.push(message) } } as any;

	createGuardrails(configPath)(pi);
	return { handler, ctx, notifications, messages };
};

describe("guardrails config cache", () => {
	test("adapts canonical and namespaced shell block events", async () => {
		const { handler, ctx, messages } = setupGuardrailsHandler({
			version: 1,
			skillBindings: {
				"python-tooling": { requiresSkill: "python" },
			},
			agentBash: {
				rules: [
					{ match: { type: "executable", names: ["python3"] }, action: { type: "block", message: "no python", requiresBinding: "python-tooling" } },
					{ match: { type: "executable", names: ["pip"] }, action: { type: "block", message: "no pip", requiresBinding: "python-tooling" } },
					{ match: { type: "executable", names: ["poetry"] }, action: { type: "block", message: "no poetry", requiresBinding: "python-tooling" } },
				],
			},
			protectedPaths: { rules: [] },
		});

		for (const [toolName, command, expected] of [
			["bash", "python3 - <<'PY'\nprint(1)\nPY", "Required skill `python` has been loaded into context"],
			["functions.bash", "pip install rich", "Required skill `python` has been loaded into context"],
			["custom.namespace.bash", "poetry install", "Required skill `python` has been loaded into context"],
			["pwsh", "python3 -c \"print(1)\"", "Required skill `python` has been loaded into context"],
			["functions.pwsh", "pip install rich", "Required skill `python` has been loaded into context"],
			["custom.namespace.pwsh", "poetry install", "Required skill `python` has been loaded into context"],
		] as const) {
			const result = await handler?.({ toolName, input: { command } }, ctx);
			expect(result).toEqual({ block: true, reason: expect.stringContaining(expected) });
		}
		expect(messages).toHaveLength(1);
		expect(messages[0]?.customType).toBe("guardrails-skill-load");
		expect(messages[0]?.content).toContain("<required_skill_load name=\"python\"");
	});

	test("adapts canonical and namespaced shell warn events", async () => {
		const { handler, ctx, notifications, messages } = setupGuardrailsHandler({
			version: 1,
			agentBash: {
				rules: [
					{ match: { type: "executable", names: ["rg"] }, action: { type: "warn", message: "use grep tool" } },
					{ match: { type: "executable", names: ["fd", "find"] }, action: { type: "warn", message: "use find tool" } },
				],
			},
			protectedPaths: { rules: [] },
		});

		for (const [toolName, command] of [
			["bash", "rg TODO"],
			["functions.bash", "fd '*.ts'"],
			["custom.namespace.bash", "find src -name '*.ts'"],
			["pwsh", "rg TODO"],
			["functions.pwsh", "fd '*.ts'"],
			["custom.namespace.pwsh", "find src -name '*.ts'"],
		] as const) {
			const result = await handler?.({ toolName, input: { command } }, ctx);
			expect(result).toBeUndefined();
		}

		expect(notifications).toHaveLength(6);
		expect(messages).toHaveLength(6);
	});

	test("adapts canonical and namespaced protected path events", async () => {
		const { handler, ctx } = setupGuardrailsHandler({
			version: 1,
			agentBash: { rules: [] },
			protectedPaths: {
				rules: [
					{ pattern: ".env", tools: ["read"], action: { type: "block", message: "no env reads" } },
					{ pattern: ".env", tools: ["write", "edit"], action: { type: "block", message: "no env writes" } },
				],
			},
		});

		for (const [toolName, path, reason] of [
			["read", "/tmp/project/.env", "no env reads"],
			["functions.read", "/tmp/project/.env", "no env reads"],
			["custom.namespace.read", "/tmp/project/.env", "no env reads"],
			["write", "/tmp/project/.env", "no env writes"],
			["functions.write", "/tmp/project/.env", "no env writes"],
			["custom.namespace.write", "/tmp/project/.env", "no env writes"],
			["edit", "/tmp/project/.env", "no env writes"],
			["functions.edit", "/tmp/project/.env", "no env writes"],
			["custom.namespace.edit", "/tmp/project/.env", "no env writes"],
		] as const) {
			const result = await handler?.({ toolName, input: { path } }, ctx);
			expect(result).toEqual({ block: true, reason });
		}
	});

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
