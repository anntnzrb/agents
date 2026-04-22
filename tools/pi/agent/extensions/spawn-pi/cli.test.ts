import { describe, expect, test } from "bun:test";
import { buildPiArgs, type InheritedCliArgs } from "./cli.js";

const baseInput = {
	task: "demo",
	modelArg: undefined,
	thinkingLevel: undefined,
};

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
});
