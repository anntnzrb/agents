import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import {
	isPlainObject,
	type PlainObject,
	type ProviderVerbosity,
} from "./types.js";

export type LlmPatcherConfig = {
	version: 1;
	openai: {
		enabled: boolean;
		gpt5: {
			textVerbosity: ProviderVerbosity;
		};
	};
};

export type LoadConfigResult =
	| { ok: true; config: LlmPatcherConfig }
	| { ok: false; reason: string; config: LlmPatcherConfig };

const DEFAULT_CONFIG: LlmPatcherConfig = {
	version: 1,
	openai: {
		enabled: true,
		gpt5: {
			textVerbosity: "low",
		},
	},
};

export const configPath = join(homedir(), ".pi", "agent", "llm-patcher.jsonc");
export const traceLogPath = join(homedir(), ".pi", "agent", "llm-patcher.trace.jsonl");

const parseJsonc = (source: string): unknown => {
	const withoutBlockComments = source.replace(/\/\*[\s\S]*?\*\//g, "");
	const withoutLineComments = withoutBlockComments.replace(/^\s*\/\/.*$/gm, "");
	const withoutTrailingCommas = withoutLineComments.replace(/,\s*([}\]])/g, "$1");
	return JSON.parse(withoutTrailingCommas);
};

const normalizeVerbosity = (value: unknown): ProviderVerbosity | null =>
	value === "low" || value === "medium" || value === "high" ? value : null;

const getOpenAIConfig = (value: PlainObject): PlainObject | string => {
	const openaiValue = value["openai"] === undefined ? {} : value["openai"];
	return isPlainObject(openaiValue) ? openaiValue : "openai must be an object";
};

const getGpt5Config = (value: PlainObject): PlainObject | string => {
	const gpt5Value = value["gpt5"] === undefined ? {} : value["gpt5"];
	return isPlainObject(gpt5Value) ? gpt5Value : "openai.gpt5 must be an object";
};

const normalizeConfig = (value: unknown): LlmPatcherConfig | string => {
	if (!isPlainObject(value)) return "config root must be an object";
	if (value["version"] !== undefined && value["version"] !== 1) {
		return "version must be 1";
	}

	const openaiValue = getOpenAIConfig(value);
	if (typeof openaiValue === "string") return openaiValue;

	const gpt5Value = getGpt5Config(openaiValue);
	if (typeof gpt5Value === "string") return gpt5Value;

	const textVerbosity =
		normalizeVerbosity(gpt5Value["textVerbosity"]) ??
		DEFAULT_CONFIG.openai.gpt5.textVerbosity;

	const enabled =
		typeof openaiValue["enabled"] === "boolean"
			? openaiValue["enabled"]
			: DEFAULT_CONFIG.openai.enabled;

	return {
		version: 1,
		openai: {
			enabled,
			gpt5: {
				textVerbosity,
			},
		},
	};
};

const loadConfigText = (path: string): string | null => {
	if (!existsSync(path)) return null;
	return readFileSync(path, "utf8");
};

export const loadConfig = (path = configPath): LoadConfigResult => {
	let raw: string | null;
	try {
		raw = loadConfigText(path);
	} catch (error) {
		const detail = error instanceof Error ? error.message : String(error);
		return {
			ok: false,
			reason: `llm-patcher config unavailable at ${path}: ${detail}`,
			config: DEFAULT_CONFIG,
		};
	}

	if (raw === null) {
		return { ok: true, config: DEFAULT_CONFIG };
	}

	try {
		const normalized = normalizeConfig(parseJsonc(raw));
		if (typeof normalized === "string") {
			return {
				ok: false,
				reason: `llm-patcher config invalid at ${path}: ${normalized}`,
				config: DEFAULT_CONFIG,
			};
		}
		return { ok: true, config: normalized };
	} catch (error) {
		const detail = error instanceof Error ? error.message : String(error);
		return {
			ok: false,
			reason: `llm-patcher config parse failed at ${path}: ${detail}`,
			config: DEFAULT_CONFIG,
		};
	}
};
