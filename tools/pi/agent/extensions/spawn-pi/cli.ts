import fs from "node:fs";
import path from "node:path";

export type InheritedCliArgs = {
	extensionArgs: string[];
	toolsArg: string | undefined;
	noTools: boolean;
};

const isToolsFlag = (arg: string): boolean => arg === "--tools" || arg.startsWith("--tools=");
const isExtensionFlag = (arg: string): boolean =>
	arg === "-e" || arg === "--extension" || arg.startsWith("--extension=");

export const getInheritedCliArgs = (argv: readonly string[] = process.argv): InheritedCliArgs => {
	const inherited: InheritedCliArgs = {
		extensionArgs: [],
		toolsArg: undefined,
		noTools: false,
	};

	for (let i = 2; i < argv.length; i++) {
		const arg = argv[i];
		if (!arg) continue;

		if (arg === "--no-extensions") {
			inherited.extensionArgs.push(arg);
			continue;
		}

		if (isExtensionFlag(arg)) {
			inherited.extensionArgs.push(arg);
			if ((arg === "-e" || arg === "--extension") && argv[i + 1]) {
				inherited.extensionArgs.push(argv[i + 1] ?? "");
				i++;
			}
			continue;
		}

		if (arg === "--no-tools") {
			inherited.noTools = true;
			continue;
		}

		if (isToolsFlag(arg)) {
			inherited.toolsArg = arg === "--tools" ? argv[i + 1] : arg.slice("--tools=".length);
			if (arg === "--tools" && argv[i + 1]) i++;
		}
	}

	return inherited;
};

export const getPiInvocation = (args: readonly string[]): { command: string; args: string[] } => {
	const currentScript = process.argv[1];
	if (currentScript && fs.existsSync(currentScript)) {
		return { command: process.execPath, args: [currentScript, ...args] };
	}

	const execName = path.basename(process.execPath).toLowerCase();
	const isGenericRuntime = /^(node|bun)(\.exe)?$/.test(execName);
	if (!isGenericRuntime) return { command: process.execPath, args: [...args] };

	return { command: "pi", args: [...args] };
};

export const formatModelArg = (model?: { provider?: string; id?: string } | null): string | undefined => {
	if (!model?.id) return undefined;
	return model.provider ? `${model.provider}/${model.id}` : model.id;
};

export const buildPiArgs = (input: {
	task: string;
	modelArg: string | undefined;
	thinkingLevel: string | undefined;
	inheritedCliArgs: InheritedCliArgs;
}): string[] => {
	const args = ["--mode", "json", ...input.inheritedCliArgs.extensionArgs, "-p", "--no-session"];

	if (input.modelArg) args.push("--model", input.modelArg);
	if (input.thinkingLevel) args.push("--thinking", input.thinkingLevel);

	if (input.inheritedCliArgs.toolsArg) {
		args.push("--tools", input.inheritedCliArgs.toolsArg);
	} else if (input.inheritedCliArgs.noTools) {
		args.push("--no-tools");
	}

	args.push(`Task: ${input.task}`);
	return args;
};
