import type { LlmPatcherConfig } from "./config.js";
import {
	changed,
	getString,
	isPlainObject,
	unchanged,
	type PatchFieldChange,
	type PatchResult,
	type PlainObject,
	type ProviderPayloadPatcher,
	type ProviderVerbosity,
} from "./types.js";

type OpenAIResponsesText = PlainObject & {
	verbosity?: ProviderVerbosity;
};

type OpenAIResponsesPayload = PlainObject & {
	model: string;
	input: unknown;
	stream?: boolean;
	text?: OpenAIResponsesText;
};

const GPT5_MODEL_PREFIX = "gpt-5";
const OPENAI_PROVIDER = "openai";
const GPT5_VERBOSITY_RULE = "openai-gpt5-text-verbosity";

const isOpenAIResponsesText = (value: unknown): value is OpenAIResponsesText =>
	isPlainObject(value);

const isOpenAIResponsesPayload = (
	payload: unknown,
): payload is OpenAIResponsesPayload => {
	if (!isPlainObject(payload)) return false;
	const model = getString(payload["model"]);
	if (!model) return false;
	if (!("input" in payload)) return false;
	return true;
};

const isGpt5Model = (model: string): boolean =>
	model.toLowerCase().startsWith(GPT5_MODEL_PREFIX);

const buildPatchedText = (
	current: unknown,
	verbosity: ProviderVerbosity,
): OpenAIResponsesText => ({
	...(isOpenAIResponsesText(current) ? current : {}),
	verbosity,
});

const createTrace = (
	model: string | undefined,
	changed: boolean,
	reason: string,
	changes: readonly PatchFieldChange[] = [],
) => ({
	provider: OPENAI_PROVIDER,
	rule: GPT5_VERBOSITY_RULE,
	model,
	changed,
	reason,
	changes,
});

const patchOpenAIVerbosity = (
	payload: unknown,
	verbosity: ProviderVerbosity,
): PatchResult => {
	if (!isOpenAIResponsesPayload(payload)) {
		return unchanged(createTrace(undefined, false, "payload-not-openai-responses"));
	}
	if (!isGpt5Model(payload.model)) {
		return unchanged(createTrace(payload.model, false, "model-not-gpt5"));
	}
	if (payload.text?.verbosity === verbosity) {
		return unchanged(createTrace(payload.model, false, "verbosity-already-set"));
	}

	const changes: readonly PatchFieldChange[] = [
		{
			path: "text.verbosity",
			before: payload.text?.verbosity,
			after: verbosity,
		},
	];

	return changed(
		{
			...payload,
			text: buildPatchedText(payload.text, verbosity),
		},
		createTrace(payload.model, true, "patched-text-verbosity", changes),
	);
};

export const createOpenAIPatcher = (
	config: LlmPatcherConfig,
): ProviderPayloadPatcher => {
	const enabled = config.openai.enabled;
	const verbosity = config.openai.gpt5.textVerbosity;

	return (payload) => {
		if (!enabled) {
			return unchanged(
				createTrace(
					isPlainObject(payload) ? getString(payload["model"]) : undefined,
					false,
					"openai-patcher-disabled",
				),
			);
		}
		return patchOpenAIVerbosity(payload, verbosity);
	};
};
