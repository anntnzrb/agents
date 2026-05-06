import type { ModelLike, ServiceTier } from "./logic.js";
import { effectiveOpenAIServiceTier, patchOpenAIServiceTier, supportsOpenAIServiceTier, supportsOpenAIServiceTierValue } from "./openai.js";
import type { ProviderOptionsSettings, ProviderOptionsProvider } from "./settings.js";

export type RequestPatchContext = {
	model: ModelLike | undefined;
	payload: unknown;
	settings: ProviderOptionsSettings;
};

export type TierChoice = {
	provider: ProviderOptionsProvider;
	tier: ServiceTier;
	label: string;
};

export type ProviderOptionsPatcher = {
	provider: ProviderOptionsProvider;
	getTierChoices(model: ModelLike | undefined): readonly TierChoice[];
	getEffectiveTier(model: ModelLike | undefined, tier: ServiceTier): ServiceTier;
	patchServiceTier(context: RequestPatchContext, tier: ServiceTier): unknown | undefined;
};

const OPENAI_TIER_CHOICES: readonly TierChoice[] = [
	{ provider: "openai", tier: "off", label: "off — do not send service_tier" },
	{ provider: "openai", tier: "default", label: "default — normal OpenAI routing" },
	{ provider: "openai", tier: "flex", label: "flex — cheaper/slower when supported" },
	{ provider: "openai", tier: "priority", label: "priority — faster OpenAI routing" },
];

const PATCHERS: readonly ProviderOptionsPatcher[] = [
	{
		provider: "openai",
		getTierChoices: (model) =>
			supportsOpenAIServiceTier(model)
				? OPENAI_TIER_CHOICES.filter((choice) => supportsOpenAIServiceTierValue(model, choice.tier))
				: [],
		getEffectiveTier: effectiveOpenAIServiceTier,
		patchServiceTier: (context, tier) => patchOpenAIServiceTier(context.model, context.payload, tier),
	},
];

export const getApplicableTierChoices = (model: ModelLike | undefined): readonly TierChoice[] =>
	PATCHERS.flatMap((patcher) => patcher.getTierChoices(model));

export const getEffectiveServiceTier = (model: ModelLike | undefined, provider: ProviderOptionsProvider, tier: ServiceTier): ServiceTier => {
	const patcher = PATCHERS.find((candidate) => candidate.provider === provider);
	return patcher?.getEffectiveTier(model, tier) ?? "off";
};

export const patchProviderOptionsRequest = (context: RequestPatchContext): unknown | undefined => {
	let nextPayload = context.payload;
	let changed = false;

	for (const patcher of PATCHERS) {
		const tier = context.settings.serviceTier[patcher.provider];
		const patched = patcher.patchServiceTier({ ...context, payload: nextPayload }, tier);
		if (patched !== undefined) {
			nextPayload = patched;
			changed = true;
		}
	}

	return changed ? nextPayload : undefined;
};
