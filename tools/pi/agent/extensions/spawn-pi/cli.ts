import { existsSync } from "node:fs";
import { basename } from "node:path";

export type InheritedTools =
	| { mode: "default" }
	| { mode: "disabled" }
	| { mode: "explicit"; value: string };

export type InheritedCliArgs = {
	extensionArgs: string[];
	tools: InheritedTools;
};

type RuntimeInfo = {
	argv: readonly string[];
	execPath: string;
	existsSync: (filePath: string) => boolean;
};

const isToolsFlag = (arg: string): boolean =>
	arg === "--tools" || arg.startsWith("--tools=");

const getInlineFlagValue = (
	arg: string,
	flag: "--tools" | "--extension",
): string | null => (arg.startsWith(`${flag}=`) ? arg.slice(flag.length + 1) : null);

export const getInheritedCliArgs = (
	argv: readonly string[] = process.argv,
): InheritedCliArgs => {
	const extensionArgs: string[] = [];
	let tools: InheritedTools = { mode: "default" };

	for (let index = 2; index < argv.length; index += 1) {
		const arg = argv[index];
		if (!arg) continue;

		if (arg === "--no-extensions") {
			extensionArgs.push(arg);
			continue;
		}

		if (arg === "-e" || arg === "--extension") {
			const extension = argv[index + 1];
			if (!extension) continue;
			extensionArgs.push("--extension", extension);
			index += 1;
			continue;
		}

		const inlineExtension = getInlineFlagValue(arg, "--extension");
		if (inlineExtension) {
			extensionArgs.push(arg);
			continue;
		}

		if (arg === "--no-tools") {
			tools = { mode: "disabled" };
			continue;
		}

		if (!isToolsFlag(arg)) continue;

		if (arg === "--tools") {
			const value = argv[index + 1];
			if (!value) continue;
			tools = { mode: "explicit", value };
			index += 1;
			continue;
		}

		const value = getInlineFlagValue(arg, "--tools");
		if (value) tools = { mode: "explicit", value };
	}

	return { extensionArgs, tools };
};

export const getPiInvocation = (
	args: readonly string[],
	runtime: RuntimeInfo = {
		argv: process.argv,
		execPath: process.execPath,
		existsSync,
	},
): { command: string; args: string[] } => {
	const currentScript = runtime.argv[1];
	if (currentScript && runtime.existsSync(currentScript)) {
		return { command: runtime.execPath, args: [currentScript, ...args] };
	}

	const execName = basename(runtime.execPath).toLowerCase();
	const isGenericRuntime = /^(node|bun)(\.exe)?$/.test(execName);
	if (!isGenericRuntime) return { command: runtime.execPath, args: [...args] };

	return { command: "pi", args: [...args] };
};

export const formatModelArg = (
	model?: { provider?: string; id?: string } | null,
): string | undefined => {
	if (!model?.id) return undefined;
	return model.provider ? `${model.provider}/${model.id}` : model.id;
};

const buildChildPrompt = (task: string): string =>
	[
		`Task: ${task}`,
		"Return only the final answer needed by the parent.",
		"Be concise.",
		"Do not delegate further.",
	].join("\n");

const normalizeTools = (tools: readonly string[] | undefined): string[] | undefined => {
	if (!tools) return undefined;
	return [...new Set(tools.map((tool) => tool.trim()).filter(Boolean))];
};

export const buildPiArgs = (input: {
	task: string;
	modelArg: string | undefined;
	thinkingLevel: string | undefined;
	inheritedCliArgs: InheritedCliArgs;
	runtimeTools?: readonly string[];
}): string[] => {
	const args = [
		"--mode",
		"json",
		...input.inheritedCliArgs.extensionArgs,
		"-p",
		"--no-session",
		"--no-prompt-templates",
		"--offline",
	];

	if (input.modelArg) args.push("--model", input.modelArg);
	if (input.thinkingLevel) args.push("--thinking", input.thinkingLevel);

	const runtimeTools = normalizeTools(input.runtimeTools);
	if (runtimeTools) {
		if (runtimeTools.length === 0) args.push("--no-tools");
		else args.push("--tools", runtimeTools.join(","));
	} else {
		switch (input.inheritedCliArgs.tools.mode) {
			case "explicit":
				args.push("--tools", input.inheritedCliArgs.tools.value);
				break;
			case "disabled":
				args.push("--no-tools");
				break;
			case "default":
				break;
		}
	}

	args.push(buildChildPrompt(input.task));
	return args;
};
