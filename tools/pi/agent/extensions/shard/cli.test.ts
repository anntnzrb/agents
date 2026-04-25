import { describe, expect, test } from "bun:test";
import { buildPiArgs, type InheritedCliArgs } from "./cli.js";

const baseInput = {
	task: "demo",
	childMode: "worker" as const,
	modelArg: undefined,
	thinkingLevel: undefined,
};

const getPrompt = (args: string[]): string => args[args.length - 1] ?? "";

describe("buildPiArgs tool inheritance", () => {
	test("prefers runtime tools over inherited CLI tools", () => {
		const inheritedCliArgs: InheritedCliArgs = {
			extensionArgs: [],
			tools: { mode: "explicit", value: "read,bash" },
		};

		const args = buildPiArgs({
			...baseInput,
			inheritedCliArgs,
			runtimeTools: ["read", "edit", "write", "pwsh"],
		});

		expect(args).toContain("--tools");
		expect(args[args.indexOf("--tools") + 1]).toBe("read,edit,write,pwsh");
	});

	test("passes --no-tools when runtime tools are empty", () => {
		const inheritedCliArgs: InheritedCliArgs = {
			extensionArgs: [],
			tools: { mode: "default" },
		};

		const args = buildPiArgs({
			...baseInput,
			inheritedCliArgs,
			runtimeTools: [],
		});

		expect(args).toContain("--no-tools");
		expect(args).not.toContain("--tools");
	});

	test("falls back to inherited CLI tools when runtime tools are missing", () => {
		const inheritedCliArgs: InheritedCliArgs = {
			extensionArgs: [],
			tools: { mode: "explicit", value: "read,pwsh" },
		};

		const args = buildPiArgs({
			...baseInput,
			inheritedCliArgs,
		});

		expect(args).toContain("--tools");
		expect(args[args.indexOf("--tools") + 1]).toBe("read,pwsh");
	});

	test("forwards extension args in explorer mode", () => {
		const inheritedCliArgs: InheritedCliArgs = {
			extensionArgs: ["--extension", "read", "--extension=/tmp/find.ts"],
			tools: { mode: "default" },
		};

		const args = buildPiArgs({
			...baseInput,
			childMode: "explorer",
			inheritedCliArgs,
			runtimeTools: ["read", "grep", "find"],
		});

		expect(args).toContain("--extension");
		expect(args).toContain("read");
		expect(args).toContain("--extension=/tmp/find.ts");
	});
});

describe("buildPiArgs prompts", () => {
	test("worker prompt includes worker mode", () => {
		const args = buildPiArgs({
			...baseInput,
			inheritedCliArgs: { extensionArgs: [], tools: { mode: "default" } },
		});

		const prompt = getPrompt(args);
		expect(prompt).toContain("Mode: worker");
		expect(prompt).toContain("delegated child Pi worker");
		expect(prompt).toContain("Do not delegate further.");
	});

	test("explorer prompt includes read-only and no-shell language", () => {
		const args = buildPiArgs({
			...baseInput,
			childMode: "explorer",
			inheritedCliArgs: { extensionArgs: [], tools: { mode: "default" } },
		});

		const prompt = getPrompt(args);
		expect(prompt).toContain("Mode: explorer");
		expect(prompt).toContain("read-only child Pi explorer");
		expect(prompt).toContain("Do not run shell commands.");
		expect(prompt).toContain("Do not modify files.");
	});
});
