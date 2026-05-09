import { appendFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { loadConfig, traceLogPath } from "./config.js";
import { createOpenAIPatcher } from "./openai.js";
import type { LlmPatcherConfig } from "./config.js";
import type { PatchResult, ProviderPayloadPatcher } from "./types.js";

const createPatchers = (
	config: LlmPatcherConfig,
): readonly ProviderPayloadPatcher[] => [createOpenAIPatcher(config)];

const applyPatchers = (
	payload: unknown,
	payloadPatchers: readonly ProviderPayloadPatcher[],
): PatchResult => {
	let nextPayload = payload;
	let finalResult: PatchResult | null = null;

	for (const patcher of payloadPatchers) {
		const result = patcher(nextPayload);
		finalResult = result;
		if (result.changed) {
			nextPayload = result.payload;
		}
	}

	return (
		finalResult ?? {
			changed: false,
			trace: {
				provider: "unknown",
				rule: "no-patchers",
				changed: false,
				reason: "no-patchers-registered",
				changes: [],
			},
		}
	);
};

const appendTrace = (result: PatchResult): void => {
	mkdirSync(dirname(traceLogPath), { recursive: true });
	appendFileSync(
		traceLogPath,
		`${JSON.stringify({
			ts: new Date().toISOString(),
			...result.trace,
		})}\n`,
		"utf8",
	);
};

export default function llmPatcherExtension(pi: ExtensionAPI) {
	const configResult = loadConfig();
	if (!configResult.ok) {
		console.warn(configResult.reason);
	}

	const patchers = createPatchers(configResult.config);

	pi.on("before_provider_request", (event) => {
		const result = applyPatchers(event.payload, patchers);
		appendTrace(result);
		return result.changed ? result.payload : undefined;
	});
}
